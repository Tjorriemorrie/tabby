import datetime
import logging
import re

import requests
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Meeting, Race, Result, RunnerMeta

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
                'link_form': item['_links'].get('form'),
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
def monitor_race(pk):
    """Monitor the race"""
    logger.info(f'Monitoring race id {pk}')
    race = Race.objects.get(id=pk)
    logger.info(f'self url = {race.link_self}')
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
    race.number_of_places = res.get('numberOfPlaces')
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
        minutes = 9
        if delta.seconds > 60 * minutes:
            logger.warning(f'{race.meeting.name} {race.number}: is more than few minutes away, waiting till then')
            countdown = delta.seconds - (60 * minutes)
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
    add_meta()


@shared_task
def add_meta():
    """create runner metas for unprocessed races"""
    # fetch all unprocessed races
    races = Race.objects.filter(
        has_results=True).filter(
        has_processed=False).all()

    for race in races:
        for runner in race.runner_set.all():
            result = runner.result if hasattr(runner, 'result') else None
            odds = runner.fixedodd_set.first()
            if not odds:
                logger.warning(f'No fixed odds for {runner}')
                continue
            runner_meta, created = RunnerMeta.objects.update_or_create(
                race=race,
                runner=runner,
                defaults={
                    'win_odds': odds.win_perc,
                    'place_odds': odds.place_perc,
                    'rating': runner.dfs_form_rating / 100,
                    'won': result.won if result else False,
                    'placed': result.placed if result else False,
                })
            if created:
                logger.info(f'Created {runner_meta}')

        race.has_processed = True
        race.save()
        logger.warning(f'Created meta for {race} runners')
    logger.warning(f'>>>> Task add_meta finished for {len(races)} races')
    return len(races)


@shared_task
def cleanup():
    race_cleanup()
    meeting_cleanup()


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
        logger.warning(f'Deleted race: {r}')
    logger.warning(f'>>>> Race cleanup done on {len(races)} objects')


@shared_task
def meeting_cleanup():
    """Delete meeting without any races"""
    meetings = Meeting.objects.all()
    for meeting in meetings:
        if not meeting.race_set.count():
            logger.info(f'Delete empty meeting {meeting}')
    logger.warning(f'>>>> Meeting cleanup done on {len(meetings)} objects')
