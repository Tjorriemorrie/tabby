# Generated by Django 2.0.1 on 2018-01-30 01:00

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tab', '0025_remove_race_win_market'),
        ('betfair', '0018_auto_20180130_1126'),
    ]

    operations = [
        migrations.AddField(
            model_name='market',
            name='race',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='tab.Race'),
        ),
    ]