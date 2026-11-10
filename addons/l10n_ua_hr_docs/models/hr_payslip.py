# -*- coding: utf-8 -*-
"""Затверджений табель - джерело відпрацьованого часу для розрахункового листка.

Без табеля листок рахує дні за графіком, як раніше. Коли за місяць є затверджений табель,
дні і години у листку беруться з нього, а оклад рахується пропорційно: за годинами, якщо
заповнені норма і факт годин, інакше за днями.

Так бухгалтер виправляє час в одному місці - у табелі - і натискає «Перерахувати листки».
"""
from odoo import models

_UA_MONTHS = {1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
              7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень"}


def _ua_sheet_label(sheet):
    """Назва табеля людською мовою: «табель за вересень 2026». Після «за» - знахідний відмінок."""
    return "табель за %s %d" % (_UA_MONTHS.get(sheet.month, str(sheet.month)), sheet.year)


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

    def _ua_timesheet_line(self):
        """Рядок затвердженого табеля за місяць листка, якщо він є."""
        self.ensure_one()
        if not self.employee_id or not self.date_from:
            return None
        line = self.env["ua.timesheet.line"].sudo().search([
            ("employee_id", "=", self.employee_id.id),
            ("sheet_id.state", "=", "confirmed"),
            ("sheet_id.year", "=", self.date_from.year),
            ("sheet_id.month", "=", self.date_from.month),
            ("sheet_id.company_id", "=", self.company_id.id),
        ], limit=1)
        return line or None

    # Назви рядків відпрацьованого часу. Рушій OCA пише назву перекладом у момент
    # створення листка, тому в старих листках лишається англійський текст.
    UA_WORKED_NAMES = {"WORK100": "Відпрацьовані дні"}

    def get_worked_day_lines(self, contracts, date_from, date_to):
        """Дні і години WORK100 з табеля. Дні відсутності лишаються окремими рядками,
        тому у WORK100 тримаємо суму «факт + відсутності», як це робить рушій OCA."""
        res = super().get_worked_day_lines(contracts, date_from, date_to)
        for vals in res:
            name = self.UA_WORKED_NAMES.get(vals.get("code"))
            if name:
                vals["name"] = name
        line = self._ua_timesheet_line()
        if not line:
            return res
        absent_days = line._absent_days()
        hours_day = line.hours_day or (line.norm_hours / line.norm_days if line.norm_days else 8.0)
        for vals in res:
            if vals.get("code") == "WORK100":
                vals["number_of_days"] = line.days_worked + absent_days
                vals["number_of_hours"] = line.hours + absent_days * hours_day
        return res

    def compute_sheet(self):
        """Перед розрахунком оновлюємо відпрацьований час із затвердженого табеля.

        OCA рахує рядки листка, але не переписує «Відпрацьовано», тому робимо це самі:
        інакше у друкованому листку лишилися б дні за графіком, а сума - за табелем.
        """
        for slip in self:
            if not slip._ua_timesheet_line():
                continue
            contracts = slip._get_employee_contracts()
            if not contracts:
                continue
            worked = slip.get_worked_day_lines(contracts, slip.date_from, slip.date_to)
            slip.worked_days_line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in worked]
        return super().compute_sheet()

    def _ua_payroll_values(self, contracts):
        values = super()._ua_payroll_values(contracts)
        line = self._ua_timesheet_line()
        ratio = -1.0
        if line:
            # norm_hours у табелі вже враховує ставку (weekly_hours × робочі дні / 5 × fte,
            # addons/l10n_ua_hr_docs/models/ua_timesheet_sheet.py::_compute_norm) - тут fte
            # вдруге не множимо, інакше очікувані години заниження вдвічі і ratio впирається в 1.0
            expected_hours = line.norm_hours
            if expected_hours and line.hours:
                ratio = line.hours / expected_hours
            elif line.norm_days:
                ratio = line.days_worked / line.norm_days
            ratio = min(max(ratio, 0.0), 1.0) if ratio >= 0 else -1.0
        values["time_ratio"] = ratio
        values.update(self._ua_pay_type_values(contracts, line))
        return values

    def _ua_pay_type_values(self, contracts, line):
        """pay_type/hour_rate/fact_hours/night_hours для правил HOURLY і NIGHT.

        hour_rate - завжди «грн/год»: для погодинних це ставка з версії контракту,
        для окладних - еквівалент (оклад / норма годин місяця), потрібний лише для
        нічної надбавки (ст. 108 КЗпП рахує від годинної ставки, не від окладу)."""
        contract = contracts[:1]
        pay_type = contract.ua_pay_type if contract else "monthly"
        fact_hours = line.hours if line else 0.0
        night_hours = line.night_hours if line else 0.0
        if pay_type == "hourly":
            hour_rate = contract.ua_hour_rate or 0.0
        else:
            norm_hours = line.norm_hours if line else 0.0
            if not norm_hours:
                weekly_hours = contract.ua_weekly_hours if contract and contract.ua_weekly_hours else 40.0
                norm_hours = weekly_hours * 52.0 / 12.0
            wage = contract.wage or 0.0
            hour_rate = (wage / norm_hours) if norm_hours else 0.0
        return {"pay_type": pay_type, "hour_rate": hour_rate, "fact_hours": fact_hours, "night_hours": night_hours}

    def _ua_payroll_sources(self, contracts):
        """Джерела входів, які додає цей модуль: time_ratio і все, що повертає _ua_pay_type_values().

        Викликає _ua_timesheet_line() - той самий метод, яким рахуються самі значення,
        і не робить окремого важкого запиту."""
        res = super()._ua_payroll_sources(contracts)
        line = self._ua_timesheet_line()
        contract = contracts[:1]

        sheet_source = None
        if line:
            sheet_source = {"model": "ua.timesheet.sheet", "res_id": line.sheet_id.id,
                            "label": _ua_sheet_label(line.sheet_id),
                            "basis": "Затверджений табель обліку робочого часу (форма П-5)"}

        # time_ratio: сентинел -1, коли табеля немає - розрахунок мовчки переходить на графік контракту.
        if not line:
            res["time_ratio"] = _entry(
                "Частка відпрацьованого часу з табеля", "share", "missing",
                note="Немає затвердженого табеля за місяць листка - time_ratio = -1, і мінімальна "
                     "зарплата/оклад рахуються від графіка контракту, а не від табеля.")
        else:
            res["time_ratio"] = _entry("Частка відпрацьованого часу з табеля", "share", "supplied",
                                       source=sheet_source)

        # pay_type і hour_rate: залежать від контракту (версії), не від табеля.
        if not contract:
            no_contract_note = "Немає активного контракту (версії) на дату листка."
            res["pay_type"] = _entry("Вид оплати", "flag", "missing", note=no_contract_note)
            res["hour_rate"] = _entry("Годинна ставка", "money", "missing", note=no_contract_note)
            pay_type = "monthly"
        else:
            contract_source = {"model": "hr.version", "res_id": contract.id,
                               "label": "версія контракту працівника", "basis": "Умови оплати праці (hr.version)"}
            pay_type = contract.ua_pay_type or "monthly"
            res["pay_type"] = _entry("Вид оплати", "flag", "supplied", source=contract_source)
            if pay_type == "hourly":
                res["hour_rate"] = _entry("Годинна ставка", "money", "supplied", source=contract_source)
            else:
                res["hour_rate"] = _entry(
                    "Годинна ставка (еквівалент окладу)", "money", "calculated",
                    note="Оклад контракту поділено на норму годин місяця; потрібна лише для нічної "
                         "надбавки (ст. 108 КЗпП рахує від годинної ставки, не від окладу).")

        # fact_hours: застосовується лише до погодинної оплати (правило HOURLY, ua_salary_rules_pay.xml).
        if pay_type != "hourly":
            res["fact_hours"] = _entry(
                "Фактичні години з табеля", "hours", "not_applicable",
                note="Погодинні ключі не застосовуються: контракт на окладі (BASIC), не погодинна оплата.")
        elif not line:
            res["fact_hours"] = _entry(
                "Фактичні години з табеля", "hours", "missing",
                note="Немає затвердженого табеля - фактичні години невідомі, погодинний розрахунок піде з нулем.")
        else:
            res["fact_hours"] = _entry("Фактичні години з табеля", "hours", "supplied", source=sheet_source)

        # night_hours: діє для обох видів оплати (умова правила NIGHT - лише bool(night_hours)).
        if not line:
            res["night_hours"] = _entry(
                "Нічні години з табеля", "hours", "missing",
                note="Немає затвердженого табеля - нічні години невідомі (0), надбавка не нарахується, "
                     "навіть якщо нічні зміни фактично були.")
        else:
            res["night_hours"] = _entry("Нічні години з табеля", "hours", "supplied", source=sheet_source)

        return res
