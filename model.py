import logging
import os
import sys
from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class Race(Base):
    __tablename__ = 'race'

    id = Column(Integer, primary_key=True)
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
        minutes, seconds = time_str.split(':')
        time = int(minutes) * 60 + float(seconds)
        logger.debug('{} from {}'.format(time, time_str))
        self.time = time


# Create an engine that stores data in the local directory's
# sqlalchemy_example.db file.
engine = create_engine('sqlite:///tab.db')

DBSession = sessionmaker(bind=engine, autocommit=True, autoflush=True)
# DBSession.bind = engine
# A DBSession() instance establishes all conversations with the database
# and represents a "staging zone" for all the objects loaded into the
# database session object. Any change made against the objects in the
# session won't be persisted into the database until you call
# session.commit(). If you're not happy about the changes, you can
# revert all of them back to the last commit by calling
# session.rollback()
db_session = DBSession()
