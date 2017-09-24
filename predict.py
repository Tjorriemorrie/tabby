import json
import logging

import numpy as np
from keras.models import load_model

from model import load_races, delete_race, db_session

logger = logging.getLogger(__name__)

STATUSES = {'Open', 'LateScratched', 'Placing', 'Loser', 'Winner', 'Normal', 'Closed'}

BET_TYPE_WIN = 'W'
BET_TYPE_PLACE = 'P'
BET_TYPES = [BET_TYPE_WIN, BET_TYPE_PLACE]

RACE_TYPE_RACING = 'R'
RACE_TYPE_GRAYHOUND = 'G'
RACE_TYPE_HARNESS = 'H'
RACE_TYPES = [RACE_TYPE_RACING, RACE_TYPE_GRAYHOUND, RACE_TYPE_HARNESS]

MODELS = {
    RACE_TYPE_RACING: {
        BET_TYPE_WIN: load_model('models/R30x30W.h5'),
        BET_TYPE_PLACE: load_model('models/R30x30P.h5'),
    },
    RACE_TYPE_GRAYHOUND: {
        BET_TYPE_WIN: load_model('models/G30x30W.h5'),
        BET_TYPE_PLACE: load_model('models/G30x30P.h5'),
    },
    RACE_TYPE_HARNESS: {
        BET_TYPE_WIN: load_model('models/H30x30W.h5'),
        BET_TYPE_PLACE: load_model('models/H30x30P.h5'),
    },
}


class NoRunnersError(Exception):
    pass


class NoOddsError(Exception):
    pass


def predictions(debug, odds_only, category):
    """main method to update predictions in db"""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    races = load_races(category)
    logger.info('predicting on {} {} races...'.format(len(races), category or 'all'))

    for i, race in enumerate(races):
        logger.info('Predicting race {} {}'.format(race.meeting_name, race.meeting_date))

        runners = race.get_runners()

        # shared with watching
        try:
            add_scaled_odds(runners)
            if not odds_only:
                for bet_type in BET_TYPES:
                    race.num_runners = add_predictions(runners, race.race_type)
                    add_probabilities(runners)
        # back to unshared
        except KeyError as e:
            print(json.dumps(runners, indent=4, default=str, sort_keys=True))
            raise
            # logger.error(e)
            # delete_race(race.id)
        except NoOddsError as e:
            logger.error(e)
            delete_race(race.id)
        else:
            race.set_runners(runners)
            logger.info('{:.1f}% completed'.format(i / len(races) * 100))

    logger.info('saving...')
    db_session.commit()


def add_scaled_odds(runners):
    """add odds for fixed and perimutuel"""
    # convert decimal odds to percentages
    # print(json.dumps(runners[0], indent=4, default=str, sort_keys=True))
    # raise Exception('')

    # get odds listing for ranking
    all_odds = sorted([r['fixedOdds']['returnWin'] for r in runners
                       if r['fixedOdds']['returnWin'] and r['fixedOdds']['returnWin'] > 0])

    for runner in runners:

        # best odds for betting
        runner['win_odds'] = runner['fixedOdds']['returnWin']
        runner['place_odds'] = runner['fixedOdds']['returnPlace']
        logger.debug('#{} win_odds = {} and place_odds = {}'.format(
            runner['runnerNumber'], runner['win_odds'], runner['place_odds']))

        if not runner['win_odds'] or not runner['place_odds']:
            runner['win_rank'] = len(runners)
            runner['win_perc'] = 0
            continue

        # add runner rank
        runner['win_rank'] = all_odds.index(runner['win_odds']) + 1

        # odds for scaling
        runner['win_perc'] = 1 / runner['win_odds']
        logger.debug('#{} odds {:.2f} => perc {:.2f}'.format(
            runner['runnerNumber'], runner['win_odds'], runner['win_perc']))

    # get total (scratched has 0 for win)
    total = sum([r['win_perc'] for r in runners])
    logger.debug('total win_perc {:.2f}'.format(total))
    if not total:
        raise NoOddsError()

    # scale it
    for runner in runners:
        runner['win_scaled'] = total and runner['win_perc'] / total
        logger.debug('#{} perc {:.2f} => scale {:.2f}'.format(
            runner['runnerNumber'], runner['win_perc'], runner['win_scaled']))

        for k in ['odds_win', 'odds_perc', 'rank_win', 'odds_scale',
                  'prediction', 'probability']:
            runner.pop(k, None)


def add_predictions(runners, race_type):
    """predict for bet type"""
    if race_type not in RACE_TYPES:
        raise ValueError('Unknown race type {}'.format(race_type))

    # xn
    xn = len([r for r in runners if r['win_odds']])
    if not xn:
        # print(json.dumps(runners, indent=4, default=str, sort_keys=True))
        raise NoRunnersError()

    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        # model
        mdl = MODELS[race_type][bet_type]
        logger.debug('loaded model for {} {}'.format(race_type, bet_type))

        for runner in runners:
            prediction = 0

            if not runner['win_odds']:
                logger.debug('runner scratched')
            else:
                # get data
                x = [(runner['win_perc'], runner['win_scaled'], runner['win_rank'], xn)]
                # make prediction on data
                preds = mdl.predict(np.array(x))
                prediction = sum(preds[0])
                logger.debug('#{} {} prediction: {:.2f} from {}'.format(runner['runnerNumber'], bet_type, prediction, x))
            runner[pred] = prediction

    # return num_runners
    return xn


def add_probabilities(runners):
    """convert predictions to probabilities"""
    # get total (scratched has 0 for prediction)
    for bet_type in BET_TYPES:
        pred = '{}_pred'.format(bet_type)
        prob = '{}_prob'.format(bet_type)

        total_pred = sum([r[pred] for r in runners])
        logger.info('total {} prediction = {}'.format(bet_type, total_pred))

        # scale predictions
        for runner in runners:
            probability = runner[pred] / total_pred
            runner[prob] = probability
            if runner[pred]:
                logger.info('#{} {} probability: {:.2f}'.format(runner['runnerNumber'], bet_type, probability))

        # total probability must be 1
        total_prob = sum(r[prob] for r in runners)
        logger.debug('total {} probability = {}'.format(bet_type, total_prob))
        if round(total_prob, 2) != 1.00:
            raise ValueError('Probability must be 1, has {}'.format(total_prob))


###################################################################################
# bet types
###################################################################################


# WIN
# If the runner you pick wins the race, you win. This is our most popular bet type and the
    # betting equivalent of trying to select the quickest queue at the supermarket.

# PLACE
#
# Pick a runner and if it finishes 1st, 2nd or 3rd* you'll collect winnings. This bet type
    # increases your chances compared to a Win bet, but also reduces the potential rewards  and
    # thrill. It’s like skydiving with three parachutes.* No 3rd place dividend when 7 or  less
    # horses race.

# EACH WAY
#
# An Each Way bet combines the Win and Place bets. If your runner wins, you will collect both a
    # Win and Place dividend or if your runner finishes 2nd or 3rd you will collect the Place
    # dividend only.
#

# QUINELLA
#
# To win the Quinella you are required to correctly select the two runners that finish 1st and
    # 2nd in a race, in any order. Flexi betting available.
    # NN should input any combination of two runners
        #    x = [(runner['odds_perc'], runner['odds_scale'], runner['rank_win'], xn)]
        # xn - num runners
        # xap - alpha odds perc
        # xas - alpha odds scaled
        # xar - alpha ranked
        # xbp - beta odds perc
        # xbs - beta odds scaled
        # xbr - beta ranked

#
#
# EXACTA
#
# An Exacta requires you to correctly select the two runners that finish 1st and 2nd in a race in
    #   the correct order.Flexi betting available.
#
#
# DUET
#
# The Duet requires you to correctly select 2 of the 3 placegetters in any order and is only
    # available on races that have eight or more runners. The Duet will pay three dividends for
    # the following combinations: 1st and 2nd, 1st and 3rd, and 2nd and 3rd.Flexi betting available.
#
#
# TRIFECTA
#
# You need to pick the first three finishers, in correct order. In many senses winning a trifecta
    #   is like winning that really, really big teddy bear when you play carnival games - it’s
    # hard to do, but you’ll be the envy of everyone if you manage it.
#
#
# FIRST 4
#
# A winning First 4 bet requires you to pick the first four finishers in a single race,
    # in correct  order. It really isn’t easy to do, but you’ll probably remember the day you
    # won a First 4 alongside your wedding day and the days your children were born. Flexi
    # betting available.
#
#
# DAILY DOUBLE
#
# The Daily Double requires you to correctly pick the winners of two TAB nominated races. Daily
    # Doubles for each race meeting are marked in the "Exotic Bet Info" column on Today's and
    # Tomorrow's Racing Schedules on tab.com.au. Daily Double legs are marked as D-D.Flexi
    # betting available.
#
#
# RUNNING DOUBLE
#
# The Running Double requires you to correctly select the winners of any two consecutive races
    # at the one race meeting e.g. Race 2 winner and Race 3 winner. Flexi betting available.
#
#
# QUADDIE
#
# Pick the four winners from the four races nominated by TAB at the one meeting. If you like the
    #  idea of being chaired around on your mates’ shoulders and receiving raucous rounds of
    # applause from random strangers, win a Quaddie. Flexi betting available.
#
#
# BIG6
#
# A BIG6 requires you to pick six winners from six races nominated by TAB. The races that make up
    #   a BIG6 may be at the same race meeting or at different race meetings. There is at least
    # one BIG6 available every week. Available BIG6s are indicated in the "Exotic Bet Info"
    # column on Today's and Tomorrow's Racing Schedules on tab.com.au. Flexi betting available.
#
#
# ALL UP
#
# A more complex bet which involves parlaying your winnings from one race into one or more other
    #  races. To parlay means to create a single bet that links together two or more individual
    # bets and is dependent on all of those bets winning together. All Up bets  parlay (i.e
    # reinvest) dividends across ALL races. To obtain a payout ALL races must be successful.
#
# An All Up bet is a Parlayforumula bet with the formula number the same as the number of races
    # or legs selected.
#
#
# PARLAYFORMULA
#
# A more complex bet which involves parlaying your winnings from one race into one or more other
    #  races. To parlay means to create a single bet that links together two or more individual
    # bets and is dependent on all of those bets winning together. You can have a Parlayformula
    # on a minimum of two and up to a maximum of six races, and you can place a combination of
    # Win, Place, Win & Place or Quinella bets. You can expand your options by parlaying your
    # bets over 2, 3, 4, 5 or 6 races using a Formula Number, which means you don"t have to be
    # successful in every leg to be a winner. For example, if you take a Formula 3 bet over 4
    # races, the TAB computer will automatically generate all possible combinations of 3 races
    # with this bet. To collect a dividend you must be successful in at least 3 of your 4
    # selected  races.
#
#
# MYSTERY BET
#
# The easiest way to have a bet. Mystery Bets are available on the next race to run, and on the
    # feature race of the day. Mystery Bets are computer generated selections and are available
    # in  a:
# - $1 Single Trifecta
# - $2 Single Quinella
# - $3 Box Trifecta (50 cent investment)
# - $3 3-Up (Win, Exacta and Trifecta in the one bet).
#
#
# PRICE DEFINTIONS
#
# Fixed Odds: You will be paid out the odds that you secured at the time of your bet. For
    # example, if you bet $2 on a horse that is $5 on fixed odds, you will get back $10 if your
    # horse is successful.
# Tote: The money spent on a particular bet type (e.g. Win bet) on the one race is pooled
    # together.  After fees and taxes are removed, the pool is divided up by the amount of
    # winning  $1 bets. If you place a successful $5 bet, you’ll have five shares in the winning
    #  pool.
#
#
# OTHER BETTING OPTIONS
#
# What is boxing?
# When you "box" the runners in your bet, you cover all possible combinations for the  finishing
    # order. Available on Quinella, Exacta, Duet, Trifecta and First 4.
#
# What is a Standout?
# A Standout is a single runner you pick to come in 1st place, and any of the other runners you
    # select can fill the other places in any order. Available on Exacta, Trifecta and First 4.
#
# What is a multiple bet?
# A multiple bet is where you pick more than one runner in each leg of the bet. Available on
    # Quinella, Exacta, Duet, Doubles, Trifecta, First 4 and Quaddie.
#
# What is a Roving Banker?
# Select a runner as your "Roving Banker", and then select other runners to fill the remaining
    # places. The Roving Banker must finish in a place, with any of your other nominated runners
    #  must fill the remaining places in any order. Available in Exacta, Trifecta and First 4.
#
# What is Flexi betting?
# Flexi Betting allows you to take any Exotic bet type at an outlay to suit your pocket - so you
    #  can have multiple selections without being restricted by your budget! All you need to do
    # is  decide on your selections and the total amount you wish to spend on your bet. Your bet
    #  will cost whatever you choose - and if you win, you will receive a percentage of the full
    #  dividend. For example, let's say you want to box five runners in a Trifecta. This would
    # normally cost $60 for a $1 investment. If you decide you want to spend $15, that's all it
    # will cost. $15 represents 25% of $60, which means if you win, you will receive 25% of the
    # full Trifecta dividend. So if the winning Trifecta dividend is $200, you'll collect $50.
    # It's  that easy!
#
# Flexi Betting in 4 Easy Steps
# Step One 	Decide how much you want to spend. The number of selections you choose does not
    # impact  on your total spend. Once you decide how much you want to spend, that will be the
    # total cost of the bet. For example, $15.
#
# Step Two 	Select your combinations. Let's say that you wanted to box 5 horses in a Trifecta.
    # This would normally cost you $60, for a $1 investment.
#
# Step Three 	After your bet is processed, the TAB calculates the percentage bet that you have
    #  waged. This percentage is based on what the bet would normally cost if you placed the bet
    #  for $1. We call it a Bet Percentage. In our example, your percentage would be :$15 (the
    # amount you choose to spend) divided by $60 (cost of the bet for $1) = 25%.
#
# Step Four 	If successful, you will collect the percentage of the dividend that you have
    # waged: Let's say the winning Trifecta dividend is $200.00. Your collect will be: 25% of
    # $200 = $50
