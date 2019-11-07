from django.utils import timezone
from django import template

register = template.Library()


@register.filter(name='percentage')
def percentage(val, dec=None):
    val *= 100
    if dec is None:
        if abs(val) < 1:
            dec = 2
        elif abs(val) < 10:
            dec = 1
        else:
            dec = 0
    val = round(val, dec)
    if dec == 0:
        val = int(val)
    return f'{val}%'


@register.filter(name='float')
def flot(val, dec=None):
    if dec is None:
        if val < 1:
            dec = 2
        elif val < 10:
            dec = 1
        else:
            dec = 0
    val = round(val, dec)
    if dec == 0:
        val = int(val)
    return f'{val}'


@register.filter(name='odds')
def odds(val):
    if not val:
        return '-'
    val = max(-2, min(1000, float(val)))
    if val < 4:
        dec = 2
    elif val < 20:
        dec = 1
    else:
        dec = 0
    val = round(val, dec)
    if dec == 0:
        val = int(val)
    return f'{val}'


@register.filter(name='as_odds')
def as_odds(val):
    return 1000 if not val else 1 / val


@register.filter(name='secs')
def secs(val):
    if not val:
        return
    delta = timezone.now() - val
    return delta.seconds
