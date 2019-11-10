from django.urls import path

from .views import MeetingListView, MeetingDetailView, RaceDetailView
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('meetings/', MeetingListView.as_view(), name='meetings'),
    path('meetings/<int:pk>', MeetingDetailView.as_view(), name='meeting'),
    path('races/<int:pk>', RaceDetailView.as_view(), name='race'),
]
