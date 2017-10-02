import json
import logging
import time

import arrow
import requests
from sqlalchemy.orm.exc import NoResultFound
from terminaltables import SingleTable

from model import Race, save_race, list_race_dates, delete_oldest
from predict import add_predictions, add_scaled_odds, add_probabilities, NoRunnersError, BET_TYPE_WIN, BET_TYPES, \
    BET_TYPE_PLACE, NoOddsError, add_predictions_v2
from simulate import bet_positive_dutch, NoBetsError, bet_positive_dutch_v2

logger = logging.getLogger(__name__)


# race data
data = {}


def next_to_go(debug, oncely, make_bets):
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('next to go!')

    if make_bets:
        s = requests.Session()
        user_data = login(s)
        # {'accountNumber': 2181808, 'username': '2181808', 'customerId': 2127443,
        #  'preferences': {'general': {'rounding': 'DOWN'},
        #                  'betting': {'maxAmount': '$0.00', 'acceptCounterOffer': {'amount': False, 'price': False},
        #                              'acceptReducedPrice': False, 'defaultFlexi': True, 'defaultBetType': 'WIN_PLACE'}},
        #  'jurisdiction': 'NSW', 'tier': 'bronze', 'accountBalance': '$0.00', 'withdrawalBalance': '$0.00',
        #  'verified': True, 'withdrawalBlocked': False, 'eftWithdrawalEnabled': False, 'emailVerified': True,
        #  'verificationStatus': 'SUCCEEDED', 'authentication': {
        #     'token': '0756956ce91e52a2105c3eaf356e6e7bea2097230f424a4e31e7436409491c9146e782a1dda0e587b8d0debac6ac4444c16b26015c8feabeac531283d992e0ef0310f5fb30e437146fd99c83b6ccb192825632159ee4179920a3c3dce0209ff8d76016bc2b6a0627ae404877fcd07a0bc3',
        #     'inactivityExpiry': '2017-09-28T20:08:11.456Z', 'absoluteExpiry': '2017-09-28T20:08:11.455Z',
        #     'scopes': ['*']}}
        balance_data = get_balance(s)
        # {'accountBalance': '$0.00', 'withdrawalBalance': '$0.00', 'authentication': {'token': '07c22592ed169fd6652ee951f7392495bd04d479bd44373ce8d53af34b0b4e1f1c2f5434023a17dba68469a522bff2d553fe8ffd17dd87557e0dcd5d0ad367f991b3d72c3b9a7f707a993d5827345ca47cc557cfb9f21aa9f63b2ec2cd5a7a0f49d91179963f46f0832116937b1652c994', 'inactivityExpiry': '2017-09-28T20:08:11.523Z', 'absoluteExpiry': '2017-09-28T20:08:11.455Z', 'scopes': ['*']}}
        balance = balance_data['accountBalance']
    else:
        balance = 1000
    bet_chunk = balance * 0.01

    # infinitely get next to go
    while True:

        update_races()
        next_race = get_next_race()
        next_race['status'] = 'betting'

        # skip the woofies and harnessies
        # if next_race['meeting']['raceType'] in ['H']:
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
        try:
            add_scaled_odds(runners)
        except NoOddsError as e:
            logger.error(e)
            continue

        try:
            add_predictions_v2(runners, next_race['meeting']['raceType'])
        except NoRunnersError:
            logger.warning('No runners for {}'.format(details['meeting']['meetingName']))
            continue

        try:
            add_probabilities(runners)
        except NoOddsError as e:
            logger.warning(e)
            continue

        # drop scratched
        runners = [r for r in runners if r['has_odds']]
        if not runners:
            continue

        # calculate bets
        bet_method = bet_positive_dutch_v2
        try:
            if next_race['meeting']['raceType'] == 'R':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, 'R', bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, 'R', bet_type)

            elif next_race['meeting']['raceType'] == 'G':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, 'G', bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, 'G', bet_type)

            elif next_race['meeting']['raceType'] == 'H':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, 'H', bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, 'H', bet_type)
        except NoBetsError as e:
            logger.warning(e)
            continue

        if not num_bets_win and not (num_bets_place and len(runners) >= 8) and not oncely:
            logger.warning('No bettable runners on {} {}'.format(
                details['meeting']['meetingName'], details['raceNumber']))
            continue

        # make bet
        bet_chunk = balance * 0.01
        # logger.info('making bet of {:.2f}'.format(bet_chunk))

        # RACES
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

        # RUNNERS
        runner_table = [['Name',
                         '#', 'W Odds', 'W Prob', 'W Bet', 'W Profit',
                         '#', 'P Odds', 'P Prob', 'P Bet', 'P Winning']]
        for runner in runners:
            runner_row = [
                runner['runnerName'],
            ]
            # win
            prob = '{}_prob'.format(BET_TYPE_WIN)
            bet = '{}_bet'.format(BET_TYPE_WIN)
            runner_bet = runner[bet] if num_bets_win else 0
            pp = runner_bet * runner['win_odds'] - bet_chunk
            runner_row.extend([
                runner['runnerNumber'],
                '{:.2f}'.format(runner['win_odds']),
                '{:.0f}%'.format(runner[prob] * 100),
                runner_bet and '{:.2f}'.format(runner_bet) or '-',
                '{:.2f}'.format(pp),
            ])
            # place
            prob = '{}_prob'.format(BET_TYPE_PLACE)
            bet = '{}_bet'.format(BET_TYPE_PLACE)
            runner_bet = runner[bet] if num_bets_place and len(runners) >= 8 else 0
            pp = runner_bet * runner['place_odds']
            runner_row.extend([
                runner['runnerNumber'],
                '{:.2f}'.format(runner['place_odds']),
                '{:.0f}%'.format(runner[prob] * 100),
                runner_bet and '{:.2f}'.format(runner_bet) or '-',
                '{:.2f}'.format(pp),
            ])
            runner_table.append(runner_row)
        print('\n')
        print(SingleTable(runner_table, title='Bet now on {} {} {}'.format(
            next_race['meeting']['raceType'], next_race['meeting']['meetingName'], next_race['raceNumber'])).table)

        if oncely:
            return
        time.sleep(5)


def login(s):
    url = 'https://webapi.tab.com.au/v1/account-service/tab/authenticate'
    data = {
        'accountNumber': 2181808,
        'password': 'fok4jou2tab',
        'channel': 'TABCOMAU',
        'scopes': ['*'],
    }
    res = s.post(url, json=data)
    res.raise_for_status()
    res = res.json()
    s.headers.update({'TabcorpAuth': res['authentication']['token']})
    logger.info(res)


def get_balance(s):
    url = 'https://webapi.tab.com.au/v1/account-service/tab/accounts/2181808/balance'
    res = s.get(url)
    res.raise_for_status()
    res = res.json()
    logger.info('balance {}'.format(res))
    return res


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
        time_to_sleep = race['raceStartTime'] - arrow.utcnow()
        logger.info('time to sleep {} (or {:.0f}s)'.format(time_to_sleep, time_to_sleep.total_seconds()))
        if time_to_sleep.total_seconds() < 0:
            break
        time.sleep(min(60, time_to_sleep.total_seconds()))


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


####################################################################################
# scrape history results
####################################################################################

def scrape_history(debug, lst, dt_target, predict, red):
    """scrape yesterday results and predict and save it"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('get results!')

    # reduce?
    if red:
        dt = delete_oldest()
        logger.info('Deleted {}'.format(dt))
        return

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

    for meeting in meetings['meetings']:
        # print(json.dumps(meeting, indent=4, default=str, sort_keys=True))
        # raise Exception('')
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
            except (KeyError, ZeroDivisionError, NoOddsError) as e:
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


