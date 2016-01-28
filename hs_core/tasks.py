from __future__ import absolute_import

import requests

from django.conf import settings

from celery import shared_task

from hs_core.models import BaseResource
from hs_core.hydroshare.resource import get_activated_doi

@shared_task
def check_doi_activation():
    msg_lst = []
    pending_resources = BaseResource.objects.filter(raccess__published=True, doi__contains='pending')

    for res in pending_resources:
        if res.metadata.dates.all().filter(type='published'):
            pub_date = res.metadata.dates.all().filter(type='published')[0]
            pub_date = pub_date[:10]
            act_doi = get_activated_doi(res.doi)
            r = requests.get('https://test.crossref.org/search/doi?pid={USERNAME}:{PASSWORD}&format=info&doi={DOI}'.format(
                                USERNAME=settings.CROSSREF_LOGIN_ID, PASSWORD=settings.CROSSREF_LOGIN_PWD, DOI=act_doi))
            r_data = r.json()
            if r.data['PRIME-DOI'] == "success":
                res.doi = act_doi
            else:
                msg_lst.append("Published resource DOI {res_doi} is not yet activated with request data deposited since {pub_date}\n.".format(res_doi=act_doi, pub_date=pub_date))
        else:
           msg_lst.append("{res_id} does not have published date in its metadata.\n".format(res_id=res.short_id))

        email_msg = ''.join(msg_lst)
        # send email to support@hydroshare.org

    return True