import click
import logging.config
from scraper import next_to_go
from model import Base, engine, db_session

logger = logging.getLogger(__name__)


@click.group()
@click.option('--debug', is_flag=True)
@click.pass_context
def cli(ctx, debug):
    ctx.obj['debug'] = debug


@click.command()
@click.option('--create', is_flag=True, help='create db tables')
@click.option('--drop', is_flag=True, help='drop db tables')
@click.pass_context
def db(ctx, create, drop):
    if drop:
        logging.info('dropping db tables...')
        for table in ['race']:
            db_session.execute('DROP TABLE IF EXISTS {}'.format(table))
    if create:
        logging.info('creating db tables...')
        Base.metadata.create_all(engine)
cli.add_command(db)


@click.command()
# @click.option('--profile', is_flag=True, help='cprofile app for performance')
@click.pass_context
def scrape(ctx):
    debug = ctx.obj['debug']
    logging.info('running scraping command')
    next_to_go()
cli.add_command(scrape)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    cli(obj={})
