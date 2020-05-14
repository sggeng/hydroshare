import csv
import math
from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from theme.models import UserQuota
from hs_core.hydroshare.resource import get_quota_usage_from_irods


class Command(BaseCommand):
    help = "Output potential quota inconsistencies between iRODS and Django for all users in HydroShare"

    def add_arguments(self, parser):
        parser.add_argument('output_file_name_with_path', help='output file name with path')

    def handle(self, *args, **options):
        quota_report_list = []
        for uq in UserQuota.objects.filter(
                user__is_active=True).filter(user__is_superuser=False):
            try:
                used_value = get_quota_usage_from_irods(uq.user.username)
                if not math.isclose(used_value, uq.used_value, abs_tol=0.1):
                    # report inconsistency
                    report_dict = {'django:': uq.used_value,
                                   'irods': used_value}
                    quota_report_list.append(report_dict)
                    print('quota incosistency: {} reported in django vs {} reported in iRODS'.format(
                        uq.used_value, used_value), flush=True)
            except ValidationError as ex:
                print(ex, flush=True)

        if quota_report_list:
            with open(options['output_file_name_with_path'], 'w') as csvfile:
                w = csv.writer(csvfile)
                fields = [
                    'Quota reported in Django',
                    'Quota reported in iRODS'
                ]
                w.writerow(fields)

                for q in quota_report_list:
                    values = [
                        q['django'],
                        q['irods']
                    ]
                    w.writerow([str(v) for v in values])
