import json
import datetime
import logging
import re
from django.core.cache import cache

import pandas as pd
from betfairlightweight.filters import market_filter, time_range, price_projection, price_data, place_instruction, limit_order
from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from sklearn.linear_model import LinearRegression

from tab.models import Race
from .client import get_betfair_client, ET_HORSE_RACING, ET_GREYHOUND_RACING
from .models import Event, Market, Book, Runner, RunnerBook, Accuracy, Bucket, Bet

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def list_market_catalogue(self):
    logger.warning('+' * 80)
    trading = get_betfair_client()
    time_ago = timezone.now() + datetime.timedelta(minutes=1)
    time_fwd = timezone.now() + datetime.timedelta(minutes=60)
    mfilter = market_filter(
        event_type_ids=[ET_HORSE_RACING, ET_GREYHOUND_RACING],
        market_start_time=time_range(
            from_=time_ago.strftime('%Y-%m-%dT%H:%I:%S.000Z'),
            to=time_fwd.strftime('%Y-%m-%dT%H:%I:%S.000Z')
        )
    )
    res = trading.betting.list_market_catalogue(
        mfilter,
        market_projection=[
            'EVENT',
            'MARKET_START_TIME',
            'MARKET_DESCRIPTION',
            'RUNNER_METADATA',
        ],
        sort='FIRST_TO_START',
        max_results=100,
        lightweight=True)
    if not len(res):
        logger.error('Market catalogue listing is empty')
        trading.session_token = None
        raise self.retry(countdown=5, max_retries=12)

    for cat in res:
        if 'venue' not in cat['event']:
            logger.error(f'No event venue in {cat}')
            continue
        try:
            event = parse_event(cat['event'])
            market = parse_market(event, cat)
            runners = parse_runners(market, cat['runners'])
        except:
            logger.warning(cat)
            raise
    logger.warning(f'BETFAIR: Scraped {len(res)} from market catalogue')


@shared_task
def parse_event(event):
    """Parses event from Event object"""
    event, created = Event.objects.update_or_create(
        event_id=event['id'],
        defaults={
            'open_date': parse_datetime(event['openDate']),
            'venue': event['venue'].upper(),
            'name': event['name'],
            'country_code': event['countryCode'],
            'timezone': event['timezone'],
        }
    )
    if created:
        logger.warning(f'Created {event}')
    else:
        logger.info(f'Updated {event}')
    return event


@shared_task
def parse_market(event, cat):
    """Parses market from MarketCatalogue object"""
    market, created = Market.objects.update_or_create(
        market_id=cat['marketId'],
        defaults={
            'event': event,
            # catalogue
            'name': cat['marketName'],
            'total_matched': cat['totalMatched'],
            'start_time': parse_datetime(cat['marketStartTime']),
            # description
            'betting_type': cat['description']['bettingType'],
            'market_time': parse_datetime(cat['description']['marketTime']),
            'market_type': cat['description']['marketType'],
            'suspend_time': parse_datetime(cat['description']['suspendTime']),
            'turn_in_play_enabled': cat['description']['turnInPlayEnabled'],
            'race_type': cat['description'].get('raceType'),
        }
    )
    if created:
        logger.warning(f'Created {market}')
    else:
        logger.info(f'Updated {market}')
    return market


@shared_task
def parse_runners(market, items):
    """Parses runners from MarketCatalogue object"""
    runners = []
    for runner_item in items:
        num = runner_item['metadata'].get('CLOTH_NUMBER')
        if not num:
            matches = re.match(r'^(\d+)', runner_item['runnerName'])
            if matches:
                num = matches.groups(0)[0]
            else:
                logger.error(f'Could not match number for {runner_item}')
        runner, created = Runner.objects.update_or_create(
            selection_id=runner_item['selectionId'],
            defaults={
                'market': market,
                # default
                'name': runner_item['runnerName'].upper(),
                'sort_priority': runner_item['sortPriority'],
                'handicap': runner_item['handicap'],
                # metadata
                'cloth_number': num,
                'stall_draw': runner_item['metadata'].get('STALL_DRAW'),
                'runner_id': runner_item['metadata']['runnerId'],
            }
        )
        if created:
            logger.info(f'Created {runner}')
        else:
            logger.debug(f'Updated {runner}')
        runners.append(runner)
    return runners


@shared_task
def monitor_market_book(race_pk):
    """monitor the market book of the given race"""
    try:
        market = Market.objects.get(race_id=race_pk)
    except Market.DoesNotExist:
        link_betfair_market.delay(race_pk)
    else:
        monitor_market(market.pk)


@shared_task
def link_betfair_market(race_pk):
    race = Race.objects.get(id=race_pk)
    try:
        market = Market.objects.get(
            market_type='WIN',
            event__venue=race.meeting.name,
            start_time=race.start_time,
        )
    except Market.DoesNotExist:
        logger.error(f'Betfair event not found for {race}')
        return
    market.race = race
    market.save()
    logger.warning(f'Linked {market} onto {race}!')


@shared_task
def monitor_market(pk):
    """monitor market"""
    market = Market.objects.get(id=pk)
    trading = get_betfair_client()
    res = trading.betting.list_market_book(
        market_ids=[market.market_id],
        price_projection=price_projection(
            price_data(
                sp_available=False,
                sp_traded=False,
                ex_best_offers=True,
                ex_all_offers=True,
                ex_traded=True,
            )
        ),
        order_projection='ALL',
        match_projection='ROLLED_UP_BY_PRICE',
        lightweight=True)

    if len(res) != 1:
        raise Exception(f'MarketBook not found for {market}')
    item = res[0]

    # check that book is open and not inplay
    if item['status'] != 'OPEN' or item['inplay']:
        logger.error(f'Book for market is not open/inplay: {market}')
        return

    book = upsert_market_book(market, item)
    rbooks = upsert_runner_book(book, item)
    if book.number_of_active_runners != len(rbooks):
        logger.error(f'Missing runners {book.number_of_active_runners} vs {len(rbooks)} in {book}')
        logger.error(f'Market has {market.runner_set.count()} runners (expecting {book.number_of_runners} from book)')
    logger.warning(f'Finished monitored market {market}')


@shared_task
def upsert_market_book(market, res):
    # create book for version
    book, created = Book.objects.update_or_create(
        market=market,
        last_match_time=res.get('lastMatchTime'),
        defaults={
            'is_market_data_delayed': res['isMarketDataDelayed'],
            'status': res['status'],
            'bet_delay': res['betDelay'],
            'bsp_reconciled': res['bspReconciled'],
            'complete': res['complete'],
            'inplay': res['inplay'],
            'number_of_winners': res['numberOfWinners'],
            'number_of_runners': res['numberOfRunners'],
            'number_of_active_runners': res['numberOfActiveRunners'],
            'total_matched': res.get('totalMatched'),
            'total_available': res['totalAvailable'],
            'cross_matching': res['crossMatching'],
            'runners_voidable': res['runnersVoidable'],
            'version': res['version'],
        }
    )
    if created:
        logger.info(f'Created {book}')
    else:
        logger.info(f'Updated {book}')
    return book


@shared_task
def upsert_runner_book(book, res):
    # create book for every runner
    rbooks = []
    for item in res['runners']:
        try:
            runner = Runner.objects.get(selection_id=item['selectionId'])
        except Runner.DoesNotExist:
            logger.error(f'Could not find runner for {item["selectionId"]}')
            continue

        best_back = item['ex']['availableToBack'][0] if item['ex']['availableToBack'] else {}
        best_lay = item['ex']['availableToLay'][0] if item['ex']['availableToLay'] else {}
        rbook, created = RunnerBook.objects.update_or_create(
            book=book,
            runner=runner,
            defaults={
                'status': item['status'],
                'adjustment_factor': item.get('adjustmentFactor'),
                'last_price_traded': item.get('lastPriceTraded'),
                'total_matched': item.get('totalMatched'),
                'back_price': best_back.get('price'),
                'back_size': best_back.get('size'),
                'lay_price': best_lay.get('price'),
                'lay_size': best_lay.get('size'),
            }
        )
        if created:
            logger.info(f'Created {rbook}')
        else:
            logger.info(f'Updated {rbook}')
        rbooks.append(rbook)
    return rbooks


########################################################################################################################
# Post processing
########################################################################################################################

@shared_task
def post_process():
    cleanup()
    if analyze():
        create_buckets()


@shared_task
def cleanup():
    """Delete from bottom up where there are no odds"""
    # clear rbooks
    res = RunnerBook.objects.filter(
        status='ACTIVE',
        back_price__isnull=True,
        lay_price__isnull=True,
    ).delete()
    logger.warning(f'Deleted rbooks: {res}')

    # clear books
    res = Book.objects.exclude(
        runnerbook__isnull=False
    ).delete()
    logger.warning(f'Deleted books: {res}')

    # clear markets
    yesterday = timezone.now() - datetime.timedelta(hours=24)
    res = Market.objects.filter(
        start_time__lt=yesterday,
    ).exclude(
        book__isnull=False,
    ).delete()
    logger.warning(f'Deleted markets: {res}')

    # clear events
    res = Event.objects.exclude(
        market__isnull=False
    ).delete()
    logger.warning(f'Deleted events: {res}')

    # clear runners (no cascade)
    res = Runner.objects.exclude(
        market__isnull=False
    ).delete()
    logger.warning(f'Deleted runners: {res}')

    logger.warning(f'Betfair cleanup done')


@shared_task
def analyze():
    """create analysis for results"""

    # update markets
    markets = Market.objects.filter(
        race__has_results=True,
        has_processed=False
    )
    print(markets.query)
    markets = markets.all()

    for market in markets:
        Accuracy.objects.filter(market=market).delete()
        for tab_runner in market.race.runner_set.all():
            try:
                rbook = RunnerBook.objects.filter(
                    book=market.book_set.last(),
                    runner__cloth_number=tab_runner.runner_number).get()
            except RunnerBook.DoesNotExist:
                logger.error(f'RunnerBook not found for {tab_runner}')
                continue

            if not rbook.last_price_traded:
                logger.error(f'RunnerBook has no last price traded: {rbook}')
                continue

            result = tab_runner.result if hasattr(tab_runner, 'result') else None
            accuracy = Accuracy(market=market, runner_book=rbook)
            accuracy.dec = rbook.last_price_traded
            accuracy.perc = 1 / accuracy.dec
            accuracy.won = bool(result) and result.pos == 1
            accuracy.error = accuracy.perc - accuracy.won
            accuracy.save()

        market.has_processed = True
        market.save()
        logger.warning(f'Created accuracy for {market}')
    logger.warning(f'Accuracy finished for {len(markets)} markets')
    return len(markets)


@shared_task()
def create_buckets():
    """buckets the abs errors for betting range values"""
    df = pd.DataFrame.from_records(Accuracy.objects.all().values())
    # df['win_error_abs'] = df['win_error'].abs()
    Bucket.objects.all().delete()
    bins = 0
    while bins < 10:
        bins += 1
        df['bins'] = 1
        df['cats'] = pd.qcut(df['perc'], bins)
        flag_exit = False
        for name, grp in df.groupby('cats'):

            # linear regression for coefficients
            ols = LinearRegression().fit(
                grp['perc'].values.reshape(-1, 1),
                grp['won'].values.reshape(-1, 1))

            # create bucket from bin group
            bucket = Bucket.objects.create(
                bins=bins,
                left=name.left,
                right=name.right,
                total=len(grp),
                count=grp['won'].sum(),
                win_mean=grp['won'].mean(),
                coef=ols.coef_[0],
                intercept=ols.intercept_,
            )

            # check flag
            if bucket.count <= 1:
                flag_exit = True

        if flag_exit:
            break
    logger.warning(f'Created max {bins} BetFair buckets')


########################################################################################################################
# Betting
########################################################################################################################

@shared_task
def run_bet():
    """list and make bets"""
    betting = cache.get('betting')
    if not betting:
        logger.warning('No betting')
        return

    list_current_bets()
    list_settled_bets()
    list_lapsed_bets()
    place_bets.apply_async()


@shared_task
def place_bets():
    """makes bets. This will run once every minute. We only pick races starting
    within the last minute. No previous bets, just make bets. Races start normally
    on the minute and this task will run on the 30th second."""
    logger.info('$' * 80)
    amt = 5
    margin = 0.05
    time_ago = timezone.now() - datetime.timedelta(seconds=30)
    time_fwd = timezone.now()
    races = Race.objects.filter(
        start_time__gte=time_ago,
        start_time__lte=time_fwd
    ).all()
    if not races:
        logger.warning('No races to bet on')
        return

    trading = get_betfair_client()
    for race in races:
        market = race.win_market
        if not market:
            logger.error(f'No market for {race}')
            continue
        logger.warning(f'$$$ Betting on {race}')

        ix = []
        ix_info = {}
        for runner in race.runner_set.all():
            try:
                bf_runner = market.runner_set.get(cloth_number=runner.runner_number)
            except Exception as e:
                logger.error(f'$$ {e}')
                logger.warning(f'No betfair for {runner}')
                continue
            trade = runner.trade
            if not trade:
                logger.warning(f'no trade for {runner}')
                continue
            fo = runner.fixedodd_set.first()
            est = 1 / fo.win_est
            if est >= 10:
                logger.warning(f'Odds {est} too bad for {runner}')
                continue
            for side in ['BACK', 'LAY']:
                # e.g. to back: est 4.5 < trade 5.5 (at 95%)
                if side == 'BACK' and est > trade * (1 - margin):
                    logger.warning(f'No profitable {side} bet for {runner}')
                    continue
                # e.g. to lay: est 8.80 > trade 6.70 (at 105%)
                if side == 'LAY' and est < trade * (1 + margin):
                    logger.warning(f'No profitable {side} bet for {runner}')
                    continue
                ix.append(place_instruction(
                    'LIMIT', bf_runner.selection_id, side,
                    limit_order=limit_order(persistence_type='LAPSE',
                                            size=amt, price=trade)))
                logger.warning(f'Placed bet {runner.runner_number}: {side} {amt}x {trade}')
                ix_info[bf_runner.selection_id] = {
                    'bf_runner': bf_runner,
                    'est': est,
                    'trade': trade,
                    'back': runner.back,
                    'lay': runner.lay,
                    'margin': margin,
                }

        if not ix:
            logger.error(f'No ix for {market}')
            continue

        # place orders
        res = trading.betting.place_orders(
            market.market_id,
            instructions=ix,
            lightweight=True)
        # print(json.dumps(res, indent=4, default=str, sort_keys=True))
        if res['status'] != 'SUCCESS':
            raise Exception(f'Market {res["marketId"]}: {res["errorCode"]}')
        for ix in res['instructionReports']:
            bet_info = ix_info[ix['instruction']['selectionId']]
            if ix['instruction']['side'] == 'BACK':
                liability = ix['instruction']['limitOrder']['size']
                payout = ix['instruction']['limitOrder']['size'] * (ix['instruction']['limitOrder']['price'] - 1)
            else:
                liability = ix['instruction']['limitOrder']['size'] * (ix['instruction']['limitOrder']['price'] - 1)
                payout = ix['instruction']['limitOrder']['size']
            bet = Bet(market=market, runner=bet_info['bf_runner'], bet_id=ix['betId'],
                      est=bet_info['est'], trade=bet_info['trade'],
                      back=bet_info['back'], lay=bet_info['lay'],
                      margin=margin, payout=payout, liability=liability,

                      status=ix['orderStatus'],
                      placed_at=parse_datetime(ix['placedDate']),
                      size_matched=ix['sizeMatched'],

                      order_type=ix['instruction']['orderType'],
                      side=ix['instruction']['side'],

                      persistence_type=ix['instruction']['limitOrder']['persistenceType'],
                      price=ix['instruction']['limitOrder']['price'],
                      size=ix['instruction']['limitOrder']['size'])
            bet.save()
            logger.warning(f'Created {bet}')
        logger.warning(f'Placed {len(ix)} bets for {market}')
"""
        {
            "averagePriceMatched": 0.0,
            "betId": "115930244839",
            "instruction": {
                "limitOrder": {
                    "persistenceType": "LAPSE",
                    "price": 10.0,
                    "size": 5.0
                },
                "orderType": "LIMIT",
                "selectionId": 10895351,
                "side": "BACK"
            },
            "orderStatus": "EXECUTABLE",
            "placedDate": "2018-02-09T09:41:33.000Z",
            "sizeMatched": 0.0,
            "status": "SUCCESS"
        },

"""


def list_current_bets():
    """
    Update orders with list_current_orders.
    list from market status 'placed'
    """
    bets = Bet.objects.outstanding()
    if not bets:
        logger.info(f'No current bets to look up')
        return
    logger.warning(f'Looking up {len(bets)} current bets...')

    trading = get_betfair_client()
    res = trading.betting.list_current_orders(
        bet_ids=[b.bet_id for b in bets],
        order_projection='ALL',
        order_by='BY_PLACE_TIME',
        lightweight=True)
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))

    for ix in res['currentOrders']:
        market = Market.objects.get(market_id=ix['marketId'])
        bf_runner = Runner.objects.get(selection_id=ix['selectionId'])
        bet, created = Bet.objects.update_or_create(
            bet_id=ix['betId'],
            market=market,
            runner=bf_runner,
            defaults={
                'order_type': ix['orderType'],
                'persistence_type': ix['persistenceType'],
                'placed_at': parse_datetime(ix['placedDate']),
                'price': ix['priceSize']['price'],
                'size': ix['priceSize']['size'],
                'side': ix['side'],
                'size_cancelled': ix['sizeCancelled'],
                'size_lapsed': ix['sizeLapsed'],
                'size_matched': ix['sizeMatched'],
                'size_remaining': ix['sizeRemaining'],
                'size_voided': ix['sizeVoided'],
                'status': ix['status'],
            })
        if created:
            logger.warning(f'Created {bet}')
        else:
            logger.warning(f'Updated {bet}')
"""
"currentOrders": [
        {
            "averagePriceMatched": 0.0,
            "betId": "115934943681",
            "bspLiability": 0.0,
            "handicap": 0.0,
            "marketId": "1.139870823",
            "orderType": "LIMIT",
            "persistenceType": "LAPSE",
            "placedDate": "2018-02-09T10:51:29.000Z",
            "priceSize": {
                "price": 3.95,
                "size": 5.0
            },
            "regulatorCode": "MALTA LOTTERIES AND GAMBLING AUTHORITY",
            "selectionId": 12580825,
            "side": "BACK",
            "sizeCancelled": 0.0,
            "sizeLapsed": 0.0,
            "sizeMatched": 0.0,
            "sizeRemaining": 5.0,
            "sizeVoided": 0.0,
            "status": "EXECUTABLE"
        },
"""


def list_settled_bets():
    """
    list_cleared_bets
    list from market status 'placed'
    update market status 'placed' to 'finished'
    """
    bets = Bet.objects.outstanding()
    if not bets:
        logger.info(f'No settled bets to look up')
        return
    logger.warning(f'Looking up {len(bets)} settled bets...')

    trading = get_betfair_client()
    res = trading.betting.list_cleared_orders(
        bet_status='SETTLED',
        bet_ids=[b.bet_id for b in bets],
        lightweight=True)
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))
    for ix in res['clearedOrders']:
        market = Market.objects.get(market_id=ix['marketId'])
        bf_runner = Runner.objects.get(selection_id=ix['selectionId'])
        bet, created = Bet.objects.update_or_create(
            bet_id=ix['betId'],
            market=market,
            runner=bf_runner,
            defaults={
                'outcome': ix['betOutcome'],
                'profit': ix['profit'],
            })
        if created:
            logger.error(f'Created {bet}')
        else:
            logger.warning(f'Updated {bet}')

"""
            "betCount": 1,
            "betId": "116019707654",
            "betOutcome": "LOST",
            "eventId": "28582075",
            "eventTypeId": "7",
            "handicap": 0.0,
            "lastMatchedDate": "2018-02-09T23:54:21.000Z",
            "marketId": "1.139926911",
            "orderType": "LIMIT",
            "persistenceType": "LAPSE",
            "placedDate": "2018-02-09T23:54:10.000Z",
            "priceMatched": 5.6,
            "priceReduced": false,
            "priceRequested": 5.6,
            "profit": -5.0,
            "selectionId": 17103170,
            "settledDate": "2018-02-09T23:59:12.000Z",
            "side": "BACK",
            "sizeSettled": 5.0
"""


def list_lapsed_bets():
    """
    list_cleared_bets
    list from market status 'placed'
    update market status 'placed' to 'finished'
    """
    bets = Bet.objects.outstanding()
    if not bets:
        logger.info(f'No lapsed bets to look up')
        return
    logger.warning(f'Looking up {len(bets)} lapsed bets...')

    trading = get_betfair_client()
    res = trading.betting.list_cleared_orders(
        bet_status='LAPSED',
        bet_ids=[b.bet_id for b in bets],
        lightweight=True)
    # print(json.dumps(res, indent=4, default=str, sort_keys=True))
    for ix in res['clearedOrders']:
        market = Market.objects.get(market_id=ix['marketId'])
        bf_runner = Runner.objects.get(selection_id=ix['selectionId'])
        bet, created = Bet.objects.update_or_create(
            bet_id=ix['betId'],
            market=market,
            runner=bf_runner,
            defaults={
                'status': 'LAPSED',
                'size_cancelled': ix['sizeCancelled'],
            })
        if created:
            logger.error(f'Created lapsed {bet}')
        else:
            logger.warning(f'Updated lapsed {bet}')


def get_odds(odd):
    config = {
        2: (2, 0.01),
        3: (2, 0.02),
        4: (2, 0.05),
        6: (1, 0.1),
        10: (1, 0.2),
        20: (1, 0.5),
        30: (0, 1),
        50: (0, 2),
        100: (0, 5),
        1000: (0, 10),
    }
    for cutoff, increment in config.items():
        if odd <= cutoff:
            odd = bf_round(odd, increment[0], increment[1])
            break
    return odd


def bf_round(x, prec=2, base=.05):
    return round(base * round(float(x) / base), prec)
