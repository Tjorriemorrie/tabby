import json
import logging
import math
from operator import itemgetter

import numpy as np
from keras.models import load_model

from trueskill import Rating, rate, setup, quality, global_env
from constants import *
from data.player import load_player, delete_race_players, save_players, db_session as player_session, get_last_player_date
from data.race import load_races, delete_race, db_session as race_session

logger = logging.getLogger(__name__)

setup(backend='scipy')


def run(race_types, odds_only, pred_only, force):
    """main method to update predictions in db"""
    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))
        cache = {}

        # force truncate
        if force:
            delete_race_players(race_type)
            races = load_races(race_type)
            logger.info('loaded {} races...'.format(len(races)))
        # if predictions
        elif pred_only:
            races = load_races(race_type)
            logger.info('loaded {} races...'.format(len(races)))
        # continue for new races
        else:
            last_date = get_last_player_date(race_type)
            races = load_races(race_type, last_date)
            logger.info('loaded {} races since {}...'.format(len(races), last_date))

        if not races:
            raise Exception('No new races')

        for i, race in enumerate(races):
            logger.debug('Running race {} {}'.format(race.meeting_name, race.meeting_date))
            runners = race.get_runners()

            if not pred_only:
                try:
                    add_odds(runners, cache, force)
                except OddsError as e:
                    logger.warning(e)
                    delete_race(race.id)
                    continue
                else:
                    # with odds the outcome can be saved to players
                    rate_outcome(race, runners, race.get_results(), cache)

            if not odds_only:
                try:
                    add_predictions(runners, race_type)
                    add_probabilities(runners)
                except PredictionError as e:
                    logger.info('Skipping {}'.format(race))
                    continue
                except (Exception, ProbabilityError):
                    print(json.dumps(race, indent=4, default=str, sort_keys=True))
                    print(json.dumps(runners, indent=4, default=str, sort_keys=True))
                    # delete_race(race.id)
                    race_session.commit()
                    raise

            race.num_runners = len([r for r in runners if r['has_odds']])
            race.set_runners(runners)
            logger.info('{:.1f}% completed'.format(i / len(races) * 100))

        logger.info('saving...')
        race_session.commit()
        player_session.commit()


class OddsError(Exception):
    pass


def add_odds(runners, cache=None, create_new=False):
    """add values for fixed and tote"""
    cache = cache or {}

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

    new_rating = Rating()
    for i, runner in enumerate(runners):
        runner['has_odds'] = True

        # add odds
        runner['fwo'] = runner['fixedOdds']['returnWin']
        runner['fpo'] = runner['fixedOdds']['returnPlace']
        runner['two'] = runner['parimutuel']['returnWin']
        runner['tpo'] = runner['parimutuel']['returnPlace']
        logger.debug('#{} fwo:{} fpo:{} two:{} tpo:{}'.format(
            runner['runnerNumber'], runner['fwo'], runner['fpo'], runner['two'], runner['tpo']))

        if not runner['fwo'] or not runner['fpo'] or not runner['two'] or not runner['tpo']:
            logger.debug('#{} has no odds'.format(runner['runnerNumber']))
            runner['has_odds'] = False
            continue

        # add odds for betting later
        runner['win_odds'] = runner['parimutuel']['returnWin']
        runner['place_odds'] = runner['parimutuel']['returnPlace']

        # add percentage repr of odds
        runner['fwp'] = 1 / runner['fwo']
        runner['fpp'] = 1 / runner['fpo']
        runner['twp'] = 1 / runner['two']
        runner['tpp'] = 1 / runner['tpo']

        # add rank of odds
        runner['fwr'] = 1 - (all_fwo.index(runner['fwo']) / len(runners))
        runner['fpr'] = 1 - (all_fpo.index(runner['fpo']) / len(runners))
        runner['twr'] = 1 - (all_two.index(runner['two']) / len(runners))
        runner['tpr'] = 1 - (all_tpo.index(runner['tpo']) / len(runners))
        logger.debug('#{} win rank {:.2f} and place rank {:.2f}'.format(
            runner['runnerNumber'], runner['fwr'], runner['fpr']))

        # add ratings - find player in cache preferably
        mu, sigma = new_rating.mu, new_rating.sigma
        cnt = 1
        try:
            player = cache[runner['runnerName']]
            mu, sigma = player.rating_m, player.rating_s
            cnt = player.cnt + 1
        except KeyError:
            if not create_new:
                player = load_player(runner['runnerName'])
                if player:
                    mu, sigma = player.rating_m, player.rating_s
                    cnt = player.cnt + 1

        logger.debug('#{} rating mu {} sigma {}'.format(runner['runnerNumber'], mu, sigma))
        runner['rating_mu'] = mu
        runner['rating_sigma'] = sigma
        runner['mu_scaled'] = mu / new_rating.mu
        runner['sigma_scaled'] = sigma / new_rating.sigma
        runner['cnt'] = cnt

    # drop runners without odds
    runners = [r for r in runners if r['has_odds']]
    num_runners = len(runners)
    logger.debug('num runners now {}'.format(len(runners)))
    if num_runners <= 2:
        raise OddsError('No enough runners: {}'.format(num_runners))

    # get percentage totals (scratched has 0 for win)
    total_fwp = sum([r['fwp'] for r in runners])
    total_fpp = sum([r['fpp'] for r in runners])
    total_twp = sum([r['twp'] for r in runners])
    total_tpp = sum([r['tpp'] for r in runners])
    logger.debug('totals: fwp={:.2f} fpp={:.2f} twp={:.2f} tpp={:.2f}'.format(
        total_fwp, total_fpp, total_twp, total_tpp))
    if not total_fwp or not total_fpp:
        raise OddsError('No total win perc {} or no total place perc {}'.format(total_fwp, total_fpp))

    for runner in runners:
        # scale it
        runner['num_runners'] = 1 / num_runners
        runner['fws'] = runner['fwp'] / total_fwp
        runner['fps'] = runner['fpp'] / total_fpp
        runner['tws'] = runner['twp'] / total_twp
        runner['tps'] = runner['tpp'] / total_tpp

        # now calculate rating win probability
        t1 = [Rating(runner['rating_mu'], runner['rating_sigma'])] * (len(runners) - 1)
        t2 = [Rating(pp['rating_mu'], pp['rating_sigma']) for pp in runners if pp != runner]
        assert len(t1) == len(t2)
        rating_pred = probability_NvsM(t1, t2)
        logger.debug('#{} rating {} prob {:.2f}'.format(
            runner['runnerNumber'], runner['rating_mu'], rating_pred))
        runner['rating_pred'] = rating_pred

    # normalize to a prob
    all_rating_preds = sum(r['rating_pred'] for r in runners)
    for runner in runners:
        runner['rating_prob'] = runner['rating_pred'] / all_rating_preds
        logger.debug('#{} pred {:.2f} to prob {:.2f}'.format(runner['runnerNumber'], runner['rating_pred'], runner['rating_prob']))


def rate_outcome(race, runners, results, cache):
    """do rating from results, not finishingPosition (it is also 0 for non-placed)"""
    parts = [r for r in runners if r['has_odds']]
    logger.debug('{} participants'.format(len(parts)))

    team = [(Rating(p['rating_mu'], p['rating_sigma']),) for p in parts]
    logger.debug('team = {}'.format(team))

    for p in parts:
        p['pos'] = 5
    for i, result in enumerate(results):
        for n in result:
            for p in parts:
                if p['runnerNumber'] == n:
                    logger.debug('outcome found: n {} and p {} at rank {}'.format(n, p['runnerNumber'], i+1))
                    p['pos'] = i + 1
                    break
    pos = [p['pos'] for p in parts]

    try:
        new_ratings = rate(team, pos)
        logger.debug('new ratings {}'.format(new_ratings))
    except:
        logger.info(team)
        logger.info(pos)
        raise
    save_players(race, parts, new_ratings, cache)


################################################################################################
# prediction
################################################################################################

MODELS = {
    RACE_TYPE_RACING: {
        BET_TYPE_WIN: load_model('each_way/v3/models/R64x64W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v3/models/R64x64P.h5'),
    },
    RACE_TYPE_GRAYHOUND: {
        BET_TYPE_WIN: load_model('each_way/v3/models/G64x64W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v3/models/G64x64P.h5'),
    },
    RACE_TYPE_HARNESS: {
        BET_TYPE_WIN: load_model('each_way/v3/models/H64x64W.h5'),
        BET_TYPE_PLACE: load_model('each_way/v3/models/H64x64P.h5'),
    },
}


class PredictionError(Exception):
    pass


def add_predictions(runners, race_type):
    """predict for bet type"""
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)

        # model
        mdl = MODELS[race_type][bet_type]

        runners = [r for r in runners]

        for r in runners:
            if not r['has_odds']:
                r[pred] = 0
                continue

            X = [r['num_runners'],
                 r['fws'], r['fps'], r['tws'], r['tps'],
                 r['fwr'], r['fpr'], r['twr'], r['tpr'],
                 r['mu_scaled'], r['sigma_scaled'], r['rating_prob']
            ]
            logger.debug('{} x of {}'.format(len(X), X))

            # make prediction on data
            p = mdl.predict(np.array([X]))
            p = sum(p[0])
            logger.debug('preds={}'.format(p))
            logger.debug('#{} {} prediction: {:.2f}'.format(r['runnerNumber'], bet_type, p))
            r[pred] = p


class ProbabilityError(Exception):
    pass


def add_probabilities(runners):
    """convert predictions to probabilities"""
    # get total (scratched has 0 for prediction)
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        preds = [r[pred] for r in runners]
        total_pred = sum(preds)
        logger.debug('total {} prediction = {}'.format(bet_type, total_pred))
        if not total_pred:
            raise ProbabilityError('No total prediction, retrain {}, got {}'.format(bet_type, preds))

        # scale predictions
        for runner in runners:
            if not runner['has_odds']:
                runner[prob] = 0
                continue

            probability = runner[pred] / total_pred
            runner[prob] = probability
            if runner[pred]:
                logger.debug('#{} {} probability: {:.2f}'.format(runner['runnerNumber'], bet_type, probability))
            # if runner['runnerName'] == 'TARNHELM' and runner['win_odds'] == 2.3 and bet_type == BET_TYPE_PLACE:
            #     raise Exception(probability)

        # total probability must be 1
        total_prob = sum(r[prob] for r in runners)
        logger.debug('total {} probability = {}'.format(bet_type, round(total_prob, 2)))
        if round(total_prob, 2) != 1:
            raise ProbabilityError('Probability must be 1, has {}'.format(total_prob))


################################################################################################
# betting
################################################################################################

class NoBetsError(Exception):
    pass


X = {
    RACE_TYPE_RACING: {
        # $0.11 profit per race     4% of races 823 / 18895     [4.494],
        # $0.07 profit per race     12% of races 2410 / 19348   [0., 3.497, 7.021],     0.01
        # $0.03 profit per race     14% of races 2719 / 19348   [5.014, 2.41, 3.367],   0.1
        # $0.09 profit per race     7% of races 1441 / 19348    [6.183, 2.992, 3.967],  0.2
        # $0.08 profit per race     6% of races 1202 / 19348    [4.138, 1.028, 5.706],  0.3
        # $0.05 profit per race     21% of races 4001 / 19362   [7.24, 2.908, 0.],      0.4
        # $0.08 profit per race     11% of races 2204 / 19588   [2.658, 3.581, 6.256],  0.5
        # $0.07 profit per race     9% of races 1766 / 19588
        BET_TYPE_WIN: [9.295, 3.717, -0.],
        # $0.69 profit per race     38% of races 8947 / 23559   [0.539],
        # $0.89 profit per race     6% of races 1127 / 19348    [0., 1.818, 3.561],     0.01
        # $1.11 profit per race     14% of races 2725 / 19348   [-0., 1.2, 2.414],      0.1
        # $1.29 profit per race     24% of races 4661 / 19348   [1., 2., 1.],           0.2
        # $1.28 profit per race     20% of races 3859 / 19362   [-0., 6.597, 1.098],    0.3
        # $1.38 profit per race     25% of races 4904 / 19453   [6.128, 0., 0.947],     0.4
        # $1.39 profit per race     30% of races 5877 / 19588
        BET_TYPE_PLACE: [3.567, -0., 0.889],
    },
    RACE_TYPE_GRAYHOUND: {
        # $0.27 profit per race     15% of races 3539 / 23559   [2.659],
        # $0.12 profit per race     1% of races 244 / 24178     [5.256, 1.774, 7.168],  0.01
        # $0.16 profit per race     22% of races 5381 / 24178   [1.168, 5.818, 2.339],  0.1
        # $0.15 profit per race     9% of races 2101 / 24178    [3.027, 4.102, 3.026],  0.2
        # $0.16 profit per race     3% of races 659 / 24179     [2., 3.999, 6.299],     0.3
        # $0.25 profit per race     5% of races 1273 / 24285    [2.859, 4.771, 3.346],  0.4
        # $0.24 profit per race     14% of races 3454 / 24406   [7.216, 2.679, 1.768],  0.5
        # $0.24 profit per race     12% of races 2981 / 24406
        BET_TYPE_WIN: [1.845, 4.5, 2.767],
        # $0.67 profit per race     37% of races 9332 / 25038   [0.591],
        # $0.11 profit per race     0% of races 54 / 24178      [5.367, 3.889, 4.667],  0.01
        # $0.53 profit per race     9% of races 2224 / 24178    [0., 1.136, 2.422],     0.1
        # $0.58 profit per race     14% of races 3479 / 24178   [-0., 5.473, 0.944],    0.2
        # $0.57 profit per race     14% of races 3499 / 24179   [0., 0.979, 1.997],     0.3
        # $0.59 profit per race     12% of races 2895 / 24285   [7.024, 0., 1.024],     0.4
        # $0.66 profit per race     19% of races 4682 / 24406
        BET_TYPE_PLACE: [2.717, 0., 0.882],
    },
    RACE_TYPE_HARNESS: {
        # $0.22 profit per race     6% of races 921 / 15007     [3.318],
        # $0.16 profit per race     5% of races 796 / 15399     [7.085, 3.5, 3.501],    0.01
        # $0.15 profit per race     16% of races 2490 / 15399   [2.326, 3.504, 2.414],  0.1
        # $0.16 profit per race     8% of races 1308 / 15399    [3.075, 7.175, 0.962],  0.2
        # $0.08 profit per race     28% of races 4359 / 15404   [2., 2., 5.25],         0.3
        # $0.18 profit per race     8% of races 1176 / 15467    [3.093, 4.123, 3.106],  0.4
        # $0.17 profit per race     5% of races 724 / 15540     [6.117, 3.616, 3.421],  0.5
        # $0.15 profit per race     10% of races 1504 / 15540
        BET_TYPE_WIN: [5.146, 1.797, 2.94],
        # $0.84 profit per race     51% of races 7589 / 15007   [0.35],
        # $0.37 profit per race     98% of races 15028 / 15399  [1.808, -0., 0.],       0.01
        # $0.56 profit per race     10% of races 1549 / 15399   [1.136, 4.592, 0.],     0.1
        # $0.63 profit per race     12% of races 1872 / 15399   [1., 2., 1.],           0.2
        # $0.71 profit per race     15% of races 2339 / 15404   [-0., 4.255, 0.97],     0.3
        # $0.71 profit per race     15% of races 2361 / 15540   [0., 3.158, 0.991],     0.4
        # $0.86 profit per race     20% of races 3083 / 15540
        BET_TYPE_PLACE: [2.665, 0., 0.89],
    },
}


def bet_positive_dutch(runners, bet_chunk, race_type, bet_type, x=None):
    """dutch betting on probability"""
    prob = '{}_prob'.format(bet_type)
    bet = '{}_bet'.format(bet_type)
    x = X[race_type][bet_type]

    if bet_type == 'W':
        key_odds = 'win_odds'
        key_scaled = 'fws'
    else:
        key_odds = 'place_odds'
        key_scaled = 'fps'

    # sort runners from favourite to underdog
    runners.sort(key=lambda r: r.get(prob, 0), reverse=True)

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), -1, -1):
        logger.debug('Trying to form pool for {}...'.format(num_bets))

        # reset bets
        for runner in runners:
            runner[bet] = 0

        # recreate smaller pool
        pool = runners[:num_bets]
        assert len(pool) == num_bets
        if not pool:
            continue

        # all prediction values
        total_probs = sum([r[prob] for r in pool])
        if not total_probs:
            continue

        # dutch for all in pool
        for runner in pool:

            # scale bet according to prediction
            runner[bet] = round(bet_chunk * runner[prob] / total_probs, 1)
            runner['{}_type'.format(bet)] = 'parimutuel'
            #             print('bet {:.2f}'.format(runner[bet]))

            # need to check all as we scale to probs and not odds
            odds = runner[key_odds]
            odds_scaled = runner[key_scaled]
            runner['payout'] = runner[bet] * odds
            runner['odds_scaled'] = runner[prob] / odds_scaled

        total_bets = sum(p[bet] for p in pool)
        profits = [p['payout'] - total_bets for p in pool]

        ###################################################################################
        # FIRST
        ###################################################################################
        first_profit_flag = False
        if profits[0] / bet_chunk >= x[0]:
            first_profit_flag = True

        ###################################################################################
        # AVG
        ###################################################################################
        avg_profit_flag = False
        avg_profit = sum(profits) / len(profits)
        if avg_profit / bet_chunk >= x[1]:
            avg_profit_flag = True

        ###################################################################################
        # LAST
        ###################################################################################
        last_profit_flag = False
        if profits[-1] / bet_chunk >= x[2]:
            last_profit_flag = True

        if sum([last_profit_flag, avg_profit_flag, first_profit_flag]) >= 2:
            logger.debug('{} found for {} runners!'.format(bet, len(pool)))
            break
    else:
        logger.debug('No {} bet found!'.format(bet))
        assert all(r[bet] == 0 for r in runners)
        assert num_bets == 0
        return runners, num_bets

    # put bets from pool into runners
    for p in pool:
        for r in runners:
            if r['runnerNumber'] == p['runnerNumber']:
                r[bet] = p[bet]
                r['{}_type'.format(bet)] = p['{}_type'.format(bet)]
                logger.debug('#{} placed {} of {}'.format(r['runnerNumber'], bet, r[bet]))
                break

    logger.debug('Making {} {} bets'.format(bet_type, num_bets))
    return runners, num_bets




################################################################################################
# trueskill extras
################################################################################################

def probability_NvsM(team1_ratings, team2_ratings, env=None):
    """Calculates the win probability of the first team over the second team.
    :param team1_ratings: ratings of the first team participants.
    :param team2_ratings: ratings of another team participants.
    :param env: the :class:`TrueSkill` object.  Defaults to the global
                environment.
    """
    if env is None:
        env = global_env()

    team1_mu = sum(r.mu for r in team1_ratings)
    team1_sigma = sum((env.beta**2 + r.sigma**2) for r in team1_ratings)
    team2_mu = sum(r.mu for r in team2_ratings)
    team2_sigma = sum((env.beta**2 + r.sigma**2) for r in team2_ratings)

    x = (team1_mu - team2_mu) / math.sqrt(team1_sigma + team2_sigma)
    probability_win_team1 = env.cdf(x)
    return probability_win_team1


def probability_1vs1(rating1, rating2, env=None):
    """A shortcut to calculate the win probability between just 2 players in
    a head-to-head match
    :param rating1: the rating.
    :param rating2: the another rating.
    :param env: the :class:`TrueSkill` object.  Defaults to the global
                environment.
    :return: probability the first player wins
    """
    return probability_NvsM((rating1,), (rating2,), env=env)


def cles(greaters, lessers):
    """Common-Language Effect Size
    Probability that a random draw from `greater` is in fact greater
    than a random draw from `lesser`.
    Args:
      lesser, greater: Iterables of comparables.
    """
    if len(lessers) == 0 and len(greaters) == 0:
        raise ValueError('At least one argument must be non-empty')
    # These values are a bit arbitrary, but make some sense.
    # (It might be appropriate to warn for these cases.)
    if len(lessers) == 0:
        return 1
    if len(greaters) == 0:
        return 0
    numerator = 0
    lessers, greaters = sorted(lessers), sorted(greaters)
    lesser_index = 0
    for greater in greaters:
        while lesser_index < len(lessers) and lessers[lesser_index] < greater:
            lesser_index += 1
        numerator += lesser_index  # the count less than the greater
    denominator = len(lessers) * len(greaters)
    return float(numerator) / denominator
