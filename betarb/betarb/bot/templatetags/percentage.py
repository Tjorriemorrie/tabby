from django import template

register = template.Library()


@register.filter(name='percentage')
def percentage(val, dec=None):
    val *= 100
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
    return f'{val}%'
