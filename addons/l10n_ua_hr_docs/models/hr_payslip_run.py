# -*- coding: utf-8 -*-
"""Пакет листків місяця: заява-розрахунок ПФУ з нього і процедура відкриття місяця.

`ua_prepare_month` - те, що робить бухгалтер на початку місяця: табель, пакет,
чернетка листка на кожного працівника з чинною версією договору, перерахунок.
Процедура живе тут, бо тут і створюються її записи (пакет, листки, табель поруч
у цьому ж модулі); сторінка «Період» лише кличе її кнопкою.
"""
from datetime import date, timedelta

from odoo import _, api, models


def _bounds(year, month):
    """Перший і останній день місяця."""
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return first, last


def as_company(env, company):
    """Компанія з запису, з id або з середовища - логіку кличуть і з Python, і по RPC."""
    if isinstance(company, int):
        return env["res.company"].browse(company)
    return company or env.company


class HrPayslipRun(models.Model):
    _inherit = "hr.payslip.run"

    def action_ua_pfu_claim(self):
        self.ensure_one()
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", self.id), ("state", "=", "draft")], limit=1)
        if not claim:
            claim = self.env["ua.pfu.claim"].create({"payslip_run_id": self.id, "company_id": self.company_id.id})
            claim.action_refill()
        return {
            "type": "ir.actions.act_window",
            "res_model": "ua.pfu.claim",
            "view_mode": "form",
            "res_id": claim.id,
            "target": "current",
        }

    # ------------------------------------------------------------------ складання
    @api.model
    def ua_compose(self, company, year=None, month=None, **params):
        """Новий пакет листків на місяць: назва, межі місяця, компанія."""
        company = as_company(self.env, company)
        year, month = int(year), int(month)
        first, last = _bounds(year, month)
        return self.create({
            "name": _("Зарплата %(month)02d.%(year)s") % {"month": month, "year": year},
            "date_start": first, "date_end": last, "company_id": company.id,
        })

    # ------------------------------------------------------------------ відкриття місяця
    @api.model
    def ua_prepare_month(self, company, year, month):
        """Підготувати місяць: табель, чернетки листків, перерахунок.

        Нічого не проводить і нічого не платить. Мета - щоб бухгалтер побачив числа
        і перелік винятків, а не заповнював документи руками."""
        company = as_company(self.env, company)
        year, month = int(year), int(month)
        first, last = _bounds(year, month)
        done = []

        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)], limit=1)
        if not sheet:
            sheet = self.env["ua.timesheet.sheet"].create({
                "company_id": company.id, "year": year, "month": month})
            sheet.action_refill()
            done.append(_("табель створено"))
        elif sheet.state == "draft" and not sheet.line_ids:
            sheet.action_refill()
            done.append(_("табель заповнено"))

        Payslip = self.env["hr.payslip"]
        existing = Payslip.search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel")])
        covered = existing.mapped("employee_id")
        run = self.search([
            ("company_id", "=", company.id), ("date_start", "=", first), ("date_end", "=", last)], limit=1)
        if not run:
            run = self.ua_compose(company, year, month)
        created = 0
        for employee in self.env["hr.employee"].search([("company_id", "=", company.id), ("active", "=", True)]):
            if employee in covered:
                continue
            version = employee.sudo().version_ids.filtered(
                lambda v: v.contract_date_start and v.contract_date_start <= last
                and (not v.contract_date_end or v.contract_date_end >= first)).sorted("contract_date_start")[-1:]
            if not version:
                continue
            slip = Payslip.create({
                "employee_id": employee.id, "date_from": first, "date_to": last,
                "payslip_run_id": run.id, "company_id": company.id,
            })
            slip.onchange_employee()
            created += 1
        if created:
            done.append(_("створено листків: %s") % created)

        drafts = Payslip.search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "in", ("draft", "verify"))])
        if drafts:
            drafts.compute_sheet()
            done.append(_("перераховано листків: %s") % len(drafts))
        return {"message": "; ".join(done) if done else _("Змінювати не було чого: місяць уже підготовлено.")}
