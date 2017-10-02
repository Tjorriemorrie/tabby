import logging

import arrow
import requests

from data.race import save_race, list_race_dates, delete_oldest

logger = logging.getLogger(__name__)


def scrape_history(lst, dt_target, red):
    """scrape yesterday results and predict and save it"""
    logger.setLevel(logging.DEBUG)
    logger.info('get results!')

    # reduce?
    if red:
        dt = delete_oldest()
        logger.info('Deleted {}'.format(dt))
        return

    # list result dates
    if lst:
        for dt in list_race_dates():
            logger.info('Date: {}'.format(dt))
        return

    dt_target = dt_target and arrow.get(dt_target) or arrow.now().shift(days=-1)
    logger.debug(f'Date target = {dt_target}')

    # scrape yesterday's races
    url = 'https://api.beta.tab.com.au/v1/historical-results-service/NSW/racing/{}'.format(
        dt_target.format('YYYY-MM-DD'))
    logger.info('Scraping {}'.format(url))

    meetings = requests.get(url)
    meetings.raise_for_status()
    meetings = meetings.json()
    logger.info('Found {} results'.format(len(meetings)))

    for meeting in meetings['meetings']:
        # print(json.dumps(meeting, indent=4, default=str, sort_keys=True))
        # raise Exception('')
        logger.info('Processing meeting {}'.format(meeting['meetingName']))

        for race_basic in meeting['races']:
            logger.info('Processing race {} {}'.format(race_basic['raceName'], race_basic['raceNumber']))

            url = race_basic['_links']['self']
            logger.info('Scraping race {}'.format(url))
            race = requests.get(url)
            race.raise_for_status()
            race = race.json()
            # print(json.dumps(race, indent=4, default=str, sort_keys=True))
            # raise Exception('')

            save_race(race)


####################################################################################
# meeting
####################################################################################

# race types
# race['meeting']['raceType'] can be R, G, H
# race_types = Counter()
# for race in races:
#     race_types.update(race['meeting']['raceType'])
# logger.info('Race types: {}'.format(race_types.most_common()))
#     print(json.dumps(race, indent=4, default=str))
# {
#     "raceStartTime": "2017-09-12T07:34:00.000Z",
#     "raceNumber": 6,
#     "raceName": "CORDINA CHICKENS PACE MS",
#     "raceDistance": 1609,
#     "broadcastChannel": "Sky Racing 1",
#     "broadcastChannels": [
#         "Sky Racing 1"
#     ],
#     "meeting": {
#         "sellCode": {
#             "meetingCode": "S",
#             "scheduledType": "H"
#         },
#         "raceType": "H",
#         "meetingName": "MENANGLE",
#         "location": "NSW",
#         "weatherCondition": "FINE",
#         "trackCondition": "FAST",
#         "railPosition": null,
#         "venueMnemonic": "MEN",
#         "meetingDate": "2017-09-12"
#     },
#     "_links": {
#         "self": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6?jurisdiction=NSW",
#         "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6/form?jurisdiction=NSW",
#         "bigBets": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/H/MEN/races/6/big-bets?jurisdiction=NSW"
#     }
# }


####################################################################################
# runner
####################################################################################

    # {
#     "_links": {
#         "form": "https://api.beta.tab.com.au/v1/tab-info-service/racing/dates/2017-09-12/meetings/G/GOS/races/7/form/1?jurisdiction=NSW"
#     },
#     "barrierNumber": 1,
#     "blinkers": false,
#     "claimAmount": 0,
#     "dfsFormRating": 96,
#     "earlySpeedRating": 87,
#     "earlySpeedRatingBand": "LEADER",
#     "emergency": false,
#     "fixedOdds": {
#         "allowPlace": true,
#         "bettingStatus": "Open",
#         "differential": null,
#         "flucs": [
#             {
#                 "returnWin": 2.6,
#                 "returnWinTime": "2017-09-12T10:38:45.000Z"
#             },
#             {
#                 "returnWin": 2.7,
#                 "returnWinTime": "2017-09-12T10:35:26.000Z"
#             },
#             {
#                 "returnWin": 2.8,
#                 "returnWinTime": "2017-09-12T07:57:21.000Z"
#             }
#         ],
#         "isFavouritePlace": true,
#         "isFavouriteWin": true,
#         "percentageChange": 4,
#         "propositionNumber": 165951,
#         "returnPlace": 1.3,
#         "returnWin": 2.7,
#         "returnWinOpen": 2.8,
#         "returnWinOpenDaily": 2.8,
#         "returnWinTime": "2017-09-12T10:48:05.000Z"
#     },
#     "handicapWeight": 0,
#     "harnessHandicap": null,
#     "last5Starts": "43341",
#     "parimutuel": {
#         "bettingStatus": "Open",
#         "isFavouritePlace": false,
#         "isFavouriteWin": false,
#         "marketMovers": [
#             {
#                 "returnWin": 4.2,
#                 "returnWinTime": "2017-09-12T10:52:24.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 4.5,
#                 "returnWinTime": "2017-09-12T10:51:44.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 4.4,
#                 "returnWinTime": "2017-09-12T10:50:38.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 3.8,
#                 "returnWinTime": "2017-09-12T10:49:41.000Z",
#                 "specialDisplayIndicator": false
#             },
#             {
#                 "returnWin": 5.2,
#                 "returnWinTime": "2017-09-12T10:39:39.000Z",
#                 "specialDisplayIndicator": true
#             }
#         ],
#         "percentageChange": -17,
#         "returnPlace": 1.3,
#         "returnWin": 3.5
#     },
#     "penalty": 0,
#     "riderDriverFullName": null,
#     "riderDriverName": "",
#     "runnerName": "LIBERTY LEE",
#     "runnerNumber": 1,
#     "silkURL": "https://api.beta.tab.com.au/v1/tab-info-service/racing/silk/1",
#     "tcdwIndicators": "TCD",
#     "techFormRating": 0,
#     "totalRatingPoints": 17,
#     "trainerFullName": "BETTY KEENE",
#     "trainerName": "B Keene"
# },


