# Generated by Django 2.0.1 on 2018-02-12 11:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('betfair', '0031_auto_20180210_1101'),
    ]

    operations = [
        migrations.AddField(
            model_name='bet',
            name='bracket',
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),
    ]
