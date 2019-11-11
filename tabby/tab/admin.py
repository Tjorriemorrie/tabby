from django.contrib import admin

from .models import RunnerMeta, Var


@admin.register(RunnerMeta)
class RunnerMetaAdmin(admin.ModelAdmin):
    pass


@admin.register(Var)
class VarAdmin(admin.ModelAdmin):
    list_display = ('key', 'ran_at', 'val1', 'val2')
