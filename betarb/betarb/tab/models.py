from django.db import models


class Meeting(models.Model):
    LOCATIONS = (
        ('QLD', 'Queensland'),
    )
    TYPES = (
        ('G', 'Grayhound'),
        ('R', 'Racing'),
        ('H', 'Harness'),
    )

    name = models.CharField(max_length=50)
    date = models.DateField()

    location = models.CharField(max_length=10, choices=LOCATIONS)
    race_type = models.CharField(max_length=1, choices=TYPES)
    rail_position = models.CharField(max_length=30, null=True)
    track_condition = models.CharField(max_length=30, null=True)
    venue_mnemonic = models.CharField(max_length=10)
    weather_condition = models.CharField(max_length=30, null=True)


class Race(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE)
    number = models.IntegerField()

    link_self = models.CharField(max_length=255)
    link_form = models.CharField(max_length=255)
    link_big_bets = models.CharField(max_length=255)
    distance = models.IntegerField()
    name = models.CharField(max_length=50)
    start_time = models.DateTimeField()
