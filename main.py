import logging.config

import click

logger = logging.getLogger(__name__)


@click.group()
@click.option('-v', '--verbose', count=True)
@click.pass_context
def cli(ctx, verbose):
    if verbose > 0:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO
    logging.basicConfig(level=logging_level)
    pass


@click.command()
@click.argument('table', type=click.Choice(['race', 'runbo']))
@click.pass_context
def db(ctx, table):
    from data.race import recreate_race_db
    if table == 'race':
        recreate_race_db()
    if table == 'runbo':
        # recreate_runbo()
        pass
cli.add_command(db)


@click.command()
@click.option('--list', 'lst', is_flag=True, help='list dates already scraped')
@click.option('--dt', help='scrape this specific date')
@click.option('--reduce', 'red', is_flag=True, help='Delete oldest data')
@click.pass_context
def scrape(ctx, lst, dt, red):
    from data.scraper import scrape_history
    scrape_history(lst, dt, red)
cli.add_command(scrape)


@click.command()
@click.argument('race_types', nargs=-1)
@click.option('--each_way', default='v1', help='version for each way')
@click.option('--oncely', is_flag=True, help='only run once')
@click.option('--bet', is_flag=True, help='make real bets')
@click.pass_context
def watch(ctx, each_way, race_types, oncely, bet):
    from watch import next_to_go
    next_to_go(race_types, each_way, oncely, bet)
cli.add_command(watch)


@click.command()
@click.argument('version')
@click.option('-R', 'race_types', flag_value='R', default=False)
@click.option('-G', 'race_types', flag_value='G', default=False)
@click.option('-H', 'race_types', flag_value='H', default=False)
@click.option('--odds_only', is_flag=True)
@click.option('--pred_only', is_flag=True)
@click.pass_context
def each_way(ctx, version, race_types, odds_only, pred_only):
    logger.debug('version: {}'.format(version))
    logger.debug('race_types: {}'.format(race_types))
    logger.debug('odds_only: {}'.format(odds_only))
    logger.debug('pred_only: {}'.format(pred_only))
    if version == 'v1':
        from each_way.v1.predict import run
        run(race_types, odds_only, pred_only)
    elif version == 'v2':
        from each_way.v2.predict import run
        run(race_types, odds_only, pred_only)
    else:
        raise Exception('Unhandled version number {}'.format(version))
cli.add_command(each_way)


# @click.command()
# @click.pass_context
# def sim(ctx):
#     debug = ctx.obj['debug']
#     simulate(debug)
# cli.add_command(sim)
#
#
# @click.command()
# @click.argument('race_type', type=click.Choice(['R', 'G', 'H']))
# @click.argument('bet_type', type=click.Choice(['Q']))
# @click.pass_context
# def build(ctx, race_type, bet_type):
#     debug = ctx.obj['debug']
#     build_exotic_bets(debug, race_type, bet_type)
# cli.add_command(build)


if __name__ == '__main__':
    cli(obj={})
