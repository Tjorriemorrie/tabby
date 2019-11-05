import json
import logging

import arrow
from sqlalchemy import func, Column, Integer, String, DateTime, Float, Date, Text
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger(__name__)

Base = declarative_base()

# Create an engine that stores data in the local directory's
# sqlalchemy_example.db file.
engine = create_engine('sqlite:///data/player.db')

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


class Player(Base):
    """Unique is date, runner_name, race_id"""
    __tablename__ = 'player'

    id = Column(Integer, primary_key=True)

    # race info
    race_id = Column(Integer)
    race_type = Column(String(250))
    meeting_name = Column(String(250))
    race_number = Column(Integer)
    raced_at = Column(DateTime, index=True)

    # runner info
    name = Column(String(250), index=True)
    cnt = Column(Integer)
    pos = Column(Integer)
    rating_m_prev = Column(Float)
    rating_s_prev = Column(Float)
    rating_m = Column(Float)
    rating_s = Column(Float)

    def __str__(self):
        return '<{} {} {} {}>'.format(self.__class__.__name__, self.rating_m, 
                                      self.name, self.race_start_time)


def recreate_player_db():
    db_session = DBSession()
    logging.info('dropping db tables...')
    db_session.execute('DROP TABLE IF EXISTS {}'.format(Player.__name__))
    logging.info('creating db tables...')
    Base.metadata.create_all(engine)
    logging.info('done')


def load_player(name):
    logger.debug('Loading player for {}...'.format(name))

    sql = db_session.query(Player).filter(
        Player.name == name).order_by(
        Player.raced_at.desc()
    )

    return sql.first()


def delete_race_players(race_type):
    """delete race type"""
    logger.info('deleting {}'.format(race_type))
    db_session.query(Player).filter(Player.race_type == race_type).delete()
    db_session.commit()


def save_players(race, parts, new_ratings, cache):
    """save new ratings from race"""
    for p, n in zip(parts, new_ratings):
        player = Player()
        db_session.add(player)

        player.race_id = race.id
        player.race_type = race.race_type
        player.meeting_name = race.meeting_name
        player.race_number = race.race_number
        player.raced_at = race.race_start_time
        player.name = p['runnerName']
        player.cnt = p['cnt']
        player.pos = p['pos']
        player.rating_m_prev = p['rating_mu']
        player.rating_s_prev = p['rating_sigma']
        player.rating_m = n[0].mu
        player.rating_s = n[0].sigma
        logger.debug('{} got {}. rating from {} to {}'.format(
            player.name, player.pos, p['rating_mu'], n[0]))

        # update cache
        cache[p['runnerName']] = player

    # logger.debug('Saving...')
    # db_session.commit()


def get_last_player_date(race_type):
    """Max date for race type"""
    return db_session.query(
        func.max(Player.raced_at)
    ).filter(
        Player.race_type == race_type
    ).scalar()
