import json
import logging
import math

import numpy as np
from keras.models import load_model

from constants import *
from data.race import load_races, delete_race, db_session

logger = logging.getLogger(__name__)

STATUSES = {'Open', 'LateScratched', 'Placing', 'Loser', 'Winner', 'Normal', 'Closed'}

MODELS = {
    RACE_TYPE_RACING: {
        BET_TYPE_WIN: load_model('each_way/v1/models/R30x30W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v1/models/R30x30P.h5'),
    },
    RACE_TYPE_GRAYHOUND: {
        BET_TYPE_WIN: load_model('each_way/v1/models/G30x30W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v1/models/G30x30P.h5'),
    },
    RACE_TYPE_HARNESS: {
        BET_TYPE_WIN: load_model('each_way/v1/models/H30x30W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v1/models/H30x30P.h5'),
    },
}


def run(race_types, odds_only, pred_only):
    """main method to update predictions in db"""
    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))

        races = load_races(race_type)
        logger.info('loaded {} races...'.format(len(races)))

        for i, race in enumerate(races):
            logger.debug('Running race {} {}'.format(race.meeting_name, race.meeting_date))
            runners = race.get_runners()

            try:
                # shared with watching
                if not pred_only:
                    add_odds(runners)
                if not odds_only:
                    add_predictions(runners, race_type)
                    add_probabilities(runners)
            except OddsError as e:
                logger.warning(e)
                delete_race(race.id)
            except Exception:
                print(json.dumps(race, indent=4, default=str, sort_keys=True))
                print(json.dumps(runners, indent=4, default=str, sort_keys=True))
                raise
            else:
                race.num_runners = len([r for r in runners if r['has_odds']])
                race.set_runners(runners)
                logger.info('{:.1f}% completed'.format(i / len(races) * 100))

        logger.info('saving...')
        db_session.commit()


class OddsError(Exception):
    pass


def add_odds(runners):
    """add odds for fixed odds ONLY"""
    # convert decimal odds to percentages
    # print(json.dumps(runners[0], indent=4, default=str, sort_keys=True))
    # raise Exception('')

    # get odds listing for ranking
    try:
        all_win_odds = sorted([r['fixedOdds']['returnWin'] for r in runners
                               if r['fixedOdds']['returnWin'] and r['fixedOdds']['returnWin'] > 0])
        all_place_odds = sorted([r['fixedOdds']['returnPlace'] for r in runners
                                 if r['fixedOdds']['returnPlace'] and r['fixedOdds']['returnPlace'] > 0])
    except KeyError as e:
        raise OddsError(e)
    logger.debug('Total fixed win odds {}'.format(all_win_odds))
    logger.debug('Total fixed place odds {}'.format(all_place_odds))

    if not all_win_odds or not all_place_odds:
        raise OddsError('No all win odds {} or no all place odds {}'.format(all_win_odds, all_place_odds))

    for runner in runners:
        runner['has_odds'] = True

        # best odds for betting
        runner['win_odds'] = runner['fixedOdds']['returnWin']
        runner['place_odds'] = runner['fixedOdds']['returnPlace']
        logger.debug('#{} fixed win_odds = {} and fixed place_odds = {}'.format(
            runner['runnerNumber'], runner['win_odds'], runner['place_odds']))

        if not runner['win_odds'] or not runner['place_odds']:
            logger.warning('#{} has no odds win {} or place {}'.format(
                runner['runnerNumber'], runner['win_odds'], runner['place_odds']))
            runner['has_odds'] = False
            runner['win_rank'] = math.log(len(runners))
            runner['win_perc'] = 0
            runner['place_rank'] = math.log(len(runners))
            runner['place_perc'] = 0
            continue

        # add runner rank
        runner['win_rank'] = all_win_odds.index(runner['win_odds']) + 1
        runner['place_rank'] = all_place_odds.index(runner['place_odds']) + 1
        logger.debug('#{} win rank {:.2f} and place rank {:.2f}'.format(
            runner['runnerNumber'], runner['win_rank'], runner['place_rank']))

        # odds for scaling
        runner['win_perc'] = 1 / runner['win_odds']
        logger.debug('#{} fixed win odds {:.2f} => fixed perc {:.2f}'.format(
            runner['runnerNumber'], runner['win_odds'], runner['win_perc']))
        runner['place_perc'] = 1 / runner['place_odds']
        logger.debug('#{} fixed place odds {:.2f} => fixed perc {:.2f}'.format(
            runner['runnerNumber'], runner['place_odds'], runner['place_perc']))

    # get total (scratched has 0 for win)
    total_win_perc = sum([r['win_perc'] for r in runners])
    total_place_perc = sum([r['place_perc'] for r in runners])
    logger.debug('total fixed win_perc {:.2f} fixed place_perc {:.2f}'.format(
        total_win_perc, total_place_perc))

    if not total_win_perc or not total_place_perc:
        raise OddsError('No total win perc {} or no total place perc {}'.format(total_win_perc, total_place_perc))

    num_runners = len([r for r in runners if r['has_odds']])

    # scale it
    for runner in runners:
        runner['num_runners'] = num_runners
        runner['win_scaled'] = runner['win_perc'] / total_win_perc
        logger.debug('#{} fixed win perc {:.2f} => fixed win scale {:.2f}'.format(
            runner['runnerNumber'], runner['win_perc'], runner['win_scaled']))
        runner['place_scaled'] = runner['place_perc'] / total_place_perc
        logger.debug('#{} fixed place perc {:.2f} => fixed place scale {:.2f}'.format(
            runner['runnerNumber'], runner['place_perc'], runner['place_scaled']))

        # validate %
        if runner['win_perc'] > 1 or runner['win_scaled'] > 1 or runner['place_perc'] > 1 or runner['place_scaled'] > 1:
            raise Exception('Invalid odds perc/scaled')

        # cleanup
        for k in ['odds_win', 'odds_perc', 'rank_win', 'odds_scale',
                  'prediction', 'probability',
                  'fix_win_odds', 'fix_place_odds', 'par_win_odds', 'par_place_odds',
                  'fix_win_rank', 'fix_win_perc', 'fix_place_rank', 'fix_place_perc',
                  'par_win_rank', 'par_win_perc', 'par_place_rank', 'par_place_perc',
                  'fix_win_scaled', 'fix_place_scaled', 'par_win_scaled', 'par_place_scaled']:
            runner.pop(k, None)


def add_predictions(runners, race_type):
    """predict for bet type"""
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)

        # model
        mdl = MODELS[race_type][bet_type]

        for runner in runners:
            prediction = 0

            if not runner['has_odds']:
                logger.debug('runner scratched')
            else:
                # get data
                # xp, xs, xr, xn
                x = [(
                    runner['win_perc'], runner['win_scaled'], runner['win_rank'], runner['num_runners']
                )]

                # make prediction on data
                preds = mdl.predict(np.array(x))
                prediction = sum(preds[0])
                logger.debug('#{} {} prediction: {:.2f}'.format(runner['runnerNumber'], bet_type, prediction))
            runner[pred] = prediction


class ProbabilityError(Exception):
    pass


def add_probabilities(runners):
    """convert predictions to probabilities"""
    # get total (scratched has 0 for prediction)
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        total_pred = sum(r[pred] for r in runners)
        logger.debug('total {} prediction = {}'.format(bet_type, total_pred))
        if not total_pred:
            raise ProbabilityError('No total prediction')

        # scale predictions
        for runner in runners:
            probability = runner[pred] / total_pred
            runner[prob] = probability
            if runner[pred]:
                logger.debug('#{} {} probability: {:.2f}'.format(runner['runnerNumber'], bet_type, probability))

        # total probability must be 1
        total_prob = sum(r[prob] for r in runners)
        logger.debug('total {} probability = {}'.format(bet_type, round(total_prob, 2)))
        if round(total_prob, 2) != 1:
            raise ProbabilityError('Probability must be 1, has {}'.format(total_prob))
