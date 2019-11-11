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

    def handled(self, meeting, results=False, processed=False):
        """races that have results and processed"""
        return super().get_queryset().filter(
            meeting=meeting
        ).filter(
            has_results=results
        ).filter(
            has_processed=processed
        )


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


class VarManager(models.Manager):

    def next_to_train(self):
        vars_train = super().get_queryset().exclude(
            key='multi_origin'
        ).order_by('ran_at').all()[:3]
        vars_keep = super().get_queryset().exclude(
            key='multi_origin'
        ).order_by('ran_at').all()[3:]
        vars_multi = super().get_queryset().filter(key='multi_origin').get()
        return vars_train, vars_keep, vars_multi
