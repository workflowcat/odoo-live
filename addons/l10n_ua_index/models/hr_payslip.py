# -*- coding: utf-8 -*-
"""Сума індексації для правила INDEX.

Наростаючий індекс = добуток місячних індексів споживчих цін з місяця, наступного за базовим,
до місяця листка. Сума = прожитковий мінімум для працездатних × (наростаючий індекс - 1).
Місяці без внесеного індексу вважаємо за 100 % і показуємо їх окремим списком, щоб бухгалтер
бачив, чого бракує.

Спрощення, які має підтвердити бухгалтер:
- індексація не ділиться пропорційно до відпрацьованого часу;
- підвищення окладу порівнюється з сумою індексації лише через базовий місяць
  (нова версія контракту з більшим окладом переносить базовий місяць).
"""
from odoo import models


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_index_months(self, base_date):
        """Місяці, за які береться індекс: від наступного за базовим до місяця листка."""
        months = []
        year, month = _next_month(base_date.year, base_date.month)
        last = (self.date_to.year, self.date_to.month)
        while (year, month) <= last and len(months) < 240:
            months.append((year, month))
            year, month = _next_month(year, month)
        return months

    def ua_index_detail(self):
        """(сума, наростаючий відсоток, місяці без індексу) для правила і перевірок."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        if employee.ua_index_off:
            return 0.0, 0.0, []
        base = employee.ua_index_base or employee._ua_index_base_auto()
        if not base:
            return 0.0, 0.0, []
        months = self._ua_index_months(base)
        if not months:
            return 0.0, 0.0, []
        indexes = self.env["ua.cpi.index"].sudo().search([]).mapped(lambda r: ((r.year, r.month), r.value))
        index_map = dict(indexes)
        cumulative = 1.0
        missing = []
        for key in months:
            value = index_map.get(key)
            if value:
                cumulative *= value / 100.0
            else:
                missing.append(key)
        percent = round((cumulative - 1.0) * 100.0, 4)
        if percent <= 0:
            return 0.0, percent, missing
        living_wage = self.env["ua.payroll.param"].get_all(self.date_to, self.company_id)["living_wage"]
        return round(living_wage * percent / 100.0, 2), percent, missing

    def ua_index_amount(self):
        return self.ua_index_detail()[0]

    def _ua_payroll_values(self, contracts):
        values = super()._ua_payroll_values(contracts)
        values["index_amount"] = self.ua_index_amount()
        return values
