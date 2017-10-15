import json
import logging
import math
import time
from statistics import mean, stdev
from math import sqrt
from itertools import combinations
from operator import itemgetter
from random import gauss

import numpy as np
import scipy as sp
from trueskill import Rating, rate, setup, quality, global_env

from constants import *
from data.race import load_races, delete_race, db_session
from data.player import load_player, delete_race_type, save_players

logger = logging.getLogger(__name__)

setup(backend='scipy')


def run(race_types):
    """main method to update ratings in db"""
    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))
        delete_race_type(race_type)

        races = load_races(race_type)
        logger.info('loaded {} races...'.format(len(races)))

        for i, race in enumerate(races):
            logger.info('{:.1f}% completed'.format(i / len(races) * 100))
            logger.debug('Running race {} {}'.format(race.meeting_name, race.meeting_date))
            runners = race.get_runners()
            add_ratings(runners)
            results = race.get_results()
            try:
                rate_outcome(race, runners, results)
            except (KeyError, ValueError) as e:
                logger.warning(e)
                delete_race(race.id)

    logger.info('saving races...')
    db_session.commit()


def add_ratings(runners, race_type):
    """add ratings to runners"""
    logger.debug('adding ratings for {} runners'.format(len(runners)))
    for runner in runners:
        # print(json.dumps(runner, indent=4, default=str, sort_keys=True))
        # raise Exception('')
        player = load_player(runner['runnerName'])
        if player:
            rating = Rating(player.rating_m, player.rating_s)
            cnt = player.cnt + 1
        else:
            rating = Rating()
            cnt = 1
        logger.debug(rating)
        runner['rating'] = rating
        runner['cnt'] = cnt
        runner['W_pred'], runner['P_pred'] = 0, 0
        # r['sample'] = [gauss(r['rating'].mu, r['rating'].sigma) for _ in range(1000)]

    pool = [r for r in runners if r['has_odds']]
    for p in pool:
        t1 = [p['rating']] * (len(pool) - 1)
        t2 = [pp['rating'] for pp in pool]
        pwin = probability_NvsM(t1, t2)
        logger.debug('#{} rating {} odds {:.2f} pwin {:.2f}'.format(
            p['runnerNumber'], p['rating'], p['win_perc'], pwin))
        p['W_pred'] = pwin


def rate_outcome(race, runners, results):
    """do rating from results, not finishingPosition"""
    parts = [r for r in runners if r['fixedOdds']['returnWin'] and r['parimutuel']['returnWin']]
    logger.debug('{} participants'.format(len(parts)))

    team = [(p['rating'],) for p in parts]
    logger.debug('team = {}'.format(team))

    for p in parts:
        p['rank'] = 5
    for i, result in enumerate(results):
        for n in result:
            for p in parts:
                if p['runnerNumber'] == n:
                    logger.debug('outcome found: n {} and p {} at rank {}'.format(n, p['runnerNumber'], i+1))
                    p['rank'] = i + 1
                    break
    ranks = [p['rank'] for p in parts]
    logger.debug('ranks = {}'.format(ranks))

    try:
        new_ratings = rate(team, ranks)
    except:
        logger.info(team)
        logger.info(ranks)
        raise
    save_players(race, parts, new_ratings)


def add_probabilities(runners):
    """Use quality for probability
    use relu: only scale positive bets higher than oddspred"""
    total = sum([r['W_pred'] for r in runners if r['has_odds']])
    logger.debug('total positive pred {:.2f}'.format(total))

    for runner in runners:
        runner['W_prob'], runner['P_prob'] = 0, 0
        if runner['has_odds'] and runner['']


def add_bets(runners, bet_chunk, race_type, bet_type):
    raise Exception('foo')
    return runners, 0


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
