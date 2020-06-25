# -*- coding: utf-8 -*-
# Generated by Django 1.11.28 on 2020-06-25 19:10
from __future__ import unicode_literals

from django.db import migrations


def fill_csdms_names(apps, schema_editor):
    """ Store CSDMS names into LDAWord model
    """
    LDAWord = apps.get_model('hs_explore', 'LDAWord')
    CSDMSName = apps.get_model('hs_csdms', 'CSDMSName')
    csdms_names = set()
    splitted_names = set()
    for csdms_record in CSDMSName.objects.filter(part='name'):
        csdms_name = csdms_record.value
        csdms_names.add(csdms_name)
        if len(csdms_name) <= 1:
            continue
        lda_word_record = LDAWord()
        lda_word_record.source = 'CSDMS'
        lda_word_record.word_type = 'keep'
        lda_word_record.part = 'name'
        lda_word_record.value = csdms_name
        lda_word_record.save()
        tokens = csdms_name.split(" ")
        splitted_names.update(tokens)

    for splitted_name in splitted_names:
        if len(splitted_name) <= 1 or splitted_name in csdms_names:
            continue
        lda_word_record = LDAWord()
        lda_word_record.source = 'CSDMS'
        lda_word_record.word_type = 'keep'
        lda_word_record.part = 'name'
        lda_word_record.value = splitted_name
        lda_word_record.save()


def fill_odm2(apps, schema_editor):
    """ Store ODM2 names into LDAWord model
    """
    ODM2Variable = apps.get_model('hs_odm2', 'ODM2Variable')
    LDAWord = apps.get_model('hs_explore', 'LDAWord')
    term_names = ODM2Variable.objects.all().values_list('name').order_by('name')
    odm2_list = [str(t[0].replace(",", " -")) for t in term_names if not t[0][0].isdigit()]
    modified_list = []
    for odm2 in odm2_list:
        tokens = odm2.split(' - ')
        new_string = tokens[0]
        if len(tokens) > 1:
            new_string = tokens[1] + ' ' + tokens[0]
        modified_list.append(new_string.lower())

    for odm2_name in modified_list:
        lda_word_record = LDAWord()
        lda_word_record.source = 'ODM2'
        lda_word_record.word_type = 'keep'
        lda_word_record.part = 'name'
        lda_word_record.value = odm2_name
        lda_word_record.save()


def fill_stop_words(apps, schema_editor):
    """ Store common English and customized stop-words into the LDAWord model
    """
    LDAWord = apps.get_model('hs_explore', 'LDAWord')
    customized_stops = ['max', 'maximum', 'minimum', 'origin', '________', 'center',
                        'rapid', 'test', 'example', 'demo', 'mm', 'jupyter_hub',
                        'ipython', 'odm2', 'min', 'net', 'unit', 'rating',
                        'hydrologic', 'age', 'contact', 'log', 'change', 'count',
                        'run', 'pi', 'et', 'al', 'set', 'zone', 'latitude', 'longitude',
                        'region', 'matter', 'section', 'column', 'domain', 'height', 'depth',
                        'top', 'bottom', 'left', 'right', 'upper', 'lower', 'location',
                        'image', 'link', 'paper', 'day', 'second', 'parameter', 'solution',
                        'public', 'first', 'sources', 'main', 'sample', 'new', 'total',
                        'state', 'water', 'source', 'resource', 'available', 'year', 'area',
                        'model', 'rate', 'time', 'ratio', 'west', 'south', 'east', 'north',
                        'small', 'big', 'large', 'huge']

    english_stops = ['through', 'should', "shouldn't", 'both', 'in', 'which', "needn't",
                     'its', "wouldn't", 'ourselves', 'at', 'than', 'she', 'yourselves',
                     "you'll", 'it', "weren't", 'here', 'be', 'does', 'who', 'him', 'own',
                     'these', 'her', 'they', 'won', 'ours', "couldn't", 'further', 'a',
                     "hasn't", 'not', 'the', 'having', 'hers', 's', 'or', 'then', 'myself',
                     'during', 'themselves', 'on', 'down', 'doing', 'before', 'is', 'each',
                     'them', 'our', 'wouldn', 'll', 'off', 'nor', "you'd", 'aren', 'had',
                     'yourself', 'to', 'don', 'm', 'yours', 'more', "wasn't", 'was',
                     'because', 'very', 'couldn', "that'll", 'your', 'have', 'over', 'where',
                     'until', "isn't", 'itself', "aren't", 'me', 'we', 'ain', "haven't",
                     'too', 'needn', "won't", 'didn', "don't", 'for', 'i', 'are', "should've",
                     'but', 'from', 'why', 'of', "shan't", "you're", 'all', 'himself', 'theirs',
                     'd', 'whom', 'while', 'again', "didn't", 'few', 'after', 'some', 'shan',
                     't', 'weren', 'haven', 'do', "mightn't", 'can', "you've", 'an', 'only',
                     'his', 'being', 'above', 'any', 'has', 'same', 'their', 'as', 'mustn', 've',
                     'wasn', "she's", 'no', 'such', 'under', 'so', 'doesn', 'ma', 'about', 'those',
                     'shouldn', 'below', 'what', "doesn't", 'he', 'hadn', 'with', 'just', 'am',
                     'y', 'there', 'other', 'if', 'isn', 'between', 'mightn', 'how', 'up', 'my',
                     'this', 'once', 'were', 'out', 'when', 'that', 'by', 'into', 'and', 'will',
                     'o', 'now', "it's", "hadn't", "mustn't", 'been', 'did', 're', 'herself',
                     'against', 'hasn', 'you', 'most']

    for stop_word in customized_stops:
        lda_word_record = LDAWord()
        lda_word_record.source = 'Customized'
        lda_word_record.word_type = 'stop'
        lda_word_record.part = 'name'
        lda_word_record.value = stop_word
        lda_word_record.save()

    for stop_word in english_stops:
        lda_word_record = LDAWord()
        lda_word_record.source = 'English'
        lda_word_record.word_type = 'stop'
        lda_word_record.part = 'name'
        lda_word_record.value = stop_word
        lda_word_record.save()


class Migration(migrations.Migration):
    dependencies = [
        ('hs_explore', '0001_initial'),
        ('hs_csdms', '0002_auto_20200625_1746'),
        ('hs_odm2', '0002_auto_20190723_1644'),
    ]

    operations = [
        migrations.RunPython(fill_csdms_names),
        migrations.RunPython(fill_odm2),
        migrations.RunPython(fill_stop_words),
    ]
