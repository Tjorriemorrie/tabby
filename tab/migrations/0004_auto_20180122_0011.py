# Generated by Django 2.0.1 on 2018-01-22 00:11

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tab', '0003_auto_20180119_2133'),
    ]

    operations = [
        migrations.CreateModel(
            name='FixedOdd',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('as_at', models.DateTimeField()),
                ('win_dec', models.FloatField()),
                ('place_dec', models.FloatField()),
            ],
        ),
        migrations.CreateModel(
            name='ParimutuelOdd',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('as_at', models.DateTimeField()),
                ('win_dec', models.FloatField()),
                ('place_dec', models.FloatField()),
            ],
        ),
        migrations.CreateModel(
            name='Runner',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('link_form', models.CharField(max_length=255)),
                ('name', models.CharField(max_length=50)),
                ('trainer_name', models.CharField(max_length=100)),
                ('rider_name', models.CharField(max_length=100)),
                ('runner_number', models.IntegerField()),
                ('barrier_number', models.IntegerField()),
                ('handicap_weight', models.FloatField(null=True)),
                ('harness_handicap', models.FloatField(null=True)),
                ('last_5_starts', models.CharField(max_length=5)),
                ('dfs_form_rating', models.IntegerField()),
                ('tech_form_rating', models.IntegerField()),
                ('fixed_betting_status', models.CharField(max_length=20)),
                ('parimutuel_betting_status', models.CharField(max_length=20)),
            ],
        ),
        migrations.AddField(
            model_name='race',
            name='class_conditions',
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='race',
            name='direction',
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='race',
            name='fixed_odds_update_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='race',
            name='has_fixed_odds',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='race',
            name='has_parimutuel',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='race',
            name='number_of_places',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='race',
            name='odds_update_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='race',
            name='status',
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='runner',
            name='race',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tab.Race'),
        ),
        migrations.AddField(
            model_name='parimutuelodd',
            name='runner',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tab.Runner'),
        ),
        migrations.AddField(
            model_name='fixedodd',
            name='runner',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tab.Runner'),
        ),
    ]