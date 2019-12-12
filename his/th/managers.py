from django.utils import timezone
from django.db import models
from django.db.models import Avg, Max


class VarManager(models.Manager):

    def next_to_train(self):
        vars_train = super().get_queryset().exclude(
            key='multi_origin'
        ).order_by('ran_at').all()[:3]
        vars_keep = super().get_queryset().exclude(
            key='multi_origin'
        ).order_by('ran_at').all()[3:]
        vars_multi = super().get_queryset().filter(key='multi_origin').get()
        return vars_train, vars_keep, vars_multi
