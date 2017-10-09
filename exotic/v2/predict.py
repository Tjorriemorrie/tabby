import json
from operator import itemgetter
import logging

import numpy as np
from itertools import combinations
from keras.models import load_model

from constants import *
from data.race import load_races
from data.exotic import db_session, clear_exotic, save_exotic, load_exotics

logger = logging.getLogger(__name__)

MODELS = {
    RACE_TYPE_RACING: {
        # BET_TYPE_QUINELLA: load_model('exotic/v1/models/R40x40Q.h5'),
    },
    RACE_TYPE_GRAYHOUND: {
        # BET_TYPE_WIN: load_model('each_way/v2/models/G50x50W.h5'),
    },
    RACE_TYPE_HARNESS: {
        # BET_TYPE_WIN: load_model('each_way/v2/models/H50x50W.h5'),
    },
}


def build(bet_type, race_types):
    """main method to update predictions in db"""
    logger.info('building exotic bets')

    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))

        # recreate as cannot update with no unique info being stored
        clear_exotic(race_type, bet_type)

        races = load_races(race_type)
        if bet_type == BET_TYPE_QUINELLA:
            r = 2
        else:
            raise Exception(bet_type)
        logger.info('building combinations from {} races for {} repeats'.format(len(races), r))

        for race in races:
            # get num runners (requires at least 8)
            # if race.num_runners < 8:
            #     logger.debug('skipping {}'.format(race))
            #     continue

            # get results
            res1, res2, res3, res4 = race.get_results()
            logger.debug('winners = {} {} {} {}'.format(res1, res2, res3, res4))
            try:
                res1, res2, res3, res4 = res1[0], res2[0], res3[0], res4[0]
            except IndexError as e:
                logger.warning('bad results: {}'.format(race.get_results()))
                continue

            # get runners
            runners = race.get_runners()
            # remove scratched
            try:
                runners = [r for r in runners if r['has_odds']]
            except:
                print(json.dumps(race, indent=4, default=str, sort_keys=True))
                print(json.dumps(runners, indent=4, default=str, sort_keys=True))
                raise

            combs = build_combinations(runners, r)
            for comb in combs:
                comb.update({
                    'race_type': race_type,
                    'bet_type': bet_type,
                    'res1': res1,
                    'res2': res2,
                    'res3': res3,
                    'res4': res4,
                })
                if bet_type == BET_TYPE_QUINELLA:
                    success = 1 if comb['run1_num'] == res1 and comb['run2_num'] == res2 else 0
                    comb.update({
                        'success': success,
                        'dividend': race.quinella,
                    })
                save_exotic(comb)
            logger.info('Adding {} combinations for race {}'.format(len(combs), race))

        logger.info('saving...')
        db_session.commit()


def build_combinations(runners, r):
    """build combinations of r length"""

    # data rows will be permutations for each bet type
    # but combinations if sorted (best chance first)
    runners = sorted(runners, key=itemgetter('win_scaled'), reverse=True)
    logger.debug('sorted {} runners'.format(len(runners)))
    combs = combinations(runners, r)

    data = []
    for comb in combs:
        item = {}
        for i, runner in enumerate(comb):
            if not runner['has_odds']:
                logger.debug('#{} runner does not have odds'.format(runner['runnerNumber']))
                break
            item.update({
                'run{}_num'.format(i + 1): runner['runnerNumber'],
                'run{}_win_perc'.format(i + 1): runner['win_perc'],
                'run{}_win_scaled'.format(i + 1): runner['win_scaled'],
                'run{}_win_rank'.format(i + 1): runner['win_rank'],
                'run{}_place_perc'.format(i + 1): runner['place_perc'],
                'run{}_place_scaled'.format(i + 1): runner['place_scaled'],
                'run{}_place_rank'.format(i + 1): runner['place_rank'],
            })
        else:
            item.update({'num_runners': 1 / runner['num_runners']})
            data.append(item)
    logger.debug('Created {} combs'.format(len(data)))
    return data


def predict(bet_type, race_types):
    """make predictions on race and bet type for backtesting"""
    logger.debug('predicting for race types {}'.format(race_types))

    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))

        # exotics
        exotics = load_exotics(bet_type, race_type)

        for i, exotic in enumerate(exotics):
            logger.info('{:.0f}% completed'.format(i / len(exotics) * 100))
            comb = exotic.to_dict()
            exotic.prediction = make_prediction(comb)

        logger.debug('saving...')
        db_session.commit()


def make_prediction(comb):
    # model
    mdl = MODELS[comb['race_type']][comb['bet_type']]

    # xn, x1wp, x1ws, x1wr, x1pp, x1ps, x1pr, x2wp, x2ws, x2wr, x2pp, x2ps, x2pr
    x = [(
        comb['num_runners'],
        comb['run1_win_perc'], comb['run1_win_scaled'], comb['run1_win_rank'],
        comb['run1_place_perc'], comb['run1_place_scaled'], comb['run1_place_rank'],
        comb['run2_win_perc'], comb['run2_win_scaled'], comb['run2_win_rank'],
        comb['run2_place_perc'], comb['run2_place_scaled'], comb['run2_place_rank'],
    )]
    # logger.debug('#{}, {} X={}'.format(comb['run1_num'], comb['run2_num'], x))

    # make prediction on data
    preds = mdl.predict(np.array(x))
    prediction = sum(preds[0])
    # logger.debug('#{}, {} prediction: {:.2f}'.format(comb['run1_num'], comb['run2_num'], prediction))
    return prediction


# class ProbabilityError(Exception):
#     pass
#
#
# def add_probabilities(runners):
#     """convert predictions to probabilities"""
#     # get total (scratched has 0 for prediction)
#     for bet_type in BET_TYPES:
#         pred = '{}_pred'.format(bet_type)
#         prob = '{}_prob'.format(bet_type)
#
#         preds = [r[pred] for r in runners]
#         total_pred = sum(preds)
#         logger.debug('total {} prediction = {}'.format(bet_type, total_pred))
#         if not total_pred:
#             raise ProbabilityError('No total prediction, retrain {}, got {}'.format(bet_type, preds))
#
#         # scale predictions
#         for runner in runners:
#             probability = runner[pred] / total_pred
#             runner[prob] = probability
#             if runner[pred]:
#                 logger.debug('#{} {} probability: {:.2f}'.format(runner['runnerNumber'], bet_type, probability))
#             # if runner['runnerName'] == 'TARNHELM' and runner['win_odds'] == 2.3 and bet_type == BET_TYPE_PLACE:
#             #     raise Exception(probability)
#
#         # total probability must be 1
#         total_prob = sum(r[prob] for r in runners)
#         logger.debug('total {} probability = {}'.format(bet_type, round(total_prob, 2)))
#         if round(total_prob, 2) != 1:
#             raise ProbabilityError('Probability must be 1, has {}'.format(total_prob))
