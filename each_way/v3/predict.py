import json
import logging
import math
from operator import itemgetter

import numpy as np
from keras.models import load_model

from constants import *
from data.race import load_races, delete_race, db_session

logger = logging.getLogger(__name__)


MODELS = {
    RACE_TYPE_RACING: {
        # BET_TYPE_WIN: load_model('each_way/v2/models/R50x50W.h5'),
        # BET_TYPE_PLACE: load_model('each_way/v2/models/R50x50P.h5'),
    },
    RACE_TYPE_GRAYHOUND: {
        BET_TYPE_WIN: load_model('each_way/v3/models/G64x64W.h5'),
        # BET_TYPE_PLACE: load_model('each_way/v2/models/G50x50P.h5'),
    },
    RACE_TYPE_HARNESS: {
        # BET_TYPE_WIN: load_model('each_way/v2/models/H50x50W.h5'),
        # BET_TYPE_PLACE: load_model('each_way/v2/models/H50x50P.h5'),
    },
}


def run(race_types, odds_only, pred_only):
    """main method to update predictions in db"""
    for race_type in ['G']:
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
                    add_predictions(runners, race_type, BET_TYPE_WIN)
                    # add_probabilities(runners)
            except OddsError as e:
                logger.warning(e)
                delete_race(race.id)
                db_session.commit()
            except PredictionError as e:
                logger.info('Skipping {}'.format(race))
            except (Exception, ProbabilityError):
                print(json.dumps(race, indent=4, default=str, sort_keys=True))
                print(json.dumps(runners, indent=4, default=str, sort_keys=True))
                # delete_race(race.id)
                db_session.commit()
                raise
            else:
                race.num_runners = len([r for r in runners if r['has_odds']])
                race.set_runners(runners)
                logger.info('{:.0f}% completed'.format(i / len(races) * 100))

        logger.info('saving...')
        db_session.commit()


class OddsError(Exception):
    pass


def add_odds(runners):
    """add values for fixed and tote"""
    # get odds listing for ranking
    try:
        all_fwo = sorted([r['fixedOdds']['returnWin'] for r in runners
                          if r['fixedOdds']['returnWin'] and r['fixedOdds']['returnWin'] > 0])
        all_fpo = sorted([r['fixedOdds']['returnPlace'] for r in runners
                          if r['fixedOdds']['returnPlace'] and r['fixedOdds']['returnPlace'] > 0])
        all_two = sorted([r['parimutuel']['returnWin'] for r in runners
                          if r['parimutuel']['returnWin'] and r['parimutuel']['returnWin'] > 0])
        all_tpo = sorted([r['parimutuel']['returnPlace'] for r in runners
                          if r['parimutuel']['returnPlace'] and r['parimutuel']['returnPlace'] > 0])
    except KeyError as e:
        raise OddsError(e)
    logger.debug('Total fixed win odds {}'.format(all_fwo))
    logger.debug('Total fixed place odds {}'.format(all_fpo))
    logger.debug('Total tote win odds {}'.format(all_two))
    logger.debug('Total tote place odds {}'.format(all_tpo))

    if not all_fwo or not all_fpo or not all_two or not all_tpo:
        raise OddsError('No all odds fwo {} / fpo {} two {} tpo {} '.format(
            all_fwo, all_fpo, all_two, all_tpo))

    for runner in runners:
        runner['has_odds'] = True

        # add odds
        runner['fwo'] = runner['fixedOdds']['returnWin']
        runner['fpo'] = runner['fixedOdds']['returnPlace']
        runner['two'] = runner['parimutuel']['returnWin']
        runner['tpo'] = runner['parimutuel']['returnPlace']
        runner['win_odds'] = runner['parimutuel']['returnWin']
        runner['place_odds'] = runner['parimutuel']['returnPlace']
        logger.debug('#{} fwo:{} fpo:{} two:{} tpo:{}'.format(
            runner['runnerNumber'], runner['fwo'], runner['fpo'], runner['two'], runner['tpo']))

        if not runner['fwo'] or not runner['fpo'] or not runner['two'] or not runner['tpo']:
            logger.debug('#{} has no odds'.format(runner['runnerNumber']))
            runner['has_odds'] = False
            continue

        # add scaling
        runner['fwp'] = 1 / runner['fwo']
        runner['fpp'] = 1 / runner['fpo']
        runner['twp'] = 1 / runner['two']
        runner['tpp'] = 1 / runner['tpo']


class PredictionError(Exception):
    pass


def add_predictions(runners, race_type):
    """predict for bet type"""
    for bet_type in BET_TYPES:
        if bet_type == BET_TYPE_PLACE:
            continue
        pred = '{}_pred'.format(bet_type)

        # model
        mdl = MODELS[race_type][bet_type]

        runners = [r for r in runners if r['has_odds']]
        if len(runners) != 8:
            raise PredictionError('Runners are not length 8')

        runners = sorted(runners, key=itemgetter('fwo'))

        x = []
        for r in runners:
            x.extend([r['fwp'], r['fpp'], r['twp'], r['tpp']])
        logger.debug('{} x of {}'.format(len(x), x))

        # make prediction on data
        preds = mdl.predict(np.array([x]))
        logger.debug('preds={}'.format(preds))
        for r, p in zip(runners, preds[0]):
            logger.debug('#{} {} prediction: {:.2f}'.format(r['runnerNumber'], bet_type, p))
            r[pred] = p


class ProbabilityError(Exception):
    pass


def add_probabilities(runners):
    """convert predictions to probabilities"""
    # get total (scratched has 0 for prediction)
    for bet_type in BET_TYPES:
        if bet_type == BET_TYPE_PLACE:
            continue
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        for r in runners:
            if not r['has_odds']:
                continue
            r[prob] = r[pred]
