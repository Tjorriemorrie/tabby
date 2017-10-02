import json
import logging
import time

import arrow
import requests
from terminaltables import SingleTable

from constants import *

logger = logging.getLogger(__name__)


# race data
data = {}


def next_to_go(race_types, each_way, oncely, make_bets):
    logger.info('next to go!')
    race_types = race_types or ['R', 'G', 'H']
    add_odds, add_predictions, add_probabilities, bet_method = load_each_way(each_way)

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

    # infinitely get next to go
    while True:

        update_races()
        next_race = get_next_race()
        next_race['status'] = 'betting'

        # skip the woofies and harnessies
        if next_race['meeting']['raceType'] not in race_types:
            logger.debug('skipping {} {}'.format(next_race['meeting']['raceType'], next_race['meeting']['meetingName']))
            continue

        # WAIT for race to start
        if not oncely:
            try:
                wait_for_next(next_race)
            except KeyError as e:
                logger.error(e)
                continue

        details = get_details(next_race)
        runners = details['runners']

        # add probability (do not delete or skip keyerrors here)
        try:
            add_odds(runners)
            add_predictions(runners, next_race['meeting']['raceType'])
            add_probabilities(runners)
        except Exception as e:
            logger.warning(e)
            continue

        # drop scratched
        runners = [r for r in runners if r['has_odds']]
        if not runners:
            logger.warning('No runners in race')
            continue

        # bet
        bet_chunk = balance * 0.01
        # logger.info('making bet of {:.2f}'.format(bet_chunk))

        # calculate bets
        try:
            if next_race['meeting']['raceType'] == 'R':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, RACE_TYPE_RACING, bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, RACE_TYPE_RACING, bet_type)

            elif next_race['meeting']['raceType'] == 'G':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, RACE_TYPE_GRAYHOUND, bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, RACE_TYPE_GRAYHOUND, bet_type)

            elif next_race['meeting']['raceType'] == 'H':
                for bet_type in BET_TYPES:
                    if bet_type == BET_TYPE_WIN:
                        runners, num_bets_win = bet_method(runners, bet_chunk, RACE_TYPE_HARNESS, bet_type)
                    elif bet_type == BET_TYPE_PLACE:
                        runners, num_bets_place = bet_method(runners, bet_chunk, RACE_TYPE_HARNESS, bet_type)
        except Exception as e:
            logger.warning(e)
            continue

        details = get_details(next_race)
        if not details['allowFixedOddsPlace'] or not details['allowParimutuelPlace']:
            logger.error('fixed or parimutuel betting not allowed')
            continue

        if not num_bets_win and not num_bets_place and not oncely:
            logger.info('No bettable runners on {} {}\n'.format(
                details['meeting']['meetingName'], details['raceNumber']))
            continue

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
            runner_bet = runner[bet] if num_bets_place else 0
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
    logger.info('Next: {} {}'.format(race['meeting']['meetingName'], race['raceNumber']))
    logger.debug('Next start time {}'.format(race['raceStartTime']))
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


def load_each_way(version):
    if version == 'v1':
        from each_way.v1.predict import add_odds, add_predictions, add_probabilities
        from each_way.v1.betting import bet_positive_dutch
        return add_odds, add_predictions, add_probabilities, bet_positive_dutch
    elif version == 'v2':
        from each_way.v2.predict import add_odds, add_predictions, add_probabilities
        from each_way.v2.betting import bet_positive_dutch
        return add_odds, add_predictions, add_probabilities, bet_positive_dutch
    else:
        raise ValueError('Unexpected version for each way {}'.format(version))
