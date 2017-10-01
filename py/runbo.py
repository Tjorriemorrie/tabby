import json
import logging

import arrow
from sqlalchemy import Column, Integer, String, DateTime, Float, Date, Text
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound
from os import path

logger = logging.getLogger(__name__)

Base = declarative_base()

# Create an engine that stores data in the local directory's
# sqlalchemy_example.db file.

engine = create_engine('sqlite:///data/runbo.db')

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


class Runbo(Base):
    """Exotic betting combinations of runners pre-compiled"""
    __tablename__ = 'runbo'

    id = Column(Integer, primary_key=True)
    race_type = Column(String(250))
    bet_type = Column(String(250))

    # general
    num_runners = Column(Integer)
    res1 = Column(Integer)
    res2 = Column(Integer)
    res3 = Column(Integer)
    res4 = Column(Integer)

    # runners (should be sorted by odds)
    run1_num = Column(Integer)
    run1_win_perc = Column(Float)
    run1_win_scaled = Column(Float)
    run1_win_rank = Column(Integer)

    run2_num = Column(Integer)
    run2_win_perc = Column(Float)
    run2_win_scaled = Column(Float)
    run2_win_rank = Column(Integer)

    run3_num = Column(Integer)
    run3_win_perc = Column(Float)
    run3_win_scaled = Column(Float)
    run3_win_rank = Column(Integer)

    run4_num = Column(Integer)
    run4_win_perc = Column(Float)
    run4_win_scaled = Column(Float)
    run4_win_rank = Column(Integer)

    # result
    success = Column(Integer)
    dividend = Column(Float)


def recreate_runbo():
    logging.info('dropping db tables...')
    db_session.execute('DROP TABLE IF EXISTS {}'.format(Runbo.__tablename__))
    logging.info('creating db tables...')
    Base.metadata.create_all(engine)
    logger.info('done')


def clear_runbo(race_type, bet_type):
    logger.info('clearing {} {}'.format(race_type, bet_type))
    db_session.query(Runbo).filter(
        Runbo.race_type == race_type,
        Runbo.bet_type == bet_type
    ).delete()
    db_session.commit()


def save_runbo(comb):
    r = Runbo(**comb)
    db_session.add(r)
