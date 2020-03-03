# Create your views here.
from django.views.generic import TemplateView  # ListView
from hs_core.models import get_user
from hs_core.search_indexes import BaseResourceIndex
from haystack.query import SearchQuerySet
from hs_core.hydroshare.utils import get_resource_by_shortkey
from hs_explore.models import RecommendedResource, Status, PropensityPrefToPair, \
    PropensityPreferences


class RecommendResources(TemplateView):
    """ Get the top five recommendations for resources, users, groups """
    template_name = 'recommended_resources.html'

    def get_context_data(self, **kwargs):

        target_user = get_user(self.request)
        target_username = target_user.username
        action = str(self.request.GET['action'])

        if action == 'update':
            gk = str(self.request.GET['genre_key'])
            gv = str(self.request.GET['genre_value'])
            ind = BaseResourceIndex()

            recommended_recs = RecommendedResource.objects.filter(user=target_user)
            recommended_recs.delete()

            out = SearchQuerySet()
            out = out.filter(recommend_to_users=target_username)
            rpp = PropensityPreferences.objects.get(user=target_user)
            rpp.reject('Resource', gk, gv)
            all_pp = rpp.preferences.all()
            propensity_preferences = PropensityPrefToPair.objects.filter(prop_pref=rpp,
                                                                         pair__in=all_pp,
                                                                         state='Seen',
                                                                         pref_for='Resource')
            target_propensity_preferences_set = set()
            for p in propensity_preferences:
                if p.pair.key == 'subject':
                    target_propensity_preferences_set.add(p.pair.value)

            for thing in out:
                res = get_resource_by_shortkey(thing.short_id)

                subjects = ind.prepare_subject(res)
                subjects = [sub.lower() for sub in subjects]
                intersection_cardinality = len(set.intersection(*[target_propensity_preferences_set,
                                               set(subjects)]))
                union_cardinality = len(set.union(*[target_propensity_preferences_set,
                                        set(subjects)]))
                js2 = intersection_cardinality/float(union_cardinality)
                js = js2

                r1 = RecommendedResource.recommend(target_user, res, 'Propensity', round(js, 4))
                common_subjects = set.intersection(target_propensity_preferences_set,
                                                   set(subjects))
                for cs in common_subjects:
                    r1.relate('subject', cs, 1)

        context = super(RecommendResources, self).get_context_data(**kwargs)

        context['resource_list'] = RecommendedResource.objects\
            .filter(state__lte=Status.STATUS_EXPLORED, user__username=target_username)\
            .order_by('-relevance')[:Status.RECOMMENDATION_LIMIT]

        for r in context['resource_list']:
            if r.state == Status.STATUS_NEW:
                r.shown()

        return context