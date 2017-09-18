import json
import logging

import arrow
from sqlalchemy import Column, Integer, String, DateTime, Float, Date, Text
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger(__name__)

Base = declarative_base()

# Create an engine that stores data in the local directory's
# sqlalchemy_example.db file.
engine = create_engine('sqlite:///tab.db')

DBSession = sessionmaker(bind=engine, autocommit=False, autoflush=True)
# DBSession.bind = engine
# A DBSession() instance establishes all conversations with the database
# and represents a "staging zone" for all the objects loaded into the
# database session object. Any change made against the objects in the
# session won't be persisted into the database until you call
# session.commit(). If you're not happy about the changes, you can
# revert all of them back to the last commit by calling
# session.rollback()

db_session = DBSession()


class Form(Base):
    __tablename__ = 'form'

    id = Column(Integer, primary_key=True)
    race_type = Column(String(250))

    runner_name = Column(String(250))
    sire = Column(String(250))
    dam = Column(String(250))
    age = Column(Integer)
    sex = Column(String(250))
    colour = Column(String(250))
    trainer = Column(String(250))
    trainer_location = Column(String(250))

    start_type = Column(String(250))
    raced_at = Column(DateTime)
    race_number = Column(Integer)
    finishing_position = Column(String(250))
    number_of_starters = Column(Integer)
    draw = Column(Integer)
    margin = Column(Float)
    venue = Column(String(250))
    audio = Column(String(250))
    video = Column(String(250))
    distance = Column(Integer)
    class_ = Column(String(250))
    handicap = Column(Float)
    rider = Column(String(250))
    starting_position = Column(Integer)
    odds = Column(Float)
    winner_or_second = Column(String(250))
    position_in_run = Column(String(250))
    track_condition = Column(String(250))
    time = Column(Float)

    def __repr__(self):
        return '<{} {} {} {:.1f}s>'.format(
            self.__class__.__name__,
            self.runner_name,
            self.raced_at.strftime('%-d %b'),
            self.time)

    def time_from_string(self, time_str):
        if ':' in time_str:
            minutes, seconds = time_str.split(':')
        else:
            minutes, seconds = 0, time_str
        time = int(minutes) * 60 + float(seconds)
        logger.debug('{} from {}'.format(time, time_str))
        self.time = time


class Race(Base):
    """Unique is date, venue, type, race#"""
    __tablename__ = 'race'

    id = Column(Integer, primary_key=True)

    # meeting
    meeting_name = Column(String(250))
    location = Column(String(250))
    venue_mnemonic = Column(String(250))
    race_type = Column(String(250))
    meeting_date = Column(Date)

    # race info
    race_number = Column(Integer)
    race_name = Column(String(250))
    race_start_time = Column(DateTime)
    race_status = Column(String(250))
    race_distance = Column(Integer)

    # lists
    results_data = Column(Text)
    num_runners = Column(Integer)
    runners_data = Column(Text)

    def __str__(self):
        return '<{} {} {} {} {}>'.format(self.__class__.__name__, self.meeting_date,
                                         self.venue_mnemonic, self.race_type, self.race_number)

    def get_runners(self):
        return json.loads(self.runners_data)

    def set_runners(self, data):
        self.runners_data = json.dumps(data)

    def get_results(self):
        return json.loads(self.results_data)

    def set_results(self, data):
        self.results_data = json.dumps(data)


def save_race(race):
    logger.info('Saving race...')

    # get existing row
    sql = db_session.query(Race).filter(
        Race.meeting_date == race['meeting']['meetingDate'],
        Race.venue_mnemonic == race['meeting']['venueMnemonic'],
        Race.race_type == race['meeting']['raceType'],
        Race.race_number == race['raceNumber'])

    try:
        r = sql.one()
        logger.debug('existing run found: {}'.format(r))

    except NoResultFound:
        logger.debug('creating new race...')
        r = Race()
        db_session.add(r)

        # meeting info
        r.meeting_name = race['meeting']['meetingName']
        r.location = race['meeting']['location']
        r.venue_mnemonic = race['meeting']['venueMnemonic']
        r.race_type = race['meeting']['raceType']
        r.meeting_date = arrow.get(race['meeting']['meetingDate']).date()

        # race info
        r.race_number = race['raceNumber']
        r.race_name = race['raceName']
        r.race_start_time = arrow.get(race['raceStartTime']).datetime
        r.race_status = race['raceStatus']
        r.race_distance = race['raceDistance']

    # lists
    r.num_runners = race.get('num_runners')
    r.set_runners(race['runners'])
    r.set_results(race['results'])

    logger.info('Saving {}'.format(r))
    db_session.commit()


def load_races():
    logger.info('Loading races...')

    sql = db_session.query(Race)
    return sql.all()


def list_race_dates():
    """list all dates"""
    return db_session.query(Race.meeting_date).order_by(Race.meeting_date.desc()).distinct()


def delete_race(id_):
    """list all dates"""
    return db_session.query(Race).filter(Race.id == id_).delete()
