# Generated by Django 2.0.1 on 2018-01-28 10:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('betfair', '0013_auto_20180128_2036'),
    ]

    operations = [
        migrations.AlterField(
            model_name='market',
            name='total_matched',
            field=models.FloatField(null=True),
        ),
    ]
