# Generated by Django 2.0.1 on 2018-01-28 07:23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('betfair', '0009_auto_20180128_1733'),
    ]

    operations = [
        migrations.AlterField(
            model_name='book',
            name='last_match_time',
            field=models.DateTimeField(null=True),
        ),
    ]
