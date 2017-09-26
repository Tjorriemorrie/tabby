import logging
from itertools import combinations
from operator import itemgetter

from model import load_races
from py.runbo import db_session, clear_runbo, save_runbo

logger = logging.getLogger(__name__)


def build_exotic_bets(debug, race_type, bet_type):
    """main method to update predictions in db"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.info('building exotic bets')

    # recreate as cannot update with no unique info being stored
    clear_runbo(race_type, bet_type)

    races = load_races(None)
    if bet_type == 'Q':
        r = 2
    else:
        raise Exception(bet_type)
    logger.info('building combinations from {} races for {} repeats'.format(len(races), r))

    for race in races:

        # get num runners (requires at least 8)
        if race.num_runners < 8:
            logger.debug('skipping {}'.format(race))
            continue

        # get results
        res1, res2, res3, res4 = race.get_results()
        res1, res2, res3, res4 = res1[0], res2[0], res3[0], res4[0]
        logger.debug('winners = {} {} {} {}'.format(res1, res2, res3, res4))

        # get runners
        # data rows will be permutations of 2
        # but combinations if sorted
        runners = sorted(race.get_runners(), key=itemgetter('win_scaled'))

        combs = build_combinations(runners, r)
        for comb in combs:
            comb.update({
                'race_type': race_type,
                'bet_type': bet_type,
                'num_runners': race.num_runners,
                'res1': res1,
                'res2': res2,
                'res3': res3,
                'res4': res4,
            })
            if r == 2:
                out = 1 if comb['run1_num'] == res1 and comb['run2_num'] == res2 else 0
                comb.update({
                    'quinella_div': race['quinella'],
                    'quinella_out': out,
                })
            save_runbo(comb)
        logger.info('Adding {} combinations for race {}'.format(len(combs), race))

    logger.info('saving...')
    db_session.commit()


def build_combinations(runners, r):
    combs = combinations(runners, r)
    data = []
    for comb in combs:
        item = {}
        for i, runner in enumerate(comb):
            item.update({
                'run{}_num'.format(i + 1): runner['runnerNumber'],
                'run{}_win_perc'.format(i + 1): runner['win_perc'],
                'run{}_win_scaled'.format(i + 1): runner['win_scaled'],
                'run{}_win_rank'.format(i + 1): runner['win_rank'],
            })
        data = data.append(item)
    return data
