# -*- coding: utf-8 -*-
"""Дані військового обліку на картці працівника."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

STATUS = [
    ("none", "Не підлягає обліку"),
    ("conscript", "Призовник"),
    ("liable", "Військовозобов'язаний"),
    ("reserve", "Резервіст"),
    ("removed", "Знятий з обліку"),
    ("excluded", "Виключений з обліку"),
]
LIABLE_STATUSES = ("conscript", "liable", "reserve")
# Категорії за офіційним витягом зі списків персонального обліку (постанова КМУ № 1487): списки ведуться
# окремо серед призовників, військовозобов'язаних і резервістів, а всередині - за офіцерським і
# рядовим/сержантським складом. Стать (жінки) і стан обліку (призовник/резервіст) - не категорія, а фільтр.
CATEGORY = [("officers", "Офіцерський склад"), ("ranks", "Рядовий, сержантський і старшинський склад")]
CATEGORY_MIGRATE = {"sergeants": "ranks", "soldiers": "ranks"}
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
    ua_mil_women_list = fields.Boolean(
        "У списку жінок", compute="_compute_ua_mil_women_list", store=True, groups="hr.group_hr_user",
        help="Військовозобов'язана жінка: за офіційною формою ведеться в окремому списку, не за категорією.")

    # Резерв+ (витяг): необов'язковий блок для тих, хто перебуває в оперативному резерві за програмою
    # "Резерв+". Не пов'язано з "Заброньований" вище (те - звільнення від мобілізації, це - облік у резерві).
    ua_reserve_number = fields.Char("Номер витягу Резерв+", groups="hr.group_hr_user")
    ua_reserve_date = fields.Date("Дата витягу Резерв+", groups="hr.group_hr_user",
                                   help="Дата видачі витягу з Резерв+, на дату прийняття на роботу.")
    ua_reserve_filename = fields.Char("Файл витягу (назва)", groups="hr.group_hr_user")
    ua_reserve_file = fields.Binary("Файл витягу Резерв+", attachment=True, groups="hr.group_hr_user")

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

    @api.depends("sex", "ua_mil_status")
    def _compute_ua_mil_women_list(self):
        for emp in self:
            emp.ua_mil_women_list = emp.sex == "female" and emp.ua_mil_status in LIABLE_STATUSES

    def ua_mil_register_check(self, note=None):
        """Записати звірку з ТЦК: подія обліку плюс дата останньої звірки.

        Правило одне на всю систему - і для картки працівника, і для списку персонального
        обліку. Екран лише каже, звідки звірка прийшла (note)."""
        today = fields.Date.context_today(self)
        Event = self.env["ua.military.event"].sudo()
        for emp in self:
            Event.create({
                "employee_id": emp.id,
                "date": today,
                "kind": "check",
                "note": note or _("Звірка з ТЦК"),
            })
        self.sudo().write({"ua_mil_last_check": today})
        return today

    @api.constrains("ua_mil_doc_type", "ua_mil_status")
    def _check_ua_mil_doc_type(self):
        for emp in self:
            if emp.ua_mil_doc_type == "registration" and emp.ua_mil_status != "conscript":
                raise ValidationError(_(
                    "«Посвідчення про приписку» - лише для призовників. У %(name)s стан обліку: %(status)s."
                ) % {"name": emp.name, "status": dict(STATUS).get(emp.ua_mil_status, emp.ua_mil_status or "-")})
