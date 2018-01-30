import pandas as pd
from django.shortcuts import render

from tab.models import Race, Accuracy, Bucket as TabBucket, FixedOdd
from betfair.models import Bucket as BfBucket


def index(request):
    context = {
        'incoming': Race.objects.incoming(),
        'outgoing': Race.objects.outgoing(),
        'tab_bucket_overall': TabBucket.objects.get(bins=1),
        'tab_buckets': TabBucket.objects.latest_bins(),
        'bf_bucket_overall': BfBucket.objects.get(bins=1),
        'bf_buckets': BfBucket.objects.latest_bins(),
    }
    return render(request, 'bot/index.html', context)
