import logging.config

import click
import arrow

from py.build import build_exotic_bets
from model import Base, engine, DBSession
from predict import predictions
from py.runbo import recreate_runbo
from scraper import next_to_go, scrape_history
from simulate import simulate

logger = logging.getLogger(__name__)


@click.group()
@click.option('--debug', is_flag=True, help='enable debugging and log level')
@click.pass_context
def cli(ctx, debug):
    ctx.obj['debug'] = debug


@click.command()
@click.option('--create', is_flag=True, help='create db tables')
@click.option('--drop', is_flag=True, help='drop db tables')
@click.option('--runbo', is_flag=True, help='recreate runbo db tables')
@click.pass_context
def db(ctx, create, drop, runbo):
    if runbo:
        recreate_runbo()
    else:
        db_session = DBSession()
        if drop:
            logging.info('dropping db tables...')
            for table in ['race']:
                db_session.execute('DROP TABLE IF EXISTS {}'.format(table))
        if create:
            logging.info('creating db tables...')
            Base.metadata.create_all(engine)
cli.add_command(db)


@click.command()
@click.option('--oncely', is_flag=True, help='only run once')
@click.option('--bet', is_flag=True, help='make real bets')
@click.pass_context
def watch(ctx, oncely, bet):
    debug = ctx.obj['debug']
    next_to_go(debug, oncely, bet)
cli.add_command(watch)


@click.command()
@click.option('--list', 'lst', is_flag=True, help='list dates already scraped')
@click.option('--dt', help='scrape this specific date')
@click.option('--predict', '-p', multiple=True, type=click.Choice(['G', 'H', 'R']))
@click.option('--reduce', 'red', is_flag=True, help='Delete oldest data')
@click.pass_context
def scrape(ctx, lst, dt, predict, red):
    debug = ctx.obj['debug']
    scrape_history(debug, lst, dt, predict, red)
cli.add_command(scrape)


@click.command()
@click.option('--odds_only', is_flag=True, help='only update runners odds')
@click.option('-R', 'category', flag_value='R', default=False)
@click.option('-G', 'category', flag_value='G', default=False)
@click.option('-H', 'category', flag_value='H', default=False)
@click.pass_context
def predict(ctx, odds_only, category):
    debug = ctx.obj['debug']
    predictions(debug, odds_only, category)
cli.add_command(predict)


@click.command()
@click.pass_context
def sim(ctx):
    debug = ctx.obj['debug']
    simulate(debug)
cli.add_command(sim)


@click.command()
@click.argument('race_type', type=click.Choice(['R', 'G', 'H']))
@click.argument('bet_type', type=click.Choice(['Q']))
@click.pass_context
def build(ctx, race_type, bet_type):
    debug = ctx.obj['debug']
    build_exotic_bets(debug, race_type, bet_type)
cli.add_command(build)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    cli(obj={})
