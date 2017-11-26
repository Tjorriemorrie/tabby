import json
import logging
import time
from math import ceil
from copy import deepcopy
from statistics import mean, stdev

import arrow
import requests
from terminaltables import SingleTable

logger = logging.getLogger(__name__)

# race data
data = {}


def run(balance, target):
    """main"""
    logger.info('Starting martin with {} and target {}%'.format(balance, target))

    # history
    history = []

    # buckets
    buckets = []

    # num
    num = 0

    # infinitely get next to go
    while True:
        print('>' * 130)
        print('>' * 130)

        update_races()
        next_race = get_next_race()
        wait_for_next(next_race)
        update_details(next_race)
        print('\n' * 2)

        print('+' * 80)
        balance, buckets = update_buckets(balance, buckets, history)
        buckets, history = retire_buckets(buckets, history)
        # logger.info('{} in history'.format(len(history)))
        print('\n')
        print('+' * 80)

        runners_with_odds = len([r for r in next_race['details']['runners'] if r['fixedOdds']['returnPlace']])
        racers = 2 if runners_with_odds >= 8 else 1
        for racer in range(racers):
            try:
                bucket, num = get_next_bucket(next_race, balance, target, num, buckets, racer)
            except IndexError as e:
                print(json.dumps(buckets, indent=4, default=str, sort_keys=True))
                print(json.dumps(next_race, indent=4, default=str, sort_keys=True))
                logger.exception('no runners??')
                continue

            try:
                bet = bucket.process(next_race, racer)
            except Exception as e:
                logger.exception('Problems processing race in bucket!')
                continue

            balance -= bet
            logger.info('Balance is now {:.0f}'.format(balance))

        next_race['status'] = 'betting'
        if balance <= 0:
            logger.exception('BUSTED!')


def title(race):
    """Title helper for race"""
    return '[{}] {} R{}'.format(
        race['meeting']['raceType'],
        race['meeting']['meetingName'],
        race['raceNumber'])


def update_races():
    """update races.
     - scrape the next to go list
     - for every race add to races if new and set status to upcoming
     - scrape details so that avg place bet can be calculated"""
    url = 'https://api.beta.tab.com.au/v1/tab-info-service/racing/next-to-go/races?jurisdiction=NSW'
    logger.debug('scraping {}'.format(url))
    res = requests.get(url)
    res.raise_for_status()
    res = res.json()
    races = res['races']
    logger.debug('{} races scraped'.format(len(races)))

    added = 0
    for race in races:
        # print(json.dumps(race, indent=4, default=str, sort_keys=True))
        # raise Exception('update_races race')
        key = '{}_{}'.format(race['meeting']['meetingName'], race['raceNumber'])
        if key not in data:
            logger.debug('adding {} to data'.format(key))
            race['raceStartTime'] = arrow.get(race['raceStartTime'])
            race['status'] = 'upcoming'
            update_details(race)
            data[key] = race
            added += 1
            if added >= 2:
                logger.debug('Stopping to update races after 3')
                break


def update_details(race):
    """Get details (aka runners) for race"""
    res = requests.get(race['_links']['self'])
    res.raise_for_status()
    res = res.json()
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))
    # raise Exception('update_runners')
    logger.debug('Details updated for {}'.format(title(race)))
    race['details'] = res
    runners = [r for r in race['details']['runners'] if r['fixedOdds']['returnPlace']]
    runners = sorted(runners, key=lambda r: r['fixedOdds']['returnPlace'])
    runners = [r for r in runners if r['fixedOdds']['returnPlace'] > 1]
    race['details']['runners'] = runners
    # logger.debug('Race {} runners {}'.format(title(race), [name(r) for r in race['details']['runners']]))


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
    logger.info('Next: {}'.format(title(next_race)))
    return next_race


def wait_for_next(race):
    """Wait for the next race to be close to starting"""
    logger.debug('Next start time {}'.format(race['raceStartTime']))
    while True:
        time_to_sleep = race['raceStartTime'] - arrow.utcnow()
        logger.debug('time to sleep {}'.format(time_to_sleep))
        if time_to_sleep.total_seconds() < 0:
            break
        sleep_for = min(60, time_to_sleep.total_seconds())
        logger.info('waiting for {}'.format(time_to_sleep))
        time.sleep(sleep_for)


def get_next_bucket(race, balance, target, num, buckets, racer):
    """Get the bucket for the given race. Require a pool, so about 10.
    Then sort buckets from highest odds to lowest. These buckets will be losers, and then
    starting with highest odds, iterate on list till race odds is higher."""
    if len(buckets) >= 10:
        buckets.sort(key=lambda b: b.races[-1]['odds'], reverse=True)
        logger.debug('buckets sorted starting with highest odds')
        race_odds = race['details']['runners'][racer]['fixedOdds']['returnPlace']
        for bucket in buckets:
            if bucket.status == Bucket.STATUS_READY and bucket.races[-1]['odds'] <= race_odds:
                logger.debug('Returning first ready bucket with lower odds')
                return bucket, num

    logger.debug('No suitable bucket found, returning a new bucket')
    num += 1
    bucket = Bucket(target, balance * target / 100, num)
    buckets.append(bucket)
    return bucket, num


def name(runner, odds=None):
    """Helper to display runner"""
    # print(json.dumps(runner, indent=4, default=str, sort_keys=True))
    # raise Exception('runner')
    return '#{} {} - {:.2f}'.format(
        runner['runnerNumber'],
        runner['runnerName'],
        odds or runner['fixedOdds']['returnPlace'])


def update_buckets(balance, buckets, history):
    """update buckets with results from races"""
    logger.debug('updating buckets')
    for bucket in buckets:
        payout = bucket.update()
        bucket.print()
        if payout:
            balance += payout
            logger.debug('balance {:.0f} after payout added of {:.2f}'.format(balance, payout))
    history.extend([b for b in buckets if b.status == Bucket.STATUS_DONE])
    buckets = [b for b in buckets if b.status != Bucket.STATUS_DONE]
    logger.debug('all buckets updated')
    return balance, buckets


def retire_buckets(buckets, history):
    """Retire buckets when their odds are so high, no fav winner is coming along"""
    if len(buckets) > 20:
        if buckets[0].status == Bucket.STATUS_READY:
            bucket = buckets.pop(0)
            bucket.print()
            logger.warning('Bucket moved to history')
            history.append(bucket)
    return buckets, history


def get_dividend(dividends, runnerNumber, bet_type):
    """Get dividend amount from results"""
    for dividend in dividends:
        if dividend['wageringProduct'].startswith(bet_type):
            logger.debug('Dividend found: {}'.format(dividend))
            for div in dividend['poolDividends']:
                if runnerNumber in div['selections']:
                    logger.debug('#{} amount {} found for selection'.format(runnerNumber, div['amount']))
                    return div['amount']
    logger.debug('#{} not in selection'.format(runnerNumber))
    return 0


class Bucket:
    """A bucket to hold races and make bets till it is profitable"""

    STATUS_READY = 'ready'
    STATUS_BUSY = 'busy'
    STATUS_DONE = 'done'

    def __init__(self, target, margin, num):
        self.num = num
        self.status = self.STATUS_READY
        self.races = []
        self.target = target
        self.margin = margin
        self.profit = 0

    def process(self, race, racer):
        """Process next race to bucket"""
        race = deepcopy(race)
        self.races.append(race)
        logger.debug('{} added to bucket'.format(title(race)))

        short = self.margin - self.profit
        logger.info('Require ${:.2f}'.format(short))

        race['fav'] = runner = race['details']['runners'][racer]
        logger.debug('{} is favourite'.format(name(runner)))
        # assert all(r['fixedOdds']['returnPlace'] >= race['fav']['fixedOdds']['returnPlace']
        #            for r in race['details']['runners'])

        race['odds'] = odds = runner['fixedOdds']['returnPlace']
        bet = max([1, short / (odds - 1)])
        race['bet'] = bet = ceil(bet * 10) / 10
        logger.debug('Bet of ${:.2f}'.format(bet))

        race['outcome'] = 0
        race['cum'] = 0
        race['status'] = 'betting'
        self.status = self.STATUS_BUSY

        self.print()

        return bet

    def update(self):
        """Update races with results"""
        if self.status != self.STATUS_BUSY:
            logger.debug('Bucket status is not busy')
            return

        race = self.races[-1]
        assert race['outcome'] == 0
        update_details(race)

        if race['details']['raceStatus'] == 'Abandoned':
            race['status'] = 'abandoned'
            logger.info('{} has been abandoned!'.format(title(race)))
            return

        if not race['details'].get('results'):
            logger.info('No results yet for {}'.format(title(race)))
            return

        if not race['details'].get('dividends'):
            logger.info('No dividends yet for {}'.format(title(race)))
            return

        div = get_dividend(race['details']['dividends'], race['fav']['runnerNumber'], 'P')
        if div:
            payout = race['bet'] * race['odds']
        else:
            payout = 0

        race['outcome'] = outcome = payout - race['bet']
        logger.info('{} div {:.2f} outcome {:.2f}'.format(title(race), div, outcome))

        self.profit += outcome
        race['cum'] = self.profit

        self.status = self.STATUS_DONE if self.profit > 0 else self.STATUS_READY
        logger.debug('Bucket status = {}'.format(self.status))

        race['status'] = 'finished'

        return payout

    def print(self):
        """print bucket to terminal"""
        data = [['Race', 'Runner', 'Bet', 'Outcome', 'Cum']]
        for race in self.races:
            data.append([
                title(race),
                name(race['fav'], race['odds']),
                '{:.2f}'.format(race['bet']),
                '-' if not race['outcome'] else '{:.2f}'.format(race['outcome']),
                '-' if not race['cum'] else '{:.2f}'.format(race['cum']),
            ])
        print(SingleTable(data, title='#{} {}'.format(self.num, self.status)).table)
