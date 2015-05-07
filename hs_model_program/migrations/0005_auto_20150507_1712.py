# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import datetime


class Migration(migrations.Migration):

    dependencies = [
        ('hs_model_program', '0004_auto_20150506_2310'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mpmetadata',
            name='date_released',
            field=models.DateTimeField(default=datetime.datetime(2015, 5, 7, 17, 12, 21, 762144), help_text=b'The date of the software release (m/d/Y H:M)', null=True, verbose_name=b'Release Date', blank=True),
            preserve_default=True,
        ),
    ]
