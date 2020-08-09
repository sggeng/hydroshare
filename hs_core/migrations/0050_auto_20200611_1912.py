# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-06-11 19:12
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hs_core', '0049_auto_20200610_1938'),
    ]

    operations = [
        migrations.AlterField(
            model_name='baseresource',
            name='doi',
            field=models.CharField(blank=True, db_index=True, default='', help_text="Permanent identifier. Never changes once it's been set.", max_length=128),
        ),
    ]