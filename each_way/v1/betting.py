import logging

from constants import *

logger = logging.getLogger(__name__)


X = {
    RACE_TYPE_RACING: {
        # $0.00 profit per race
        # 0% of races 1 / 7057
        # [-0.007875,  5.81    ]
        # $0.00 profit per race
        # 0% of races 1 / 7057
        # [0.7, 5.81],
        # $-0.10 profit per race
        # 4% of races 76 / 1959
        BET_TYPE_WIN: [0.00009, 1.291595],
        # $-0.01 profit per race
        # 3% of races 211 / 7057
        # [-0.956445, 1.539453]
        # $0.02 profit per race
        # 16% of races 125 / 800
        # [0.000027, 1.387664],
        # $0.02 profit per race
        # 3% of races 53 / 1959
        BET_TYPE_PLACE: [0., 1.436842],
    },
    RACE_TYPE_GRAYHOUND: {
        # $0.01 profit per race
        # 1% of races 106 / 8942
        # [-0.007875,  5.81    ],
        # $0.11 profit per race
        # 2% of races 20 / 1067
        # [0.000242, 1.168355],
        # $0.03 profit per race
        # 2% of races 42 / 2506
        BET_TYPE_WIN: [0., 1.178947],
        # $0.01 profit per race
        # 1% of races 106 / 8942
        # [-1.01875, 1.4175],
        # $0.01 profit per race
        # 1% of races 12 / 1343
        # [0.000031, 1.4175],
        # $0.00 profit per race
        # 1% of races 16 / 2506
        BET_TYPE_PLACE: [-0.000063, 1.435],
    },
    RACE_TYPE_HARNESS: {
        # $0.05 profit per race
        # 1% of races 85 / 5700
        # [-0.007875,  5.81    ],
        # $0.63 profit per race
        # 17% of races 166 / 949
        # [-0.000029, 1.320559],
        # $0.27 profit per race
        # 9% of races 133 / 1482
        BET_TYPE_WIN: [0.000072, 1.394531],
        # $0.01 profit per race
        # 2% of races 121 / 5700
        # [-0.007875,  5.81    ],
        # $0.05 profit per race
        # 12% of races 135 / 1112
        # [0.000096, 1.248808],
        # $0.04 profit per race
        # 2% of races 37 / 1482
        BET_TYPE_PLACE: [-0.000031, 1.4525],
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
