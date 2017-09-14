from operator import attrgetter, itemgetter
import json
import logging
import time
from os import path

import arrow
import numpy as np
import requests
from collections import Counter
from keras.models import load_model
from sqlalchemy.orm.exc import NoResultFound
from terminaltables import SingleTable

from model import Race, save_race, load_races
from predict import predict

logger = logging.getLogger(__name__)


FILE_NEXT_TO_GO = path.join(path.dirname(path.abspath(__file__)), 'next_to_go.pkl')

# returns a compiled model
# identical to the previous one
model_default = None

# race data
data = {}


def next_to_go(debug, simulate):
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('next to go!')

    model_default = load_model('model_default.h5')

    # infinitely get next to go
    while True:
        bet_amount = 40

        update_races()
        race = get_next_race()
        race['status'] = 'betting'
        wait_for_next(race)

        # get latest race odds
        details = get_details(race)
        if not details['willHaveFixedOdds'] or not details['fixedOddsOnlineBetting']:
            race['status'] = 'no odds'
            logger.warning('No fixed odds for {}'.format(details['raceName']))
            continue

        # save forms training data
        forms = get_forms(race)
        persist_forms(race, forms)

        # refresh latest odds
        wait_for_update(details)
        details = get_details(race)

        # runners odds
        add_predictions(details)
        add_probabilities(details)

        # get results


        race_table = [['Type', 'Meeting', 'Race', '#', 'Start Time', 'status']]
        for race in list(data.values())[:-20]:
            race_table.append([
                race['meeting']['raceType'],
                race['meeting']['meetingName'],
                race['raceName'],
                race['raceNumber'],
                race['raceStartTime'].humanize(),
                race['status']
            ])
        print('\n')
        print(SingleTable(race_table, title='Races').table)

        runner_table = [['#', 'Name', 'Prob', 'Take', 'Odds']]
        for runner in details['runners']:
            runner_table.append([
                runner['runnerNumber'],
                runner['runnerName'],
                '{:.0f}%'.format(runner['probability'] * 100),
                runner['odds_taken'],
                '{:.0f}%'.format(runner['odds'] * 100),
            ])
        print('\n')
        print(SingleTable(runner_table, title='{} {} {}'.format(
            race['meeting']['meetingName'], race['raceName'], race['raceNumber'])).table)

        return


def add_probabilities(details):
    # get total
    total = sum([r['prediction'] for r in details['runners']])
    logger.debug('total prediction = {}'.format(total))

    # scale predictions
    for runner in details['runners']:
        runner['probability'] = runner['prediction'] / total
        logger.debug('prob = {}'.format(runner['probability']))
        if not runner['probability'] or not runner['fixedOdds']['returnWin']:
            runner['odds_taken'] = 'out'
            runner['odds'] = 0
            continue

        # is odds favourable?
        odds = 1 / runner['fixedOdds']['returnWin']
        odds_taken = 'fixed'
        if runner['parimutuel']['bettingStatus'] == 'Open':
            tote_odds = 1 / runner['parimutuel']['returnWin']
            if tote_odds > odds:
                odds_taken = 'tote'
                odds = tote_odds
        runner['odds_taken'] = odds_taken
        runner['odds'] = odds

def add_predictions(details):
    # select specific model
    model = model_default
    race_type = details['meeting']['raceType']

    # get num runners
    num_runners = sum([r['fixedOdds']['bettingStatus'] == 'Open' for r in details['runners']])
    logger.debug('{} runners'.format(num_runners))

    # make prediction for each runner separately
    for runner in details['runners']:
        prediction = 0
        if runner['fixedOdds']['bettingStatus'] == 'Open':
            data = [(runner['fixedOdds']['returnWin'], num_runners)]
            logger.debug('data = {}'.format(data))
            preds = model.predict(np.array(data))
            prediction = sum(preds[0])
        elif runner['fixedOdds']['bettingStatus'] == 'LateScratched':
            logger.debug('runner scratched')
        else:
            raise ValueError('unknown status {}'.format(runner['fixedOdds']['bettingStatus']))
        runner['prediction'] = prediction
        logger.debug('prediction = {}'.format(runner['prediction']))

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



def update_races():
    url = 'https://api.beta.tab.com.au/v1/tab-info-service/racing/next-to-go/races?jurisdiction=NSW'
    logger.debug('scraping {}'.format(url))
    res = requests.get(url)
    res.raise_for_status()
    res = res.json()
    races = res['races']
    logger.debug('{} races scraped'.format(len(races)))

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

    for race in races:
        key = '{}_{}'.format(race['raceName'], race['raceNumber'])
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
            if next_race is None:
                next_race = race
                start = race['raceStartTime']
            elif race['raceStartTime'] < start:
                next_race = race
                start = race['raceStartTime']
    logger.debug('next race {} start at {}'.format(next_race['raceName'], start))

    # if not saved_meeting:
    #     res = requests.get(new_race['_links']['self'])
    #     res.raise_for_status()
    #     res = res.json()
    #     print(json.dumps(res, indent=4, default=str, sort_keys=True))
    #     with open(FILE_NEXT_TO_GO, 'wb') as f:
    #         pickle.dump(res, f)
    #     saved_meeting = True
    return next_race


def wait_for_next(race):
    logger.debug('next start time {}'.format(race['raceStartTime']))
    now_one_min = arrow.utcnow().shift(minutes=1)
    logger.debug('now one min {}'.format(now_one_min))
    time_to_sleep = race['raceStartTime'] - now_one_min
    logger.debug('time to sleep {} (or {}s)'.format(time_to_sleep, time_to_sleep.total_seconds()))
    # time.sleep(max(0, time_to_sleep.total_seconds()))


def get_details(race):
    # runners
    res = requests.get(race['_links']['self'])
    res.raise_for_status()
    res = res.json()
    print(json.dumps(res, indent=4, default=str, sort_keys=True))
    # raise Exception('what is out of race look like?')
    return res


def wait_for_update(details):
    details['fixedOddsUpdateTime'] = arrow.get(details['fixedOddsUpdateTime'])
    logger.debug('next update time {}'.format(details['fixedOddsUpdateTime']))
    now_one_sec = arrow.utcnow().shift(seconds=1)
    logger.debug('now one sec {}'.format(now_one_sec))
    time_to_sleep = details['fixedOddsUpdateTime'] - now_one_sec
    logger.debug('time to sleep {} (or {}s)'.format(time_to_sleep, time_to_sleep.total_seconds()))
    time.sleep(max(0, time_to_sleep.total_seconds()))


def get_forms(race):
    # form of runners
    res = requests.get(race['_links']['form'])
    res.raise_for_status()
    res = res.json()
    forms = res['form']
    logger.info('{} runners'.format(len(forms)))
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

def get_results(debug):
    """scrape yesterday results and predict and save it"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('get results!')

    # scrape yesterday's races
    yesterday = arrow.now().shift(days=-1)
    url = 'https://api.beta.tab.com.au/v1/historical-results-service/NSW/racing/{}'.format(yesterday.format('YYYY-MM-DD'))
    logger.info('Scraping {}'.format(url))

    meetings = requests.get(url)
    meetings.raise_for_status()
    meetings = meetings.json()
    logger.info('Found {} results'.format(len(meetings)))
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))

    for meeting in meetings['meetings']:
        logger.info('Processing meeting {}'.format(meeting['meetingName']))

        for race_basic in meeting['races']:
            logger.info('Processing race {} {}'.format(race_basic['raceName'], race_basic['raceNumber']))

            url = race_basic['_links']['self']
            logger.info('Scraping race {}'.format(url))
            race = requests.get(url)
            race.raise_for_status()
            race = race.json()
            # print(json.dumps(res, indent=4, default=str, sort_keys=True))

            try:
                predict(race)
            except KeyError as e:
                logger.error(e)
                continue

            save_race(race)


####################################################################################
# betting
####################################################################################

def bet_positive_odds(runners, bet_chunk):
    """calculate amount to bet"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # total (only of runners we are betting on)
    all_odds_scaled = [r['odds_scaled'] for r in runners
                       if r['probability'] > r['odds_scaled']]
    num_bets = len(all_odds_scaled)
    total = sum(all_odds_scaled)
    logger.debug('{} total odds for bets {}'.format(num_bets, total))

    for runner in runners:
        # default bet to 0 (for all)
        runner['bet'] = 0
        # make bet
        if runner['probability'] > runner['odds_scaled']:
            runner['bet'] = runner['odds_scaled'] / total * bet_chunk
        logger.debug('#{} bet = {:.2f} (odds={:.2f} prob={:.2f})'.format(
            runner['runnerNumber'], runner['bet'], runner['odds_scaled'], runner['probability']))

    return runners, num_bets


def dutching(runners, bet_chunk):
    """calculate amount to bet using normal dutching"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_best']]

    # sort runners from favourite to underdog
    runners.sort(key=itemgetter('odds_scaled'), reverse=True)
    logger.info('runners are sorted {}'.format(
        [(r['runnerNumber'], round(r['probability'], 2), round(r['odds_scaled'], 2)) for r in runners]))

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):
        logger.info('Spread on {} runners'.format(num_bets))

        # reset bets for all
        for runner in runners:
            runner['bet'] = 0

        pool = runners[:num_bets]
        logger.info('{} in pool'.format(len(pool)))

        # all odds
        total = sum([r['odds_scaled'] for r in pool])
        logger.info('total odds {}'.format(total))

        # dutch for all in pool (scaled is only from fixedOdds)
        for runner in pool:
            runner['bet'] = runner['odds_scaled'] / total * bet_chunk
            profit = runner['bet'] * runner['odds_best'] - bet_chunk
            logger.debug('#{} bet = {:.2f} (best={} scale={:.2f} prob={:.2f} profit={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_best'],
                runner['odds_scaled'], runner['probability'], profit))

        # exit when profitable
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets


def dutching_reverse(runners, bet_chunk):
    """calculate amount to bet using normal dutching but drop worst diff"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_best']]

    # sort runners from best to worst odds
    runners.sort(key=lambda r: r['probability'] - r['odds_scaled'], reverse=True)
    logger.info('runners are sorted {}'.format(
        [(r['runnerNumber'], round(r['probability'], 2), round(r['odds_scaled'], 2)) for r in runners]))

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):
        logger.info('Spread on {} runners'.format(num_bets))

        # reset bets for all
        for runner in runners:
            runner['bet'] = 0

        pool = runners[:num_bets]
        logger.info('{} in pool'.format(len(pool)))

        # all odds
        total = sum([r['odds_scaled'] for r in pool])
        logger.info('total odds {}'.format(total))

        # dutch for all in pool (scaled is only from fixedOdds)
        for runner in pool:
            runner['bet'] = runner['odds_scaled'] / total * bet_chunk
            logger.debug('#{} bet = {:.2f} (odds={:.2f} prob={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_scaled'], runner['probability']))

        # exit when profitable
        profit = pool[0]['bet'] * pool[0]['odds_best'] - bet_chunk
        logger.info('profit currently at {} ({} * {} - {})'.format(
            profit, pool[0]['bet'], pool[0]['odds_best'], bet_chunk))
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets


def dutching_fav(runners, bet_chunk):
    """calculate amount to bet using normal dutching but drop favourite"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_best']]

    # sort runners from best to worst odds
    runners.sort(key=itemgetter('odds_scaled'))
    logger.info('runners are sorted {}'.format(
        [(r['runnerNumber'], round(r['probability'], 2), round(r['odds_scaled'], 2)) for r in runners]))

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):
        logger.info('Spread on {} runners'.format(num_bets))

        # reset bets for all
        for runner in runners:
            runner['bet'] = 0

        pool = runners[:num_bets]
        logger.info('{} in pool'.format(len(pool)))

        # all odds
        total = sum([r['odds_scaled'] for r in pool])
        logger.info('total odds {}'.format(total))

        # dutch for all in pool (scaled is only from fixedOdds)
        for runner in pool:
            runner['bet'] = runner['odds_scaled'] / total * bet_chunk
            profit = runner['bet'] * runner['odds_best'] - bet_chunk
            logger.debug('#{} bet = {:.2f} (best={} scale={:.2f} prob={:.2f} profit={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_best'],
                runner['odds_scaled'], runner['probability'], profit))

        # exit when profitable
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets


def bet_results(book, runners, results, bet_chunk, num_bets, num_runners):
    winner = int(results[0][0])
    logger.info('winner = {}'.format(winner))
    ranked = None
    outcome = {
        'success': False,
        'profit': -bet_chunk,
        'num_bets': num_bets,
        'num_runners': num_runners,
    }
    for i, runner in enumerate(runners):
        # logger.debug('betted {} on {}'.format(runner['bet'], runner['runnerNumber']))
        if int(runner['runnerNumber']) == winner:
            ranked = num_runners - i
            if runner['bet']:
                profit = runner['bet'] * runner['odds_best'] - bet_chunk
                logger.warning('you win {:.0f}!'.format(profit))
                outcome = {
                    'success': True,
                    'profit': profit,
                    'num_bets': num_bets,
                    'num_runners': num_runners,
                }
            break

    # added where runners is thinned and winner is not in runners
    if not outcome['success']:
        logger.error('you lose {:.0f}!'.format(bet_chunk))

    outcome['ranked'] = ranked
    book.append(outcome)


def model_results(debug):
    """model results for best betting pattern"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('model results!')
    balance = 1000

    races = load_races()
    logger.info('Loaded {} races...'.format(len(races)))

    for strategy in [dutching]:  # dutching_fav]:  #dutching_reverse]: #bet_positive_odds
        input('continue...')
        book = []
        for race in races:
            if race.race_type != 'R':
                continue
                
            bet_chunk = balance * 0.05
            runners = race.get_runners()
            # print(json.dumps(runners, indent=4, default=str, sort_keys=True))
            # return
            runners, num_bets = strategy(runners, bet_chunk)
            bet_results(book, runners, race.get_results(), bet_chunk, num_bets, race.num_runners)
            # break

        logger.info('{}'.format(strategy.__name__))

        # races
        logger.info('Races: {}'.format(len(book)))

        # nums
        c = Counter('{}/{}'.format(o['num_bets'], o['num_runners']) for o in book)
        logger.info('Num bets common = {}'.format(c.most_common(5)))

        # success
        success_ratio = sum([o['success'] for o in book]) / len(book)
        logger.info('Success = {:.0f}%'.format(success_ratio * 100))

        # profit
        profits = sum([o['profit'] for o in book])
        logger.info('Profits = {:.0f}'.format(profits))

        # ranks
        r = Counter(o['ranked'] for o in book)
        logger.info('ranked = {}'.format(r.most_common()))
