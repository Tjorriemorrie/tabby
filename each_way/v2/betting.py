import logging

from constants import *

logger = logging.getLogger(__name__)


X = {
    RACE_TYPE_RACING: {
        # $0.21 profit per race     8% of races 146 / 1939      [0.000032, 1.115354],
        # $0.67 profit per race     12% of races 344 / 2980     [0.000003, 1.402734],
        # $0.98 profit per race     31% of races 1261 / 4116
        BET_TYPE_WIN: [2.083643, 0.951995],
        # $0.85 profit per race     33% of races 646 / 1939     [0.000004, 1.271217],
        # $1.58 profit per race     43% of races 1292 / 2980
        BET_TYPE_PLACE: [0.000036, 1.219246],
    },
    RACE_TYPE_GRAYHOUND: {
        # $0.06 profit per race     1% of races 36 / 2506       [0.000147, 1.289712],
        # $0.70 profit per race     16% of races 599 / 3799     [0.000023, 1.229441],
        # $0.85 profit per race     18% of races 947 / 5359
        BET_TYPE_WIN: [1.887109, 1.112253],
        # $0.67 profit per race     33% of races 820 / 2506     [-0.000035, 1.163503],
        # $1.16 profit per race     31% of races 1188 / 3799
        BET_TYPE_PLACE: [0.485937, 1.242198],
    },
    RACE_TYPE_HARNESS: {
        # $0.46 profit per race     11% of races 168 / 1482     [0.000046, 1.250354],
        # $0.89 profit per race     29% of races 670 / 2290     [0.000074, 1.267714],
        # $1.14 profit per race     31% of races 989 / 3236
        BET_TYPE_WIN: [1.173401, 1.243652],
        # $0.86 profit per race     48% of races 707 / 1482     [-0.000004, 1.054276],
        # $1.55 profit per race     34% of races 783 / 2290
        BET_TYPE_PLACE: [0.525, 0.825],
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
        return runners, 0

    # put bets from pool into runners
    for p in pool:
        for r in runners:
            if r['runnerNumber'] == p['runnerNumber']:
                r[bet] = p[bet]
                break

    return runners, num_bets
