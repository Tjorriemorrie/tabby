import logging

import numpy as np
from keras.models import load_model

logger = logging.getLogger(__name__)


# returns a compiled model
# identical to the previous one
model_default = load_model('model_default.h5')


STATUSES = {'Open', 'LateScratched', 'Placing', 'Loser', 'Winner', 'Normal'}


def predict(race):
    logger.info('predicting race...')
    add_predictions(race)
    add_probabilities(race)
    add_scaled_odds(race)


def add_predictions(race):
    # select specific model
    model = model_default

    race_type = race['meeting']['raceType']

    # get num runners
    num_runners = sum(is_good_status(r) for r in race['runners'])
    logger.info('{} runners'.format(num_runners))
    race['num_runners'] = num_runners

    # make prediction for each runner separately
    for runner in race['runners']:
        prediction = 0
        if is_good_status(runner):
            data = [(runner['fixedOdds']['returnWin'], num_runners)]
            logger.debug('data = {}'.format(data))
            preds = model.predict(np.array(data))
            prediction = sum(preds[0])
        else:
            logger.debug('runner scratched')
        runner['prediction'] = prediction
        logger.info('prediction = {}'.format(prediction))


def add_probabilities(race):
    # get total (scratched has 0 for prediction)
    total = sum([r['prediction'] for r in race['runners']])
    logger.info('total prediction = {}'.format(total))

    # scale predictions
    for runner in race['runners']:
        runner['probability'] = runner['prediction'] / total
        logger.debug('prob = {}'.format(runner['probability']))


def add_scaled_odds(race):
    # convert decimal odds to percentages
    for runner in race['runners']:

        # best odds for betting
        runner['odds_best'] = max([runner['fixedOdds']['returnWin'], runner['parimutuel']['returnWin']])

        # fixed odds for scaling
        runner['odds_perc'] = runner['fixedOdds']['returnWin'] and 1 / runner['fixedOdds']['returnWin']
        logger.info('Percentaged odds {:.2f} => {:.2f}'.format(runner['fixedOdds']['returnWin'], runner['odds_perc']))

    # get total (scratched has 0 for win)
    total = sum([r['odds_perc'] for r in race['runners']])
    logger.info('total odds_perc = {:.2f}'.format(total))

    # scale it
    for runner in race['runners']:
        runner['odds_scaled'] = runner['odds_perc'] / total
        logger.info('Scaled odds {:.2f} => {:.2f}'.format(runner['odds_perc'], runner['odds_scaled']))


def is_good_status(runner, tote=False):
    status = runner['fixedOdds']['bettingStatus']
    if tote:
        status = runner['parimutuel']['bettingStatus']
    if status not in STATUSES:
        raise ValueError('unknown status {}'.format(status))
    return status not in ['LateScratched']
