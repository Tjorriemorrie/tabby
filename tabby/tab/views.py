from django.shortcuts import render
from django.views.generic import ListView, DetailView

from .models import Meeting, Race


def index(request):
    return render(request, 'tab/index.html', {})


class MeetingListView(ListView):
    model = Meeting
    queryset = Meeting.objects.order_by('-date')

    # def head(self, *args, **kwargs):
    #     last_book = self.get_queryset().latest('publication_date')
    #     response = HttpResponse('')
    #     # RFC 1123 date format
    #     response['Last-Modified'] = last_book.publication_date.strftime('%a, %d %b %Y %H:%M:%S GMT')
    #     return response


class MeetingDetailView(DetailView):
    model = Meeting


class RaceDetailView(DetailView):
    model = Race
