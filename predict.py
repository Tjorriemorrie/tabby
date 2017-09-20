import json
import logging

import numpy as np
from keras.models import load_model

from model import load_races, delete_race, db_session

logger = logging.getLogger(__name__)

STATUSES = {'Open', 'LateScratched', 'Placing', 'Loser', 'Winner', 'Normal', 'Closed'}

# models for every type of racing
MODELS = {
    'G': load_model('models/G30x30.h5'),
    'H': load_model('models/i5p_40x40x40x40.h5'),
    'R': load_model('models/R30x30.h5'),
}


class NoRunnersError(Exception):
    pass


def predictions(debug, odds_only, category):
    """main method to update predictions in db"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    races = load_races()
    logger.info('predicting on {} races...'.format(len(races)))

    for i, race in enumerate(races):
        logger.info('Predicting race {} {}'.format(race.meeting_name, race.meeting_date))

        # skip non-racing
        if race.race_type != category:
            continue

        runners = race.get_runners()

        # shared with watching
        try:
            add_scaled_odds(runners)
            if not odds_only:
                race.num_runners = add_predictions(runners, race.race_type)
                add_probabilities(runners)
        except KeyError as e:
            print(json.dumps(runners, indent=4, default=str, sort_keys=True))
            raise
            # logger.error(e)
            # delete_race(race.id)
        else:
            logger.info('{:.1f}% completed'.format(i / len(races) * 100))
            race.set_runners(runners)

    logger.info('saving...')
    db_session.commit()


def bettable(r):
    """is runner bettable"""
    return r['probability'] > r['odds_scale'] and r['odds_win'] > 0


def add_scaled_odds(runners):
    """add odds for fixed and perimutuel"""
    # convert decimal odds to percentages
    # print(json.dumps(runners[0], indent=4, default=str, sort_keys=True))
    # raise Exception('')

    # get odds listing for ranking
    all_odds = sorted([r['fixedOdds']['returnWin'] for r in runners if r['fixedOdds']['returnWin'] > 0])

    for runner in runners:

        # best odds for betting
        runner['odds_win'] = runner['fixedOdds']['returnWin']

        if not runner['odds_win']:
            runner['rank_win'] = len(runners)
            runner['odds_perc'] = 0
            continue

        # add runner rank
        runner['rank_win'] = all_odds.index(runner['odds_win']) + 1

        # odds for scaling
        runner['odds_perc'] = 1 / runner['odds_win']
        logger.debug('#{} odds {:.2f} => perc {:.2f}'.format(
            runner['runnerNumber'], runner['odds_win'], runner['odds_perc']))

    # get total (scratched has 0 for win)
    total = sum([r['odds_perc'] for r in runners])
    logger.debug('total {:.2f}'.format(total))

    # scale it
    for runner in runners:
        runner['odds_scale'] = total and runner['odds_perc'] / total
        logger.debug('#{} perc {:.2f} => scale {:.2f}'.format(
            runner['runnerNumber'], runner['odds_perc'], runner['odds_scale']))

        for k in ['odds_fwin', 'odds_twin',
                  'odds_fwin', 'odds_twin',
                  'odds_fperc', 'odds_tperc',
                  'rank_fwin', 'rank_twin',
                  'odds_fscale', 'odds_tscale']:
            runner.pop(k, None)


def add_predictions(runners, race_type):
    """xp xs xr xn"""
    # model
    mdl = MODELS[race_type]

    # xn
    xn = len([r for r in runners if r['odds_win']])
    if not xn:
        # print(json.dumps(runners, indent=4, default=str, sort_keys=True))
        raise NoRunnersError()

    for runner in runners:
        prediction = 0

        if not runner['odds_win']:
            logger.debug('runner scratched')
        else:
            # get data
            x = [(runner['odds_perc'], runner['odds_scale'], runner['rank_win'], xn)]
            # make prediction on data
            preds = mdl.predict(np.array(x))
            prediction = sum(preds[0])
            logger.debug('#{} prediction: {:.2f} from {}'.format(runner['runnerNumber'], prediction, x))
        runner['prediction'] = prediction

    # return num_runners
    return xn


def add_probabilities(runners):
    """convert predictions to probabilities"""
    # get total (scratched has 0 for prediction)
    total = sum([r['prediction'] for r in runners])
    logger.info('total prediction = {}'.format(total))

    # scale predictions
    for runner in runners:
        probability = runner['prediction'] / total
        runner['probability'] = probability
        if runner['prediction']:
            logger.info('#{} probability: {:.2f}'.format(runner['runnerNumber'], probability))

    # total probability must be 1
    total_prob = sum(r['probability'] for r in runners)
    if round(total_prob, 2) != 1.00:
        raise ValueError('Probability must be 1, has {}'.format(total_prob))


def is_good_status(runner):
    status = runner['fixedOdds']['bettingStatus']
    if status not in STATUSES:
        print(json.dumps(runner, indent=4, default=str, sort_keys=True))
        raise ValueError('unknown status {}'.format(status))
    return status not in ['LateScratched', 'Reserve']
