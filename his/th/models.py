from django.db import models

from .managers import VarManager


class Meeting(models.Model):
    TYPES = (
        ('G', 'Grayhound'),
        ('R', 'Racing'),
        ('H', 'Harness'),
    )

    date = models.DateField()
    venue = models.CharField(max_length=50)
    region = models.CharField(max_length=20, null=True)
    race_type = models.CharField(max_length=1, choices=TYPES)
    track_condition = models.CharField(max_length=30, null=True)
    weather_condition = models.CharField(max_length=30, null=True)

    def __str__(self):
        return f'Meeting({self.venue} {self.race_type} {self.region} {self.date})'


class Race(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE)

    number = models.IntegerField()
    href = models.CharField(max_length=255)
    distance = models.IntegerField()
    name = models.CharField(max_length=50)
    start_time = models.DateTimeField()

    direction = models.CharField(max_length=20, null=True)
    has_fixed_odds = models.BooleanField(default=True)
    has_parimutuel = models.BooleanField(default=True)
    class_conditions = models.CharField(max_length=20, null=True)
    status = models.CharField(max_length=20, null=True)
    number_of_places = models.IntegerField(null=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f'Race({self.id} {self.meeting.venue} R{self.number} time={self.start_time})'


class Runner(models.Model):
    race = models.ForeignKey(Race, on_delete=models.CASCADE)

    number = models.IntegerField()
    name = models.CharField(max_length=50)
    barrier = models.IntegerField()

    trainer = models.CharField(max_length=100, null=True)
    rider = models.CharField(max_length=100, null=True)

    last_5_starts = models.CharField(max_length=5, null=True)
    form_rating = models.IntegerField(null=True)

    fixed_win = models.FloatField(null=True)
    fixed_place = models.FloatField(null=True)
    tote_win = models.FloatField(null=True)
    tote_place = models.FloatField(null=True)

    class Meta:
        ordering = ['number']

    def won(self):
        outcome = self.race.outcome
        return self == outcome.first

    def placed(self):
        outcome = self.race.outcome
        return self in {outcome.first, outcome.second, outcome.third, outcome.fourth}


class Outcome(models.Model):
    race = models.OneToOneField(Race, on_delete=models.CASCADE)

    first = models.ForeignKey(Runner, related_name='first', on_delete=models.CASCADE)
    second = models.ForeignKey(Runner, related_name='second', on_delete=models.CASCADE)
    third = models.ForeignKey(Runner, related_name='third', on_delete=models.CASCADE)
    fourth = models.ForeignKey(Runner, related_name='fourth', on_delete=models.CASCADE, null=True)

    odds_evens = models.FloatField(null=True)
    quinella = models.FloatField(null=True)
    exacta = models.FloatField(null=True)
    duet12 = models.FloatField(null=True)
    duet13 = models.FloatField(null=True)
    duet23 = models.FloatField(null=True)
    trifecta = models.FloatField(null=True)
    trio = models.FloatField(null=True)
    quaddie = models.FloatField(null=True)
    first_four = models.FloatField(null=True)
    early_quaddie = models.FloatField(null=True)


class RunnerMeta(models.Model):
    race = models.ForeignKey(Race, on_delete=models.CASCADE)
    runner = models.OneToOneField(Runner, on_delete=models.CASCADE)

    fixed_win = models.FloatField()
    fixed_place = models.FloatField()
    tote_win = models.FloatField()
    tote_place = models.FloatField()

    won = models.BooleanField()
    placed = models.BooleanField()

    def __str__(self):
        return f'RunnerMeta(race={self.race} runner={self.runner})'


class Var(models.Model):
    objects = VarManager()

    key = models.CharField(max_length=20)
    val1 = models.FloatField(default=0, blank=True)
    val2 = models.FloatField(default=0, blank=True)
    val3 = models.FloatField(null=True, blank=True)
    val4 = models.FloatField(null=True, blank=True)
    val5 = models.FloatField(null=True, blank=True)
    ran_at = models.DateTimeField()

    def __str__(self):
        return f'Var(key={self.key})'
