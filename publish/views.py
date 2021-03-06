# coding:utf8
import json
from datetime import datetime
import time
import requests

from django.shortcuts import render, HttpResponse, render_to_response
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.mail import EmailMultiAlternatives, get_connection, EmailMessage, send_mail
from django.template import Context, loader
from django.db.models import Q

from publish import models
from publish.utils import serialize_instance, cut_str, send_mail_thread
from asset import models as asset_models
from asset import utils as asset_utils
from mico.settings import EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, CMDB_URL
from asynchronous_send_mail import send_mail as async_send_mail


@login_required
def initProject(request):
    page = request.GET.get('page', 1)
    gogroup_objs = asset_models.gogroup.objects.all()
    mailgroup_objs = models.MailGroup.objects.all()
    user_objs = User.objects.filter(is_active=True)
    approver_objs = models.Approver.objects.all()

    project_list = []
    projectinfo_objs = models.ProjectInfo.objects.all().order_by('group__name')
    for projectinfo in projectinfo_objs:
        tmp_dict = {
            'project_id': projectinfo.id,
            'project_name': projectinfo.group.name,
            'owner_list': projectinfo.owner.all().values_list('username', flat=True),
            'mailgroup_list': projectinfo.mail_group.all().values_list('email', flat=True),
            'first_list': projectinfo.first_approver.all().values_list('username', flat=True),
            'second_list': projectinfo.second_approver.all().values_list('username', flat=True),
            'creator': projectinfo.creator.username,
        }
        project_list.append(tmp_dict)

    # 分页
    paginator = Paginator(project_list, 10)
    try:
        final_projectinfo_list = paginator.page(page)
    except PageNotAnInteger:
        final_projectinfo_list = paginator.page(1)
    except EmptyPage:
        final_projectinfo_list = paginator.page(paginator.num_pages)

    return render(request, 'publish/gogroup_init.html',
                  {'gogroup_objs': gogroup_objs, 'mailgroup_objs': mailgroup_objs, 'user_objs': user_objs, 'approver_objs': approver_objs,
                   'project_list': final_projectinfo_list})


@login_required
def createProject(request):
    user = request.user
    ip = request.META['REMOTE_ADDR']
    project_select_list = request.POST.getlist('project_select_list')
    project_id_list = [int(project_id) for project_id in project_select_list]
    owner_select_list = request.POST.getlist('owner_select_list')
    owner_list = [int(i) for i in owner_select_list]
    first_select_list = request.POST.getlist('first_select_list')
    first_list = [int(i) for i in first_select_list if i]
    second_select_list = request.POST.getlist('second_select_list')
    second_list = [int(i) for i in second_select_list if i]
    mailgroup_select_list = request.POST.getlist('mailgroup_select_list')
    mailgroup_list = [int(i) for i in mailgroup_select_list if i]

    errcode = 0
    msg = 'ok'

    gogroup_objs = asset_models.gogroup.objects.filter(id__in=project_id_list)
    if len(gogroup_objs) == 0:
        errcode = 500
        msg = u'所选项目不存在'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        for gogroup_obj in gogroup_objs:
            try:
                project_obj = models.ProjectInfo.objects.get(group=gogroup_obj)
            except models.ProjectInfo.DoesNotExist:
                project_obj = models.ProjectInfo.objects.create(group=gogroup_obj, creator=user)
                for owner in owner_list:
                    project_obj.owner.add(owner)

                if first_list:
                    for first in first_list:
                        project_obj.first_approver.add(first)

                if second_list:
                    for second in second_list:
                        project_obj.second_approver.add(second)

                if mailgroup_list:
                    for mailgroup in mailgroup_list:
                        project_obj.mail_group.add(mailgroup)

                log_res = 'Successfully create Initialization Info of gogroup : {0}'.format(project_obj.group.name)
                asset_utils.logs(user.username, ip, 'create Initialization Info', log_res)

            else:
                print 'already exist'
                errcode = 500
                msg = project_obj.group.name + u'项目初始化信息已存在'
                data = dict(code=errcode, msg=msg)
                return HttpResponse(json.dumps(data), content_type='application/json')

        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def projectDelete(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    projectinfo_id = int(request.POST['projectinfo_id'])

    try:
        project_obj = models.ProjectInfo.objects.get(id=projectinfo_id)
    except models.ProjectInfo.DoesNotExist:
        errcode = 500
        msg = u'所选项目初始化信息不存在'
    else:
        try:
            project_obj.creator
        except:
            project_obj.creator = None
            project_obj.save()

        if user == project_obj.creator:
            project_obj.delete()
            log_res = 'Successfully delete Initialization Info of gogroup : {0}'.format(project_obj.group.name)
            asset_utils.logs(user.username, ip, 'delete Initialization Info', log_res)
        else:
            owner_list = project_obj.owner.all()
            if user in owner_list:
                log_res = 'Successfully delete Initialization Info of gogroup : {0}'.format(project_obj.group.name)
                asset_utils.logs(user.username, ip, 'delete Initialization Info', log_res)
                project_obj.delete()
            else:
                errcode = 500
                msg = u'你不是此项目的负责人，不能删除'

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def LevelList(request):
    page = request.GET.get('page', 1)

    project_objs = models.ProjectInfo.objects.all().order_by('group__name')

    timeslot_objs = models.TimeSlotLevel.objects.filter().order_by('-is_global', 'approval_level__name',
                                                                   'start_of_week', 'end_of_week', 'start_time',
                                                                   'end_time')
    level_list = []
    for timeslot in timeslot_objs:
        project_list = timeslot.project_timeslotlevel.all().order_by('group__name')
        if project_list:
            level_list.append(
                {'timeslot': timeslot, 'project_list': project_list, 'creator': timeslot.creator.username})

    # 分页
    paginator = Paginator(level_list, 10)
    try:
        final_level_list = paginator.page(page)
    except PageNotAnInteger:
        final_level_list = paginator.page(1)
    except EmptyPage:
        final_level_list = paginator.page(paginator.num_pages)
    return render(request, 'publish/level_list.html', {'level_list': final_level_list, 'project_objs': project_objs})


@login_required
def LevelDetail(request):
    errcode = 0
    msg = 'ok'
    content = {}

    timeslot_id = int(request.GET['timeslot_id'])

    try:
        timeslot_obj = models.TimeSlotLevel.objects.get(id=timeslot_id)
    except models.TimeSlotLevel.DoesNotExist:
        errcode = 500
        msg = u'所选等级不存在'
    else:
        content['level_type'] = timeslot_obj.get_is_global_display()
        content['creator'] = timeslot_obj.creator.username
        content[
            'time'] = timeslot_obj.get_start_of_week_display() + ' ~ ' + timeslot_obj.get_end_of_week_display() + ' ' + timeslot_obj.start_time + ' ~ ' + timeslot_obj.end_time
        content['approval_level'] = timeslot_obj.approval_level.get_name_display()
        approval_level = timeslot_obj.approval_level.name
        content['project_list'] = []
        project_objs = timeslot_obj.project_timeslotlevel.all().order_by('group__name')
        for projectinfo in project_objs:
            if approval_level == '1':
                first_list = []
                second_list = []
            elif approval_level == '2':
                first_list = projectinfo.first_approver.all().values_list('username', flat=True)
                second_list = []
            else:
                first_list = projectinfo.first_approver.all().values_list('username', flat=True)
                second_list = projectinfo.second_approver.all().values_list('username', flat=True)
            tmp_dict = {
                'project_name': projectinfo.group.name,
                'owner_list': projectinfo.owner.all().values_list('username', flat=True),
                'mailgroup_list': projectinfo.mail_group.all().values_list('email', flat=True),
                'first_list': first_list,
                'second_list': second_list,
            }
            content['project_list'].append(tmp_dict)

    data = dict(code=errcode, msg=msg, content=content)
    return render_to_response('publish/level_detail_modal.html', data)


@login_required
def LevelCreate(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']

    radio = request.POST['radio']
    level_list = request.POST.getlist('level_list')
    project_select_list = request.POST.getlist('project_select_list')
    project_id_list = [int(project_id) for project_id in project_select_list]
    project_objs = models.ProjectInfo.objects.filter(id__in=project_id_list)

    if len(project_objs) == 0:
        errcode = 500
        msg = u'所选项目初始化信息不存在'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        for project_obj in project_objs:
            first_approver_objs = project_obj.first_approver.all()
            second_approver_objs = project_obj.second_approver.all()
            if radio == '1':
                print 'radio 1'
                old_time_objs = project_obj.timeslot_level.all()
                for level_str in level_list:
                    level = level_str.strip().split(',')
                    start_of_week = level[0]
                    end_of_week = level[1]
                    start_time = level[2]
                    end_time = level[3]
                    approval_level = level[4]

                    if approval_level == '2' and not first_approver_objs:
                        errcode = 500
                        msg = u'项目 {0} 无一级审批人'.format(project_obj.group.name)
                        data = dict(code=errcode, msg=msg)
                        res_log = 'Failed to create Approve Level of gogroup : {0}. Reason: no first approver'.format(
                            project_obj.group.name)
                        asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
                        return HttpResponse(json.dumps(data), content_type='application/json')
                    if approval_level == '3' and not second_approver_objs:
                        errcode = 500
                        msg = u'项目 {0} 无二级审批人'.format(project_obj.group.name)
                        data = dict(code=errcode, msg=msg)
                        res_log = 'Failed to create Approve Level of gogroup : {0}. Reason: no second approver'.format(
                            project_obj.group.name)
                        asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
                        return HttpResponse(json.dumps(data), content_type='application/json')

                    try:
                        approval_level_obj = models.ApprovalLevel.objects.get(name=approval_level)
                    except models.ApprovalLevel.DoesNotExist:
                        errcode = 500
                        msg = u'所选审批级别不存在'
                        data = dict(code=errcode, msg=msg)
                        return HttpResponse(json.dumps(data), content_type='application/json')
                    else:
                        time_obj = models.TimeSlotLevel.objects.get_or_create(start_of_week=start_of_week,
                                                                              end_of_week=end_of_week,
                                                                              start_time=start_time,
                                                                              end_time=end_time,
                                                                              approval_level=approval_level_obj,
                                                                              creator=user)
                        if time_obj not in old_time_objs:
                            project_obj.timeslot_level.add(time_obj[0])
                            res_log = 'Successfully create Approve Level of gogroup: {0}'.format(project_obj.group.name)
                            asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
            else:
                print 'radio 2'
                old_time_objs = project_obj.timeslot_level.all()
                timeslot_id_list = [int(level_id) for level_id in level_list]
                time_objs = models.TimeSlotLevel.objects.filter(id__in=timeslot_id_list)
                for time_obj in time_objs:
                    if time_obj.approval_level.name == '2' and not first_approver_objs:
                        errcode = 500
                        msg = u'项目 {0} 无一级审批人'.format(project_obj.group.name)
                        data = dict(code=errcode, msg=msg)
                        res_log = 'Failed to create Approve Level of gogroup : {0}. Reason: no first approver'.format(
                            project_obj.group.name)
                        asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
                        return HttpResponse(json.dumps(data), content_type='application/json')
                    if time_obj.approval_level.name == '3' and not second_approver_objs:
                        errcode = 500
                        msg = u'项目 {0} 无二级审批人'.format(project_obj.group.name)
                        data = dict(code=errcode, msg=msg)
                        res_log = 'Failed to create Approve Level of gogroup : {0}. Reason: no second approver'.format(
                            project_obj.group.name)
                        asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
                        return HttpResponse(json.dumps(data), content_type='application/json')

                    print 'LevelCreate--time_obj : ', time_obj
                    if time_obj not in old_time_objs:
                        print 'LevelCreate--add'
                        res_log = 'Successfully create Approve Level of gogroup: {0}'.format(project_obj.group.name)
                        asset_utils.logs(user.username, ip, 'create Approve Level', res_log)
                        project_obj.timeslot_level.add(time_obj)

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def LevelDelete(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    timeslot_id = int(request.POST['timeslot_id'])
    print 'LevelDelete---timeslot_id : ', timeslot_id

    try:
        timeslot_obj = models.TimeSlotLevel.objects.get(id=timeslot_id)
    except models.TimeSlotLevel.DoesNotExist:
        errcode = 500
        msg = u'所选项目审批级别不存在'
    else:
        # 删除项目审批级别
        projectinfo_objs = timeslot_obj.project_timeslotlevel.all()

        for projectinfo in projectinfo_objs:
            # print projectinfo
            # print projectinfo.creator
            # print user
            # if projectinfo.creator == user:
            #     print 'project info creator == user'
            projectinfo.timeslot_level.remove(timeslot_obj)
            res_log = 'Successfully delete Approve Level of gogroup : {0}'.format(projectinfo.group.name)
            asset_utils.logs(user.username, ip, 'delete Approve Level', res_log)

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def templateList(request):
    page = request.GET.get('page', 1)
    timeslot_objs = models.TimeSlotLevel.objects.filter(is_global='2').order_by('approval_level__name', 'start_of_week',
                                                                                'end_of_week', 'start_time', 'end_time')
    # 分页
    paginator = Paginator(timeslot_objs, 10)
    try:
        final_level_list = paginator.page(page)
    except PageNotAnInteger:
        final_level_list = paginator.page(1)
    except EmptyPage:
        final_level_list = paginator.page(paginator.num_pages)
    return render(request, 'publish/template_list.html', {'timeslot_objs': final_level_list})


@login_required
def templateCheckboxList(request):
    timeslot_objs = models.TimeSlotLevel.objects.filter(is_global='2').order_by('approval_level__name', 'start_of_week',
                                                                                'end_of_week', 'start_time', 'end_time')
    return render(request, 'publish/template_checbox.html', {'timeslot_objs': timeslot_objs})


@login_required
def templateCreate(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    weekday_start = request.POST['weekday_start']
    weekday_end = request.POST['weekday_end']
    time_start = request.POST['time_start']
    time_end = request.POST['time_end']
    level = request.POST['level']

    try:
        level_obj = models.ApprovalLevel.objects.get(name=level)
    except models.ApprovalLevel.DoesNotExist:
        errcode = 500
        msg = u'所选等级不存在'
    else:
        try:
            time_obj = models.TimeSlotLevel.objects.get(start_of_week=weekday_start, end_of_week=weekday_end,
                                                        start_time=time_start, end_time=time_end,
                                                        approval_level=level_obj, is_global='2')
        except models.TimeSlotLevel.DoesNotExist:
            time_obj = models.TimeSlotLevel.objects.create(start_of_week=weekday_start, end_of_week=weekday_end,
                                                           start_time=time_start, end_time=time_end,
                                                           approval_level=level_obj, is_global='2',
                                                           creator=user)
            res_log = 'Successfully create Approve Level Template of level : {0}'.format(level_obj.get_name_display())
            asset_utils.logs(user.username, ip, 'create Approve Level Template', res_log)
            print 'create template ok : ', time_obj.id
        else:
            errcode = 500
            msg = u'相同【时间段<--->级别】已存在'

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


def templateDelete(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    timeslot_id = int(request.POST['timeslot_id'])

    try:
        timeslot_obj = models.TimeSlotLevel.objects.get(id=timeslot_id)
    except models.TimeSlotLevel.DoesNotExist:
        errcode = 500
        msg = u'所选【时间段<--->级别】不存在'
    else:
        if timeslot_obj.creator:
            if timeslot_obj.creator == user:
                res_log = 'Successfully delete Approve Level Template of level : {0}'.format(
                    timeslot_obj.approval_level.get_name_display())
                asset_utils.logs(user.username, ip, 'delete Approve Level Template', res_log)
                timeslot_obj.delete()
            else:
                errcode = 500
                msg = u'你不是创建人，不能删除'
        else:
            res_log = 'Successfully delete Approve Level Template of level : {0}'.format(
                timeslot_obj.approval_level.get_name_display())
            asset_utils.logs(user.username, ip, 'delete Approve Level Template', res_log)
            timeslot_obj.delete()

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def PublishSheetList(request):
    page_1 = request.GET.get('page_1', 1)
    page_2 = request.GET.get('page_2', 1)
    page_3 = request.GET.get('page_3', 1)
    errcode = 0
    msg = 'ok'
    user = request.user
    publishsheets = models.PublishSheet.objects.filter(Q(status='1') | Q(status='2') | Q(status='3')).order_by(
        'publish_date', 'publish_time')

    tobe_approved_list = []
    approve_refused_list = []
    approve_passed_list = []
    for publish in publishsheets:
        services_objs = publish.goservices.all()
        services_1 = services_objs[0]
        ser_list = services_objs.order_by('name').values_list('name', flat=True).distinct()
        services_str = ', '.join(sorted(list(set(ser_list))))
        env = services_1.get_env_display()
        gogroup_obj = services_1.group
        level = publish.approval_level.get_name_display()
        approve_level = publish.approval_level.name
        if approve_level == '1':
            first_str = ''
            second_str = ''
        elif approve_level == '2':
            first_list = publish.first_approver.all().values_list('username', flat=True)
            first_str = ', '.join(first_list)
            second_str = ''
        else:
            first_list = publish.first_approver.all().values_list('username', flat=True)
            first_str = ', '.join(first_list)
            second_list = publish.second_approver.all().values_list('username', flat=True)
            second_str = ', '.join(second_list)

        tmp_dict = serialize_instance(publish)

        if len(publish.sql_before) > 40:
            tmp_dict['sql_before'] = cut_str(publish.sql_before, 40)
        if len(publish.sql_after) > 40:
            tmp_dict['sql_after'] = cut_str(publish.sql_after, 40)
        if len(publish.consul_key) > 40:
            tmp_dict['consul_key'] = cut_str(publish.consul_key, 40)

        tmp_dict.update({'id': publish.id, 'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env,
                         'approve_level': approve_level, 'level': level, 'first_str': first_str,
                         'second_str': second_str, 'creator': publish.creator.username})

        tmp_dict['can_publish'] = False

        # 判断是否超时
        publish_datetime_str = publish.publish_date + ' ' + publish.publish_time
        publish_datetime_format = time.strptime(publish_datetime_str, '%Y-%m-%d %H:%M')
        publish_datetime_int = time.mktime(publish_datetime_format)
        now_int = time.time()
        if publish_datetime_int <= now_int:
            if publish.status == '4' or publish.status == '5' or publish.status == '6':
                pass
            elif publish.status == '2':
                tmp_dict['can_publish'] = False
                approve_refused_list.append(tmp_dict)
            else:
                # 超时
                if publish.status == '1':
                    # 状态为审批中
                    # print 'publish.id : ', publish.id
                    if publish.approval_level.name == '1':
                        # 无需审批的单子
                        if publish_datetime_int + 3600 < now_int:
                            # 超时15分钟未发布
                            publish.status = '5'
                            publish.save()
                        else:
                            # print 'here----can_publish'
                            # 超时15分钟之内，可以发布
                            tmp_dict['can_publish'] = True
                            if tmp_dict['can_publish'] and user == publish.creator:
                                tmp_dict['can_publish'] = True
                            else:
                                tmp_dict['can_publish'] = False
                            approve_passed_list.append(tmp_dict)
                    else:
                        # 一级审批和二级审批的单子，超时未审批
                        publish.status = '6'
                        publish.save()
                else:
                    # 状态为审批通过
                    if publish.approval_level.name == '2':
                        # 一级审批
                        if publish_datetime_int + 3600 < now_int:
                            # 超时15分钟未发布
                            publish.status = '5'
                            publish.save()
                        else:
                            # 超时15分钟之内，可以发布
                            tmp_dict['can_publish'] = True
                            if tmp_dict['can_publish'] and user == publish.creator:
                                tmp_dict['can_publish'] = True
                            else:
                                tmp_dict['can_publish'] = False
                            approve_passed_list.append(tmp_dict)
                    else:
                        # 二级审批
                        try:
                            history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=publish)
                        except models.PublishApprovalHistory.DoesNotExist:
                            errcode = 500
                            msg = u'审批历史不存在'
                        else:
                            if history_obj.approve_count == '1':
                                # 第二级审批人，超时未审批
                                publish.status = '6'
                                publish.save()
                            else:
                                if publish_datetime_int + 3600 < now_int:
                                    # 超时15分钟未发布
                                    publish.status = '5'
                                    publish.save()
                                else:
                                    # 超时15分钟之内，可以发布
                                    tmp_dict['can_publish'] = True
                                    if tmp_dict['can_publish'] and user == publish.creator:
                                        tmp_dict['can_publish'] = True
                                    else:
                                        tmp_dict['can_publish'] = False
                                    approve_passed_list.append(tmp_dict)

        else:
            tmp_dict['can_publish'] = False
            if publish.approval_level.name == '1':
                # 无需审批
                approve_passed_list.append(tmp_dict)
            elif publish.approval_level.name == '2':
                # 一级审批
                if publish.status == '1':
                    tobe_approved_list.append(tmp_dict)
                elif publish.status == '2':
                    approve_refused_list.append(tmp_dict)
                elif publish.status == '3':
                    approve_passed_list.append(tmp_dict)
            else:
                # 二级审批
                if publish.status == '1':
                    tobe_approved_list.append(tmp_dict)
                elif publish.status == '2':
                    approve_refused_list.append(tmp_dict)
                elif publish.status == '3':
                    # 判断一级审批完成还是二级审批完成
                    try:
                        history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=publish)
                    except models.PublishApprovalHistory.DoesNotExist:
                        errcode = 500
                        msg = u'审批历史不存在'
                    else:
                        if history_obj.approve_count == '1':
                            tobe_approved_list.append(tmp_dict)
                        else:
                            approve_passed_list.append(tmp_dict)

    # 分页
    paginator1 = Paginator(tobe_approved_list, 10)
    try:
        tobe_approved_list = paginator1.page(page_1)
    except PageNotAnInteger:
        tobe_approved_list = paginator1.page(1)
    except EmptyPage:
        tobe_approved_list = paginator1.page(paginator1.num_pages)

    paginator2 = Paginator(approve_refused_list, 10)
    try:
        approve_refused_list = paginator2.page(page_2)
    except PageNotAnInteger:
        approve_refused_list = paginator2.page(1)
    except EmptyPage:
        approve_refused_list = paginator2.page(paginator2.num_pages)

    paginator3 = Paginator(approve_passed_list, 10)
    try:
        approve_passed_list = paginator3.page(page_3)
    except PageNotAnInteger:
        approve_passed_list = paginator3.page(1)
    except EmptyPage:
        approve_passed_list = paginator3.page(paginator3.num_pages)
    data = dict(code=errcode, msg=msg, tobe_approved_list=tobe_approved_list, approve_refused_list=approve_refused_list,
                approve_passed_list=approve_passed_list)

    return render(request, 'publish/publish_sheets_list.html', data)


@login_required
def PublishSheetDoneList(request):
    # 已完成 & 超时未审批 & 超时未发布的发布单
    page_1 = request.GET.get('page_1', 1)
    page_2 = request.GET.get('page_2', 1)
    page_3 = request.GET.get('page_3', 1)
    publishsheets = models.PublishSheet.objects.filter(Q(status='4') | Q(status='5') | Q(status='6')).order_by(
        '-publish_date', '-publish_time')

    done_list = []
    outtime_notpublish_list = []
    outtime_notapprove_list = []
    for publish in publishsheets:
        services_objs = publish.goservices.all().order_by('name')
        ser_list = services_objs.values_list('name', flat=True).distinct()
        services_str = ', '.join(sorted(list(set(ser_list))))
        services_1 = services_objs[0]
        env = services_1.get_env_display()
        gogroup_obj = services_1.group
        level = publish.approval_level.get_name_display()
        approve_level = publish.approval_level.name

        if approve_level == '1':
            first_str = ''
            second_str = ''
        elif approve_level == '2':
            first_list = publish.first_approver.all().values_list('username', flat=True)
            first_str = ', '.join(first_list)
            second_str = ''
        else:
            first_list = publish.first_approver.all().values_list('username', flat=True)
            first_str = ', '.join(first_list)
            second_list = publish.second_approver.all().values_list('username', flat=True)
            second_str = ', '.join(second_list)

        tmp_dict = serialize_instance(publish)
        if len(publish.sql_before) > 40:
            tmp_dict['sql_before'] = cut_str(publish.sql_before, 40)
        if len(publish.sql_after) > 40:
            tmp_dict['sql_after'] = cut_str(publish.sql_after, 40)
        if len(publish.consul_key) > 40:
            tmp_dict['consul_key'] = cut_str(publish.consul_key, 40)
        tmp_dict.update(
            {'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env, 'approve_level': approve_level,
             'level': level, 'first_str': first_str, 'second_str': second_str, 'creator': publish.creator.username})

        if publish.status == '4':
            done_list.append(tmp_dict)
        elif publish.status == '5':
            outtime_notpublish_list.append(tmp_dict)
        elif publish.status == '6':
            outtime_notapprove_list.append(tmp_dict)
        else:
            pass

    errcode = 0
    msg = 'ok'
    # 分页
    paginator1 = Paginator(done_list, 10)
    try:
        final_done_list = paginator1.page(page_1)
    except PageNotAnInteger:
        final_done_list = paginator1.page(1)
    except EmptyPage:
        final_done_list = paginator1.page(paginator1.num_pages)

    paginator2 = Paginator(outtime_notpublish_list, 10)
    try:
        final_outtime_notpublish_list = paginator2.page(page_3)
    except PageNotAnInteger:
        final_outtime_notpublish_list = paginator2.page(1)
    except EmptyPage:
        final_outtime_notpublish_list = paginator2.page(paginator2.num_pages)

    paginator3 = Paginator(outtime_notapprove_list, 10)
    try:
        final_outtime_notapprove_list = paginator3.page(page_2)
    except PageNotAnInteger:
        final_outtime_notapprove_list = paginator3.page(1)
    except EmptyPage:
        final_outtime_notapprove_list = paginator3.page(paginator3.num_pages)

    data = dict(code=errcode, msg=msg, done_list=final_done_list,
                outtime_notapprove_list=final_outtime_notapprove_list,
                outtime_notpublish_list=final_outtime_notpublish_list)

    return render(request, 'publish/publish_done.html', data)


@login_required
def PublishSheetRefuseReason(request):
    errcode = 0
    msg = 'ok'
    content = {}

    sheet_id = int(request.GET['sheet_id'])

    try:
        sheet_obj = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'所选发布单不存在'
    else:
        try:
            sheet_history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=sheet_obj, approve_status=2)
        except models.PublishApprovalHistory.DoesNotExist:
            errcode = 500
            msg = u'所选发布单审批记录不存在'
        else:
            content['approve_count'] = sheet_history_obj.approve_count
            if sheet_obj.approval_level.name == '2':
                # 一级审批, 被拒绝
                content['first_approver'] = sheet_history_obj.first_approver.username
                content['first_approve_time'] = sheet_history_obj.first_approve_time
                content['refuse_reason'] = sheet_history_obj.refuse_reason
            else:
                # 二级审批
                if sheet_history_obj.approve_count == '1':
                    # 一级审批被拒绝
                    content['first_approver'] = sheet_history_obj.first_approver.username
                    content['first_approve_time'] = sheet_history_obj.first_approve_time
                    content['refuse_reason'] = sheet_history_obj.refuse_reason
                else:
                    # 二级审批被拒绝
                    content['first_approver'] = sheet_history_obj.first_approver.username
                    content['first_approve_time'] = sheet_history_obj.first_approve_time
                    content['second_approver'] = sheet_history_obj.second_approver.username
                    content['second_approve_time'] = sheet_history_obj.second_approve_time
                    content['refuse_reason'] = sheet_history_obj.refuse_reason

    data = dict(code=errcode, msg=msg, content=content)
    return render_to_response('publish/publish_sheet_refusereason.html', data)


@login_required()
def createPublishSheetInit(request):
    gogroup_objs = asset_models.gogroup.objects.all()
    user_objs = User.objects.filter(is_active=True)
    return render(request, 'publish/publish_create.html', {'gogroup_objs': gogroup_objs, 'user_objs': user_objs})


@login_required
def createPublishSheet(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    project_name = request.POST['project_name']
    env_id = request.POST['env_id']
    tapd_url = request.POST['tapd_url']
    reboot_services_list = request.POST.getlist('reboot_services_list', [])
    sql_before = request.POST['sql_before']
    sql_after = request.POST['sql_after']
    consul_key = request.POST['consul_key']
    publish_date = request.POST['publish_date']
    qa_list = request.POST.getlist('qa_list', [])
    if_review = request.POST['if_review']
    review_list = request.POST.getlist('review_list', [])
    if_browse = request.POST['if_browse']
    if_order = request.POST['if_order']
    if_buy = request.POST['if_buy']
    reason = request.POST['reason']
    comment = request.POST['comment']

    if '/' in publish_date:
        publish_date = '-'.join(publish_date.split('/'))

    publish_time = request.POST['publish_time']

    try:
        gogroup_obj = asset_models.gogroup.objects.get(name=project_name)
    except asset_models.gogroup.DoesNotExist:
        errcode = 500
        msg = u'go项目不存在'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        try:
            projectinfo_obj = models.ProjectInfo.objects.get(group=gogroup_obj)
        except models.ProjectInfo.DoesNotExist:
            print 'no project_info of this gogroup: ', project_name
            projectinfo_obj = None

        init_approval_level = models.ApprovalLevel.objects.get(name='1')
        approval_level = ''
        slot = False  # 是否有级别定义

        publishsheet_obj = models.PublishSheet()
        publishsheet_obj.creator = user
        publishsheet_obj.tapd_url = tapd_url
        publishsheet_obj.publish_date = publish_date
        publishsheet_obj.publish_time = publish_time
        publishsheet_obj.sql_before = sql_before
        publishsheet_obj.sql_after = sql_after
        publishsheet_obj.consul_key = consul_key
        publishsheet_obj.status = '1'
        publishsheet_obj.if_review = if_review
        publishsheet_obj.if_browse = if_browse
        publishsheet_obj.if_order = if_order
        publishsheet_obj.if_buy = if_buy
        publishsheet_obj.reason = reason

        if comment.strip():
            publishsheet_obj.comment = comment.strip()

        # 查看节假日时间段，二级审批
        festival_objs = models.Festival.objects.all()
        if len(festival_objs) > 0:
            for festival_obj in festival_objs:
                publish_time_format = time.strptime(str(publish_date) + ' ' + str(publish_time), '%Y-%m-%d %H:%M')
                publish_time_int = time.mktime(publish_time_format)
                start_time_format = time.strptime(festival_obj.start_day.strftime("%Y-%m-%d %H:%M"), '%Y-%m-%d %H:%M')
                start_time_int = time.mktime(start_time_format)
                if festival_obj.end_day:
                    end_time_format = time.strptime(festival_obj.end_day.strftime("%Y-%m-%d %H:%M"), '%Y-%m-%d %H:%M')
                    end_time_int = time.mktime(end_time_format)
                else:
                    end_time_int = start_time_int + 86400

                if start_time_int <= publish_time_int <= end_time_int:
                    approval_level = models.ApprovalLevel.objects.get(name='3')
                    print 'festival done'
                    slot = True
                    break

        publish_week = datetime.strptime(publish_date, '%Y-%m-%d').isoweekday()
        # 查看通用模板时间段
        template_objs = models.TimeSlotLevel.objects.filter(is_global='2')
        if len(template_objs) > 0:
            for template_obj in template_objs:
                start_week_int = int(template_obj.start_of_week)
                end_week_int = int(template_obj.end_of_week)
                # print 'publish_week : ', publish_week
                # print 'start_week_int : ', start_week_int
                # print 'end_week_int : ', end_week_int
                if start_week_int <= publish_week <= end_week_int:
                    publish_time_format = time.strptime(str(publish_date) + ' ' + str(publish_time), '%Y-%m-%d %H:%M')
                    start_time_format = time.strptime(str(publish_date) + ' ' + str(template_obj.start_time),
                                                      '%Y-%m-%d %H:%M')
                    end_time_format = time.strptime(str(publish_date) + ' ' + str(template_obj.end_time),
                                                    '%Y-%m-%d %H:%M')
                    publish_time_int = time.mktime(publish_time_format)
                    start_time_int = time.mktime(start_time_format)
                    end_time_int = time.mktime(end_time_format)
                    if end_time_int <= start_time_int:
                        end_time_int = end_time_int + 86400
                    # print 'publish_time_int : ', publish_time_int
                    # print 'start_time_int : ', start_time_int
                    # print 'end_time_int : ', end_time_int
                    if start_time_int <= publish_time_int <= end_time_int:
                        print 'template ok : ', template_obj.approval_level.get_name_display()
                        approval_level = template_obj.approval_level
                        slot = True
                        break

        if not slot:
            # 查看自定义模板时间段
            if projectinfo_obj:
                custom_objs = projectinfo_obj.timeslot_level.all()
                if len(custom_objs) > 0:
                    for custom_obj in custom_objs:
                        start_week_int = int(custom_obj.start_of_week)
                        end_week_int = int(custom_obj.end_of_week)
                        if start_week_int <= publish_week <= end_week_int:
                            publish_time_format = time.strptime(str(publish_date) + ' ' + str(publish_time),
                                                                '%Y-%m-%d %H:%M')
                            start_time_format = time.strptime(str(publish_date) + ' ' + str(custom_obj.start_time),
                                                              '%Y-%m-%d %H:%M')
                            end_time_format = time.strptime(str(publish_date) + ' ' + str(custom_obj.end_time),
                                                            '%Y-%m-%d %H:%M')
                            publish_time_int = time.mktime(publish_time_format)
                            start_time_int = time.mktime(start_time_format)
                            end_time_int = time.mktime(end_time_format)
                            if end_time_int <= start_time_int:
                                end_time_int = end_time_int + 86400
                            if start_time_int <= publish_time_int <= end_time_int:
                                approval_level = custom_obj.approval_level
                                print 'custom ok : ', custom_obj.approval_level.get_name_display()
                                slot = True
                                break

        if slot:
            # print 'if slot'
            if approval_level:
                # print 'if approval_level'
                if approval_level != init_approval_level:
                    # print 'if !='
                    if not reason:
                        errcode = 500
                        msg = u'{0}，请填写紧急发布原因'.format(approval_level.get_name_display())
                        data = dict(code=errcode, msg=msg)
                        return HttpResponse(json.dumps(data), content_type='application/json')
        else:
            # print 'else'
            approval_level = init_approval_level

        publishsheet_obj.approval_level = approval_level
        publishsheet_obj.save()
        res_log = 'Successfully create Publish Sheet, id : {0}, gogroup: {1}'.format(publishsheet_obj.id,
                                                                                     gogroup_obj.name)
        asset_utils.logs(user.username, ip, 'create Publish Sheet', res_log)
        print '^^^^^save publishsheet_obj ok，id ----', publishsheet_obj.id

        if projectinfo_obj:
            # 添加审批人
            publishsheet_obj.first_approver = projectinfo_obj.first_approver.all()
            publishsheet_obj.second_approver = projectinfo_obj.second_approver.all()

        goservices_objs = asset_models.goservices.objects.filter(env=env_id).filter(name__in=reboot_services_list,
                                                                                    group=gogroup_obj)
        for goservice in goservices_objs:
            publishsheet_obj.goservices.add(goservice)

        qa_id_list = [int(qa_id) for qa_id in qa_list]
        qa_objs = User.objects.filter(id__in=qa_id_list)
        for qa_obj in qa_objs:
            publishsheet_obj.qa.add(qa_obj)

        if if_review == '1':
            review_id_list = [int(qa_id) for qa_id in review_list]
            reviewer_objs = User.objects.filter(id__in=review_id_list)
            for reviewer_obj in reviewer_objs:
                publishsheet_obj.reviewer.add(reviewer_obj)

        subject = u'cmdb发布系统'
        ser_list = goservices_objs.order_by('name').values_list('name', flat=True).distinct()
        services_str = ', '.join(sorted(list(set(ser_list))))
        env = goservices_objs[0].get_env_display()
        sheet_dict = {
            'services_str': services_str,
            'gogroup': project_name,
            'creator': user.username,
            'env': env,
            'approval_level': approval_level.get_name_display(),
            'id': publishsheet_obj.id,
            'publish_date': publishsheet_obj.publish_date,
            'publish_time': publishsheet_obj.publish_time,
            'reason': publishsheet_obj.reason,
        }
        if publishsheet_obj.approval_level.name != '1':
            if projectinfo_obj:
                # 发邮件给一级审批人
                to_list = [approver.email for approver in publishsheet_obj.first_approver.all() if approver.email]
                content = {
                    'title': subject,
                    'sheet': sheet_dict,
                    'head_content': u'请审批发布单',
                    'can_approve': '1',
                    'cmdb_url': CMDB_URL,
                }
                email_template_name = 'email/publish_sheet.html'
                email_content = loader.render_to_string(email_template_name, content)
                async_send_mail(subject, '', EMAIL_HOST_USER, to_list, fail_silently=False, html=email_content)
                # url = CMDB_URL + 'asset/project/send/email/'
                # params = {
                #     'sheet_id': publishsheet_obj.id,
                #     'head_content': u'请审批发布单',
                #     'to': to_list,
                #     'can_approve': '1'
                # }
                # r = requests.get(url, params)
                # if r.status_code != 200:
                #     errcode = 500
                #     msg = u'给一级审批人的邮件发送失败'

                # 发邮件给项目的邮件组
                if projectinfo_obj.mail_group.all():
                    to_list = [approver.email for approver in projectinfo_obj.mail_group.all() if approver.email]
                    content = {
                        'title': subject,
                        'sheet': sheet_dict,
                        'head_content': u'新增发布单',
                        'can_approve': '2',
                        'cmdb_url': CMDB_URL,
                    }
                    email_template_name = 'email/publish_sheet.html'
                    email_content = loader.render_to_string(email_template_name, content)
                    async_send_mail(subject, '', EMAIL_HOST_USER, to_list, fail_silently=False, html=email_content)
                    # url = CMDB_URL + 'asset/project/send/email/'
                    # params = {
                    #     'sheet_id': publishsheet_obj.id,
                    #     'head_content': u'新增发布单',
                    #     'to': to_list,
                    #     'can_approve': '2'
                    # }
                    # r = requests.get(url, params)
                    # if r.status_code != 200:
                    #     errcode = 500
                    #     msg = u'给通知邮件组的邮件发送失败'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def PublishSheetDelete(request):
    errcode = 0
    msg = 'ok'
    user = request.user
    ip = request.META['REMOTE_ADDR']
    sheet_id = int(request.POST['sheet_id'])

    try:
        publish_obj = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'所选发布单不存在'
    else:
        if publish_obj.creator:
            if publish_obj.creator == user:
                publish_obj.delete()
                project_name = publish_obj.goservices.all()[0].group.name
                res_log = 'Successfully delete Publish Sheet, id : {0}, gogroup: {1}'.format(publish_obj.id,
                                                                                             project_name)
                asset_utils.logs(user.username, ip, 'delete Publish Sheet', res_log)
            else:
                errcode = 500
                msg = u'你不是创建人，不能删除'
        else:
            print 'no creator'
            publish_obj.delete()
            project_name = publish_obj.goservices.all()[0].group.name
            res_log = 'Successfully delete Publish Sheet, id : {0}, gogroup: {1}'.format(publish_obj.id, project_name)
            asset_utils.logs(user.username, ip, 'delete Publish Sheet', res_log)

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def ApproveList(request):
    page_1 = request.GET.get('page_1', 1)
    page_2 = request.GET.get('page_2', 1)
    page_3 = request.GET.get('page_3', 1)
    user = request.user
    publishsheets = models.PublishSheet.objects.filter(~Q(status='6')).order_by('publish_date', 'publish_time')

    tobe_approved_list = []
    approve_refused_list = []
    approve_passed_list = []
    for publish in publishsheets:
        publish_datetime_str = publish.publish_date + ' ' + publish.publish_time
        publish_datetime_format = time.strptime(publish_datetime_str, '%Y-%m-%d %H:%M')
        publish_datetime_int = time.mktime(publish_datetime_format)
        now_int = time.time()
        if publish_datetime_int < now_int and publish.status == '1':
            if publish.approval_level.name != '1':
                # 超时未审批
                publish.status = '6'
                publish.save()
        else:
            approve_level = publish.approval_level.name
            services_objs = publish.goservices.all().order_by('name')
            ser_list = services_objs.values_list('name', flat=True).distinct()
            services_str = ', '.join(sorted(list(set(ser_list))))
            services_1 = services_objs[0]
            env = services_1.get_env_display()
            gogroup_obj = services_1.group
            level = publish.approval_level.get_name_display()

            tmp_dict = serialize_instance(publish)
            if len(publish.sql_before) > 40:
                tmp_dict['sql_before'] = cut_str(publish.sql_before, 40)
            if len(publish.sql_after) > 40:
                tmp_dict['sql_after'] = cut_str(publish.sql_after, 40)
            if len(publish.consul_key) > 40:
                tmp_dict['consul_key'] = cut_str(publish.consul_key, 40)

            # 判断单子状态，决定是否显示在我的审批页面
            if approve_level == '1':
                # 无需审批，不显示在审批页面
                pass
            elif approve_level == '2':
                # 一级审批的单子
                first_list = publish.first_approver.all().values_list('username', flat=True)
                first_str = ', '.join(first_list)
                second_str = ''

                tmp_dict.update(
                    {'id': publish.id, 'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env,
                     'approve_level': approve_level, 'level': level, 'first_str': first_str,
                     'second_str': second_str, 'creator': publish.creator.username})

                if user.username in first_list:
                    if publish.status == '1':
                        tobe_approved_list.append(tmp_dict)
                    elif publish.status == '2':
                        approve_refused_list.append(tmp_dict)
                    elif publish.status == '6':
                        # 超时未审批
                        pass
                    else:
                        approve_passed_list.append(tmp_dict)

            else:
                # 二级审批的单子
                first_list = publish.first_approver.all().values_list('username', flat=True)
                first_str = ', '.join(first_list)
                second_list = publish.second_approver.all().values_list('username', flat=True)
                second_str = ', '.join(second_list)

                tmp_dict.update(
                    {'id': publish.id, 'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env,
                     'approve_level': approve_level, 'level': level, 'first_str': first_str,
                     'second_str': second_str, 'creator': publish.creator.username})

                if user.username in first_list:
                    if publish.status == '1':
                        tobe_approved_list.append(tmp_dict)
                    elif publish.status == '2':
                        approve_refused_list.append(tmp_dict)
                    else:
                        if publish.status == '3':
                            try:
                                history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=publish)
                            except models.PublishApprovalHistory.DoesNotExist:
                                tobe_approved_list.append(tmp_dict)
                            else:
                                if history_obj.approve_count == '1' and user.username in second_list:
                                    # 既是一级审批人，又是二级审批人
                                    tobe_approved_list.append(tmp_dict)
                                else:
                                    approve_passed_list.append(tmp_dict)
                        else:
                            approve_passed_list.append(tmp_dict)
                elif user.username in second_list:
                    try:
                        history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=publish)
                    except models.PublishApprovalHistory.DoesNotExist:
                        print '2----history not exist'
                    else:
                        if publish.status == '2':
                            if history_obj.approve_count == '2':
                                if history_obj.second_approver == user:
                                    approve_refused_list.append(tmp_dict)

                        if publish.status == '3':
                            if history_obj.approve_count == '1':
                                tobe_approved_list.append(tmp_dict)
                            else:
                                if history_obj.second_approver == user:
                                    approve_passed_list.append(tmp_dict)

    # 分页
    paginator1 = Paginator(tobe_approved_list, 10)
    try:
        tobe_approved_list = paginator1.page(page_1)
    except PageNotAnInteger:
        tobe_approved_list = paginator1.page(1)
    except EmptyPage:
        tobe_approved_list = paginator1.page(paginator1.num_pages)
    paginator2 = Paginator(approve_refused_list, 10)

    try:
        approve_refused_list = paginator2.page(page_2)
    except PageNotAnInteger:
        approve_refused_list = paginator2.page(1)
    except EmptyPage:
        approve_refused_list = paginator2.page(paginator2.num_pages)
    paginator3 = Paginator(approve_passed_list, 10)

    try:
        approve_passed_list = paginator3.page(page_3)
    except PageNotAnInteger:
        approve_passed_list = paginator3.page(1)
    except EmptyPage:
        approve_passed_list = paginator3.page(paginator3.num_pages)
    return render(request, 'approve/approve_list.html',
                  {'tobe_approved_list': tobe_approved_list, 'approve_refused_list': approve_refused_list,
                   'approve_passed_list': approve_passed_list})


@login_required
def ApproveInit(request):
    sheet_id = request.GET['sheet_id']
    errcode = 0
    msg = 'ok'
    try:
        publishsheet = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'发布单不存在'
        data = dict(code=errcode, msg=msg)
        return render(request, 'publish/publish_sheets_list.html', data)
    else:
        tmp_dict = serialize_instance(publishsheet)
        service_objs = publishsheet.goservices.all()
        gogroup = service_objs[0].group
        ser_list = service_objs.values_list('name', flat=True).distinct()
        try:
            publish_history = models.PublishApprovalHistory.objects.get(publish_sheet=publishsheet)
        except models.PublishApprovalHistory.DoesNotExist:
            # 从未审批过
            tmp_dict.update({
                'group_name': gogroup.name,
                'services': ', '.join(sorted(list(set(ser_list)))),
                'env': service_objs[0].get_env_display()
            })
        else:
            # 被第一审批通过
            first_approver = publish_history.first_approver
            first_approve_time = publish_history.first_approve_time
            # first_notices = publish_history.first_notices
            approve_status = publish_history.approve_status

            tmp_dict.update({
                'group_name': gogroup.name,
                'services': ', '.join(sorted(list(set(ser_list)))),
                'env': service_objs[0].get_env_display(),
                'first_approver': first_approver,
                'first_approve_time': first_approve_time,
                # 'first_notices': first_notices,
                'approve_status': approve_status
            })

        data = dict(code=errcode, msg=msg, approve_sheet=tmp_dict)
        return render(request, 'approve/approve_sheet.html', data)


@login_required
def ApproveJudge(request):
    user = request.user
    ip = request.META['REMOTE_ADDR']
    publish_id = int(request.POST['publish_id'])
    approve = request.POST['approve']
    text = request.POST['text']
    if text:
        text = text.strip()
    errcode = 0
    msg = 'ok'

    try:
        publishsheet = models.PublishSheet.objects.get(id=publish_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'发布单不存在'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        goservices_objs = publishsheet.goservices.all()
        subject = u'cmdb发布系统'
        ser_list = goservices_objs.order_by('name').values_list('name', flat=True)
        services_str = ', '.join(ser_list)
        services_1 = goservices_objs[0]
        env = services_1.get_env_display()

        sheet_dict = {
            'services_str': services_str,
            'gogroup': services_1.group,
            'creator': user.username,
            'env': env,
            'approval_level': publishsheet.approval_level.get_name_display(),
            'id': publishsheet.id,
            'publish_date': publishsheet.publish_date,
            'publish_time': publishsheet.publish_time,
            'reason': publishsheet.reason,
        }
        try:
            projectinfo_obj = models.ProjectInfo.objects.get(group=goservices_objs[0].group)
        except models.ProjectInfo.DoesNotExist:
            projectinfo_obj = None
            first_approvers = None
            second_approvers = None
        else:
            first_approvers = projectinfo_obj.first_approver.all()
            second_approvers = projectinfo_obj.second_approver.all()

        try:
            publish_history = models.PublishApprovalHistory.objects.get(publish_sheet=publishsheet)
        except models.PublishApprovalHistory.DoesNotExist:
            # 从未审批过，现在是第一次审批
            if user not in first_approvers:
                errcode = 500
                msg = u'你不是第一审批人，不能审批'
                data = dict(code=errcode, msg=msg)
                return HttpResponse(json.dumps(data), content_type='application/json')
            publish_history = models.PublishApprovalHistory()
            publish_history.publish_sheet = publishsheet
            publish_history.approve_count = '1'
            publish_history.approve_status = approve
            publish_history.first_approver = user
            publish_history.first_approve_time = datetime.now()
            if approve == '1':
                # 第一审批通过
                # publish_history.first_notices = text
                publishsheet.status = '3'
                publishsheet.save()
                publish_history.save()
                # 收邮件方
                if publishsheet.approval_level == '2':
                    # 一级审批的单子
                    can_approve = '2'
                    to_list = [publishsheet.creator.email]
                    if projectinfo_obj:
                        to_list.extend(
                            [approver.email for approver in projectinfo_obj.mail_group.all() if approver.email])
                else:
                    # 二级审批的单子
                    can_approve = '1'
                    to_list = [approver.email for approver in publishsheet.second_approver.all() if approver.email]
            else:
                # 第一审批拒绝
                sheet_dict.update({'refuse_reason': text})
                publish_history.refuse_reason = text
                publish_history.save()
                publishsheet.status = '2'
                publishsheet.save()
                # 收邮件方
                can_approve = '2'
                to_list = [publishsheet.creator.email]
                if projectinfo_obj:
                    to_list.extend([approver.email for approver in projectinfo_obj.mail_group.all() if approver.email])

            # 发邮件
            content = {
                'title': subject,
                'sheet': sheet_dict,
                'head_content': u'发布单第一级审批结果：{0}'.format(publish_history.get_approve_status_display()),
                'can_approve': can_approve,
                'cmdb_url': CMDB_URL,
            }
            email_template_name = 'email/publish_sheet.html'
            email_content = loader.render_to_string(email_template_name, content)
            async_send_mail(subject, '', EMAIL_HOST_USER, to_list, fail_silently=False, html=email_content)
            # url = CMDB_URL + 'asset/project/send/email/'
            # params = {
            #     'sheet_id': publishsheet.id,
            #     'head_content': u'发布单第一级审批结果：{0}'.format(publish_history.get_approve_status_display()),
            #     'to': to_list,
            #     'can_approve': can_approve
            # }
            # r = requests.get(url, params)
            # print 'ApproveJudge---if-----email done'
            # if r.status_code != 200:
            #     errcode = 500
            #     msg = u'邮件发送失败'

            res_log = 'Successfully approve Publish Sheet first time, approve result : {0}'.format(
                publish_history.get_approve_status_display())
            asset_utils.logs(user.username, ip, 'approve Publish Sheet first time', res_log)
        else:
            # 被第一审批通过，现在已是第二次审批
            if user not in second_approvers:
                errcode = 500
                msg = u'你不是第二审批人，不能审批'
                data = dict(code=errcode, msg=msg)
                return HttpResponse(json.dumps(data), content_type='application/json')
            publish_history.approve_count = '2'
            publish_history.approve_status = approve
            publish_history.second_approver = user
            publish_history.second_approve_time = datetime.now()
            if approve == '1':
                # publish_history.first_notices = text
                publishsheet.status = '3'
                publishsheet.save()
            else:
                sheet_dict.update({'refuse_reason': text})
                publish_history.refuse_reason = text
                publishsheet.status = '2'
                publishsheet.save()
            publish_history.save()

            # 收邮件方
            can_approve = '2'
            to_list = [publishsheet.creator.email]
            if projectinfo_obj:
                to_list.extend([approver.email for approver in projectinfo_obj.mail_group.all() if approver.email])

            # 发邮件
            content = {
                'title': subject,
                'sheet': sheet_dict,
                'head_content': u'发布单第二级审批结果：{0}'.format(publish_history.get_approve_status_display()),
                'can_approve': can_approve,
                'cmdb_url': CMDB_URL,
            }
            email_template_name = 'email/publish_sheet.html'
            email_content = loader.render_to_string(email_template_name, content)
            async_send_mail(subject, '', EMAIL_HOST_USER, to_list, fail_silently=False, html=email_content)
            #
            # url = CMDB_URL + 'asset/project/send/email/'
            # params = {
            #     'sheet_id': publishsheet.id,
            #     'head_content': u'发布单第二级审批结果：{0}'.format(publish_history.get_approve_status_display()),
            #     'to': to_list,
            #     'can_approve': can_approve
            # }
            # r = requests.get(url, params)
            # print 'ApproveJudge---else-----email done'
            # if r.status_code != 200:
            #     errcode = 500
            #     msg = u'邮件发送失败'

            res_log = 'Successfully approve Publish Sheet second time, approve result : {0}'.format(
                publish_history.get_approve_status_display())
            asset_utils.logs(user.username, ip, 'approve Publish Sheet second time', res_log)

    data = dict(code=errcode, msg=msg)
    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def PublishSheetDetail(request):
    errcode = 0
    msg = 'ok'
    content = {}
    sheet_id = int(request.GET['sheet_id'])
    can_publish = request.GET['can_publish']
    can_delete = request.GET.get('can_delete', '2')
    user = request.user
    can_see_result = False

    try:
        sheet_obj = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'所选发布单不存在'
        print 'not exist'
    else:
        services_objs = sheet_obj.goservices.all().order_by('name')
        service_list = services_objs.values_list('name', flat=True).distinct()
        services_str = ', '.join(sorted(list(set(service_list))))
        services_1 = services_objs[0]
        env = services_1.get_env_display()
        gogroup_obj = services_1.group
        level = sheet_obj.approval_level.get_name_display()
        approve_level = sheet_obj.approval_level.name
        qa_objs = sheet_obj.qa.all().order_by('username')
        qa_str = ', '.join(qa_objs.values_list('username', flat=True))

        content = serialize_instance(sheet_obj)

        if len(sheet_obj.sql_before) > 40:
            content['sql_before'] = cut_str(sheet_obj.sql_before, 40)
        if len(sheet_obj.sql_after) > 40:
            content['sql_after'] = cut_str(sheet_obj.sql_after, 40)
        if len(sheet_obj.consul_key) > 40:
            content['consul_key'] = cut_str(sheet_obj.consul_key, 40)

        content['if_review'] = sheet_obj.get_if_review_display()
        if sheet_obj.if_review == '1':
            reviewer_objs = sheet_obj.reviewer.all().order_by('username')
            content['reviewer'] = ', '.join(reviewer_objs.values_list('username', flat=True))
        content['if_browse'] = sheet_obj.get_if_browse_display()
        content['if_order'] = sheet_obj.get_if_order_display()
        content['if_buy'] = sheet_obj.get_if_buy_display()

        if sheet_obj.creator == user:
            if approve_level == '1' and sheet_obj.status != '4':
                can_delete = '1'
            else:
                can_delete = can_delete
        else:
            can_delete = '2'

        if sheet_obj.status == '4':
            can_see_result = True

        content.update({'id': sheet_obj.id, 'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env,
                        'approve_level': approve_level, 'level': level, 'creator': sheet_obj.creator.username,
                        'qa': qa_str})

        if sheet_obj.approval_level.name == '1':
            content.update({'approve_history': 'no'})
        else:
            try:
                sheet_history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=sheet_obj)
            except models.PublishApprovalHistory.DoesNotExist:
                print 'PublishSheetDetail---history not exist'
                content.update({'approve_history': 'no'})
            else:
                content.update({'approve_history': 'yes'})

                content['approve_count'] = sheet_history_obj.approve_count
                if sheet_obj.approval_level.name == '2':
                    # 一级审批, 被拒绝
                    content['first_approver'] = sheet_history_obj.first_approver.username
                    content['first_approve_time'] = sheet_history_obj.first_approve_time
                    content['refuse_reason'] = sheet_history_obj.refuse_reason
                else:
                    # 二级审批
                    if sheet_history_obj.approve_count == '1':
                        # 一级审批时被拒绝
                        content['first_approver'] = sheet_history_obj.first_approver.username
                        content['first_approve_time'] = sheet_history_obj.first_approve_time
                        content['refuse_reason'] = sheet_history_obj.refuse_reason
                    else:
                        # 二级审批时被拒绝
                        content['first_approver'] = sheet_history_obj.first_approver.username
                        content['first_approve_time'] = sheet_history_obj.first_approve_time
                        content['second_approver'] = sheet_history_obj.second_approver.username
                        content['second_approve_time'] = sheet_history_obj.second_approve_time
                        content['refuse_reason'] = sheet_history_obj.refuse_reason

    content['can_publish'] = can_publish
    content['can_delete'] = can_delete
    content['can_see_result'] = can_see_result
    data = dict(code=errcode, msg=msg, content=content)
    return render_to_response('publish/publish_sheet_detail.html', data)


@login_required
def StartPublish(request):
    user = request.user
    ip = request.META['REMOTE_ADDR']
    sheet_id = int(request.GET['sheet_id'])
    errcode = 0
    msg = 'ok'
    try:
        publishsheet = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'发布单不存在'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        try:
            userprofile = asset_models.UserProfile.objects.get(user=user)
        except asset_models.UserProfile.DoesNotExist:
            phone_number = ''
        else:
            phone_number = userprofile.phone_number

        goservices = publishsheet.goservices.all()
        goproject_name = goservices[0].group.name
        services = goservices.values_list('name', flat=True)
        ser_list = sorted(list(set(services)))
        env = goservices[0].env
        tower_url = publishsheet.tapd_url

        publish_ok = '1'

        Publish = asset_utils.goPublish(env)

        result = []
        print '^^^^^^^^^^^^^^^^^^start to publish, ser_list : ', ser_list
        for svc in ser_list:
            try:
                rst = Publish.deployGo(goproject_name, svc, request.user.username, ip, tower_url, phone_number)
            except Exception as e:
                print 'StartPublish---e.message : ', e.message
                publish_ok = '2'
                result.extend({'run deployGo Exception': e.message})
            else:
                print '**********rst : ', rst
                for tmp_dict in rst:
                    for k in tmp_dict:
                        if 'ERROR' in tmp_dict[k] or 'error' in tmp_dict[k] or 'Skip' in tmp_dict[k]:
                            publish_ok = '2'
                if rst:
                    result.extend(rst)

            # break once deploy failed
            res = asset_utils.get_service_status(svc)
            if not res:
                print("deploy %s failed" % svc)
                publish_ok = '2'
                break

        # print 'result : ', result
        publishsheet.publish_result = result
        publishsheet.save()

        if publish_ok == '1':
            publishsheet.status = '4'
            publishsheet.if_publish_ok = '1'
            publishsheet.save()
            res_log = 'Successfully deploy Publish Sheet, gogroup : {0}'.format(goproject_name)
            asset_utils.logs(user.username, ip, 'deploy Publish Sheet', res_log)
        else:
            publishsheet.status = '4'
            publishsheet.if_publish_ok = '2'
            publishsheet.save()
            res_log = 'Failed to deploy Publish Sheet, gogroup : {0}'.format(goproject_name)
            asset_utils.logs(user.username, ip, 'deploy Publish Sheet', res_log)

        # 发邮件
        subject = u'cmdb发布系统'
        to_list = [publishsheet.creator.email]
        if publishsheet.approval_level.name != '1':
            try:
                projectinfo_obj = models.ProjectInfo.objects.get(group=publishsheet.goservices.all()[0].group)
            except models.ProjectInfo.DoesNotExist:
                projectinfo_obj = None
            else:
                if projectinfo_obj.mail_group.all():
                    to_list.extend([approver.email for approver in projectinfo_obj.mail_group.all() if approver.email])

        sheet_dict = {
            'services_str': ', '.join(services),
            'gogroup': goservices[0].group,
            'creator': user.username,
            'env': env,
            'approval_level': publishsheet.approval_level.get_name_display(),
            'id': publishsheet.id,
            'publish_date': publishsheet.publish_date,
            'publish_time': publishsheet.publish_time,
            'reason': publishsheet.reason,
        }
        content = {
            'title': subject,
            'sheet': sheet_dict,
            'head_content': u'发布单完成发布',
            'can_approve': '3',
            'cmdb_url': CMDB_URL,
        }
        email_template_name = 'email/publish_sheet.html'
        email_content = loader.render_to_string(email_template_name, content)
        async_send_mail(subject, '', EMAIL_HOST_USER, to_list, fail_silently=False, html=email_content)

        # url = CMDB_URL + 'asset/project/send/email/'
        # params = {
        #     'sheet_id': publishsheet.id,
        #     'head_content': u'发布单完成发布',
        #     'to': to_list,
        #     'can_approve': '3'
        # }
        # r = requests.get(url, params)
        # if r.status_code != 200:
        #     errcode = 500
        #     msg = u'邮件发送失败'

    data = dict(code=errcode, msg=msg, publish_result=result, publish_ok=publish_ok)
    return render(request, 'publish/publish_result.html', data)


@login_required
def PublishResult(request):
    sheet_id = int(request.GET['sheet_id'])
    errcode = 0
    msg = 'ok'
    try:
        publishsheet = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'发布单不存在'
        data = dict(code=errcode, msg=msg)
        return render(request, 'publish/publish_result.html', data)
    else:
        if publishsheet.publish_result:
            old_result = eval(publishsheet.publish_result)
            result = [res for res in old_result if res]
        else:
            result = [{'warning': u'请耐心等待，稍后请刷新'}]
        publish_ok = publishsheet.if_publish_ok
        data = dict(code=errcode, msg=msg, publish_result=result, publish_ok=publish_ok)
        return render(request, 'publish/publish_result.html', data)


@login_required
def ApproveSheetDetail(request):
    errcode = 0
    msg = 'ok'
    content = {}
    sheet_id = int(request.GET['sheet_id'])
    can_approve = request.GET['can_approve']

    try:
        sheet_obj = models.PublishSheet.objects.get(id=sheet_id)
    except models.PublishSheet.DoesNotExist:
        errcode = 500
        msg = u'所选发布单不存在'
        print 'not exist'
    else:
        services_objs = sheet_obj.goservices.all().order_by('name')
        services_str = ', '.join(services_objs.values_list('name', flat=True))
        services_1 = services_objs[0]
        env =services_1.get_env_display()
        gogroup_obj = services_1.group
        level = sheet_obj.approval_level.get_name_display()
        approve_level = sheet_obj.approval_level.name
        qa_objs = sheet_obj.qa.all().order_by('username')
        qa_str = ', '.join(qa_objs.values_list('username', flat=True))

        content = serialize_instance(sheet_obj)

        if len(sheet_obj.sql_before) > 40:
            content['sql_before'] = cut_str(sheet_obj.sql_before, 40)
        if len(sheet_obj.sql_after) > 40:
            content['sql_after'] = cut_str(sheet_obj.sql_after, 40)
        if len(sheet_obj.consul_key) > 40:
            content['consul_key'] = cut_str(sheet_obj.consul_key, 40)

        content['if_review'] = sheet_obj.get_if_review_display()
        if sheet_obj.if_review == '1':
            reviewer_objs = sheet_obj.reviewer.all().order_by('username')
            content['reviewer'] = ', '.join(reviewer_objs.values_list('username', flat=True))
        content['if_browse'] = sheet_obj.get_if_browse_display()
        content['if_order'] = sheet_obj.get_if_order_display()
        content['if_buy'] = sheet_obj.get_if_buy_display()

        content.update({'id': sheet_obj.id, 'gogroup': gogroup_obj.name, 'services_str': services_str, 'env': env,
                        'approve_level': approve_level, 'level': level, 'creator': sheet_obj.creator.username,
                        'qa': qa_str})

        if sheet_obj.approval_level.name == '1':
            content.update({'approve_history': 'no'})
        else:
            try:
                sheet_history_obj = models.PublishApprovalHistory.objects.get(publish_sheet=sheet_obj)
            except models.PublishApprovalHistory.DoesNotExist:
                print 'PublishSheetDetail---history not exist'
                content.update({'approve_history': 'no'})
            else:
                content.update({'approve_history': 'yes'})

                content['approve_count'] = sheet_history_obj.approve_count
                if sheet_obj.approval_level.name == '2':
                    # 一级审批, 被拒绝
                    content['first_approver'] = sheet_history_obj.first_approver.username
                    content['first_approve_time'] = sheet_history_obj.first_approve_time
                    content['refuse_reason'] = sheet_history_obj.refuse_reason
                else:
                    # 二级审批
                    if sheet_history_obj.approve_count == '1':
                        # 一级审批时被拒绝
                        content['first_approver'] = sheet_history_obj.first_approver.username
                        content['first_approve_time'] = sheet_history_obj.first_approve_time
                        content['refuse_reason'] = sheet_history_obj.refuse_reason
                    else:
                        # 二级审批时被拒绝
                        content['first_approver'] = sheet_history_obj.first_approver.username
                        content['first_approve_time'] = sheet_history_obj.first_approve_time
                        content['second_approver'] = sheet_history_obj.second_approver.username
                        content['second_approve_time'] = sheet_history_obj.second_approve_time
                        content['refuse_reason'] = sheet_history_obj.refuse_reason

    content['can_approve'] = can_approve
    data = dict(code=errcode, msg=msg, content=content)
    return render_to_response('approve/approve_sheet_detail.html', data)


def sendEmail(request):
    sheet_id = int(request.GET['sheet_id'])
    head_content = request.GET['head_content']
    can_approve = request.GET.get('can_approve', '2')
    to_list = request.GET.getlist('to', [])

    errcode = 0
    msg = 'ok'

    if to_list:
        try:
            sheet_obj = models.PublishSheet.objects.get(id=sheet_id)
        except models.PublishSheet.DoesNotExist:
            errcode = 500
            msg = u'所选发布单不存在'
            data = dict(code=errcode, msg=msg)
            return HttpResponse(json.dumps(data), content_type='application/json')
        else:
            sheet_dict = serialize_instance(sheet_obj)
            services_objs = sheet_obj.goservices.all()
            ser_list = services_objs.order_by('name').values_list('name', flat=True)
            services_str = ', '.join(ser_list)
            services_1 = services_objs[0]
            gogroup_obj = services_1.group
            env = services_1.get_env_display()
            sheet_dict.update(
                {'services_str': services_str, 'gogroup': gogroup_obj.name, 'creator': sheet_obj.creator.username,
                 'env': env, 'approval_level': sheet_obj.approval_level.get_name_display()})

            subject = u'cmdb发布系统'
            content = {
                'title': subject,
                'sheet': sheet_dict,
                'head_content': head_content,
                'can_approve': can_approve,
                'cmdb_url': CMDB_URL,
            }

            from_email = EMAIL_HOST_USER
            email_template_name = 'email/publish_sheet.html'
            email_content = loader.render_to_string(email_template_name, content)
            # try:
            #     send_mail(subject, "", from_email, to_list, html_message=email_content)
            # except Exception as e:
            #     print 'send_mail failed : ', e.message

            try:
                async_send_mail(subject, '', from_email, to_list, fail_silently=False, html=email_content)
            except Exception as e:
                print 'async_send_mail failed : ', e.message

            data = dict(code=errcode, msg=msg, content=content)
            return HttpResponse(json.dumps(data), content_type='application/json')
    else:
        errcode = 500
        msg = u'没有收件人'
        data = dict(code=errcode, msg=msg)
        return HttpResponse(json.dumps(data), content_type='application/json')
