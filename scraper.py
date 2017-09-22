import json
import logging
import time

import arrow
import requests
from sqlalchemy.orm.exc import NoResultFound
from terminaltables import SingleTable

from model import Race, save_race, list_race_dates
from predict import add_predictions, add_scaled_odds, add_probabilities, NoRunnersError
from simulate import bet_positive_dutch_R, bet_positive_dutch

logger = logging.getLogger(__name__)


# race data
data = {}


def next_to_go(debug, oncely, balance):
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('next to go!')

    # infinitely get next to go
    while True:

        update_races()
        next_race = get_next_race()
        next_race['status'] = 'betting'

        # skip the woofies and harnessies
        # if next_race['meeting']['raceType'] not in ['R', 'G']:
        #     logger.info('skipping {}'.format(next_race['meeting']['meetingName']))
        #     continue

        if not oncely:
            try:
                wait_for_next(next_race)
            except KeyError as e:
                logger.error(e)
                continue

        # get latest race odds
        details = get_details(next_race)

        # refresh latest odds
        # if not oncely:
        #     wait_for_update(details)

        # update details (aka runners odds)
        details = get_details(next_race)
        runners = details['runners']

        # add probability (do not delete or skip keyerrors here)
        add_scaled_odds(runners)
        try:
            add_predictions(runners, next_race['meeting']['raceType'])
        except NoRunnersError:
            logger.warning('No runners for {}'.format(details['meeting']['meetingName']))
            continue
        add_probabilities(runners)

        # drop scratched
        runners = [r for r in runners if r['odds_win']]
        if not runners:
            continue

        # add bet
        balance = int(input('Bet now on, give balance: '))
        bet_chunk = balance * 0.05
        if next_race['meeting']['raceType'] == 'R':
            x = [0.86783405, 1.22605065]
            runners, num_bets = bet_positive_dutch(runners, bet_chunk, x)
        elif next_race['meeting']['raceType'] == 'G':
            x = [2.34375000e-05, 1.16268092e+00]
            runners, num_bets = bet_positive_dutch(runners, bet_chunk, x)
        elif next_race['meeting']['raceType'] == 'H':
            x = [1.95119191, 1.14682542]
            runners, num_bets = bet_positive_dutch(runners, bet_chunk, x)
        else:
            logger.error('Unknown race type {}'.format(next_race['meeting']['raceType']))
            continue

        if not runners:
            logger.warning('No bettable runners on {} {}'.format(
                details['meeting']['meetingName'], details['raceNumber']))
            continue

        race_table = [['Type', 'Meeting', 'Race', '#', 'Start Time', 'status']]
        cnt = 0
        for race in list(data.values()):
            if race['status'] == 'upcoming':
                cnt += 1
                race_table.append([
                    race['meeting']['raceType'],
                    race['meeting']['meetingName'],
                    race['raceName'],
                    race['raceNumber'],
                    race['raceStartTime'].humanize(),
                    race['status']
                ])
            if cnt > 6:
                break
        print('\n')
        print(SingleTable(race_table, title='Races').table)

        runner_table = [['Name', 'Fixed', '#', 'Prob', 'Bet', 'PP']]
        for runner in runners:
            pp = runner['bet'] * runner['odds_win'] - bet_chunk
            runner_table.append([
                runner['runnerName'],
                '{} - {:.0f}%'.format(runner['odds_win'], runner['odds_scale'] * 100),
                runner['runnerNumber'],
                '{:.0f}%'.format(runner['probability'] * 100),
                runner['bet'] and '{:.2f}'.format(runner['bet']) or '-',
                '{:.2f}'.format(pp),
            ])
        print('\n')
        print(SingleTable(runner_table, title='{} {} {}'.format(
            next_race['meeting']['raceType'], next_race['meeting']['meetingName'], next_race['raceNumber'])).table)

        if oncely:
            return
        time.sleep(15)


def update_races():
    url = 'https://api.beta.tab.com.au/v1/tab-info-service/racing/next-to-go/races?jurisdiction=NSW'
    logger.debug('scraping {}'.format(url))
    res = requests.get(url)
    res.raise_for_status()
    res = res.json()
    races = res['races']
    logger.debug('{} races scraped'.format(len(races)))

    for race in races:
        key = '{}_{}'.format(race['meeting']['meetingName'], race['raceNumber'])
        if key not in data:
            logger.debug('adding {} to data'.format(key))
            race['raceStartTime'] = arrow.get(race['raceStartTime'])
            race['status'] = 'upcoming'
            data[key] = race


def get_next_race():
    """get next upcoming race"""
    next_race = None
    start = None
    for key, race in data.items():
        if race['status'] == 'upcoming':
            # logger.debug('next race? {} R{} {}'.format(
            #     race['meeting']['meetingName'], race['raceNumber'], race['raceStartTime']))
            if next_race is None:
                next_race = race
                start = race['raceStartTime']
            elif race['raceStartTime'] < start:
                next_race = race
                start = race['raceStartTime']
    logger.info('next race {} R{} start at {}'.format(
        next_race['meeting']['meetingName'], next_race['raceNumber'], start))
    return next_race


def wait_for_next(race):
    """Wait for the next race to be close to starting"""
    logger.info('Waiting on {} {}'.format(race['meeting']['meetingName'], race['raceNumber']))
    logger.debug('next start time {}'.format(race['raceStartTime']))
    while True:
        time_to_sleep = race['raceStartTime'] - arrow.utcnow().shift(seconds=30)
        logger.debug('time to sleep {} (or {:.0f}s)'.format(time_to_sleep, time_to_sleep.total_seconds()))
        if time_to_sleep.total_seconds() < 0:
            break
        time.sleep(min(30, time_to_sleep.total_seconds()))


def get_details(race):
    """Get details (aka runners) for race"""
    # runners
    res = requests.get(race['_links']['self'])
    res.raise_for_status()
    res = res.json()
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))
    # raise Exception('get_details')
    return res


def wait_for_update(details):
    """Wait on next update of fixed odds"""
    details['fixedOddsUpdateTime'] = arrow.get(details['fixedOddsUpdateTime'])
    logger.debug('next fixed odds update time {}'.format(details['fixedOddsUpdateTime']))
    time_to_sleep = details['fixedOddsUpdateTime'] - arrow.utcnow()
    logger.debug('time to sleep {} (or {:.0f}s)'.format(time_to_sleep, time_to_sleep.total_seconds()))
    time.sleep(max(0, time_to_sleep.total_seconds()))


def get_forms(race):
    # form of runners
    res = requests.get(race['_links']['form'])
    res.raise_for_status()
    res = res.json()
    forms = res['form']
    logger.info('{} runners'.format(len(forms)))
    # print(json.dumps(forms, indent=4, default=str, sort_keys=True))
    # raise Exception('')
    return forms


def persist_forms(race, forms):
    for form in forms:
        # print(json.dumps(runner, indent=4, default=str, sort_keys=True))

        # GRAYHOUND
        # "age": 2,
        # "bestTime": "29.44",
        # "blinkers": false,
        # "colour": "BK",
        # "dam": "LEES LEGEND",
        # "dateOfBirth": "0315",
        # "daysSinceLastRun": 15,
        # "formComment": "Finished 5.8 lengths 6th (29.68) on August 28 at Nottingham over 480m in an Or race beaten by Calling Tyler. Previously finished 12 lengths 5th (18.36) on August 21 at Nottingham over 305m in an Or race beaten by Roxholme Hat. Comes in well.",
        # "handicapWeight": 0,
        # "last20Starts": "f1442x56",
        # "prizeMoney": null,
        # "runnerName": "DAYLENS RONALDO",
        # "runnerNumber": 1,
        # "runnerStarts": {
        #     "previousStarts": [
        #         {
        #             "class": "OR",
        #             "distance": 480,
        #             "draw": 0,
        #             "finishingPosition": "6",
        #             "handicap": "0",
        #             "margin": "5.8",
        #             "numberOfStarters": 6,
        #             "odds": "11.00",
        #             "positionInRun": null,
        #             "raceNumber": 5,
        #             "startDate": "2017-08-28",
        #             "startType": "LastStarts",
        #             "startingPosition": 3,
        #             "stewardsComment": "CRD1&3",
        #             "time": "29.68",
        #             "venueAbbreviation": "NOTT",
        #             "weight": 33.7,
        #             "winnerOrSecond": "CALLING TYLER"
        #         },

        form['runnerName'] = form['runnerName'].upper()
        previous_starts = form['runnerStarts']['previousStarts']
        logger.debug('{} previous starts'.format(len(previous_starts)))

        if not previous_starts:
            continue

        for previous_start in previous_starts:
            # print(json.dumps(previous_start, indent=4, default=str, sort_keys=True))

            # exists?
            previous_start['startDate'] = arrow.get(previous_start['startDate']).datetime
            print(previous_start['startDate'])
            sql = db_session.query(Race).filter(
                Race.runner_name == form['runnerName'],
                Race.raced_at == previous_start['startDate'],
                Race.race_number == previous_start['raceNumber'])
            # logger.info('sql: {}'.format(sql))
            try:
                existing_run = sql.one()
                logger.debug('existing run: {}'.format(existing_run))
            except NoResultFound:
                logger.debug('None existing found')

                try:
                    existing_run = Race(**{
                        'race_type': race['meeting']['raceType'],
                        'runner_name': form['runnerName'],
                        'sire': form['sire'],
                        'dam': form['dam'],
                        'age': form['age'],
                        'sex': form['sex'],
                        'colour': form['colour'],
                        'trainer': form['trainerName'],
                        'trainer_location': form['trainerLocation'],

                        'start_type': previous_start['startType'],
                        'raced_at': previous_start['startDate'],
                        'race_number': previous_start['raceNumber'],
                        'finishing_position': previous_start['finishingPosition'],
                        'number_of_starters': previous_start['numberOfStarters'],
                        'draw': previous_start['draw'],
                        'margin': previous_start['margin'],
                        'venue': previous_start['venueAbbreviation'],
                        'distance': previous_start['distance'],
                        'class_': previous_start['class'],
                        'handicap': previous_start.get('handicap'),
                        'rider': previous_start.get('rider'),
                        'starting_position': previous_start['startingPosition'],
                        'odds': previous_start['odds'],
                        'winner_or_second': previous_start['winnerOrSecond'],
                        'position_in_run': previous_start['positionInRun'],
                        'track_condition': previous_start.get('trackCondition'),  # R
                    })
                except Exception:
                    print(json.dumps(form, indent=4, default=str, sort_keys=True))
                    print(json.dumps(previous_start, indent=4, default=str, sort_keys=True))
                    raise

                if 'skyRacing' in previous_start:
                    existing_run.audio = previous_start['skyRacing'].get('audio'),
                    if existing_run.audio and hasattr(existing_run.audio, '__iter__'):
                        # logger.info(existing_race.audio)
                        existing_run.audio = existing_run.audio[0]
                    existing_run.video = previous_start['skyRacing'].get('video'),
                    if existing_run.video and hasattr(existing_run.video, '__iter__'):
                        # logger.info(existing_race.video)
                        existing_run.video = existing_run.video[0]
                        # raise Exception('x')
                existing_run.time_from_string(previous_start['time'])

                # must save now before duplicates are saved
                logger.debug('saving {} {} {}'.format(
                    form['runnerName'], previous_start['startDate'], previous_start['raceNumber']))
                db_session.add(existing_run)

        # end of all previous races
    # end of all horses


####################################################################################
# scrape history results
####################################################################################

def scrape_history(debug, lst, dt_target, predict):
    """scrape yesterday results and predict and save it"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('get results!')

    # list result dates
    if lst:
        for dt in list_race_dates():
            logger.info('Date: {}'.format(dt))
        return

    dt_target = dt_target and arrow.get(dt_target) or arrow.now().shift(days=-1)
    logger.debug(f'Date target = {dt_target}')

    # scrape yesterday's races
    url = 'https://api.beta.tab.com.au/v1/historical-results-service/NSW/racing/{}'.format(
        dt_target.format('YYYY-MM-DD'))
    logger.info('Scraping {}'.format(url))

    meetings = requests.get(url)
    meetings.raise_for_status()
    meetings = meetings.json()
    logger.info('Found {} results'.format(len(meetings)))
    # print(json.dumps(meetings, indent=4, default=str, sort_keys=True))
    # raise Exception('')

    for meeting in meetings['meetings']:
        logger.info('Processing meeting {}'.format(meeting['meetingName']))

        for race_basic in meeting['races']:
            logger.info('Processing race {} {}'.format(race_basic['raceName'], race_basic['raceNumber']))

            url = race_basic['_links']['self']
            logger.info('Scraping race {}'.format(url))
            race = requests.get(url)
            race.raise_for_status()
            race = race.json()
            # print(json.dumps(race, indent=4, default=str, sort_keys=True))
            # raise Exception('')

            runners = race['runners']
            try:
                add_scaled_odds(runners)
                if race['meeting']['raceType'] in predict:
                    race['num_runners'] = add_predictions(runners, race['meeting']['raceType'])
                    add_probabilities(runners)
            except (KeyError, ZeroDivisionError) as e:
                logger.error(e)
            else:
                save_race(race)


####################################################################################
# meeting
####################################################################################

# race types
# race['meeting']['raceType'] can be R, G, H
# race_types = Counter()
# for race in races:
#     race_types.update(race['meeting']['raceType'])
# logger.info('Race types: {}'.format(race_types.most_common()))
#     print(json.dumps(race, indent=4, default=str))
# {
#     "raceStartTime": "2017-09-12T07:34:00.000Z",
#     "raceNumber": 6,
#     "raceName": "CORDINA CHICKENS PACE MS",
#     "raceDistance": 1609,
#     "broadcastChannel": "Sky Racing 1",
#     "broadcastChannels": [
#         "Sky Racing 1"
#     ],
#     "meeting": {
#         "sellCode": {
#             "meetingCode": "S",
#             "scheduledType": "H"
#         },
#         "raceType": "H",
#         "meetingName": "MENANGLE",
#         "location": "NSW",
#         "weatherCondition": "FINE",
#         "trackCondition": "FAST",
#         "railPosition": null,
#         "venueMnemonic": "MEN",
#         "meetingDate": "2017-09-12"
#     },
#     "_links": {
#         "self": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6?jurisdiction=NSW",
#         "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6/form?jurisdiction=NSW",
#         "bigBets": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6/big-bets?jurisdiction=NSW"
#     }
# }


####################################################################################
# runner
####################################################################################

    # {
#     "_links": {
#         "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/G/GOS/races/7/form/1?jurisdiction=NSW"
#     },
#     "barrierNumber": 1,
#     "blinkers": false,
#     "claimAmount": 0,
#     "dfsFormRating": 96,
#     "earlySpeedRating": 87,
#     "earlySpeedRatingBand": "LEADER",
#     "emergency": false,
#     "fixedOdds": {
#         "allowPlace": true,
#         "bettingStatus": "Open",
#         "differential": null,
#         "flucs": [
#             {
#                 "returnWin": 2.6,
#                 "returnWinTime": "2017-09-12T10:38:45.000Z"
#             },
#             {
#                 "returnWin": 2.7,
#                 "returnWinTime": "2017-09-12T10:35:26.000Z"
#             },
#             {
#                 "returnWin": 2.8,
#                 "returnWinTime": "2017-09-12T07:57:21.000Z"
#             }
#         ],
#         "isFavouritePlace": true,
#         "isFavouriteWin": true,
#         "percentageChange": 4,
#         "propositionNumber": 165951,
#         "returnPlace": 1.3,
#         "returnWin": 2.7,
#         "returnWinOpen": 2.8,
#         "returnWinOpenDaily": 2.8,
#         "returnWinTime": "2017-09-12T10:48:05.000Z"
#     },
#     "handicapWeight": 0,
#     "harnessHandicap": null,
#     "last5Starts": "43341",
#     "parimutuel": {
#         "bettingStatus": "Open",
#         "isFavouritePlace": false,
#         "isFavouriteWin": false,
#         "marketMovers": [
#             {
#                 "returnWin": 4.2,
#                 "returnWinTime": "2017-09-12T10:52:24.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 4.5,
#                 "returnWinTime": "2017-09-12T10:51:44.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 4.4,
#                 "returnWinTime": "2017-09-12T10:50:38.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 3.8,
#                 "returnWinTime": "2017-09-12T10:49:41.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 5.2,
#                 "returnWinTime": "2017-09-12T10:39:39.000Z",
#                 "specialDisplayIndicator": true
#             }
#         ],
#         "percentageChange": -17,
#         "returnPlace": 1.3,
#         "returnWin": 3.5
#     },
#     "penalty": 0,
#     "riderDriverFullName": null,
#     "riderDriverName": "",
#     "runnerName": "LIBERTY LEE",
#     "runnerNumber": 1,
#     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/1",
#     "tcdwIndicators": "TCD",
#     "techFormRating": 0,
#     "totalRatingPoints": 17,
#     "trainerFullName": "BETTY KEENE",
#     "trainerName": "B Keene"
# },


