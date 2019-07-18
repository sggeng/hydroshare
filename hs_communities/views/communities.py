from __future__ import absolute_import

import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.utils.html import mark_safe, escapejs
from django.views.generic import TemplateView

from hs_access_control.management.utilities import community_from_name_or_id
from hs_access_control.models.community import Community
from hs_communities.models import Topic


class CollaborateView(TemplateView):
    template_name = 'pages/collaborate.html'


class CommunityView(TemplateView):
    template_name = 'hs_communities/community.html'

    def dispatch(self, *args, **kwargs):
        return super(CommunityView, self).dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        # user_id = User.objects.get(pk=self.request.user.id)
        grpfilter = self.request.GET.get('grp')

        community_resources = community_from_name_or_id("CZO National Community").public_resources
        groups = []
        for c in community_resources:
            if not any(str(c.group_id) == g.get('id') for g in groups):  # if the group id is not already present in the list
                if c.group_name != "CZO National":  # The National Group is used to establish the entire Community
                    res_count = len([r for r in community_resources if r.group_name == c.group_name])
                    groups.append({'id': str(c.group_id), 'name': str(c.group_name), 'res_count': str(res_count)})

        groups = sorted(groups, key=lambda key: key['name'])
        return {
            'community_resources': community_resources,
            'groups': groups,
            'grpfilter': grpfilter,
        }


class FindCommunitiesView(TemplateView):
    template_name = 'hs_communities/find-communities.html'

    def dispatch(self, *args, **kwargs):
        return super(FindCommunitiesView, self).dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):

        return {
            'communities_list': Community.objects.all()
        }


@method_decorator(login_required, name='dispatch')
class MyCommunitiesView(TemplateView):
    template_name = 'hs_communities/my-communities.html'

    def dispatch(self, *args, **kwargs):
        return super(MyCommunitiesView, self).dispatch(*args, **kwargs)

    def group_to_community(self, grp, C):
        """
        return the community membership information of a group; group can belong to only one community
        :param grp: Group object
        :param C: Community class object
        :return: tuple id, name of community
        """
        for community in C.objects.all():
            if grp.id in [g.id for g in community.member_groups]:
                return (community.id, community.name)

    def get_context_data(self, **kwargs):
        all_communities = Community.objects.all()

        u = User.objects.get(pk=self.request.user.id)
        groups = Group.objects.filter(gaccess__active=True).exclude(name="Hydroshare Author")
        # for each group set group dynamic attributes
        for g in groups:
            g.is_user_member = u in g.gaccess.members
            g.join_request_waiting_owner_action = g.gaccess.group_membership_requests.filter(request_from=u).exists()
            g.join_request_waiting_user_action = g.gaccess.group_membership_requests.filter(invitation_to=u).exists()
            g.join_request = None
            if g.join_request_waiting_owner_action or g.join_request_waiting_user_action:
                g.join_request = g.gaccess.group_membership_requests.filter(request_from=u).first() or \
                                 g.gaccess.group_membership_requests.filter(invitation_to=u).first()

        # comm_groups = Community.objects.all()[0]
        member_of = dict()
        for comm in Community.objects.all():
            if u.id in [m.id for m in comm.member_users] or u.id in [o.id for o in comm.owners]:
                member_of[comm.id] = comm.name

        return {
            'communities_list': all_communities
        }


@method_decorator(login_required, name='dispatch')
class TopicsView(TemplateView):
    """
    TODO log failure and silently redirect to view if missing params

    id:
    name:
    action: CREATE, READ, UPDATE, DELETE
    """

    def get(self, request, *args, **kwargs):
        return render(request, 'pages/topics.html', {'topics_json': self.get_topics_data()})

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') == 'CREATE':
            try:
                new_topic = Topic()
                new_topic.name = request.POST.get('name')
                new_topic.save()
            except Exception as e:
                print("TopicsView error creating new topic {}".format(e))
        elif request.POST.get('action') == 'UPDATE':
            try:
                update_topic = Topic.objects.get(id=request.POST.get('id'))
                update_topic.name = request.POST.get('name')
                update_topic.save()
            except Exception as e:
                print("TopicsView error updating topic {}".format(e))
        elif request.POST.get('action') == 'DELETE':
            try:
                delete_topic = Topic.objects.get(id=request.POST.get('id'))
                delete_topic.delete(keep_parents=False)
            except:
                print("error")
        else:
            print("TopicsView POST action not recognized should be CREATE UPDATE or DELETE")

        return render(request, 'pages/topics.html')

    def get_topics_data(self, **kwargs):
        # u = User.objects.get(pk=self.request.user.id)
        # groups = Group.objects.filter(gaccess__active=True).exclude(name="Hydroshare Author")
        # # for each group set group dynamic attributes
        # for g in groups:
        #     g.is_user_member = u in g.gaccess.members
        #     g.join_request_waiting_owner_action = g.gaccess.group_membership_requests.filter(request_from=u).exists()
        #     g.join_request_waiting_user_action = g.gaccess.group_membership_requests.filter(invitation_to=u).exists()
        #     g.join_request = None
        #     if g.join_request_waiting_owner_action or g.join_request_waiting_user_action:
        #         g.join_request = g.gaccess.group_membership_requests.filter(request_from=u).first() or \
        #                          g.gaccess.group_membership_requests.filter(invitation_to=u).first()

        topics = Topic.objects.all().values_list('id', 'name', flat=False).order_by('name')
        topics = list(topics)  # force QuerySet evaluation
        return mark_safe(escapejs(json.dumps(topics)))
