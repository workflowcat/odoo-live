# -*- coding: utf-8 -*-
"""Індексація за Порядком 1078.

Правила, які тут реалізовані:

1. Наростаючий індекс рахується множенням місячних індексів з місяця, наступного за базовим,
   і округлюється до 0,1 %.
2. Право на виплату виникає, коли наростаючий індекс перевищує поріг (параметр
   `index_threshold`, типово 103 %). До порогу індексація дорівнює нулю.
3. Індекс місяця можна застосувати лише після його оприлюднення. Держстат публікує індекс
   місяця в наступному місяці, тому індекс самого місяця листка в розрахунок не входить.
4. Сума = прожитковий мінімум для працездатних × приріст індексу. Для неповної ставки і
   неповністю відпрацьованого місяця сума береться в тій самій пропорції, що й оклад.
5. Після місяця, за який індексацію виплачено, починається новий цикл: базовим стає цей
   місяць, наростаючий індекс рахується наново.

Що ще потребує рішення бухгалтера: порівняння підвищення окладу з можливою індексацією
(п. 5 Порядку 1078). Зараз підвищення лише переносить базовий місяць.
"""
from odoo import models

from odoo.addons.l10n_ua_payroll_rules.models.hr_payslip import ua_round

THRESHOLD_DEFAULT = 103.0

_UA_MONTHS_GEN = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
                  7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}


def _next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _ua_ym_label(ym):
    """(рік, місяць) у родовому відмінку - "вересня 2026"."""
    year, month = ym
    return "%s %d" % (_UA_MONTHS_GEN.get(month, str(month)), year)


def _entry(label, kind, state, source=None, note=None):
    """Один запис _ua_payroll_sources: label/kind/state завжди, source і/або note - за наявності."""
    out = {"label": label, "kind": kind, "state": state}
    if source is not None:
        out["source"] = source
    if note is not None:
        out["note"] = note
    return out


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_index_base_month(self):
        """Базовий місяць: пізніший з поставленого бухгалтером і місяця останньої виплати."""
        employee = self.employee_id.sudo()
        base = employee.ua_index_base or employee._ua_index_base_auto()
        paid = employee.ua_index_paid_month
        if paid and (not base or paid > base):
            base = paid
        return base

    def _ua_index_months(self, base_date):
        """Місяці індексів: від наступного за базовим до місяця перед місяцем листка.

        Індекс місяця листка не беремо: його ще не оприлюднено."""
        months = []
        year, month = _next_month(base_date.year, base_date.month)
        last_year, last_month = self.date_to.year, self.date_to.month
        last = (last_year - 1, 12) if last_month == 1 else (last_year, last_month - 1)
        while (year, month) <= last and len(months) < 240:
            months.append((year, month))
            year, month = _next_month(year, month)
        return months

    def _ua_index_published(self, key, value_date):
        """Чи оприлюднено індекс до кінця місяця листка."""
        return not value_date or value_date <= self.date_to

    def ua_index_detail(self):
        """(сума, наростаючий відсоток, місяці без індексу) для правила і перевірок."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        if employee.ua_index_off:
            return 0.0, 0.0, []
        base = self._ua_index_base_month()
        if not base:
            return 0.0, 0.0, []
        months = self._ua_index_months(base)
        if not months:
            return 0.0, 0.0, []
        rows = self.env["ua.cpi.index"].sudo().search([])
        index_map = {(row.year, row.month): row for row in rows}
        cumulative = 1.0
        missing = []
        for key in months:
            row = index_map.get(key)
            if row and self._ua_index_published(key, row.published_on):
                cumulative *= row.value / 100.0
            else:
                missing.append(key)
        percent = round(cumulative * 100.0, 1)
        params = self.env["ua.payroll.param"].get_all(self.date_to, self.company_id)
        threshold = params.get("index_threshold", THRESHOLD_DEFAULT)
        if percent <= threshold:
            return 0.0, percent, missing
        share = self._ua_index_share()
        amount = params["living_wage"] * (percent - 100.0) / 100.0 * share
        return ua_round(amount), percent, missing

    def _ua_index_share(self):
        """Пропорція ставки і відпрацьованого часу. Та сама, що й для окладу."""
        employee = self.employee_id.sudo()
        fte = float(employee.ua_fte or "1")
        worked = sum(line.number_of_days for line in self.worked_days_line_ids if line.code == "WORK100")
        absent = sum(abs(line.number_of_days) for line in self.worked_days_line_ids if line.code != "WORK100")
        norm = self._ua_month_workdays(self.contract_id) or worked or 1.0
        time_share = max(min((worked - absent) / norm, 1.0), 0.0) if norm else 1.0
        return fte * time_share

    def ua_index_amount(self):
        return self.ua_index_detail()[0]

    def _ua_payroll_values(self, contracts):
        values = super()._ua_payroll_values(contracts)
        values["index_amount"] = self.ua_index_amount()
        return values

    def _ua_payroll_sources(self, contracts):
        """Джерело index_amount. Не перераховує ua_index_detail() двома різними шляхами -
        викликає той самий метод, яким рахується саме значення."""
        res = super()._ua_payroll_sources(contracts)
        employee = self.employee_id.sudo()
        label = "Сума індексації"

        if employee.ua_index_off:
            res["index_amount"] = _entry(label, "money", "not_applicable",
                                         note="Індексацію вимкнено для працівника (ua_index_off = True).")
            return res

        base = self._ua_index_base_month()
        if not base:
            res["index_amount"] = _entry(label, "money", "not_applicable",
                                         note="Немає базового місяця індексації - ні ua_index_base, "
                                              "ні дати прийняття на роботу не визначено.")
            return res

        months = self._ua_index_months(base)
        if not months:
            res["index_amount"] = _entry(label, "money", "not_applicable",
                                         note="Немає місяців у вікні індексації - базовий місяць збігається "
                                              "з місяцем листка або пізніший за нього.")
            return res

        amount, percent, missing = self.ua_index_detail()
        if amount <= 0:
            res["index_amount"] = _entry(label, "money", "not_applicable",
                                         note="Наростаючий індекс %.1f %% не перевищує поріг - права на "
                                              "виплату індексації ще немає." % percent)
            return res

        source = {"model": "ua.cpi.index",
                  "domain": [("year", ">=", months[0][0]), ("year", "<=", months[-1][0])],
                  "label": "індекси Держстату %s - %s" % (_ua_ym_label(months[0]), _ua_ym_label(months[-1])),
                  "basis": "Постанова КМУ № 1078 (Порядок індексації грошових доходів населення)"}
        note = None
        if missing:
            note = ("Індекс не враховано для %d міс. у вікні (ще не оприлюднений на дату листка) - "
                    "наростаючий відсоток порахований без них." % len(missing))
        res["index_amount"] = _entry(label, "money", "calculated", source=source, note=note)
        return res

    def action_payslip_done(self):
        """Виплачена індексація починає новий цикл: базовим стає місяць листка."""
        res = super().action_payslip_done()
        for slip in self:
            paid = sum(slip.line_ids.filtered(lambda l: l.code == "INDEX").mapped("total"))
            if paid > 0 and slip.date_from:
                employee = slip.employee_id.sudo()
                month = slip.date_from.replace(day=1)
                if not employee.ua_index_paid_month or employee.ua_index_paid_month < month:
                    employee.ua_index_paid_month = month
        return res
