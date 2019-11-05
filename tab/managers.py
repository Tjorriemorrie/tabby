from django.utils import timezone
from django.db import models
from django.db.models import Avg, Max


class RaceManager(models.Manager):

    def incoming(self, limit=10):
        """Races that will be start soon"""
        return super().get_queryset().prefetch_related('runner_set').filter(
            start_time__gte=timezone.now()
        ).filter(
            has_fixed_odds=True
        ).order_by('start_time')[:limit]

    def outgoing(self, limit=20):
        """Races that finished recently"""
        return super().get_queryset().prefetch_related('runner_set').filter(
            start_time__lte=timezone.now()
        ).order_by('-start_time')[:limit]


class RunnerManager(models.Manager):

    def active(self):
        """Get all active runners"""
        return super().get_queryset().filter(
            fixed_betting_status='Open'
        ).all()


class FixedOddManager(models.Manager):

    def top_10(self):
        """Get last 10 updated odds"""
        return super().get_queryset().all()[:10]


class AccuracyManager(models.Manager):

    def avg_win_error(self):
        """Calculates single overall error average"""
        return super().get_queryset().all().aggregate(Avg('win_error'))['win_error__avg']


class BucketManager(models.Manager):

    def latest_bins(self):
        """Get biggest number of bins grouping"""
        max_bins = super().get_queryset().all().aggregate(Max('bins'))['bins__max']
        return super().get_queryset().filter(
            bins=max_bins
        ).order_by('left').all()

    def get_fo(self, fo):
        """get the bucket that matches the fo"""
        max_bins = super().get_queryset().all().aggregate(Max('bins'))['bins__max']
        return super().get_queryset().filter(
            bins=max_bins,
            left__lte=fo.win_perc,
            right__gt=fo.win_perc
        ).get()
