from django.db.models import Manager, Max, Avg, Sum, Count


class BucketManager(Manager):

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


class AccuracyManager(Manager):

    def avg_win_error(self):
        """Calculates single overall error average"""
        return super().get_queryset().all().aggregate(Avg('error'))['error__avg']


class BetManager(Manager):

    def roi(self):
        """Calculates roi for all bets"""
        return super().get_queryset().exclude(
            outcome__isnull=True
        ).all().aggregate(
            roi=Sum('profit') / Sum('size_matched')
        )['roi']

    def outstanding(self):
        """All outstanding bets"""
        return super().get_queryset().filter(
            outcome__isnull=True,
        ).exclude(
            status__in=['LAPSED', 'CANCELLED']
        ).all()
