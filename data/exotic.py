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

engine = create_engine('sqlite:///data/exotic.db')

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


class Exotic(Base):
    """Exotic betting combinations of runners pre-compiled"""
    __tablename__ = 'exotic'

    id = Column(Integer, primary_key=True)

    # general
    race_id = Column(Integer)
    runner_numbers = Column(String(250))
    race_type = Column(String(250))
    bet_type = Column(String(250))
    res1 = Column(Integer)
    res2 = Column(Integer)
    res3 = Column(Integer)
    res4 = Column(Integer)
    
    # inputs
    num_runners = Column(Float)

    # runners (should be sorted by odds)
    run1_num = Column(Integer)
    run1_win_perc = Column(Float)
    run1_win_scaled = Column(Float)
    run1_win_rank = Column(Float)
    run1_place_perc = Column(Float)
    run1_place_scaled = Column(Float)
    run1_place_rank = Column(Float)

    run2_num = Column(Integer)
    run2_win_perc = Column(Float)
    run2_win_scaled = Column(Float)
    run2_win_rank = Column(Float)
    run2_place_perc = Column(Float)
    run2_place_scaled = Column(Float)
    run2_place_rank = Column(Float)

    run3_num = Column(Integer)
    run3_win_perc = Column(Float)
    run3_win_scaled = Column(Float)
    run3_win_rank = Column(Float)
    run3_place_perc = Column(Float)
    run3_place_scaled = Column(Float)
    run3_place_rank = Column(Float)

    run4_num = Column(Integer)
    run4_win_perc = Column(Float)
    run4_win_scaled = Column(Float)
    run4_win_rank = Column(Float)
    run4_place_perc = Column(Float)
    run4_place_scaled = Column(Float)
    run4_place_rank = Column(Float)

    # result
    prediction = Column(Float)
    success = Column(Integer)
    dividend = Column(Float)

    def to_dict(self):
        return {x.name: getattr(self, x.name) for x in self.__table__.columns}


def recreate_exotic():
    logging.info('dropping db tables...')
    db_session.execute('DROP TABLE IF EXISTS {}'.format(Exotic.__tablename__))
    logging.info('creating db tables...')
    Base.metadata.create_all(engine)
    logger.info('done')


def clear_exotic(race_type, bet_type):
    logger.info('clearing {} {}'.format(race_type, bet_type))
    db_session.query(Exotic).filter(
        Exotic.race_type == race_type,
        Exotic.bet_type == bet_type
    ).delete()
    db_session.commit()


def load_exotics(bet_type, race_type):
    logger.info('Loading exotics for {} {}...'.format(bet_type, race_type))

    sql = db_session.query(Exotic)
    sql = sql.filter(
        Exotic.bet_type == bet_type,
        Exotic.race_type == race_type)

    return sql.all()


def save_exotic(comb):
    # logger.debug('saving exotic {}'.format(comb))
    r = Exotic(**comb)
    db_session.add(r)
