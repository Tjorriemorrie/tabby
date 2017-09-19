import json
import logging
import random
from collections import Counter
from operator import itemgetter

from model import load_races

logger = logging.getLogger(__name__)


def simulate(debug):
    """model results for best betting pattern"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('model results!')
    balance = 1000

    races = load_races()
    logger.info('Loaded {} races...'.format(len(races)))

    for strategy in [bet_positive_odds]:  # random_drop]:  # dutching_fav]:  # dutching]:  #]:  # ]:  #dutching_reverse
        book = []
        for race in races:
            # if race.race_type == 'G':
            #     continue

            bet_chunk = balance * 0.05
            runners = race.get_runners()
            # print(json.dumps(runners, indent=4, default=str, sort_keys=True))
            # return

            # drop scratched
            runners = [r for r in runners if r['odds_win']]
            if not runners:
                continue

            # default 0 bets
            for runner in runners:
                runner['bet'] = 0

            runners, num_bets = strategy(runners, bet_chunk)
            if num_bets:
                bet_results(book, runners, race.num_runners, bet_chunk, num_bets, race.race_type)
            # break

        logger.info('{}'.format(strategy.__name__))

        # races
        logger.info('Races: {}'.format(len(book)))

        # nums
        cw = Counter('{}/{}'.format(o['num_bets'], o['num_runners']) for o in book if o['success'])
        cl = Counter('{}/{}'.format(o['num_bets'], o['num_runners']) for o in book if not o['success'])
        logger.info('Num bets won = {}'.format(cw.most_common(5)))
        logger.info('Num bets los = {}'.format(cl.most_common(5)))

        # success
        success_ratio = sum([o['success'] for o in book]) / len(book)
        logger.info('Success = {:.0f}%'.format(success_ratio * 100))

        # profit
        profits = sum([o['profit'] for o in book])
        logger.info('Profit/race = {:.1f}'.format(profits / len(book)))
        total_inv = bet_chunk * len(book)
        roi = profits / total_inv
        logger.info('ROI = {:.1f}%'.format(roi * 100))

        # race types
        race_types = Counter('{}{}'.format(o['race_type'], int(o['success'])) for o in book)
        logger.info('Race types = {}'.format(race_types.most_common()))
        race_types_profits = {'Rp': 0, 'Gp': 0, 'Hp': 0, 'Ri': 0, 'Gi': 0, 'Hi': 0}
        for outcome in book:
            race_types_profits['{}i'.format(outcome['race_type'])] += bet_chunk
            race_types_profits['{}p'.format(outcome['race_type'])] += outcome['profit']
        for p, i in [('Rp', 'Ri'), ('Gp', 'Gi'), ('Hp', 'Hi')]:
            roi = race_types_profits[p] / race_types_profits[i]
            logger.info('ROI {}: {:.1f}%'.format(p, roi * 100))

        # ranks
        r = Counter(o['ranked'] for o in book)
        logger.info('ranked = {}'.format(r.most_common()))


def bet_results(book, runners, num_runners, bet_chunk, num_bets, race_type):
    win_diff = 0
    max_diff = 0
    outcome = {
        'success': 0,
        'profit': -bet_chunk,
        'num_bets': num_bets,
        'num_runners': num_runners,
    }
    for i, runner in enumerate(runners):
        diff = abs(runner['odds_scale'] - runner['probability'])
        max_diff = max(max_diff, diff)
        if int(runner['finishingPosition']) == 1:
            win_diff = diff
            if runner['bet'] > 0:
                # odds = runner['parimutuel']['returnWin'] if runner['parimutuel']['returnWin'] else runner['odds_win']
                odds = runner['odds_win']
                profit = runner['bet'] * odds - bet_chunk
                outcome = {
                    'success': 1,
                    'profit': profit,
                    'num_bets': num_bets,
                    'num_runners': num_runners,
                }
            break

    outcome['max_diff'] = max_diff
    outcome['win_diff'] = win_diff
    outcome['bet_chunk'] = bet_chunk
    outcome['race_type'] = race_type
    outcome['runners'] = runners
    book.append(outcome)


def bet_positive_max(runners, bet_chunk):
    """bet max given prob>scale"""

    num_runners = sum(r['odds_win'] > 0 for r in runners)
    max_diff = max(r['probability'] - r['odds_scale'] for r in runners)

    for runner in runners:
        runner['bet'] = 0
        if runner['probability'] - runner['odds_scale'] == max_diff:
            runner['bet'] = bet_chunk

    num_bets = sum(r['bet'] > 0 for r in runners)

    if num_bets > 2:
        logger.warning('# of bets more than 2, has {}'.format(num_bets))
        return [], 0

    if num_bets / num_runners < 0.125:
        logger.warning('ratio of bets per runners less than 12.5%, has {:.0f}'.format(num_bets / num_runners * 100))
        return [], 0

    return runners, num_bets


def bet_positive_odds(runners, bet_chunk):
    """if prob > odds, bet"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    def bettable(r):
        return (r['probability'] > min(r['odds_fscale'], r['odds_tscale'])
                and r['odds_fwin'] > 0 and r['odds_twin'] > 0)

    # total (only of runners we are betting on)
    all_odds_scaled = [r['odds_fscale'] for r in runners
                       if r['probability'] > min(r['odds_fscale'], r['odds_tscale'])]
    num_bets = len(all_odds_scaled)
    total = sum(all_odds_scaled)
    logger.debug('{} total odds for bets {}'.format(num_bets, total))

    for runner in runners:
        runner['bet'] = runner['odds_fscale'] / total * bet_chunk if bettable(runner) else 0
        logger.debug('#{} bet = {:.2f} (odds={:.2f} prob={:.2f})'.format(
            runner['runnerNumber'], runner['bet'], runner['odds_fscale'], runner['probability']))

    return runners, num_bets


def scale_positive_odds(runners, bet_chunk):
    """if prob > odds, bet proportional to the diff"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_win']]

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
            profit = runner['bet'] * runner['parimutuel']['returnWin'] - bet_chunk
            logger.debug('#{} bet = {:.2f} (best={} scale={:.2f} prob={:.2f} profit={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_win'],
                runner['odds_scaled'], runner['probability'], profit))

        # exit when profitable
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets


def bet_positive_dutch(runners, bet_chunk):
    """dutch betting on probability"""

    # sort runners from favourite to underdog
    ###############################################################################################
    # -10% roi 69% wr 100% races
    # runners.sort(key=itemgetter('probability'), reverse=True)
    ###############################################################################################
    # -7% roi 68% wr 100% races
    runners.sort(key=lambda r: r['probability'] - r['odds_scale'], reverse=True)
    ###############################################################################################

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):

        # reset bets for every iteration
        for runner in runners:
            runner['bet'] = 0

        # recreate smaller pool
        pool = runners[:num_bets]
        # print('pool is {} from {} bets'.format(len(pool), num_bets))

        # all odds
        total_probs = sum([r['probability'] for r in pool])
        #         total_scale = sum([r['odds_scale'] for r in pool])
        # print('total probability = {}'.format(total))

        # dutch for all in pool
        profits = []
        for runner in pool:
            # scale bet according to odds or prediction?
            ###################################################################################
            # -7% roi 68% wr
            runner['bet'] = bet_chunk * runner['probability'] / total_probs
            ###################################################################################
            # -13% roi 79% wr 100% races
            # runner['bet'] = bet_chunk * runner['odds_scale'] / total_scale
            ###################################################################################

            # need to check all as we scale to probs and not odds
            profits.append(runner['bet'] * runner['odds_win'] - bet_chunk)

        # exit with average profit
        avg_profit = sum(profits) / len(profits)
        ###################################################################################
        # -9% roi 76% wr 30/30
        # if avg_profit > 0:
        ###################################################################################
        # -1% roi 38% wr 26/30
        # if avg_profit > bet_chunk * 1:
        ###################################################################################
        # 1% roi 25% wr 19/30
        # if avg_profit > bet_chunk * 2:
        ###################################################################################
        # -4% roi 18% wr 13/30
        # if avg_profit > bet_chunk * 3:
        ###################################################################################

        # exit with minimum profit
        ###################################################################################
        # -7% roi 68% wr
        # if all(p > 0 for p in profits):
        ###################################################################################
        # 0% roi 35% wr 26/31
        # if min(profits) > bet_chunk * 1:
        ###################################################################################
        # 2% roi 28% wr 22/31
        # if min(profits) > bet_chunk * 1.5:
        ###################################################################################
        # 4% roi 24% wr 19/31
        # if min(profits) > bet_chunk * 2:
        ###################################################################################
        # 3% roi 21% wr 17/31
        # if min(profits) > bet_chunk * 2.5:
        ###################################################################################
        # -1% roi 18% wr 13/31
        # if min(profits) > bet_chunk * 3:
        ###################################################################################

        # 4%  2 - 2
        # 3%  1.745 - 1.75
        # 2%  2.25 - 1.75
        # 2%  2 - 2.25
        # 3.7% 1.7 - 2
        # 3.7% 1.8 - 2
        # 3.7% 1.9 - 2 (1.9 5.1% - 1.8 5.3% - 1.7 4.9%)
        # 3.4% 2.1 - 2
        # 5.0 (1.8,1.8)
        # 4.0 (2, 1.8)
        if avg_profit > bet_chunk * 1.9 and min(profits) > bet_chunk * 1.8:
            break
    else:
        return [], 0

    # put bets from pool into runners
    for p in pool:
        for r in runners:
            if r['runnerNumber'] == p['runnerNumber']:
                r['bet'] = p['bet']
                break

    # print(json.dumps(runners, indent=4, default=str, sort_keys=True))
    return runners, num_bets


def dutching_reverse(runners, bet_chunk):
    """calculate amount to bet using normal dutching but drop worst diff"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_win']]

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
        profit = pool[0]['bet'] * pool[0]['odds_win'] - bet_chunk
        logger.info('profit currently at {} ({} * {} - {})'.format(
            profit, pool[0]['bet'], pool[0]['odds_win'], bet_chunk))
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
    runners = [r for r in runners if r['odds_win']]

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
            profit = runner['bet'] * runner['odds_win'] - bet_chunk
            logger.debug('#{} bet = {:.2f} (best={} scale={:.2f} prob={:.2f} profit={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_win'],
                runner['odds_scaled'], runner['probability'], profit))

        # exit when profitable
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets


def random_drop(runners, bet_chunk):
    """calculate amount to bet using normal dutching but drop favourite"""
    logger.info('betting chunk = {}'.format(bet_chunk))

    # drop scratched
    runners = [r for r in runners if r['odds_win']]

    # sort runners from best to worst odds
    random.shuffle(runners)

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
            profit = runner['bet'] * runner['odds_win'] - bet_chunk
            logger.debug('#{} bet = {:.2f} (best={} scale={:.2f} prob={:.2f} profit={:.2f})'.format(
                runner['runnerNumber'], runner['bet'], runner['odds_win'],
                runner['odds_scaled'], runner['probability'], profit))

        # exit when profitable
        if profit > 0:
            logger.info('profitable!')
            break
        else:
            logger.info('nope, try again!')

    return pool, num_bets
