# coding: utf-8

from django.db import models
from django.contrib.auth.models import User
from asset.models import gogroup, goservices

IF_OR_NOT = (
    ('1', u'是'),
    ('2', u'否'),
)


class Approver(models.Model):
    role = models.CharField(max_length=50, verbose_name=u'角色', null=True, blank=True)
    approver = models.ForeignKey(User, verbose_name=u'审批人', related_name='approver')

    def __unicode__(self):
        return self.approver.username

    class Meta:
        verbose_name = u"审批人"
        verbose_name_plural = verbose_name


class Festival(models.Model):
    name = models.CharField(max_length=32, verbose_name=u"节日名称")
    start_day = models.DateField('日期')
    end_day = models.DateField('日期', null=True, blank=True)

    def __unicode__(self):
        return self.name

    class Meta:
        verbose_name = u"节假日"
        verbose_name_plural = verbose_name


class ApprovalLevel(models.Model):
    LEVEL = (
        ('1', u'无需审批'),
        ('2', u'一级审批'),
        ('3', u'二级审批'),
    )
    name = models.CharField(choices=LEVEL, max_length=32, verbose_name=u"审批级别", default='1')

    def __unicode__(self):
        return self.get_name_display()

    class Meta:
        verbose_name = u"审批级别"
        verbose_name_plural = verbose_name


class TimeSlotLevel(models.Model):
    DAY = (
        ('1', u'周一'),
        ('2', u'周二'),
        ('3', u'周三'),
        ('4', u'周四'),
        ('5', u'周五'),
        ('6', u'周六'),
        ('7', u'周日'),
    )
    GLOBAL = (
        ('1', u'自定义级别'),
        ('2', u'通用模板'),
    )
    is_global = models.CharField(choices=GLOBAL, max_length=32, verbose_name=u"是否通用模板", default='1')
    start_of_week = models.CharField(choices=DAY, max_length=32, verbose_name=u"起始日", default='1')
    end_of_week = models.CharField(choices=DAY, max_length=32, verbose_name=u"截止日", default='7')
    start_time = models.CharField(verbose_name=u'开始时间点', max_length=32, blank=True, null=True)
    end_time = models.CharField(verbose_name=u'结束时间点', max_length=32, blank=True, null=True)
    approval_level = models.ForeignKey(ApprovalLevel)
    creator = models.ForeignKey(User, verbose_name=u"创建者", related_name="creator_of_timeslotlevel", blank=True,
                                null=True)

    def __unicode__(self):
        return self.start_of_week + ' ' + self.end_of_week + ' ' + self.start_time + ' ' + self.end_time + ' ' + self.approval_level.get_name_display()

    class Meta:
        verbose_name = u"时间段--审批级别"
        verbose_name_plural = verbose_name


class MailGroup(models.Model):
    email = models.CharField(max_length=255)
    name = models.CharField(max_length=64, blank=True, null=True)

    def __unicode__(self):
        return self.email

    class Meta:
        verbose_name = u"邮件组"
        verbose_name_plural = verbose_name


class ProjectInfo(models.Model):
    group = models.ForeignKey(gogroup)
    owner = models.ManyToManyField(User, verbose_name=u'负责人', related_name='project_owner')
    mail_group = models.ManyToManyField(MailGroup, verbose_name=u'邮件组', related_name='project_mail_group')
    first_approver = models.ManyToManyField(User, verbose_name=u'一级审批人', related_name='project_first_level_approver')
    second_approver = models.ManyToManyField(User, verbose_name=u'二级审批人', related_name='project_second_level_approver')
    timeslot_level = models.ManyToManyField(TimeSlotLevel, verbose_name=u'时间段-审批级别',
                                            related_name='project_timeslotlevel')
    creator = models.ForeignKey(User, verbose_name=u"创建者", related_name="creator_of_projectinfo", null=True, blank=True)

    def __unicode__(self):
        return u'项目 : ' + self.group.name

    class Meta:
        verbose_name = u"项目初始化"
        verbose_name_plural = verbose_name


class PublishSheet(models.Model):
    STATUS = (
        ('1', u'审批中'),
        ('2', u'审批拒绝'),
        ('3', u'审批通过'),
        ('4', u'完成发布'),
        ('5', u'虽审批通过，但超时未发布'),
        ('6', u'超时未审批'),
    )
    creator = models.ForeignKey(User, verbose_name=u"创建者", related_name="creator_of_publishsheet", default=1)
    goservices = models.ManyToManyField(goservices, verbose_name=u'重启服务', related_name='publish_goservices')
    publish_date = models.CharField(max_length=32, verbose_name=u"发布日期")
    publish_time = models.CharField(max_length=32, verbose_name=u"发布开始时间")
    tapd_url = models.TextField(verbose_name=u"TAPD URL")
    sql_before = models.TextField(verbose_name=u"事前执行的SQL", blank=True, null=True)
    sql_after = models.TextField(verbose_name=u"事后执行的SQL", blank=True, null=True)
    consul_key = models.TextField(verbose_name=u"consul key", blank=True, null=True)
    status = models.CharField(choices=STATUS, max_length=32, verbose_name=u"发布单状态", default='1')
    approval_level = models.ForeignKey(ApprovalLevel, blank=True, null=True)
    first_approver = models.ManyToManyField(User, verbose_name=u'一级审批人',
                                            related_name='publishsheet_first_level_approver')
    second_approver = models.ManyToManyField(User, verbose_name=u'二级审批人',
                                             related_name='publishsheet_second_level_approver')
    comment = models.TextField(verbose_name=u"备注", blank=True, null=True)
    qa = models.ManyToManyField(User, verbose_name=u'测试人', related_name='publishsheet_qa')
    reason = models.TextField(verbose_name=u"紧急发布原因", blank=True, null=True)
    if_review = models.CharField(choices=IF_OR_NOT, max_length=32, verbose_name=u"是否code review", default='2')
    reviewer = models.ManyToManyField(User, verbose_name=u'code review人', related_name='publishsheet_reviewer')
    if_browse = models.CharField(choices=IF_OR_NOT, max_length=32, verbose_name=u"是否影响用户浏览", default='2')
    if_order = models.CharField(choices=IF_OR_NOT, max_length=32, verbose_name=u"是否影响订单流程", default='2')
    if_buy = models.CharField(choices=IF_OR_NOT, max_length=32, verbose_name=u"是否影响履单流程", default='2')
    if_publish_ok = models.CharField(choices=IF_OR_NOT, max_length=32, verbose_name=u"是否发布成功", default='2')
    publish_result = models.TextField(verbose_name=u"发布结果", blank=True, null=True)

    def __unicode__(self):
        return self.tapd_url

    class Meta:
        verbose_name = u"发布单"
        verbose_name_plural = verbose_name


class PublishApprovalHistory(models.Model):
    APPROVE_STATUS = (
        ('1', u'通过'),
        ('2', u'拒绝'),
    )
    APPROVE_COUNT = (
        ('1', u'第一次审批'),
        ('2', u'第二次审批'),
    )
    publish_sheet = models.ForeignKey(PublishSheet)
    approve_count = models.CharField(choices=APPROVE_COUNT, max_length=32, verbose_name=u"审批次数", default='1')
    approve_status = models.CharField(choices=APPROVE_STATUS, max_length=32, verbose_name=u"审批状态", default='1')
    refuse_reason = models.TextField(verbose_name=u"拒绝原因", blank=True, null=True)
    first_approver = models.ForeignKey(User, verbose_name=u'第一审批人', related_name='sheet_first_approver', blank=True,
                                       null=True)
    first_approve_time = models.DateTimeField(verbose_name=u'第一审批时间', auto_now_add=True, blank=True, null=True)
    # first_notices = models.TextField(verbose_name=u"第一审批人批注的注意事项", blank=True, null=True)
    second_approver = models.ForeignKey(User, verbose_name=u'第二审批人', related_name='sheet_second_approver', blank=True,
                                        null=True)
    second_approve_time = models.DateTimeField(verbose_name=u'第二审批时间', auto_now_add=True, blank=True, null=True)

    # second_notices = models.TextField(verbose_name=u"第二审批人批注的注意事项", blank=True, null=True)

    def __unicode__(self):
        return self.publish_sheet.tapd_url

    class Meta:
        verbose_name = u"发布单审批记录"
        verbose_name_plural = verbose_name
