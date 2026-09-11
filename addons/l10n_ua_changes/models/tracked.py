# -*- coding: utf-8 -*-
"""Перелік того, що потрапляє в журнал змін.

Один блок на модель. Пишемо тільки поля, які змінюють гроші, час, стан документа
або законодавчий параметр. Решту полів журнал не чіпає, щоб не тонути в дрібницях.
"""
from odoo import fields, models


class UaHrOrder(models.Model):
    _name = "ua.hr.order"
    _inherit = ["ua.hr.order", "ua.change.mixin"]

    _ua_change_area = "hr"
    _ua_change_fields = {
        "state": "Стан наказу", "date": "Дата наказу", "employee_id": "Працівник",
        "wage": "Оклад", "date_from": "З дати", "date_to": "По дату",
        "order_type": "Вид наказу", "fte": "Ставка",
    }
    _ua_change_unlink = True

    def _ua_change_label(self):
        """Чернетка наказу ще не має номера. Пишемо вид наказу і працівника."""
        if self.name:
            return "%s · %s" % (self.name, self.employee_id.name or "")
        kind = dict(self._fields["order_type"].selection).get(self.order_type, "наказ")
        return "%s (чернетка) · %s" % (kind, self.employee_id.name or "")

    def _ua_change_period(self):
        day = self.date or fields.Date.context_today(self)
        return day.year, day.month


class UaTimesheetSheet(models.Model):
    _name = "ua.timesheet.sheet"
    _inherit = ["ua.timesheet.sheet", "ua.change.mixin"]

    _ua_change_area = "time"
    _ua_change_fields = {"state": "Стан табеля"}

    def _ua_change_period(self):
        return self.year, self.month


class UaTimesheetLine(models.Model):
    _name = "ua.timesheet.line"
    _inherit = ["ua.timesheet.line", "ua.change.mixin"]

    _ua_change_area = "time"
    _ua_change_fields = {"days_worked": "Відпрацьовано днів", "hours": "Відпрацьовано годин"}
    _ua_change_unlink = False

    def _ua_change_label(self):
        return self.employee_id.name or ""

    def _ua_change_company(self):
        return self.sheet_id.company_id or self.env.company

    def _ua_change_period(self):
        return self.sheet_id.year, self.sheet_id.month


class HrPayslip(models.Model):
    _name = "hr.payslip"
    _inherit = ["hr.payslip", "ua.change.mixin"]

    _ua_change_area = "payroll"
    _ua_change_fields = {"state": "Стан листка", "date_from": "Період з", "date_to": "Період по"}

    def _ua_change_keep(self, fname, old, new):
        """Проміжні стани розрахунку не цікаві. Пишемо проведення і скасування."""
        if fname == "state":
            return "done" in (old, new) or "cancel" in (old, new)
        return True

    def _ua_change_period(self):
        day = self.date_from or fields.Date.context_today(self)
        return day.year, day.month


class HrPayslipInput(models.Model):
    _name = "hr.payslip.input"
    _inherit = ["hr.payslip.input", "ua.change.mixin"]

    _ua_change_area = "payroll"
    _ua_change_fields = {"amount": "Сума введення"}
    _ua_change_create = True

    def _ua_change_loggable(self):
        """Розрахунок листка створює порожні рядки введення для кожного правила. Їх не пишемо."""
        return bool(self.amount)

    def _ua_change_label(self):
        return "%s · %s" % (self.payslip_id.employee_id.name or "", self.name or self.code or "")

    def _ua_change_company(self):
        return self.payslip_id.company_id or self.env.company

    def _ua_change_period(self):
        day = self.payslip_id.date_from or fields.Date.context_today(self)
        return day.year, day.month


class HrPayslipLine(models.Model):
    _name = "hr.payslip.line"
    _inherit = ["hr.payslip.line", "ua.change.mixin"]

    _ua_change_area = "payroll"
    _ua_change_fields = {"amount": "Сума рядка", "quantity": "Кількість", "rate": "Відсоток"}
    _ua_change_unlink = False

    def _ua_change_label(self):
        return "%s · %s" % (self.slip_id.employee_id.name or "", self.name or self.code or "")

    def _ua_change_company(self):
        return self.slip_id.company_id or self.env.company

    def _ua_change_period(self):
        day = self.slip_id.date_from or fields.Date.context_today(self)
        return day.year, day.month


class HrVersion(models.Model):
    _name = "hr.version"
    _inherit = ["hr.version", "ua.change.mixin"]

    _ua_change_area = "hr"
    _ua_change_fields = {"wage": "Оклад", "contract_date_start": "Діє з", "contract_date_end": "Діє по",
                         "struct_id": "Структура нарахування"}

    def _ua_change_label(self):
        return self.employee_id.name or self.name or ""


class HrEmployee(models.Model):
    _name = "hr.employee"
    _inherit = ["hr.employee", "ua.change.mixin"]

    _ua_change_area = "hr"
    _ua_change_fields = {"name": "Прізвище, ім'я, по батькові", "ua_rnokpp": "РНОКПП",
                         "ua_psp": "Податкова пільга", "ua_fte": "Ставка",
                         "ua_esv_category": "Категорія ЄСВ", "departure_date": "Дата звільнення"}
    _ua_change_unlink = True


class HrLeave(models.Model):
    _name = "hr.leave"
    _inherit = ["hr.leave", "ua.change.mixin"]

    _ua_change_area = "hr"
    _ua_change_fields = {"state": "Стан відсутності", "request_date_from": "З дати",
                         "request_date_to": "По дату", "holiday_status_id": "Вид відсутності",
                         "number_of_days": "Днів"}
    _ua_change_create = True

    def _ua_change_label(self):
        return "%s · %s" % (self.employee_id.name or "", self.holiday_status_id.name or "")

    def _ua_change_period(self):
        day = self.request_date_from or fields.Date.context_today(self)
        return day.year, day.month


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "ua.change.mixin"]

    _ua_change_area = "account"
    _ua_change_fields = {"state": "Стан проводки", "date": "Дата проводки", "ref": "Опис"}

    def _ua_change_period(self):
        day = self.date or fields.Date.context_today(self)
        return day.year, day.month


class AccountBankStatementLine(models.Model):
    _name = "account.bank.statement.line"
    _inherit = ["account.bank.statement.line", "ua.change.mixin"]

    _ua_change_area = "bank"
    _ua_change_fields = {"amount": "Сума", "date": "Дата", "partner_id": "Контрагент",
                         "payment_ref": "Призначення"}

    def _ua_change_period(self):
        day = self.date or fields.Date.context_today(self)
        return day.year, day.month


class UaPaymentBatch(models.Model):
    _name = "ua.payment.batch"
    _inherit = ["ua.payment.batch", "ua.change.mixin"]

    _ua_change_area = "bank"
    _ua_change_fields = {"state": "Стан відомості", "pay_date": "Дата виплати",
                         "journal_id": "Банк"}

    def _ua_change_period(self):
        return self.year, self.month


class UaPaymentLine(models.Model):
    _name = "ua.payment.line"
    _inherit = ["ua.payment.line", "ua.change.mixin"]

    _ua_change_area = "bank"
    _ua_change_fields = {"amount": "Сума до виплати", "account_number": "Рахунок (IBAN)"}
    _ua_change_unlink = False

    def _ua_change_label(self):
        return self.employee_id.name or ""

    def _ua_change_company(self):
        return self.batch_id.company_id or self.env.company

    def _ua_change_period(self):
        return self.batch_id.year, self.batch_id.month


class UaAdvanceSheet(models.Model):
    _name = "ua.advance.sheet"
    _inherit = ["ua.advance.sheet", "ua.change.mixin"]

    _ua_change_area = "payroll"
    _ua_change_fields = {"state": "Стан авансу", "percent": "Відсоток окладу",
                         "pay_date": "Дата виплати"}

    def _ua_change_period(self):
        return self.year, self.month


class UaReportRun(models.Model):
    _name = "ua.report.run"
    _inherit = ["ua.report.run", "ua.change.mixin"]

    _ua_change_area = "report"
    _ua_change_fields = {"state": "Стан звіту"}

    def _ua_change_period(self):
        month = self.month or (self.quarter * 3 if self.quarter else fields.Date.context_today(self).month)
        return self.year, month


class UaPayrollParam(models.Model):
    _name = "ua.payroll.param"
    _inherit = ["ua.payroll.param", "ua.change.mixin"]

    _ua_change_area = "setup"
    _ua_change_fields = {"value": "Значення", "valid_from": "Діє з"}
    _ua_change_create = True

    def _ua_change_company(self):
        return self.company_id or self.env.company


class UaCpiIndex(models.Model):
    _name = "ua.cpi.index"
    _inherit = ["ua.cpi.index", "ua.change.mixin"]

    _ua_change_area = "setup"
    _ua_change_fields = {"value": "Індекс, %"}
    _ua_change_create = True

    def _ua_change_company(self):
        return self.env.company
