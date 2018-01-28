import datetime
import logging

from betfairlightweight.filters import market_filter, time_range, price_projection, price_data
from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tab.models import Race
from .client import get_betfair_client, ET_HORSE_RACING, ET_GREYHOUND_RACING
from .models import Event, Market, Book, Runner, RunnerBook

logger = logging.getLogger(__name__)


@shared_task
def list_market_catalogue():
    trading = get_betfair_client()
    time_ago = timezone.now() - datetime.timedelta(minutes=10)
    time_fwd = timezone.now() + datetime.timedelta(minutes=30)
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
        max_results=1000,
        lightweight=True)

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
        logger.warning(f'Updated {event}')
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
        logger.warning(f'Updated {market}')
    return market


@shared_task
def parse_runners(market, items):
    """Parses runners from MarketCatalogue object"""
    runners = []
    for runner_item in items:
        runner, created = Runner.objects.update_or_create(
            selection_id=runner_item['selectionId'],
            defaults={
                'market': market,
                # default
                'name': runner_item['runnerName'].upper(),
                'sort_priority': runner_item['sortPriority'],
                'handicap': runner_item['handicap'],
                # metadata
                'cloth_number': runner_item['metadata'].get('CLOTH_NUMBER'),
                'stall_draw': runner_item['metadata'].get('STALL_DRAW'),
                'runner_id': runner_item['metadata']['runnerId'],
            }
        )
        if created:
            logger.warning(f'Created {runner}')
        runners.append(runner)
    return runners


@shared_task
def monitor_market_book(race_pk):
    """monitor the market book of the given race"""
    race = Race.objects.get(id=race_pk)
    if not race.win_market:
        link_betfair_market.delay(race.pk)
    else:
        monitor_market(race.win_market.pk)


@shared_task
def link_betfair_market(pk):
    race = Race.objects.get(id=pk)
    try:
        market = Market.objects.get(
            market_type='WIN',
            event__venue=race.meeting.name,
            start_time=race.start_time,
        )
    except Market.DoesNotExist:
        logger.error(f'Betfair event not found for tab {race}')
        return
    race.win_market = market
    race.save()
    logger.warning(f'Linked {market} to {race}!')


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

    book = upsert_market_book(market, item)
    rbooks = upsert_runner_book(book, item)
    if book.number_of_active_runners != len(rbooks):
        logger.error(f'Missing runners {book.number_of_active_runners} vs {len(rbooks)} in {book}')
        logger.error(f'Market has {market.runner_set.count()} runners (expecting {book.number_of_runners} from book)')
    else:
        logger.warning(f'Successfully monitored market {market}')


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
        rbooks.append(rbook)
    return rbooks


'''
>>> list_market_book(1.139428965)
res length 1
[
   {
      "marketId": "1.139428965",
      "isMarketDataDelayed": true,
      "status": "OPEN",
      "betDelay": 0,
      "bspReconciled": false,
      "complete": true,
      "inplay": false,
      "numberOfWinners": 1,
      "numberOfRunners": 7,
      "numberOfActiveRunners": 7,
      "lastMatchTime": "2018-01-28T04:33:22.412Z",
      "totalMatched": 501.95,
      "totalAvailable": 107933.31,
      "crossMatching": false,
      "runnersVoidable": false,
      "version": 2030577311,
      "runners": [
         {
            "selectionId": 11163108,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 8.199,
            "lastPriceTraded": 6.6,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 9.2,
                     "size": 26.16
                  },
                  {
                     "price": 8.4,
                     "size": 23.44
                  },
                  {
                     "price": 6.6,
                     "size": 47.14
                  }
               ],
               "availableToLay": [
                  {
                     "price": 17.0,
                     "size": 33.64
                  },
                  {
                     "price": 22.0,
                     "size": 19.2
                  },
                  {
                     "price": 27.0,
                     "size": 22.7
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 11376314,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 33.563,
            "lastPriceTraded": 2.06,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 2.08,
                     "size": 135.92
                  },
                  {
                     "price": 2.04,
                     "size": 19.48
                  },
                  {
                     "price": 1.57,
                     "size": 17.46
                  }
               ],
               "availableToLay": [
                  {
                     "price": 2.6,
                     "size": 20.0
                  },
                  {
                     "price": 3.3,
                     "size": 64.5
                  },
                  {
                     "price": 3.7,
                     "size": 59.36
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 1506801,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 26.095,
            "lastPriceTraded": 4.2,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 4.2,
                     "size": 53.81
                  },
                  {
                     "price": 3.15,
                     "size": 90.48
                  },
                  {
                     "price": 3.0,
                     "size": 43.65
                  }
               ],
               "availableToLay": [
                  {
                     "price": 8.4,
                     "size": 44.74
                  },
                  {
                     "price": 9.0,
                     "size": 28.56
                  },
                  {
                     "price": 9.4,
                     "size": 27.93
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 11499030,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 9.562,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 10.0,
                     "size": 69.95
                  },
                  {
                     "price": 9.6,
                     "size": 64.59
                  },
                  {
                     "price": 8.8,
                     "size": 75.07
                  }
               ],
               "availableToLay": [
                  {
                     "price": 220.0,
                     "size": 18.21
                  },
                  {
                     "price": 990.0,
                     "size": 23.17
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 16932054,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 11.344,
            "lastPriceTraded": 20.0,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 13.5,
                     "size": 35.61
                  },
                  {
                     "price": 11.5,
                     "size": 68.09
                  },
                  {
                     "price": 2.64,
                     "size": 100.59
                  }
               ],
               "availableToLay": [
                  {
                     "price": 21.0,
                     "size": 19.07
                  },
                  {
                     "price": 110.0,
                     "size": 24.18
                  },
                  {
                     "price": 120.0,
                     "size": 20.0
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 13034617,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 6.265,
            "lastPriceTraded": 8.4,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 7.4,
                     "size": 136.26
                  },
                  {
                     "price": 7.0,
                     "size": 101.26
                  },
                  {
                     "price": 6.2,
                     "size": 114.77
                  }
               ],
               "availableToLay": [
                  {
                     "price": 15.0,
                     "size": 44.55
                  },
                  {
                     "price": 28.0,
                     "size": 45.88
                  },
                  {
                     "price": 30.0,
                     "size": 36.66
                  }
               ],
               "tradedVolume": []
            }
         },
         {
            "selectionId": 11409455,
            "handicap": 0.0,
            "status": "ACTIVE",
            "adjustmentFactor": 4.973,
            "lastPriceTraded": 14.0,
            "totalMatched": 0.0,
            "ex": {
               "availableToBack": [
                  {
                     "price": 14.0,
                     "size": 53.67
                  },
                  {
                     "price": 4.5,
                     "size": 22.33
                  },
                  {
                     "price": 2.16,
                     "size": 57.7
                  }
               ],
               "availableToLay": [
                  {
                     "price": 24.0,
                     "size": 20.97
                  },
                  {
                     "price": 110.0,
                     "size": 17.6
                  },
                  {
                     "price": 980.0,
                     "size": 6.95
                  }
               ],
               "tradedVolume": []
            }
         }
      ]
   }
]
>>>
'''
