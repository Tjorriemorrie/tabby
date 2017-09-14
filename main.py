import logging.config

import click

from model import Base, engine, DBSession
from scraper import next_to_go, get_results, model_results

logger = logging.getLogger(__name__)


@click.group()
@click.option('--debug', is_flag=True, help='enable debugging and log level')
@click.pass_context
def cli(ctx, debug):
    ctx.obj['debug'] = debug


@click.command()
@click.option('--create', is_flag=True, help='create db tables')
@click.option('--drop', is_flag=True, help='drop db tables')
@click.pass_context
def db(ctx, create, drop):
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
@click.option('--simulate', is_flag=True, help='no real betting')
@click.pass_context
def bet(ctx, simulate):
    debug = ctx.obj['debug']
    logging.info('running scraping command')
    next_to_go(debug, simulate)
cli.add_command(bet)


@click.command()
@click.pass_context
def results(ctx):
    debug = ctx.obj['debug']
    logging.info('scraping results')
    get_results(debug)
cli.add_command(results)


@click.command()
@click.pass_context
def model(ctx):
    debug = ctx.obj['debug']
    logging.info('model results')
    model_results(debug)
cli.add_command(model)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    cli(obj={})
