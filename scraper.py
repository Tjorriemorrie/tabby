import pickle
from sqlalchemy.orm.exc import NoResultFound
from datetime import datetime
from model import Race, db_session
import pandas as pd
from collections import Counter
import json
import logging
import requests
import sqlite3
from os import path

logger = logging.getLogger(__name__)


FILE_NEXT_TO_GO = path.join(path.dirname(path.abspath(__file__)), 'next_to_go.pkl')


def next_to_go():
    logger.info('next to go!')

    url = 'https://api.beta.tab.com.au/v1/tab-info-service/racing/next-to-go/races?jurisdiction=NSW'
    res = requests.get(url)
    res.raise_for_status()
    res = res.json()
    races = res['races']
    logger.info('{} races'.format(len(races)))

    # race types
    # race_types = Counter()
    # for race in races:
    #     race_types.update(race['meeting']['raceType'])
    # logger.info('Race types: {}'.format(race_types.most_common()))
    saved_meeting = False

    for new_race in races:

        # horse races
        if new_race['meeting']['raceType'] != 'R':
            continue

        # print(json.dumps(new_race, indent=4, default=str))

        if not saved_meeting:
            res = requests.get(new_race['_links']['self'])
            res.raise_for_status()
            res = res.json()
            print(json.dumps(res, indent=4, default=str, sort_keys=True))
            with open(FILE_NEXT_TO_GO, 'wb') as f:
                pickle.dump(res, f)
            saved_meeting = True

        # form
        res = requests.get(new_race['_links']['form'])
        res.raise_for_status()
        res = res.json()
        forms = res['form']
        logger.info('{} horses'.format(len(forms)))

        for form in forms:
            # print(json.dumps(form, indent=4, default=str, sort_keys=True))

            form['runnerName'] = form['runnerName'].upper()
            previous_starts = form['runnerStarts']['previousStarts']
            logger.info('{} previous starts'.format(len(previous_starts)))

            if not previous_starts:
                continue

            for previous_start in previous_starts:
                # print(json.dumps(previous_start, indent=4, default=str, sort_keys=True))

                # exists?
                previous_start['startDate'] = datetime.strptime(previous_start['startDate'], '%Y-%m-%d')
                sql = db_session.query(Race).filter(
                    Race.runner_name == form['runnerName'],
                    Race.raced_at == previous_start['startDate'],
                    Race.race_number == previous_start['raceNumber'])
                # logger.info('sql: {}'.format(sql))
                try:
                    existing_race = sql.one()
                    logger.info('existing race: {}'.format(existing_race))
                except NoResultFound:
                    logger.info('None existing found')
                    existing_race = Race(**{
                        'runner_name': form['runnerName'],
                        'sire': form['sire'],
                        'dam': form['dam'],
                        'age': form['age'],
                        'sex': form['sex'],
                        'colour': form['colour'],
                        'trainer': form['trainerName'],
                        'trainer_location': form['trainerLocation'],

                        'start_type': previous_start['startType'],
                        'raced_at': previous_start['startDate'],
                        'race_number': previous_start['raceNumber'],
                        'finishing_position': previous_start['finishingPosition'],
                        'number_of_starters': previous_start['numberOfStarters'],
                        'draw': previous_start['draw'],
                        'margin': previous_start['margin'],
                        'venue': previous_start['venueAbbreviation'],
                        'distance': previous_start['distance'],
                        'class_': previous_start['class'],
                        'handicap': previous_start.get('handicap'),
                        'rider': previous_start.get('rider'),
                        'starting_position': previous_start['startingPosition'],
                        'odds': previous_start['odds'],
                        'winner_or_second': previous_start['winnerOrSecond'],
                        'position_in_run': previous_start['positionInRun'],
                        'track_condition': previous_start['trackCondition'],
                    })
                    if 'skyRacing' in previous_start:
                        existing_race.audio = previous_start['skyRacing'].get('audio'),
                        if existing_race.audio and hasattr(existing_race.audio, '__iter__'):
                            # logger.info(existing_race.audio)
                            existing_race.audio = existing_race.audio[0]
                        existing_race.video = previous_start['skyRacing'].get('video'),
                        if existing_race.video and hasattr(existing_race.video, '__iter__'):
                            # logger.info(existing_race.video)
                            existing_race.video = existing_race.video[0]
                        # raise Exception('x')
                    existing_race.time_from_string(previous_start['time'])
                    logger.info(existing_race)
                    db_session.add(existing_race)

            # end of all previous races
        # end of all horses
    # end of all meetings


# returns a compiled model
# identical to the previous one
# model = load_model('my_model.h5')
