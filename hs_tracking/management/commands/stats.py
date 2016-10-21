import csv
import sys
import datetime
from calendar import monthrange
from optparse import make_option

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from ... import models as hs_tracking

from django_irods.icommands import SessionException
from hs_core.models import BaseResource
from theme.models import UserProfile


def month_year_iter(start, end):
    ym_start = 12 * start.year + start.month - 1
    ym_end = 12 * end.year + end.month - 1
    for ym in range(ym_start, ym_end):
        y, m = divmod(ym, 12)
        m += 1
        d = monthrange(y, m)[1]
        yield timezone.datetime(y, m, d, tzinfo=timezone.pytz.utc)


class Command(BaseCommand):
    help = "Output engagement stats about HydroShare"

    option_list = BaseCommand.option_list + (
        make_option(
            "--monthly-user-counts",
            dest="monthly-user-counts",
            action="store_true",
            help="user stats by month",
        ),
        make_option(
            "--monthly-orgs-counts",
            dest="monthly-orgs-counts",
            action="store_true",
            help="unique organization stats by month",
        ),
        make_option(
            "--user-details",
            dest="user-details",
            action="store_true",
            help="current user list",
        ),
        make_option(
            "--resource-stats",
            dest="resource_stats",
            action="store_true",
            help="current resource list with sizes",
        ),
        make_option(
            "--monthly-users-by-type",
            dest="monthly-users-by-type",
            action="store_true",
            help="user type stats by month",
        ),
        make_option(
            "--yesterdays-variables",
            dest="yesterdays_variables",
            action="store_true",
            help="dump tracking variables collected today",
        ),
    )

    def print_var(self, var_name, value, period=None):
        timestamp = timezone.now()
        if not period:
            print("{}: {} {}".format(timestamp, var_name, value))
        else:
            start, end = period
            print("{}: ({}/{}--{}/{}) {} {}".format(timestamp,
                                                    start.year, start.month,
                                                    end.year, end.month,
                                                    var_name, value))

    def monthly_users_counts(self, start_date, end_date):
        profiles = UserProfile.objects.filter(
            user__date_joined__lte=end_date,
            user__is_active=True
        )
        self.print_var("monthly_users_counts", profiles.count(),
                       (start_date, end_date))

    def monthly_orgs_counts(self, start_date, end_date):
        profiles = UserProfile.objects.filter(user__date_joined__lte=end_date)
        org_count = profiles.values('organization').distinct().count()
        self.print_var("monthly_orgs_counts", org_count, (start_date, end_date))

    def monthly_users_by_type(self, start_date, end_date):
        date_filtered = UserProfile.objects.filter(
            user__date_joined__lte=end_date,
            user__is_active=True
        )
        user_types = UserProfile.objects.values('user_type').distinct()
        for ut in [_['user_type'] for _ in user_types]:
            ut_users = User.objects.filter(userprofile__user_type=ut)
            sessions = hs_tracking.Session.objects.filter(
                Q(begin__gte=start_date) &
                Q(begin__lte=end_date) &
                Q(visitor__user__in=ut_users)
            )
            self.print_var("active_{}".format(ut),
                           sessions.count(), (end_date, start_date))

    def current_users_details(self):
        w = csv.writer(sys.stdout)
        fields = [
            'first name',
            'last name',
            'email',
            'user type',
            'organization',
            'created date',
            'last login',
        ]
        w.writerow(fields)

        for up in UserProfile.objects.filter(user__is_active=True):
            last_login = up.user.last_login.strftime('%m/%d/%Y') if up.user.last_login else ""
            values = [
                up.user.first_name,
                up.user.last_name,
                up.user.email,
                up.user_type,
                up.organization,
                up.user.date_joined.strftime('%m/%d/%Y'),
                last_login,
            ]
            w.writerow([unicode(v).encode("utf-8") for v in values])

    def current_resources_details(self):
        w = csv.writer(sys.stdout)
        fields = [
            'title',
            'resource type',
            'size',
            'federated resource file size',
            'creation date',
            'publication status'
        ]
        w.writerow(fields)

        resources = BaseResource.objects.all()
        for r in resources:
            f_sizes = [f.resource_file.size
                       if f.resource_file else 0
                       for f in r.files.all()]
            total_file_size = sum(f_sizes)
            try:
                f_sizes = [int(f.fed_resource_file_size)
                           if f.fed_resource_file_size else 0
                           for f in r.files.all()]
                federated_resource_file_size = sum()
            except SessionException:
                federated_resource_file_size = "SessionException"
            values = [
                r.metadata.title.value,
                r.resource_type,
                total_file_size,
                federated_resource_file_size,
                r.metadata.dates.get(type="created").start_date.strftime("%m/%d/%Y"),
                r.raccess.sharing_status,
            ]
            w.writerow([unicode(v).encode("utf-8") for v in values])

    def yesterdays_variables(self):
        w = csv.writer(sys.stdout)
        fields = [
            'timestamp',
            'user id',
            'session id',
            'name',
            'type',
            'value',
        ]
        w.writerow(fields)

        today_start = timezone.datetime.now().replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )
        yesterday_start = today_start - datetime.timedelta(days=1)
        variables = hs_tracking.Variable.objects.filter(
            timestamp__gte=yesterday_start,
            timestamp__lt=today_start
        )
        for v in variables:
            uid = v.session.visitor.user.id if v.session.visitor.user else None
            values = [
                v.timestamp,
                uid,
                v.session.id,
                v.name,
                v.type,
                v.value,
            ]
            w.writerow([unicode(v).encode("utf-8") for v in values])

    def handle(self, *args, **options):
        START_YEAR = 2016
        start_date = timezone.datetime(START_YEAR, 1, 1).date()
        end_date = timezone.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if options["monthly-user-counts"]:
            for month_end in month_year_iter(start_date, end_date):
                self.monthly_users_counts(start_date, month_end)
        if options["monthly-orgs-counts"]:
            for month_end in month_year_iter(start_date, end_date):
                self.monthly_orgs_counts(start_date, month_end)
        if options["user-details"]:
            self.current_users_details()
        if options["monthly-users-by-type"]:
            for month_end in month_year_iter(start_date, end_date):
                month_start = timezone.datetime(month_end.year, month_end.month,
                                                1, 0, 0,
                                                tzinfo=timezone.pytz.utc)
                self.monthly_users_by_type(month_start, month_end)
        if options["resource_stats"]:
            self.current_resources_details()
        if options["yesterdays_variables"]:
            self.yesterdays_variables()
