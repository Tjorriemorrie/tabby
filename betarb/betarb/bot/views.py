import pandas as pd
from django.shortcuts import render

from tab.models import Race, Accuracy, Bucket, FixedOdd


def index(request):
    context = {
        'incoming': Race.objects.incoming(),
        'outgoing': Race.objects.outgoing(),
        'bucket_overall': Bucket.objects.get(bins=1),
        'buckets': Bucket.objects.latest_bins(),
    }
    return render(request, 'bot/index.html', context)
