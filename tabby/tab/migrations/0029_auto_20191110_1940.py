# Generated by Django 2.2.7 on 2019-11-10 08:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tab', '0028_auto_20191110_1146'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='race',
            options={'ordering': ['start_time']},
        ),
        migrations.AddField(
            model_name='runnermeta',
            name='placed',
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='runnermeta',
            name='won',
            field=models.BooleanField(default=False),
            preserve_default=False,
        ),
    ]