import datetime
import logging
import re
from operator import itemgetter

import pytz
from betfairlightweight.filters import market_filter, time_range
from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .client import get_betfair_client, ET_HORSE_RACING, ET_GREYHOUND_RACING
from .models import Event, Market, Book, Runner

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
        venue=event['venue'].upper(),
        open_date=parse_datetime(event['openDate']),
        defaults={
            'name': event['name'],
            'country_code': event['countryCode'],
            'timezone': event['timezone'],
        }
    )
    if created:
        logger.warning(f'Created {event}')
    return event


@shared_task
def parse_market(event, cat):
    """Parses market from MarketCatalogue object"""
    market, created = Market.objects.update_or_create(
        event=event,
        market_id=cat['marketId'],
        defaults={
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
    return market


@shared_task
def parse_runners(market, items):
    """Parses runners from MarketCatalogue object"""
    runners = []
    for runner_item in items:
        runner, created = Runner.objects.update_or_create(
            market=market,
            selection_id=runner_item['selectionId'],
            defaults={
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
            logger.info(f'Created {runner}')
        runners.append(runner)
    return runners


'''
{
        "description": {
            "bettingType": "ODDS",
            "bspMarket": false,
            "clarifications": "NR: (EST) <br> 2. Blameitonthewhisky (8.8%,18:39)",
            "discountAllowed": true,
            "marketBaseRate": 5.0,
            "marketTime": "2018-01-28T00:50:00.000Z",
            "marketType": "OTHER_PLACE",
            "persistenceEnabled": false,
            "priceLadderDescription": {
                "type": "CLASSIC"
            },
            "raceType": "Harness",
            "regulator": "MALTA LOTTERIES AND GAMBLING AUTHORITY",
            "rules": "<table cellborder=\"0\" width=\"100%\"></table><a href=\"http://form.horseracing.betfair.com\" target=\"_blank\"><img src=\" http://content-cache.betfair.com/images/en_GB/mr_fr.gif\" title=\u201dForm/ Results\u201d border=\"0\"></a><br><br><b>MARKET INFORMATION</b><br><br>For further information please see <a href=http://content.betfair.com/aboutus/content.asp?sWhichKey=Rules%20and%20Regulations#undefined.do style=color:0163ad; text-decoration: underline; target=_blank>Rules & Regs</a>.<br><br>Who will finish 1st or 2nd in this race? NON RUNNERS DO NOT CHANGE THE PLACE TERMS. Should the number of runners be equal to or less than the number of places available as set out above in these rules all bets will be void. This market will be settled on the official result - horses running for purse only will be scratched. CARD NUMBERS ARE A GUIDE ONLY. BETS ARE PLACED ON A NAMED HORSE. Horses are NOT COUPLED. Betfair Non-Runner Rule applies. Dead heat rules apply.<br><br><b>This market will be CLOSED at the off </b>with unmatched bets cancelled once the Betfair SP reconciliation process has been completed (if applicable). ",
            "rulesHasDate": true,
            "suspendTime": "2018-01-28T00:50:00.000Z",
            "turnInPlayEnabled": false,
            "wallet": "UK wallet"
        },
        "event": {
            "countryCode": "US",
            "id": "28563665",
            "name": "Woodb (Harness) (US) 27th Jan",
            "openDate": "2018-01-28T00:10:00.000Z",
            "timezone": "US/Eastern",
            "venue": "Woodbine"
        },
        "marketId": "1.139419620",
        "marketName": "2 TBP",
        "marketStartTime": "2018-01-28T00:50:00.000Z",
        "totalMatched": 6.9832
        "runners": [
            {
                "handicap": 0.0,
                "metadata": {
                    "ADJUSTED_RATING": null,
                    "AGE": "5",
                    "BRED": "USA",
                    "CLOTH_NUMBER": "1",
                    "CLOTH_NUMBER_ALPHA": "1",
                    "COLOURS_DESCRIPTION": "white-blue-oran",
                    "COLOURS_FILENAME": null,
                    "COLOUR_TYPE": "b",
                    "DAMSIRE_BRED": "USA",
                    "DAMSIRE_NAME": "Angus Hall",
                    "DAMSIRE_YEAR_BORN": null,
                    "DAM_BRED": "USA",
                    "DAM_NAME": "J M Aggie",
                    "DAM_YEAR_BORN": null,
                    "DAYS_SINCE_LAST_RUN": "7",
                    "FORECASTPRICE_DENOMINATOR": "1",
                    "FORECASTPRICE_NUMERATOR": "12",
                    "FORM": "288329",
                    "JOCKEY_CLAIM": null,
                    "JOCKEY_NAME": "Hudon, Phillip",
                    "OFFICIAL_RATING": null,
                    "OWNER_NAME": "Peter Core-Raymond Core,Sarnia,ON",
                    "SEX_TYPE": "m",
                    "SIRE_BRED": "USA",
                    "SIRE_NAME": "Deweycheatumnhowe",
                    "SIRE_YEAR_BORN": null,
                    "STALL_DRAW": "1",
                    "TRAINER_NAME": "Coulter, Steve P",
                    "WEARING": null,
                    "WEIGHT_UNITS": "pounds",
                    "WEIGHT_VALUE": "180",
                    "runnerId": "11536121"
                },
                "runnerName": "Tymal Diamond",
                "selectionId": 11536121,
                "sortPriority": 1
            },
        ],
    },
'''


def monitor_market(pk):
    """monitor market"""
    market = Market.objects.get(id=pk)
    trading = get_betfair_client()
    res = trading.betting.list_market_book(
        market_ids=[market.market_id],
        match_projection='ROLLED_UP_BY_PRICE'
    )
    if len(res) != 1:
        raise Exception(f'Expected 1 marketbook but received {len(res)} for {market.market_id}')
    item = res[0]

    # create book for version
    book, created = Book.objects.update_or_create(
        market=market,
        version=item.version,
        defaults={
            'bet_delay': item.bet_delay,
            'bsp_reconciled': item.bsp_reconciled,
            'complete': item.complete,
            'cross_matching': item.cross_matching,
            'inplay': item.inplay,
            'is_market_data_delayed': item.is_market_data_delayed,
            'last_match_time': item.last_match_time,
            'number_of_active_runners': item.number_of_active_runners,
            'number_of_runners': item.number_of_runners,
            'number_of_winners': item.number_of_winners,
            'runners_voidable': item.runners_voidable,
            'status': item.status,
            'total_available': item.total_available,
            'total_matched': item.total_matched,
        }
    )

    # create runners

