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
                self.stdout.write(f'{race} has no outcome!')
                continue
            for runner in race.runner_set.all():
                try:
                    meta = {
                        'fixed_win': 1 / runner.fixed_win * 100,
                        'fixed_place': 1 / runner.fixed_place * 100,
                        'tote_win': 1 / runner.tote_win * 100,
                        'tote_place': 1 / runner.tote_place * 100,
                        'won': runner.won(),
                        'placed': runner.placed(),
                    }
                except ZeroDivisionError as exc:
                    self.stdout.write(f'{race} has 0 odds for something')
                    continue
                runner_meta, created = RunnerMeta.objects.update_or_create(
                    race=race,
                    runner=runner,
                    defaults=meta)
            self.stdout.write(f'Created meta for {race} runners')
        self.stdout.write(f'Finished processing {len(races)} races')
