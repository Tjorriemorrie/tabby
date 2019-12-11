from django.contrib import admin

from .models import RunnerMeta, Var, Runner


@admin.register(Runner)
class RunnerAdmin(admin.ModelAdmin):

    def race__start_time(self, obj):
        return obj.race.start_time

    def fixedodds__win_dec(self, obj):
        fixed_odds = obj.fixedodd_set.first()
        return fixed_odds.win_dec if fixed_odds else None

    def fixedodds__place_dec(self, obj):
        fixed_odds = obj.fixedodd_set.first()
        return fixed_odds.place_dec if fixed_odds else None

    date_hierarchy = 'race__start_time'
    list_display = ('race__start_time', 'runner_number', 'name', 'dfs_form_rating', 'fixedodds__win_dec',
                    'fixedodds__place_dec', 'last_5_starts', 'race',)
    list_select_related = ('race',)
    race__start_time.admin_order_field = 'race__start_time'
    fixedodds__win_dec.admin_order_field = 'fixedodd__win_dec'
    fixedodds__place_dec.admin_order_field = 'fixedodd__place_dec'


@admin.register(RunnerMeta)
class RunnerMetaAdmin(admin.ModelAdmin):
    pass


@admin.register(Var)
class VarAdmin(admin.ModelAdmin):
    list_display = ('key', 'ran_at', 'val1', 'val2')
