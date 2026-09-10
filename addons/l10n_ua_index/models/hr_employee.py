# -*- coding: utf-8 -*-
"""Базовий місяць індексації працівника.

Базовий місяць - місяць, у якому востаннє підвищили оклад. Індекс рахують з наступного
місяця. Якщо поле порожнє, базовий місяць визначаємо з історії версій контракту:
остання версія, де оклад більший за попередній; інакше місяць прийняття.
"""
from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_index_base = fields.Date(
        "Базовий місяць індексації", groups="hr.group_hr_user",
        help="Місяць останнього підвищення окладу. Порожнє - визначаємо з історії версій контракту.")
    ua_index_off = fields.Boolean(
        "Не індексувати", groups="hr.group_hr_user",
        help="Вимикає автоматичну індексацію для цього працівника.")
    ua_index_base_effective = fields.Date(
        "Базовий місяць (чинний)", compute="_compute_ua_index_base_effective", groups="hr.group_hr_user")

    @api.depends("ua_index_base", "version_ids.wage", "version_ids.date_version")
    def _compute_ua_index_base_effective(self):
        for employee in self:
            employee.ua_index_base_effective = employee.ua_index_base or employee._ua_index_base_auto()

    def _ua_index_base_auto(self):
        """Місяць останнього підвищення окладу за версіями контракту."""
        self.ensure_one()
        versions = self.sudo().version_ids.filtered(lambda v: v.date_version).sorted("date_version")
        base = None
        previous_wage = None
        for version in versions:
            wage = version.wage or 0.0
            if previous_wage is None or wage > previous_wage:
                base = version.date_version
            previous_wage = wage
        if not base:
            return False
        return base.replace(day=1)
