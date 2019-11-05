import logging

from constants import *

logger = logging.getLogger(__name__)


class NoBetsError(Exception):
    pass


def bet_direct(runners, bet_chunk, race_type, bet_type):
    """direct betting"""
    if bet_type == BET_TYPE_PLACE:
        return runners, 0

    pred = '{}_pred'.format(bet_type)
    prob = '{}_prob'.format(bet_type)
    bet = '{}_bet'.format(bet_type)

    for r in runners:
        r[bet] = 0
        if r['has_odds']:
            r[bet] = round(r[prob], 2)

    return runners, 8
