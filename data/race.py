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
engine = create_engine('sqlite:///race.db')

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

    # dividends (skip win/place/duet)
    quinella = Column(Float)
    exacta = Column(Float)
    trifecta = Column(Float)
    first_four = Column(Float)

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

    # dividends (outside create to update values)
    for dividend in race['dividends']:
        if dividend['wageringProduct'] == 'Quinella' and dividend['poolDividends']:
            r.quinella = dividend['poolDividends'][0]['amount']
        if dividend['wageringProduct'] == 'Exacta' and dividend['poolDividends']:
            r.exacta = dividend['poolDividends'][0]['amount']
        if dividend['wageringProduct'] == 'Trifecta' and dividend['poolDividends']:
            r.trifecta = dividend['poolDividends'][0]['amount']
        if dividend['wageringProduct'] == 'FirstFour' and dividend['poolDividends']:
            r.first_four = dividend['poolDividends'][0]['amount']

    # lists
    r.num_runners = race.get('num_runners')
    r.set_runners(race['runners'])
    r.set_results(race['results'])

    logger.info('Saving {}'.format(r))
    db_session.commit()


def load_races(category):
    logger.info('Loading races...')

    sql = db_session.query(Race)

    if category:
        sql = sql.filter(Race.race_type == category)

    return sql.all()


def list_race_dates():
    """list all dates"""
    return db_session.query(Race.meeting_date).order_by(Race.meeting_date.desc()).distinct()


def delete_race(id_):
    """list all dates"""
    logger.info('deleting {}'.format(id_))
    db_session.query(Race).filter(Race.id == id_).delete()
    # db_session.commit()


def delete_oldest():
    oldest_date = list_race_dates()[-1][0]
    logger.debug('oldest_date = {}'.format(oldest_date))
    db_session.query(Race).filter(Race.meeting_date == oldest_date).delete()
    db_session.commit()
    # logger.debug('vacuuming...')
    # db_session.flush()
    # db_session.execute('VACUUM')
    return oldest_date
