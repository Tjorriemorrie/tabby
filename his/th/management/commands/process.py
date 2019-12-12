from random import random

import numpy as np
from time import time

from cma import CMAOptions, CMAEvolutionStrategy
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from ...models import RunnerMeta, Var, Race, Outcome


class Command(BaseCommand):
    help = 'Process data into easy to use'

    def handle(self, *args, **kwargs):
        self.stdout.write('training model')
        races = Race.objects.all()
        for race in races:
            try:
                outcome = race.outcome
            except Outcome.DoesNotExist as exc:
                self.stdout.write(f'{Race} has no outcome!')
                continue
            for runner in race.runner_set.all():
                meta = {
                    'fixed_win': runner.fixed_win,
                    'fixed_place': runner.fixed_place,
                    'tote_win': runner.tote_win,
                    'tote_place': runner.tote_place,
                    'won': runner.won(),
                    'placed': runner.placed(),
                }
                runner_meta, created = RunnerMeta.objects.update_or_create(
                    race=race,
                    runner=runner,
                    defaults=meta)
            self.stdout.write(f'Created meta for {race} runners')
        self.stdout.write(f'Finished processing {len(races)} races')
