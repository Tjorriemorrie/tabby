import logging.config

import click
from scraper import scrape_history

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def cli(ctx):
    pass


# @click.command()
# @click.option('--create', is_flag=True, help='create db tables')
# @click.option('--drop', is_flag=True, help='drop db tables')
# @click.option('--runbo', is_flag=True, help='recreate runbo db tables')
# @click.pass_context
# def db(ctx, create, drop, runbo):
#     if runbo:
#         recreate_runbo()
#     else:
#         db_session = DBSession()
#         if drop:
#             logging.info('dropping db tables...')
#             for table in ['race']:
#                 db_session.execute('DROP TABLE IF EXISTS {}'.format(table))
#         if create:
#             logging.info('creating db tables...')
#             Base.metadata.create_all(engine)
# cli.add_command(db)


@click.command()
@click.option('--list', 'lst', is_flag=True, help='list dates already scraped')
@click.option('--dt', help='scrape this specific date')
@click.option('--reduce', 'red', is_flag=True, help='Delete oldest data')
@click.pass_context
def scrape(ctx, lst, dt, red):
    scrape_history(lst, dt, red)
cli.add_command(scrape)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    cli(obj={})
