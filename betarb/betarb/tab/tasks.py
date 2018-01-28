import datetime
import logging

import pandas as pd
import re
import requests
from celery import shared_task
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from sklearn.linear_model import LinearRegression

from betfair.models import Event
from .models import Meeting, Race, Result, Accuracy, Bucket

logger = logging.getLogger(__name__)


@shared_task
def scrape_races():
    """Scrapes the Next-To-Go races from TAB"""
    url = 'https://api.beta.tab.com.au/v1/tab-info-service/racing/next-to-go/races?jurisdiction=NSW'
    res = requests.get(url)
    res.raise_for_status()
    res = res.json()
    logger.info('Scraped {} races'.format(len(res['races'])))
    for item in res['races']:
        race, created = upsert_race(item)
        if created:
            logger.info(f'Created {race}')
        if not cache.get(race.pk):
            cache.set(race.pk, 1)
            monitor_race.delay(race.pk)
            logger.info(f'Monitoring {race}')
        else:
            logger.debug(f'Already monitoring {race}')


@shared_task
def upsert_race(item):
    meeting, created = upsert_meeting(item['meeting'])
    if created:
        logger.info('Created {}'.format(meeting))
    try:
        return meeting.race_set.update_or_create(
            number=item['raceNumber'],
            defaults={
                'distance': item['raceDistance'],
                'name': item['raceName'],
                'start_time': item['raceStartTime'],
                'link_self': item['_links']['self'],
                'link_form': item['_links']['form'],
                'link_big_bets': item['_links']['bigBets'],
            }
        )
    except:
        logger.warning(item)
        raise


@shared_task
def upsert_meeting(item):
    """Upsert a meeting into the db"""
    try:
        meeting_name = item['meetingName'].upper()
        meeting_name = re.sub('\s(PK)$', ' PARK', meeting_name)
        return Meeting.objects.update_or_create(
            name=meeting_name.upper(),
            date=item['meetingDate'],
            defaults={
                'location': item['location'],
                'race_type': item['raceType'],
                'rail_position': item['railPosition'],
                'track_condition': item['trackCondition'],
                'venue_mnemonic': item['venueMnemonic'],
                'weather_condition': item['weatherCondition'],
            }
        )
    except:
        logger.warning(item)
        raise


@shared_task
def link_races(pk):
    race = Race.objects.get(id=pk)
    try:
        start_time_gap = race.start_time - datetime.timedelta(hours=2)
        event = Event.objects.get(
            venue=race.meeting.name,
            race_number=race.number,
            start_time__gt=start_time_gap,
        )
    except Event.DoesNotExist:
        logger.error(f'Betfair event not found for tab {race}')
        return
    race.betfair_event = event
    race.save()
    logger.warning(f'Successfully linked {event} to {race} for {race.start_time.date()}')


@shared_task
def monitor_race(pk):
    """Monitor the race"""
    logger.info(f'Monitoring race id {pk}')
    race = Race.objects.get(id=pk)
    logger.info(f'self url = {race.link_self}')
    if not race.betfair_event:
        link_races.delay(race.pk)
    res = requests.get(race.link_self)
    res.raise_for_status()
    res = res.json()

    # update race fields
    race.start_time = parse_datetime(res['raceStartTime'])
    race.direction = res['trackDirection']
    race.has_fixed_odds = res['hasFixedOdds']
    race.has_parimutuel = res['hasParimutuel']
    race.class_conditions = res['raceClassConditions']
    race.status = res['raceStatus']
    race.number_of_places = res['numberOfPlaces']
    race.save()
    logger.info(f'Updated race {race}')

    for runner_item in res['runners']:
        runner, create = race.runner_set.update_or_create(
            runner_number=runner_item['runnerNumber'],
            name=runner_item['runnerName'].upper(),
            defaults={
                'link_form': runner_item.get('_links', {}).get('form'),
                'trainer_name': runner_item['trainerFullName'],
                'rider_name': runner_item['riderDriverFullName'],
                'barrier_number': runner_item['barrierNumber'],
                'handicap_weight': runner_item['handicapWeight'],
                'harness_handicap': runner_item['harnessHandicap'],
                'last_5_starts': runner_item['last5Starts'],
                'dfs_form_rating': runner_item['dfsFormRating'],
                'tech_form_rating': runner_item['techFormRating'],
                'fixed_betting_status': runner_item['fixedOdds'].get('bettingStatus'),
                'parimutuel_betting_status': runner_item['parimutuel'].get('bettingStatus'),
            }
        )
        if create:
            logger.info(f'Created runner {runner} for race {race}')

        # do not save odds when race has started
        if timezone.now() > race.start_time:
            continue

        # fixed odds
        as_at = timezone.now()
        if race.has_fixed_odds and runner_item['fixedOdds']['returnWin']:
            fo = runner_item['fixedOdds']
            if 'returnWinTime' in fo:
                as_at = parse_datetime(fo['returnWinTime'])
            elif 'scratchedTime' in fo:
                as_at = parse_datetime(fo['scratchedTime'])
            fixed_odd = runner.fixedodd_set.create(
                as_at=as_at,
                win_dec=fo['returnWin'],
                place_dec=fo['returnPlace'],
            )
            logger.debug(f'{race.meeting.name} {race.number} {runner.name}: new fixed odd {fixed_odd.win_dec}')

        # parimutuel odds
        if race.has_parimutuel and runner_item['parimutuel']['returnWin']:
            po = runner_item['parimutuel']
            parimutuel_odd = runner.parimutuelodd_set.create(
                as_at=as_at,
                win_dec=po['returnWin'],
                place_dec=po['returnPlace'],
            )
            logger.debug(
                f'{race.meeting.name} {race.number} {runner.name}: new parimutuel odd {parimutuel_odd.win_dec}')

    # save results and finish
    if res['results']:
        upsert_results.delay(race.pk, res)
        logger.info(f'{race.meeting.name} {race.number}: finished')

    # race has not started yet
    elif race.start_time > timezone.now():
        delta = race.start_time - timezone.now()
        if delta.seconds > 60 * 14:
            logger.warning(f'{race.meeting.name} {race.number}: is more than 15 minutes away, waiting till then')
            countdown = delta.seconds - (60 * 14)
        else:
            countdown = delta.seconds % 60
            countdown += 60 if countdown < 30 and delta.seconds > 120 else 0
        logger.warning(f'{race.meeting.name} {race.number}: waiting {countdown} till next odds scrape')
        monitor_race.apply_async((pk,), countdown=countdown)

    # race started but no results
    else:
        logger.warning(f'{race.meeting.name} {race.number}: race has started - waiting for results')
        monitor_race.apply_async((pk,), countdown=55)


@shared_task
def upsert_results(pk, res):
    race = Race.objects.get(id=pk)

    for i, result_items in enumerate(res['results']):
        pos = i + 1
        for rn in result_items:
            runner = race.runner_set.get(runner_number=rn)
            result, created = Result.objects.update_or_create(
                race=race,
                runner=runner,
                pos=pos,
            )
            if created:
                logger.debug(f'Created result {result} pos {pos} with {runner} and {race}')

    race.has_results = True
    race.save()
    logger.warning(f'{race.meeting.name} {race.number}: saved results')


@shared_task
def post_process():
    race_cleanup()
    if analyze():
        bucket()


@shared_task
def race_cleanup():
    """Delete race if no results and url self gives 404"""
    yesterday = timezone.now() - datetime.timedelta(hours=24)
    print(f'yesterday {yesterday}')
    races = Race.objects.filter(
        has_results=False,
        start_time__lte=yesterday
    ).all()
    for race in races:

        # has results?
        rr = [hasattr(r, 'result') for r in race.runner_set.all()]
        if any(rr):
            logger.warning(f'{race.meeting.name} {race.number}: already had results!')
            race.has_results = True
            race.save()
            continue

        # if no results,
        # can we still get results
        res = requests.get(race.link_self)
        if res.status_code == requests.codes.ok:
            upsert_results.delay(race.pk, res.json())
            continue

        # then rather delete worthless race info
        r = race.delete()
        logger.warning(f'Deleted {race.pk}: {r}')
    logger.warning(f'>>>> Race cleanup done on {len(races)} races')


@shared_task
def analyze():
    """create analysis for results"""

    # update races
    races = Race.objects.filter(
        has_results=True).filter(
        has_processed=False).all()
    for race in races:
        for runner in race.runner_set.all():
            result = runner.result if hasattr(runner, 'result') else None
            accuracy = Accuracy(race=race, runner=runner)

            fo = runner.fixedodd_set.first()
            if not fo:
                continue

            if fo.win_dec:
                accuracy.won = bool(result) and result.pos == 1
                accuracy.win_dec = fo.win_dec
                accuracy.win_perc = 1 / fo.win_dec
                accuracy.win_error = accuracy.win_perc - accuracy.won

            if fo.place_dec:
                accuracy.place = bool(result) and result.pos <= 3
                accuracy.place_dec = fo.place_dec
                accuracy.place_perc = 1 / fo.place_dec
                accuracy.place_error = accuracy.place_perc - accuracy.place

            if fo.win_dec or fo.place_dec:
                try:
                    accuracy.save()
                except IntegrityError:
                    logger.warning('Already processed')
        race.has_processed = True
        race.save()
        logger.warning(f'Created accuracy for {race.display()}')
    logger.warning(f'>>>> Task accuracy finished {len(races)} races')
    return len(races)


@shared_task
def bucket():
    """buckets the abs errors for betting range values"""
    df = pd.DataFrame.from_records(Accuracy.objects.all().values())
    # df['win_error_abs'] = df['win_error'].abs()
    Bucket.objects.all().delete()
    bins = 0
    while True:
        bins += 1
        df['bins'] = 1
        df['cats'] = pd.qcut(df['win_perc'], bins)
        flag_exit = False
        for name, grp in df.groupby('cats'):

            # linear regression for coefficients
            ols = LinearRegression().fit(
                grp['win_perc'].values.reshape(-1, 1),
                grp['won'].values.reshape(-1, 1))

            # create bucket from bin group
            bucket = Bucket.objects.create(
                bins=bins,
                left=name.left,
                right=name.right,
                total=len(grp),
                count=grp['won'].sum(),
                win_mean=grp['won'].mean(),
                coef=ols.coef_[0],
                intercept=ols.intercept_,
            )

            # check flag
            if bucket.count <= 20:
                flag_exit = True

        if flag_exit:
            break
    logger.warning(f'Created max {bins} buckets')


'''
{'races':
    [
        {
            '_links': {
                'bigBets': 'https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-19/meetings/G/IPS/races/10/big-bets?jurisdiction=NSW',
                'form': 'https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-19/meetings/G/IPS/races/10/form?jurisdiction=NSW',
                'self': 'https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-19/meetings/G/IPS/races/10?jurisdiction=NSW'
            },
            'broadcastChannel': 'Sky Racing 1',
            'broadcastChannels': ['Sky Racing 1'],
            'meeting': {
                'location': 'QLD',
                'meetingDate': '2018-01-19',
                'meetingName': 'IPSWICH',
                'raceType': 'G',
                'railPosition': None,
                'sellCode': {'meetingCode': 'B', 'scheduledType': 'G'},
                'trackCondition': 'GOOD',
                'venueMnemonic': 'IPS',
                'weatherCondition': 'FINE'},
            'raceDistance': 431,
            'raceName': 'WWW.IPSWICHGREYHOUNDS.COM',
            'raceNumber': 10,
            'raceStartTime': '2018-01-19T07:42:00.000Z'
        },
        
        
{
    "raceNumber": 1,
    "raceName": "WWW.THURLESRACES.IE MAIDEN HURDLE", 
    "raceDistance": 3200, 
    "trackDirection": "anticlockwise",
    "meeting": {
        "meetingName": "THURLES", 
        "venueMnemonic": "TRS", 
        "meetingDate": "2018-01-21", 
        "location": "IRL",
        "raceType": "R", 
        "sellCode": {"meetingCode": "I", "scheduledType": "R"}
    },
    "skyRacing": {
        "audio": "http://mediatab.skyracing.com.au/Audio_Replay/2018/01/20180121THLR01.mp3",
        "video": "http://mediatab.skyracing.com.au/Race_Replay/2018/01/20180121THLR01_V.mp4"
    },
    "hasParimutuel": true, 
    "hasFixedOdds": true, 
    "broadcastChannel": null, 
    "broadcastChannels": [], 
    "hasForm": true,
    "hasEarlySpeedRatings": false, 
    "allIn": false, 
    "cashOutEligibility": "Disabled", 
    "allowBundle": true,
    "willHaveFixedOdds": true, 
    "fixedOddsOnlineBetting": true, 
    "raceStartTime": "2018-01-21T13:20:00.000Z",
    "raceClassConditions": "HDL-MD", 
    "apprenticesCanClaim": true, 
    "prizeMoney": "$17760.00", 
    "raceStatus": "Normal",
    "substitute": "NR", 
    "results": [], 
    "pools": [
        {
            "wageringProduct": "Win", 
            "legNumber": 1, 
            "poolStatusCode": "Open", 
            "cashOutEligibility": "Disabled", 
            "legs": [
                {
                    "legNumber": 1, 
                    "raceNumber": 1, 
                    "venueMnemonic": "TRS", 
                    "raceType": "R",
                    "startTime": "2018-01-21T13:20:00.000Z"
                }
            ],
            "poolHistory": [{"poolTotal": 13, "poolTotalTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
                     {"poolTotal": 13, "poolTotalTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
                     {"poolTotal": 13, "poolTotalTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
                     {"poolTotal": 3, "poolTotalTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
     "poolTotal": 13, "jackpot": 0, "cominglingGuests": true, "substitute": "NYD"},
    {"wageringProduct": "Place", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled", "legs": [
        {"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
         "startTime": "2018-01-21T13:20:00.000Z"}], "poolTotal": 17, "jackpot": 0, "cominglingGuests": true,
     "substitute": "NYD"},
    {"wageringProduct": "Quinella", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled",
     "legs": [{"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
               "startTime": "2018-01-21T13:20:00.000Z"}], "_links": {
        "approximates": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/pools/Quinella/approximates?jurisdiction=NSW"},
     "poolTotal": 2, "jackpot": 0, "cominglingGuests": true, "substitute": "NYD"},
    {"wageringProduct": "Exacta", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled", "legs": [
        {"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
         "startTime": "2018-01-21T13:20:00.000Z"}], "_links": {
        "approximates": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/pools/Exacta/approximates?jurisdiction=NSW"},
     "poolTotal": 1, "jackpot": 0, "cominglingGuests": true, "substitute": "NYD"},
    {"wageringProduct": "Duet", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled", "legs": [
        {"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
         "startTime": "2018-01-21T13:20:00.000Z"}], "_links": {
        "approximates": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/pools/Duet/approximates?jurisdiction=NSW"},
     "poolTotal": 0, "jackpot": 0, "cominglingGuests": true, "substitute": "NYD"},
    {"wageringProduct": "Trifecta", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled",
     "legs": [{"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
               "startTime": "2018-01-21T13:20:00.000Z"}], "poolTotal": 1, "jackpot": 0, "cominglingGuests": true,
     "substitute": "NYD"},
    {"wageringProduct": "RunningDouble", "legNumber": 1, "poolStatusCode": "Open", "cashOutEligibility": "Disabled",
     "legs": [{"legNumber": 1, "raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R",
               "startTime": "2018-01-21T13:20:00.000Z"},
              {"legNumber": 2, "raceNumber": 2, "venueMnemonic": "TRS", "raceType": "R",
               "startTime": "2018-01-21T13:50:00.000Z"}], "poolTotal": 10, "jackpot": 0, "cominglingGuests": true,
     "substitute": "NYD"}], "allowMulti": true, "allowParimutuelPlace": true, "parimutuelPlaceStatus": "Open",
    "allowFixedOddsPlace": false, "numberOfPlaces": 3, "numberOfFixedOddsPlaces": 0, "runners": [
    {"runnerName": "ASKARI", "runnerNumber": 1,
     "fixedOdds": {"returnWin": 101, "returnWinTime": "2018-01-21T10:13:16.000Z", "returnWinOpen": 101,
                   "returnWinOpenDaily": 101, "returnPlace": 15.6, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795941, "differential": null,
                   "flucs": [{"returnWin": 81, "returnWinTime": "2018-01-21T10:08:48.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T10:01:43.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:33:07.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T09:27:29.000Z"}], "percentageChange": 25,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/WHITE%20%26%20EMERALD%20GREEN%20CHECK%2C%20WHITE%20SLEEVES%2C%20EMERALD%20GREEN%20STAR%20ON%20CAP",
     "trainerName": "G Elliott", "trainerFullName": "GORDON ELLIOTT", "barrierNumber": 1,
     "riderDriverName": "K Donoghue", "riderDriverFullName": "K M DONOGHUE", "handicapWeight": 75.5,
     "harnessHandicap": null, "blinkers": false, "claimAmount": -1, "last5Starts": "8x000", "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 87, "techFormRating": 87, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/1?jurisdiction=NSW"}},
    {"runnerName": "BAZAROV", "runnerNumber": 2,
     "fixedOdds": {"returnWin": 26, "returnWinTime": "2018-01-21T09:16:08.000Z", "returnWinOpen": 34,
                   "returnWinOpenDaily": 26, "returnPlace": 5.2, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795942, "differential": null,
                   "flucs": [{"returnWin": 31, "returnWinTime": "2018-01-21T09:02:53.000Z"},
                             {"returnWin": 26, "returnWinTime": "2018-01-21T08:55:18.000Z"},
                             {"returnWin": 31, "returnWinTime": "2018-01-21T08:13:18.000Z"},
                             {"returnWin": 34, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -16,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20YELLOW%20DIAMOND%2C%20BLACK%20SLEEVES%2C%20YELLOW%20ARMLET%2C%20BLACK%20CAP",
     "trainerName": "J Clifford", "trainerFullName": "JOHN O CLIFFORD", "barrierNumber": 2,
     "riderDriverName": "P Kennedy", "riderDriverFullName": "P D KENNEDY", "handicapWeight": 72,
     "harnessHandicap": null, "blinkers": false, "claimAmount": 1.5, "last5Starts": "x5066", "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 77, "techFormRating": 77, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/2?jurisdiction=NSW"}},
    {"runnerName": "BOHERARD BOY", "runnerNumber": 3,
     "fixedOdds": {"returnWin": 18, "returnWinTime": "2018-01-21T10:13:16.000Z", "returnWinOpen": 15,
                   "returnWinOpenDaily": 17, "returnPlace": 4, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795943, "differential": null,
                   "flucs": [{"returnWin": 17, "returnWinTime": "2018-01-21T10:08:48.000Z"},
                             {"returnWin": 18, "returnWinTime": "2018-01-21T10:03:58.000Z"},
                             {"returnWin": 17, "returnWinTime": "2018-01-21T09:38:44.000Z"},
                             {"returnWin": 16, "returnWinTime": "2018-01-21T09:36:52.000Z"}], "percentageChange": 6,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 22.2, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open", "marketMovers": [
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 5.1, "returnWinTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": 0},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20WHITE%20STAR%2C%20WHITE%20%26%20RED%20HOOPED%20SLEEVES%2C%20RED%20CAP",
     "trainerName": "C Byrnes", "trainerFullName": "C BYRNES", "barrierNumber": 3, "riderDriverName": "D McInerney",
     "riderDriverFullName": "D J MCINERNEY", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": 2.5, "last5Starts": "x0x55", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 88, "techFormRating": 88, "totalRatingPoints": 9, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/3?jurisdiction=NSW"}},
    {"runnerName": "DOYEN BAY", "runnerNumber": 4,
     "fixedOdds": {"returnWin": 81, "returnWinTime": "2018-01-21T10:08:48.000Z", "returnWinOpen": 71,
                   "returnWinOpenDaily": 81, "returnPlace": 12.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795944, "differential": null,
                   "flucs": [{"returnWin": 101, "returnWinTime": "2018-01-21T10:03:58.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:32:49.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T09:27:29.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:16:08.000Z"}], "percentageChange": -20,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20WHITE%20PANEL%2C%20WHITE%20%26%20RED%20HOOPED%20SLEEVES%2C%20WHITE%20CAP",
     "trainerName": "E O'Grady", "trainerFullName": "EOGHAN O'GRADY", "barrierNumber": 4,
     "riderDriverName": "P Enright", "riderDriverFullName": "P T ENRIGHT", "handicapWeight": 72,
     "harnessHandicap": null, "blinkers": false, "claimAmount": -1, "last5Starts": "f0", "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 81, "techFormRating": 81, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/4?jurisdiction=NSW"}},
    {"runnerName": "FORCE OF FORCES", "runnerNumber": 5,
     "fixedOdds": {"returnWin": 8, "returnWinTime": "2018-01-21T09:26:47.000Z", "returnWinOpen": 7.5,
                   "returnWinOpenDaily": 8.5, "returnPlace": 2.4, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795945, "differential": null,
                   "flucs": [{"returnWin": 8.5, "returnWinTime": "2018-01-21T09:23:44.000Z"},
                             {"returnWin": 8, "returnWinTime": "2018-01-21T09:21:50.000Z"},
                             {"returnWin": 8.5, "returnWinTime": "2018-01-21T09:17:48.000Z"},
                             {"returnWin": 8, "returnWinTime": "2018-01-21T09:16:08.000Z"}], "percentageChange": -6,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/LIGHT%20BLUE%2C%20RED%20BRACES%2C%20WHITE%20SLEEVES%2C%20RED%20ARMLET%2C%20LIGHT%20BLUE%20%26%20RED%20QUARTERED%20CAP",
     "trainerName": "W Mullins", "trainerFullName": "W P MULLINS", "barrierNumber": 5, "riderDriverName": "P Townend",
     "riderDriverFullName": "P TOWNEND", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "f08x", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 91, "techFormRating": 91, "totalRatingPoints": 2, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/5?jurisdiction=NSW"}},
    {"runnerName": "JETEZ", "runnerNumber": 6,
     "fixedOdds": {"returnWin": 2.25, "returnWinTime": "2018-01-21T10:03:58.000Z", "returnWinOpen": 2.6,
                   "returnWinOpenDaily": 2.3, "returnPlace": 1.28, "isFavouriteWin": true, "isFavouritePlace": true,
                   "bettingStatus": "Open", "propositionNumber": 795946, "differential": null,
                   "flucs": [{"returnWin": 2.3, "returnWinTime": "2018-01-21T09:53:42.000Z"},
                             {"returnWin": 2.4, "returnWinTime": "2018-01-21T09:38:44.000Z"},
                             {"returnWin": 2.3, "returnWinTime": "2018-01-21T09:23:44.000Z"},
                             {"returnWin": 2.4, "returnWinTime": "2018-01-21T08:46:35.000Z"}], "percentageChange": -2,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 22.2, "returnPlace": 9.7, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open", "marketMovers": [
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 5.1, "returnWinTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": 0},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/ORANGE%2C%20BLACK%20STAR%20%2C%20BLACK%20%26%20ORANGE%20HOOPED%20SLEEVES%2C%20ORANGE%20CAP%2C%20BLACK%20STAR",
     "trainerName": "Mrs J Harrington", "trainerFullName": "MRS JOHN HARRINGTON", "barrierNumber": 6,
     "riderDriverName": "R Power", "riderDriverFullName": "R M POWER", "handicapWeight": 72, "harnessHandicap": null,
     "blinkers": false, "claimAmount": -1, "last5Starts": "4x432", "tcdwIndicators": "c w", "emergency": false,
     "penalty": 0, "dfsFormRating": 95, "techFormRating": 95, "totalRatingPoints": 13, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/6?jurisdiction=NSW"}},
    {"runnerName": "LAST MAN STANDING", "runnerNumber": 7,
     "fixedOdds": {"returnWin": 6.5, "returnWinTime": "2018-01-21T10:15:06.000Z", "returnWinOpen": 5,
                   "returnWinOpenDaily": 6, "returnPlace": 2.1, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795947, "differential": null,
                   "flucs": [{"returnWin": 6, "returnWinTime": "2018-01-21T09:04:47.000Z"},
                             {"returnWin": 5.5, "returnWinTime": "2018-01-21T08:59:48.000Z"},
                             {"returnWin": 6, "returnWinTime": "2018-01-21T08:57:55.000Z"},
                             {"returnWin": 5.5, "returnWinTime": "2018-01-21T08:05:48.000Z"}], "percentageChange": 8,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 3.2, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/DARK%20BLUE", "trainerName": "M Morris",
     "trainerFullName": "M F MORRIS", "barrierNumber": 7, "riderDriverName": "D Russell",
     "riderDriverFullName": "D N RUSSELL", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "f44x", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 93, "techFormRating": 93, "totalRatingPoints": 2, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/7?jurisdiction=NSW"}},
    {"runnerName": "MISTY HOLLOW", "runnerNumber": 8,
     "fixedOdds": {"returnWin": 101, "returnWinTime": "2018-01-21T09:16:08.000Z", "returnWinOpen": 151,
                   "returnWinOpenDaily": 101, "returnPlace": 15.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "LateScratched", "propositionNumber": 795948, "differential": null,
                   "flucs": [{"returnWin": 126, "returnWinTime": "2018-01-21T08:55:18.000Z"},
                             {"returnWin": 151, "returnWinTime": "2018-01-21T08:10:17.000Z"},
                             {"returnWin": 126, "returnWinTime": "2018-01-21T08:09:02.000Z"},
                             {"returnWin": 151, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -20,
                   "allowPlace": false, "winDeduction": 0, "placeDeduction": 0,
                   "scratchedTime": "2018-01-21T10:00:13.000Z"},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Scratched"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/YELLOW%2C%20MAROON%20STARS%2C%20YELLOW%20%26%20EMERALD%20GREEN%20HOOPED%20SLEEVES%20%26%20CAP",
     "trainerName": "E Cawley", "trainerFullName": "EDWARD CAWLEY", "barrierNumber": 8, "riderDriverName": "C Timmons",
     "riderDriverFullName": "C D TIMMONS", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": 1.5, "last5Starts": "f07", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 67, "techFormRating": 67, "totalRatingPoints": 1, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/8?jurisdiction=NSW"}},
    {"runnerName": "SPEAKER CONNOLLY", "runnerNumber": 9,
     "fixedOdds": {"returnWin": 18, "returnWinTime": "2018-01-21T10:03:58.000Z", "returnWinOpen": 21,
                   "returnWinOpenDaily": 23, "returnPlace": 4, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795949, "differential": null,
                   "flucs": [{"returnWin": 19, "returnWinTime": "2018-01-21T10:01:43.000Z"},
                             {"returnWin": 18, "returnWinTime": "2018-01-21T09:55:19.000Z"},
                             {"returnWin": 19, "returnWinTime": "2018-01-21T09:47:47.000Z"},
                             {"returnWin": 21, "returnWinTime": "2018-01-21T09:43:25.000Z"}], "percentageChange": -5,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 9.7, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/YELLOW%2C%20DARK%20BLUE%20SASH%2C%20DARK%20BLUE%20CAP%2C%20YELLOW%20STAR",
     "trainerName": "A Fleming", "trainerFullName": "ALAN FLEMING", "barrierNumber": 8, "riderDriverName": "D O'Regan",
     "riderDriverFullName": "D O'REGAN", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "f58", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 78, "techFormRating": 78, "totalRatingPoints": 13, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/9?jurisdiction=NSW"}},
    {"runnerName": "DEVINE STAR", "runnerNumber": 10,
     "fixedOdds": {"returnWin": 126, "returnWinTime": "2018-01-21T10:03:58.000Z", "returnWinOpen": 201,
                   "returnWinOpenDaily": 126, "returnPlace": 18.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795950, "differential": null,
                   "flucs": [{"returnWin": 151, "returnWinTime": "2018-01-21T10:01:43.000Z"},
                             {"returnWin": 126, "returnWinTime": "2018-01-21T09:16:08.000Z"},
                             {"returnWin": 151, "returnWinTime": "2018-01-21T08:11:48.000Z"},
                             {"returnWin": 201, "returnWinTime": "2018-01-21T08:10:17.000Z"}], "percentageChange": -17,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/ROYAL%20BLUE%2C%20YELLOW%20EPAULETTES%2C%20HOOPED%20SLEEVES%2C%20YELLOW%20CAP%2C%20ROYAL%20BLUE%20STAR",
     "trainerName": "J Ryan", "trainerFullName": "JOHN PATRICK RYAN", "barrierNumber": 9,
     "riderDriverName": "C Landers", "riderDriverFullName": "C A LANDERS", "handicapWeight": 68.5,
     "harnessHandicap": null, "blinkers": false, "claimAmount": 3, "last5Starts": "f0", "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 59, "techFormRating": 59, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/10?jurisdiction=NSW"}},
    {"runnerName": "NO HOLDENBACK", "runnerNumber": 11,
     "fixedOdds": {"returnWin": 61, "returnWinTime": "2018-01-21T10:07:18.000Z", "returnWinOpen": 71,
                   "returnWinOpenDaily": 61, "returnPlace": 10.2, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795951, "differential": null,
                   "flucs": [{"returnWin": 71, "returnWinTime": "2018-01-21T10:03:58.000Z"},
                             {"returnWin": 61, "returnWinTime": "2018-01-21T09:55:19.000Z"},
                             {"returnWin": 51, "returnWinTime": "2018-01-21T09:33:07.000Z"},
                             {"returnWin": 61, "returnWinTime": "2018-01-21T09:16:08.000Z"}], "percentageChange": -14,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20WHITE%20CROSS%20OF%20LORRAINE%2C%20WHITE%20%26%20ORANGE%20HOOPED%20CAP",
     "trainerName": "A Leahy", "trainerFullName": "AUGUSTINE LEAHY", "barrierNumber": 10, "riderDriverName": "A Lynch",
     "riderDriverFullName": "A E LYNCH", "handicapWeight": 68.5, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "f6", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 70, "techFormRating": 70, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/11?jurisdiction=NSW"}},
    {"runnerName": "BUFFALO BLUES", "runnerNumber": 12,
     "fixedOdds": {"returnWin": 81, "returnWinTime": "2018-01-21T10:08:48.000Z", "returnWinOpen": 101,
                   "returnWinOpenDaily": 81, "returnPlace": 12.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795952, "differential": null,
                   "flucs": [{"returnWin": 101, "returnWinTime": "2018-01-21T10:03:58.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:16:08.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T08:15:57.000Z"},
                             {"returnWin": 126, "returnWinTime": "2018-01-21T08:13:18.000Z"}], "percentageChange": -20,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%20%26%20BLACK%20CHECK%2C%20BLACK%20SLEEVES%2C%20RED%20SEAMS%2C%20RED%20CAP%2C%20BLACK%20STAR",
     "trainerName": "P Fahy", "trainerFullName": "P A FAHY", "barrierNumber": 11, "riderDriverName": "C Leonard",
     "riderDriverFullName": "C LEONARD", "handicapWeight": 68, "harnessHandicap": null, "blinkers": false,
     "claimAmount": 3, "last5Starts": "4x097", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 75, "techFormRating": 75, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/12?jurisdiction=NSW"}},
    {"runnerName": "PETE SO HIGH", "runnerNumber": 13,
     "fixedOdds": {"returnWin": 8, "returnWinTime": "2018-01-21T09:55:19.000Z", "returnWinOpen": 7.5,
                   "returnWinOpenDaily": 8, "returnPlace": 2.4, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795953, "differential": null,
                   "flucs": [{"returnWin": 7.5, "returnWinTime": "2018-01-21T09:46:15.000Z"},
                             {"returnWin": 8, "returnWinTime": "2018-01-21T09:44:22.000Z"},
                             {"returnWin": 7.5, "returnWinTime": "2018-01-21T09:38:44.000Z"},
                             {"returnWin": 8, "returnWinTime": "2018-01-21T09:33:07.000Z"}], "percentageChange": 7,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 1.04, "returnPlace": 1, "isFavouriteWin": true, "isFavouritePlace": true,
                    "bettingStatus": "Open", "marketMovers": [
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 5.1, "returnWinTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": -95},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/MAROON%2C%20WHITE%20STAR%20%26%20ARMLET%2C%20MAROON%20CAP%2C%20WHITE%20STAR",
     "trainerName": "G Elliott", "trainerFullName": "GORDON ELLIOTT", "barrierNumber": 12,
     "riderDriverName": "J Kennedy", "riderDriverFullName": "JACK KENNEDY", "handicapWeight": 68,
     "harnessHandicap": null, "blinkers": false, "claimAmount": -1, "last5Starts": "1x334", "tcdwIndicators": "dw",
     "emergency": false, "penalty": 0, "dfsFormRating": 100, "techFormRating": 100, "totalRatingPoints": 11,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/13?jurisdiction=NSW"}},
    {"runnerName": "SAGLAWY", "runnerNumber": 14,
     "fixedOdds": {"returnWin": 4.2, "returnWinTime": "2018-01-21T10:01:43.000Z", "returnWinOpen": 3,
                   "returnWinOpenDaily": 4, "returnPlace": 1.7, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795954, "differential": null,
                   "flucs": [{"returnWin": 4, "returnWinTime": "2018-01-21T10:01:12.000Z"},
                             {"returnWin": 4.2, "returnWinTime": "2018-01-21T09:55:19.000Z"},
                             {"returnWin": 4, "returnWinTime": "2018-01-21T09:27:29.000Z"},
                             {"returnWin": 3.9, "returnWinTime": "2018-01-21T09:26:47.000Z"}], "percentageChange": 5,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20PINK%20HOOP%2C%20PINK%20ARMLET%2C%20RED%20CAP",
     "trainerName": "W Mullins", "trainerFullName": "W P MULLINS", "barrierNumber": 13, "riderDriverName": "D Mullins",
     "riderDriverFullName": "D J MULLINS", "handicapWeight": 68, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "3545x", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 99, "techFormRating": 99, "totalRatingPoints": 9, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/14?jurisdiction=NSW"}},
    {"runnerName": "CLASSICAL ROCK", "runnerNumber": 15,
     "fixedOdds": {"returnWin": 81, "returnWinTime": "2018-01-21T08:59:48.000Z", "returnWinOpen": 71,
                   "returnWinOpenDaily": 81, "returnPlace": 12.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795955, "differential": null,
                   "flucs": [{"returnWin": 101, "returnWinTime": "2018-01-21T08:57:55.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T08:56:01.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T04:16:18.000Z"},
                             {"returnWin": 71, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -20,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 22.2, "returnPlace": 2.4, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open", "marketMovers": [
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 22.2, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 5.1, "returnWinTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": 0},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/YELLOW%2C%20ROYAL%20BLUE%20TRIPLE%20DIAMOND%2C%20ROYAL%20BLUE%20DIAMONDS%20ON%20SLEEVES%2C%20YELLOW%20CAP%2C%20ROYAL%20BLUE%20DIAMONDS",
     "trainerName": "B McMahon", "trainerFullName": "BRIAN M MCMAHON", "barrierNumber": 14,
     "riderDriverName": "J Slevin", "riderDriverFullName": "J J SLEVIN", "handicapWeight": 66, "harnessHandicap": null,
     "blinkers": false, "claimAmount": -1, "last5Starts": "6x508", "tcdwIndicators": null, "emergency": false,
     "penalty": 0, "dfsFormRating": 61, "techFormRating": 61, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/15?jurisdiction=NSW"}},
    {"runnerName": "I'VE GOT RHYTHM", "runnerNumber": 16,
     "fixedOdds": {"returnWin": 81, "returnWinTime": "2018-01-21T10:08:48.000Z", "returnWinOpen": 71,
                   "returnWinOpenDaily": 81, "returnPlace": 12.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795956, "differential": null,
                   "flucs": [{"returnWin": 101, "returnWinTime": "2018-01-21T10:03:58.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:16:08.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T08:50:21.000Z"},
                             {"returnWin": 126, "returnWinTime": "2018-01-21T08:09:02.000Z"}], "percentageChange": -20,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/DARK%20BLUE%2C%20WHITE%20SEAMS%2C%20WHITE%20SPOTS%20ON%20CAP",
     "trainerName": "C O'Dwyer", "trainerFullName": "CONOR O'DWYER", "barrierNumber": 15, "riderDriverName": "R Doyle",
     "riderDriverFullName": "R A DOYLE", "handicapWeight": 66, "harnessHandicap": null, "blinkers": false,
     "claimAmount": 2.5, "last5Starts": "x8x00", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 69, "techFormRating": 69, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/16?jurisdiction=NSW"}},
    {"runnerName": "PERMANENT", "runnerNumber": 17,
     "fixedOdds": {"returnWin": 81, "returnWinTime": "2018-01-21T10:03:58.000Z", "returnWinOpen": 101,
                   "returnWinOpenDaily": 81, "returnPlace": 12.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795957, "differential": null,
                   "flucs": [{"returnWin": 101, "returnWinTime": "2018-01-21T10:01:43.000Z"},
                             {"returnWin": 81, "returnWinTime": "2018-01-21T09:26:47.000Z"},
                             {"returnWin": 101, "returnWinTime": "2018-01-21T08:55:18.000Z"},
                             {"returnWin": 151, "returnWinTime": "2018-01-21T08:05:48.000Z"}], "percentageChange": -20,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 11.1, "returnPlace": 4.8, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open", "marketMovers": [
             {"returnWin": 11.1, "returnWinTime": "2018-01-21T09:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 11.1, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 11.1, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 2.5, "returnWinTime": "2018-01-21T08:19:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": 0},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/GREY%2C%20DARK%20GREEN%20EPAULETTES%2C%20DARK%20GREEN%20CAP%2C%20GREY%20STAR",
     "trainerName": "B Cawley", "trainerFullName": "BRIAN FRANCIS CAWLEY", "barrierNumber": 16,
     "riderDriverName": "M Enright", "riderDriverFullName": "M ENRIGHT", "handicapWeight": 66, "harnessHandicap": null,
     "blinkers": false, "claimAmount": -1, "last5Starts": "60005", "tcdwIndicators": null, "emergency": false,
     "penalty": 0, "dfsFormRating": 63, "techFormRating": 63, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/17?jurisdiction=NSW"}},
    {"runnerName": "NISIOR DONN", "runnerNumber": 18,
     "fixedOdds": {"returnWin": 126, "returnWinTime": "2018-01-21T10:03:58.000Z", "returnWinOpen": 201,
                   "returnWinOpenDaily": 126, "returnPlace": 18.8, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "Open", "propositionNumber": 795958, "differential": null,
                   "flucs": [{"returnWin": 151, "returnWinTime": "2018-01-21T10:01:43.000Z"},
                             {"returnWin": 126, "returnWinTime": "2018-01-21T09:19:18.000Z"},
                             {"returnWin": 151, "returnWinTime": "2018-01-21T08:50:21.000Z"},
                             {"returnWin": 201, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -17,
                   "allowPlace": false},
     "parimutuel": {"returnWin": 0, "returnPlace": 4.8, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Open"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/BLACK%2C%20RED%20STARS%20ON%20SLEEVES%2C%20HOOPED%20CAP",
     "trainerName": "P Downey", "trainerFullName": "PATRICK DOWNEY", "barrierNumber": 17, "riderDriverName": "R Colgan",
     "riderDriverFullName": "R C COLGAN", "handicapWeight": 62.5, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": "f0x7x", "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 64, "techFormRating": 64, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/18?jurisdiction=NSW"}},
    {"runnerName": "PHYSICIST", "runnerNumber": 19,
     "fixedOdds": {"returnWin": 41, "returnWinTime": "2018-01-21T08:52:15.000Z", "returnWinOpen": 41,
                   "returnWinOpenDaily": 41, "returnPlace": 7.6, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "LateScratched", "propositionNumber": 795959, "differential": null,
                   "flucs": [{"returnWin": 51, "returnWinTime": "2018-01-21T08:10:17.000Z"},
                             {"returnWin": 41, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -20,
                   "allowPlace": false, "winDeduction": 0, "placeDeduction": 0,
                   "scratchedTime": "2018-01-21T09:16:04.000Z"},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Scratched"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/DARK%20BLUE%2C%20ORANGE%20SEAMS%2C%20ORANGE%20CAP%2C%20DARK%20BLUE%20SPOTS",
     "trainerName": "P Griffin", "trainerFullName": "PATRICK GRIFFIN", "barrierNumber": 19,
     "riderDriverName": "N Notified", "riderDriverFullName": "NOT NOTIFIED", "handicapWeight": 66,
     "harnessHandicap": null, "blinkers": false, "claimAmount": 3, "last5Starts": "20x06", "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 85, "techFormRating": 85, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/19?jurisdiction=NSW"}},
    {"runnerName": "MYANNE", "runnerNumber": 20,
     "fixedOdds": {"returnWin": 51, "returnWinTime": "2018-01-21T08:55:18.000Z", "returnWinOpen": 61,
                   "returnWinOpenDaily": 51, "returnPlace": 9.1, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "LateScratched", "propositionNumber": 795960, "differential": null,
                   "flucs": [{"returnWin": 61, "returnWinTime": "2018-01-21T08:01:19.000Z"},
                             {"returnWin": 71, "returnWinTime": "2018-01-21T07:49:18.000Z"},
                             {"returnWin": 61, "returnWinTime": "2018-01-21T07:41:48.000Z"},
                             {"returnWin": 71, "returnWinTime": "2018-01-21T07:24:45.000Z"}], "percentageChange": -16,
                   "allowPlace": false, "winDeduction": 0, "placeDeduction": 0,
                   "scratchedTime": "2018-01-21T09:16:05.000Z"},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Scratched"},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/RED%2C%20EMERALD%20GREEN%20STARS%2C%20RED%20SLEEVES%2C%20STRIPED%20CAP",
     "trainerName": "A Slattery", "trainerFullName": "ANDREW SLATTERY", "barrierNumber": 20,
     "riderDriverName": "N Notified", "riderDriverFullName": "NOT NOTIFIED", "handicapWeight": 68.5,
     "harnessHandicap": null, "blinkers": false, "claimAmount": -1, "last5Starts": null, "tcdwIndicators": null,
     "emergency": false, "penalty": 0, "dfsFormRating": 0, "techFormRating": 0, "totalRatingPoints": 0,
     "earlySpeedRating": 0, "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/20?jurisdiction=NSW"}},
    {"runnerName": "SIZING JOSHUA", "runnerNumber": 21,
     "fixedOdds": {"returnWin": 12, "returnWinTime": "2018-01-21T08:55:18.000Z", "returnWinOpen": 13,
                   "returnWinOpenDaily": 12, "returnPlace": 3.2, "isFavouriteWin": false, "isFavouritePlace": false,
                   "bettingStatus": "LateScratched", "propositionNumber": 795961, "differential": null,
                   "flucs": [{"returnWin": 13, "returnWinTime": "2018-01-21T03:06:08.000Z"}], "percentageChange": -8,
                   "allowPlace": false, "winDeduction": 6, "placeDeduction": 0,
                   "scratchedTime": "2018-01-21T09:16:06.000Z"},
     "parimutuel": {"returnWin": 0, "returnPlace": 0, "isFavouriteWin": false, "isFavouritePlace": false,
                    "bettingStatus": "Scratched", "marketMovers": [
             {"returnWin": 1.1, "returnWinTime": "2018-01-21T09:19:53.000Z", "specialDisplayIndicator": false},
             {"returnWin": 1.1, "returnWinTime": "2018-01-21T08:49:53.000Z", "specialDisplayIndicator": false}],
                    "percentageChange": -100},
     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/EMERALD%20GREEN%2C%20YELLOW%20WIDE%20VEE%20%26%20SLEEVES%2C%20RED%20CAP",
     "trainerName": "M Morris", "trainerFullName": "M F MORRIS", "barrierNumber": 21, "riderDriverName": "N Notified",
     "riderDriverFullName": "NOT NOTIFIED", "handicapWeight": 72, "harnessHandicap": null, "blinkers": false,
     "claimAmount": -1, "last5Starts": null, "tcdwIndicators": null, "emergency": false, "penalty": 0,
     "dfsFormRating": 0, "techFormRating": 0, "totalRatingPoints": 0, "earlySpeedRating": 0,
     "earlySpeedRatingBand": "BACKMARKER", "_links": {
        "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2018-01-21/meetings/R/TRS/races/1/form/21?jurisdiction=NSW"}}],
    "oddsUpdateTime": "2018-01-21T10:06:23.000Z", "fixedOddsUpdateTime": "2018-01-21T10:15:06.000Z",
    "tips": {"tipType": "Standard", "tipster": "Computaform UK", "tipRunnerNumbers": [6, 14, 13]},
    "ratings": [{"ratingType": "Rating", "ratingRunnerNumbers": [13, 14, 6, 7]},
                {"ratingType": "Last12Months", "ratingRunnerNumbers": [9, 3, 6, 14]},
                {"ratingType": "Recent", "ratingRunnerNumbers": [9, 3, 6, 2]},
                {"ratingType": "Distance", "ratingRunnerNumbers": [9, 3, 5, 6]},
                {"ratingType": "Class", "ratingRunnerNumbers": [13, 14, 6, 9]},
                {"ratingType": "Time", "ratingRunnerNumbers": [6, 13, 14, 7]},
                {"ratingType": "Overall", "ratingRunnerNumbers": [6, 9, 13, 3]}], "multiLegApproximates": [],
    "betTypes": [{"wageringProduct": "Win", "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "Place", "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "Quinella",
                  "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "Exacta", "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "Duet", "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "Trifecta",
                  "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}},
                 {"wageringProduct": "RunningDouble",
                  "firstLeg": {"raceNumber": 1, "venueMnemonic": "TRS", "raceType": "R"}}]}
'''
