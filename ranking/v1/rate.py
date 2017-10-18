import json
import logging
import math
import time
from statistics import mean, stdev
from math import sqrt
from itertools import combinations
from operator import itemgetter
from random import gauss

from each_way.v2.predict import add_odds, OddsError
import numpy as np
import scipy as sp
from trueskill import Rating, rate, setup, quality, global_env

from constants import *
from data.race import load_races, delete_race, db_session
from data.player import load_player, delete_race_type, save_players, db_session as player_session, get_last_player_date

logger = logging.getLogger(__name__)

setup(backend='scipy')


def run(race_types, force):
    """main method to update ratings in db"""
    for race_type in race_types or ['R', 'G', 'H']:
        logger.info('Running race type {}'.format(race_type))
        cache = {}

        # force truncate
        if force:
            delete_race_type(race_type)
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

            try:
                add_odds(runners)
            except OddsError as e:
                logger.warning(e)
                delete_race(race.id)
                continue

            add_ratings(runners, race_type, cache, force)
            add_probabilities(runners)
            results = race.get_results()

            try:
                rate_outcome(race, runners, results, cache)
            except (KeyError, ValueError) as e:
                logger.warning(e)
                delete_race(race.id)
            else:
                for runner in runners:
                    runner.pop('rating')
                race.set_runners(runners)
                logger.info('{:.1f}% completed {}'.format(i / len(races) * 100, race.race_start_time))

        logger.info('saving races...')
        db_session.commit()
        player_session.commit()


def add_ratings(runners, race_type, cache=None, create_new=False):
    """add ratings to runners"""
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)

        cache = cache or {}
        logger.debug('adding ratings for {} runners'.format(len(runners)))
        for runner in runners:
            # print(json.dumps(runner, indent=4, default=str, sort_keys=True))
            # raise Exception('')

            # find player in cache preferably
            rating = Rating()
            cnt = 1
            try:
                player = cache[runner['runnerName']]
                rating = Rating(player.rating_m, player.rating_s)
                cnt = player.cnt + 1
            except KeyError:
                if not create_new:
                    player = load_player(runner['runnerName'])
                    if player:
                        rating = Rating(player.rating_m, player.rating_s)
                        cnt = player.cnt + 1

            logger.debug(rating)
            runner['rating'] = rating
            runner['cnt'] = cnt
            runner[pred] = 0
            # r['sample'] = [gauss(r['rating'].mu, r['rating'].sigma) for _ in range(1000)]

        pool = [r for r in runners if r['has_odds']]
        for p in pool:
            t1 = [p['rating']] * (len(pool) - 1)
            t2 = [pp['rating'] for pp in pool]
            pwin = probability_NvsM(t1, t2)
            logger.debug('#{} rating {} odds {:.2f} pwin {:.2f}'.format(
                p['runnerNumber'], p['rating'], p['win_perc'], pwin))
            p[pred] = pwin


def rate_outcome(race, runners, results, cache):
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
    save_players(race, parts, new_ratings, cache)


def add_probabilities(runners):
    """Use quality for probability
    use relu: only scale positive bets higher than oddspred"""
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        preds = [r[pred] for r in runners if r[pred] > 0]
        total_pred = sum(preds)
        logger.debug('total {} prediction = {}'.format(bet_type, total_pred))

        for runner in runners:
            runner[prob] = 0
            if runner[pred] > 0:
                runner[prob] = runner[pred] / total_pred
                logger.debug('#{} prob {}'.format(runner['runnerNumber'], runner[prob]))


################################################################################################
# betting
################################################################################################

X = {
    RACE_TYPE_RACING: {
        # $0.00 profit per race     5% of races 571 / 12497
        BET_TYPE_WIN: [0., 2.222222],
        # $0.00 profit per race     97% of races 12599 / 13032
        BET_TYPE_PLACE: [0, 0],
    },
    RACE_TYPE_GRAYHOUND: {
        # $0.00 profit per race     0% of races 24 / 16127
        BET_TYPE_WIN: [0.000094, 23.1875],
        # $0.00 profit per race     93% of races 16127 / 17252
        BET_TYPE_PLACE: [0, 0],
    },
    RACE_TYPE_HARNESS: {
        # $0.00 profit per race     1% of races 143 / 10304
        BET_TYPE_WIN: [0.000094, 8.555556],
        # $0.00 profit per race     94% of races 10304 / 10976
        BET_TYPE_PLACE: [0, 0],
    },
}


def bet_dutch(runners, bet_chunk, race_type, bet_type, x=None):
    """dutch betting on probability"""
    prob = '{}_prob'.format(bet_type)
    bet = '{}_bet'.format(bet_type)
    #     print('X = {}'.format(x))

    if not x:
        x = X[race_type][bet_type]

    # sort runners from favourite to underdog
    runners.sort(key=lambda r: r.get(prob, 0), reverse=True)

    # start betting on all and cut off worse runner till positive outcome
    for num_bets in range(len(runners), 0, -1):

        # reset bets
        for runner in runners:
            runner[bet] = 0
            runner['{}_type'.format(bet)] = 'parimutuel'
            runner['payout'] = 0

        # recreate smaller pool
        pool = runners[:num_bets]
        #         print('pool is {} from {} bets'.format(len(pool), num_bets))

        # dutch for all in pool
        for runner in pool:
            # skip negative probability
            if runner[prob] <= 0:
                #                 print('#{} has negative prob {:.2f}'.format(runner['runnerNumber'], runner[prob]))
                continue

            # scale bet according to probability
            bet_amt = round(runner[prob] * bet_chunk)
            runner[bet] = bet_amt
            #             print('#{} bet={:.2f}'.format(runner['runnerNumber'], runner[bet]))
            if not runner[bet]:
                continue

            # payouts
            # need to check all as we scale to probs and not odds
            if bet_type == 'W':
                odds = runner['win_odds']
            elif bet_type == 'P':
                odds = runner['place_odds']
            # print('odds {:.2f} and scaled {:.2f}'.format(odds, scaled))
            runner['payout'] = runner[bet] * odds

        ###################################################################################
        # MAX NEWBIES
        ###################################################################################
        max_newbies_flag = False
        newbies = sum(p['cnt'] == 1 for p in pool if p[prob])
        newbies_ratio = newbies / len(runners)
        #         print('{} newbies, ratio={:.2f}'.format(newbies, newbies_ratio))
        if newbies_ratio <= x[0]:
            max_newbies_flag = True

        ###################################################################################
        # MIN PROFIT
        ###################################################################################
        total_bets = sum(p[bet] for p in pool)
        profits = [p['payout'] - total_bets for p in pool]
        min_profit_flag = False
        if min(profits) >= x[1]:
            min_profit_flag = True

        if max_newbies_flag and min_profit_flag:
            #             print('breaking!')
            #             raise Exception('foo')
            break
            #         else:
            #             print('flag not hit')
    else:
        #         print('no profit determined')
        return [], 0

    # put bets from pool into runners
    for p in pool:
        for r in runners:
            if r['runnerNumber'] == p['runnerNumber']:
                r[bet] = p[bet]
                r['{}_type'.format(bet)] = p['{}_type'.format(bet)]
                break

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
