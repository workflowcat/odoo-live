# -*- coding: utf-8 -*-
"""Дані військового обліку на картці працівника."""
from odoo import api, fields, models

STATUS = [
    ("none", "Не підлягає обліку"),
    ("conscript", "Призовник"),
    ("liable", "Військовозобов'язаний"),
    ("reserve", "Резервіст"),
    ("removed", "Знятий з обліку"),
    ("excluded", "Виключений з обліку"),
]
LIABLE_STATUSES = ("conscript", "liable", "reserve")
CATEGORY = [("officers", "Офіцери"), ("sergeants", "Сержанти і старшини"), ("soldiers", "Солдати і матроси")]
GROUP = [("sv", "СВ"), ("vms", "ВМС"), ("other", "Інші")]
DOC_TYPE = [("ticket", "Військовий квиток"), ("temp", "Тимчасове посвідчення"), ("registration", "Посвідчення про приписку")]
FITNESS = [("fit", "Придатний"), ("limited", "Обмежено придатний"), ("unfit", "Непридатний"), ("undefined", "Не визначено")]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_mil_status = fields.Selection(STATUS, string="Стан обліку", default="none", tracking=True, groups="hr.group_hr_user")
    ua_mil_category = fields.Selection(CATEGORY, string="Категорія обліку", groups="hr.group_hr_user")
    ua_mil_group = fields.Selection(GROUP, string="Група обліку", groups="hr.group_hr_user")
    ua_mil_rank = fields.Char("Військове звання", groups="hr.group_hr_user")
    ua_mil_vos = fields.Char("ВОС", groups="hr.group_hr_user")
    ua_mil_tcc = fields.Char("ТЦК та СП, де перебуває на обліку", groups="hr.group_hr_user")
    ua_mil_doc_type = fields.Selection(DOC_TYPE, string="Вид документа", groups="hr.group_hr_user")
    ua_mil_doc_series = fields.Char("Серія документа", groups="hr.group_hr_user")
    ua_mil_doc_number = fields.Char("Номер військового документа", groups="hr.group_hr_user")
    ua_mil_doc_date = fields.Date("Дата видачі документа", groups="hr.group_hr_user")
    ua_mil_fitness = fields.Selection(FITNESS, string="Придатність", groups="hr.group_hr_user")
    ua_mil_vlk_date = fields.Date("Дата ВЛК", groups="hr.group_hr_user")
    ua_mil_reserved = fields.Boolean("Заброньований", tracking=True, groups="hr.group_hr_user")
    ua_mil_reserve_order = fields.Char("Підстава бронювання (наказ, рішення)", groups="hr.group_hr_user")
    ua_mil_reserve_until = fields.Date("Бронювання до", tracking=True, groups="hr.group_hr_user")
    ua_mil_deferment = fields.Char("Відстрочка (підстава)", groups="hr.group_hr_user")
    ua_mil_deferment_until = fields.Date("Відстрочка до", tracking=True, groups="hr.group_hr_user")
    ua_mil_last_check = fields.Date("Дата звірки даних", tracking=True, groups="hr.group_hr_user")
    ua_mil_note = fields.Text("Примітка", groups="hr.group_hr_user")
    ua_mil_event_ids = fields.One2many("ua.military.event", "employee_id", string="Події", groups="hr.group_hr_user")
    ua_mil_needs_check = fields.Boolean("Потребує звірки", compute="_compute_ua_mil_needs_check", store=True, groups="hr.group_hr_user")

    @api.depends("ua_mil_status", "ua_mil_last_check")
    def _compute_ua_mil_needs_check(self):
        today = fields.Date.today()
        for emp in self:
            if emp.ua_mil_status not in LIABLE_STATUSES:
                emp.ua_mil_needs_check = False
            elif not emp.ua_mil_last_check:
                emp.ua_mil_needs_check = True
            else:
                emp.ua_mil_needs_check = (today - emp.ua_mil_last_check).days > 365
