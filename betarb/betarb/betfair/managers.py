from django.db.models import Manager, Max


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
