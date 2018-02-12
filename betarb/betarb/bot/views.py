import pandas as pd
from django.shortcuts import render, redirect
from statistics import mean
from django.core.cache import cache

from tab.models import Race, Accuracy as TabAccuracy, Bucket as TabBucket, FixedOdd
from betfair.models import Bucket as BfBucket, Accuracy as BfAccuracy, Bet


def index(request):
    winnings = _get_winnings()
    context = {
        'incoming': Race.objects.incoming(),
        'outgoing': Race.objects.outgoing(),
        'tab_bucket_overall': TabBucket.objects.get(bins=1),
        'tab_buckets': TabBucket.objects.latest_bins(),
        'bf_bucket_overall': BfBucket.objects.get(bins=1),
        'bf_buckets': BfBucket.objects.latest_bins(),
        'tab_error': TabAccuracy.objects.avg_win_error(),
        'bf_error': BfAccuracy.objects.avg_win_error(),
        'est_acc': _get_est_acc(),
        'betting': cache.get('betting'),

        'roi': Bet.objects.roi(),
        'outstanding': Bet.objects.outstanding(),
        'backs_pp': sum(winnings['backs']) / len(winnings['backs']),
        'backs_roi': sum(winnings['backs']) / (len(winnings['backs']) * 5),
        'lays_pp': sum(winnings['lays']) / len(winnings['lays']),
        'lays_roi': sum(winnings['lays']) / (len(winnings['lays']) * 5),
    }

    return render(request, 'bot/index.html', context)


def betting(request):
    """change betting"""
    betting = cache.get('betting')
    cache.set('betting', not bool(betting))
    return redirect(index)


def _get_est_acc():
    """get estimation accuracy"""
    est_acc = cache.get('est_acc')
    if not est_acc:
        diffs = []
        races = Race.objects.filter(
            has_results=True).filter(
            has_processed=True).all()
        for race in races:
            for runner in race.runner_set.all():
                trade = runner.trade
                if not trade:
                    continue
                trade = 1 / trade
                fo = runner.fixedodd_set.first()
                if not fo:
                    continue
                est = fo.win_est
                if not est:
                    continue
                diffs.append(trade - est)
        est_acc = mean(diffs)
        cache.set('est_acc', est_acc)
    return est_acc


def sim(request):
    """simulate winnings"""
    winnings = _get_winnings()
    back_winnings = winnings['backs']
    lay_winnings = winnings['lays']

    context = {
        'backs': back_winnings,
        'lays': lay_winnings,
        'back_total': sum(back_winnings),
        'back_wins': sum(b for b in back_winnings if b > 0),
        'back_loss': sum(b for b in back_winnings if b < 0),
        'lay_total': sum(lay_winnings),
        'lay_wins': sum(l for l in lay_winnings if l > 0),
        'lay_loss': sum(l for l in lay_winnings if l < 0),
    }

    return render(request, 'bot/sim.html', context)


def _get_winnings():
    winnings = cache.get('winnings')
    if not winnings:
        amt = 5
        back_winnings = []
        lay_winnings = []
        races = Race.objects.filter(
            has_results=True).filter(
            has_processed=True).all()
        for race in races:
            for runner in race.runner_set.all():
                trade = runner.trade
                back = runner.back
                lay = runner.lay
                if not trade or not back or not lay:
                    continue
                fo = runner.fixedodd_set.first()
                if not fo:
                    continue
                est = fo.win_est
                if not est:
                    continue
                est = 1 / est
                if not hasattr(runner, 'accuracy'):
                    continue
                won = runner.accuracy.won
                # lay when est is higher (market is below expected)
                if est > (trade * 1.05) and back < 10:
                    if won:
                        lay_winnings.append(-amt * (trade - 1))
                    else:
                        lay_winnings.append(amt * 0.95)
                # back when est is lower (market is above expected)
                elif est < (trade * 0.95) and back < 10:
                    if won:
                        back_winnings.append(amt * (trade - 1) * 0.95)
                    else:
                        back_winnings.append(-amt)
        winnings = {
            'backs': back_winnings,
            'lays': lay_winnings
        }
        cache.set('winnings', winnings)
    return winnings
