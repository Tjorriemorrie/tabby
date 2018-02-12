from django.db import models

from .managers import BucketManager, AccuracyManager, BetManager


class Event(models.Model):
    event_id = models.BigIntegerField(unique=True)

    venue = models.CharField(max_length=100)
    open_date = models.DateTimeField()

    name = models.CharField(max_length=100)
    country_code = models.CharField(max_length=10)
    timezone = models.CharField(max_length=10)

    def __str__(self):
        return f'<Event [{self.event_id}] venue={self.venue} date={self.open_date}>'


class Market(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)

    # TAB
    race = models.ForeignKey('tab.Race', null=True, on_delete=models.SET_NULL)

    # from catalogue
    market_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=50)
    total_matched = models.FloatField(null=True)
    start_time = models.DateTimeField()

    # from catalogue description
    betting_type = models.CharField(max_length=50)
    market_time = models.DateTimeField()
    market_type = models.CharField(max_length=50)
    suspend_time = models.DateTimeField()
    turn_in_play_enabled = models.BooleanField()
    race_type = models.CharField(max_length=50, null=True)

    has_processed = models.BooleanField(default=False)

    def __str__(self):
        return f'<Market [{self.market_id}] {self.event.venue} start={self.start_time}>'


class Runner(models.Model):
    market = models.ForeignKey(Market, null=True, on_delete=models.SET_NULL)

    # default
    selection_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=100)
    sort_priority = models.IntegerField()
    handicap = models.FloatField()
    # metadata
    cloth_number = models.IntegerField(null=True)
    stall_draw = models.IntegerField(null=True)
    runner_id = models.BigIntegerField()

    def __str__(self):
        return f'<Runner [{self.selection_id}] num={self.cloth_number} name={self.name}>'


class Book(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE)

    is_market_data_delayed = models.BooleanField()
    status = models.CharField(max_length=50)
    bet_delay = models.FloatField()
    bsp_reconciled = models.BooleanField()
    complete = models.BooleanField()
    inplay = models.BooleanField()
    number_of_winners = models.IntegerField()
    number_of_runners = models.IntegerField()
    number_of_active_runners = models.IntegerField()
    last_match_time = models.DateTimeField(null=True)
    total_matched = models.FloatField()
    total_available = models.FloatField()
    cross_matching = models.BooleanField()
    runners_voidable = models.BooleanField()
    version = models.BigIntegerField()

    # class Meta:
    #     ordering = ['last_match_time']

    def __str__(self):
        return f'<Book [{self.version}] status={self.status}>'


class RunnerBook(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    runner = models.ForeignKey(Runner, on_delete=models.CASCADE)

    status = models.CharField(max_length=20)
    adjustment_factor = models.FloatField(null=True)
    last_price_traded = models.FloatField(null=True)
    total_matched = models.FloatField(null=True)
    back_price = models.FloatField(null=True)
    back_size = models.FloatField(null=True)
    lay_price = models.FloatField(null=True)
    lay_size = models.FloatField(null=True)

    def __str__(self):
        return f'<RB num={self.runner.cloth_number} sel={self.runner.selection_id} back={self.back_price} lay={self.lay_price}>'


class Accuracy(models.Model):
    objects = AccuracyManager()
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    runner_book = models.ForeignKey(RunnerBook, on_delete=models.CASCADE)

    dec = models.FloatField(null=True)
    perc = models.FloatField(null=True)
    won = models.NullBooleanField()
    error = models.FloatField(null=True)


class Bucket(models.Model):
    objects = BucketManager()

    bins = models.IntegerField()
    left = models.FloatField()
    right = models.FloatField()
    total = models.IntegerField()
    count = models.IntegerField()
    win_mean = models.FloatField()
    coef = models.FloatField()
    intercept = models.FloatField()


class Bet(models.Model):
    objects = BetManager()

    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    runner = models.ForeignKey(Runner, on_delete=models.CASCADE)
    bet_id = models.BigIntegerField()

    est = models.FloatField()
    trade = models.FloatField()
    back = models.FloatField(null=True)
    lay = models.FloatField(null=True)
    margin = models.FloatField()
    payout = models.FloatField()
    liability = models.FloatField()

    order_type = models.CharField(max_length=50)
    persistence_type = models.CharField(max_length=50)
    placed_at = models.DateTimeField()
    price = models.FloatField()
    size = models.FloatField()
    side = models.CharField(max_length=20)
    size_matched = models.FloatField(null=True)
    size_remaining = models.FloatField(null=True)
    size_lapsed = models.FloatField(null=True)
    size_cancelled = models.FloatField(null=True)
    size_voided = models.FloatField(null=True)
    status = models.CharField(max_length=30)

    outcome = models.CharField(max_length=50, null=True)
    profit = models.FloatField(null=True)

    def __str__(self):
        return f'<Bet [{self.bet_id} {self.runner.cloth_number}] {self.size} x {self.price} {self.side}>'
