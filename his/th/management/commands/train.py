# from random import random
#
# import numpy as np
# from time import time
#
# from cma import CMAOptions, CMAEvolutionStrategy
# from django.core.management.base import BaseCommand
# from django.utils.timezone import now
#
# from ...models import RunnerMeta, Var
#
#
# class Command(BaseCommand):
#     help = 'Train data variables'
#
#     def handle(self, *args, **kwargs):
#         self.stdout.write('training model')
#
#         data = RunnerMeta.objects.all()
#         self.stdout.write(f'Loaded {len(data)} data rows')
#
#         vars_train, vars_keep, vars_multi = Var.objects.next_to_train()
#         self.stdout.write(f'Variables are {", ".join([v.key for v in vars_train])}')
#
#         time_start = time()
#         sigma = 2
#         cma_params = [0, 0, 0, 0, 0, 0, 0]
#         tolx = 2610  # higher is slower
#         mins = 90
#         self.stdout.write(f'CMA settings: sigma={sigma}  mins={mins}')
#
#         opts = CMAOptions()
#         opts['bounds'] = [
#             [-np.inf],
#             [np.inf]
#         ]
#         es = CMAEvolutionStrategy(cma_params, sigma, inopts=opts)
#         while not es.stop():
#             solutions = es.ask()
#             try:
#                 fitness = []
#                 for sol in solutions:
#                     vals_params = _get_vals_params(vars_train, vars_keep, vars_multi, sol)
#                     fitness.append(_train(data, vals_params, self.stdout.write))
#             except ValueError as exc:
#                 print(str(exc))
#                 continue
#             es.tell(solutions, fitness)
#             es.disp()
#             self.stdout.write(f'tolx={es.opts["tolx"]:.3f}  sol={list(es.result[5])}')
#             es.opts['tolx'] = es.result[3] / tolx
#             if time() - time_start > 60 * mins:
#                 self.stdout.write(f'>>> {mins}min limit reached')
#                 break
#         es.result_pretty()
#         self.stdout.write(f'finished after {es.result[3]} evaluations and {es.result[4]} iterations')
#
#         res = es.result[5]
#         vars_train[0].val1 = res[0]
#         vars_train[0].val2 = res[1]
#         vars_train[0].ran_at = now()
#         vars_train[0].save()
#
#         vars_train[1].val1 = res[2]
#         vars_train[1].val2 = res[3]
#         vars_train[1].ran_at = now()
#         vars_train[1].save()
#
#         vars_train[2].val2 = res[4]
#         vars_train[2].val2 = res[5]
#         vars_train[2].ran_at = now()
#         vars_train[2].save()
#
#         vars_multi.val1 = round(res[6])
#         vars_multi.ran_at = now()
#         vars_multi.save()
#
#         self.stdout.write('Saved params')
#
#
# def _get_vals_params(vars_train, vars_keep, vars_multi, sol):
#     vars_params = {}
#     sol = list(sol)
#     for var in vars_train:
#         vars_params[var.key] = (sol.pop(0), sol.pop(0))
#     for var in vars_keep:
#         vars_params[var.key] = (var.val1, var.val2)
#     vars_params[vars_multi.key] = vars_multi.val1
#     return vars_params
#
#
# def _train(data, vars, log):
#     matches = 0
#     payouts = []
#     bets = []
#     for row in data:
#         bet_size = 1
#         bet_multi = vars['multi_origin']
#         if random() > 0.80:
#             continue
#
#         # create multi and bet
#         for key, x in vars.items():
#             if key in 'multi_origin':
#                 continue
#             bet_max_limit = 1  # todo: add limit
#             bet_min_limit = 0
#             y = getattr(row, key)
#             bet_var_multi = np.polyval(x, [y])[0]
#             bet_var_multi = min(bet_max_limit, max(bet_min_limit, bet_var_multi))
#             bet_var_multi = int(round(bet_var_multi))
#             bet_multi += bet_var_multi
#         bet_amt = bet_size * bet_multi
#
#         if bet_amt < 1:
#             # log(f'no bet {row.runner}')
#             continue
#
#         payout = -bet_amt
#         if row.placed:
#             dec_odds = 1 / row.place_odds
#             payout += bet_amt * dec_odds
#
#         matches += 1
#         bets.append(bet_amt)
#         payouts.append(round(payout, 2))
#
#     participation = matches / max(1, len(data))
#     total_payouts = sum(payouts)
#     roi = total_payouts / max(1, sum(bets))
#     score = roi * participation
#     log(f'Score: {score:.2f}  ROI:{roi*100:.1f}  Part:{participation*100:.1f}%  ${total_payouts:.0f}')
#     return -score
