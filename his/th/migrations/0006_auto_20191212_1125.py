# Generated by Django 2.2.7 on 2019-12-12 00:25

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('th', '0005_remove_outcome_running_double'),
    ]

    operations = [
        migrations.RenameField(
            model_name='race',
            old_name='has_processed',
            new_name='processed',
        ),
        migrations.RemoveField(
            model_name='race',
            name='has_results',
        ),
    ]
