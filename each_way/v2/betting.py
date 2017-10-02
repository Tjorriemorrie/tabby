import logging

from constants import *

logger = logging.getLogger(__name__)


X = {
    RACE_TYPE_RACING: {
        # $0.21 profit per race     8% of races 146 / 1939
        BET_TYPE_WIN: [0.000032, 1.115354],
        # $0.85 profit per race     33% of races 646 / 1939
        BET_TYPE_PLACE: [0.000004, 1.271217],
    },
    RACE_TYPE_GRAYHOUND: {
        # $0.06 profit per race     1% of races 36 / 2506
        BET_TYPE_WIN: [0.000147, 1.289712],
        # $0.67 profit per race     33% of races 820 / 2506
        BET_TYPE_PLACE: [-0.000035, 1.163503],
    },
    RACE_TYPE_HARNESS: {
        # $0.46 profit per race     11% of races 168 / 1482
        BET_TYPE_WIN: [0.000046, 1.250354],
        # $0.86 profit per race     48% of races 707 / 1482
        BET_TYPE_PLACE: [-0.000004, 1.054276],
    },
}


class NoBetsError(Exception):
    pass


def bet_positive_dutch(runners, bet_chunk, race_type, bet_type):
    """dutch betting on probability"""
    pred = '{}_pred'.format(bet_type)
    prob = '{}_prob'.format(bet_type)
    bet = '{}_bet'.format(bet_type)

    x = X[race_type][bet_type]

    # sort runners from favourite to underdog
    runners.sort(key=lambda r: r[pred], reverse=True)

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):

        # reset bets
        for runner in runners:
            runner[bet] = 0

        # recreate smaller pool
        pool = runners[:num_bets]
        # print('pool is {} from {} bets'.format(len(pool), num_bets))

        # all prediction values
        total_preds = sum([r[pred] for r in pool])

        # dutch for all in pool
        profits = []
        scales = []
        for runner in pool:
            # scale bet according to prediction
            runner[bet] = bet_chunk * runner[pred] / total_preds

            # need to check all as we scale to probs and not odds
            if bet_type == 'W':
                odds = runner['win_odds']
                scaled = runner['win_scaled']
            elif bet_type == 'P':
                odds = runner['place_odds']
                scaled = runner['place_scaled']
            profits.append(runner[bet] * odds - bet_chunk)
            scales.append(runner[prob] / scaled)

        ###################################################################################
        # MIN PROFIT
        ###################################################################################
        min_profit_flag = False
        min_profit = min(profits)
        if min_profit > bet_chunk * x[0]:
            min_profit_flag = True

        ###################################################################################
        # MIN SCALED
        ###################################################################################
        min_scaled_flag = False
        min_scaled = min(scales)
        if min_scaled >= x[1]:
            min_scaled_flag = True

        if min_profit_flag and min_scaled_flag:
            # print('breaking: {} {} {} {}'.format(min_profit_flag, avg_profit_flag, num_bets_flag, min_probs2scale_flag))
            break

    else:
        raise NoBetsError('No profitable bets determined with {}'.format(x))

    # put bets from pool into runners
    for p in pool:
        for r in runners:
            if r['runnerNumber'] == p['runnerNumber']:
                r[bet] = p[bet]
                break

    return runners, num_bets
