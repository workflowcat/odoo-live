"""Заморожений слід розрахунку: знятий один раз, у момент проведення документа.

Рядок ніколи не переписується - нова заморозка завжди створює новий рядок.
Переможець визначається сортуванням (frozen_at desc, id desc), не update.
Так старий проведений розрахунок лишається таким, яким був, навіть якщо
сьогоднішні параметри чи правила зміняться заднім числом (третій шар моделі
з docs/payroll/explain-model.md - "Історія: як було тоді")."""

import json

from odoo import api, fields, models


class UaExplainTrace(models.Model):
    _name = "ua.explain.trace"
    _description = "Заморожений слід розрахунку"
    _order = "frozen_at desc, id desc"

    model_name = fields.Char("Модель", required=True, index=True)
    res_id = fields.Integer("ID запису", index=True)
    res_name = fields.Char("Назва запису")
    employee_id = fields.Many2one("hr.employee", string="Працівник", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", string="Компанія", default=lambda self: self.env.company)
    year = fields.Integer("Рік", index=True)
    month = fields.Integer("Місяць", index=True)
    payload = fields.Text("Дані (JSON)")
    frozen_at = fields.Datetime("Заморожено")
    frozen_by = fields.Many2one("res.users", string="Заморозив")

    @api.model
    def freeze(self, record, payload_dict):
        """Створити новий рядок сліду для запису. Завжди create, ніколи write
        на наявний рядок - див. пояснення у шапці файлу."""
        subject = payload_dict.get("subject") or {}
        employee = subject.get("employee") or {}
        period = subject.get("period") or ""
        year = month = False
        if period and "-" in period:
            y, m = (period.split("-") + ["", ""])[:2]
            try:
                year, month = int(y), int(m)
            except ValueError:
                year = month = False
        company = record.company_id if "company_id" in record._fields and record.company_id else self.env.company
        return self.sudo().create({
            "model_name": subject.get("model") or record._name,
            "res_id": subject.get("res_id") or record.id,
            "res_name": subject.get("label") or record.display_name,
            "employee_id": employee.get("id") or False,
            "company_id": company.id,
            "year": year,
            "month": month,
            "payload": json.dumps(payload_dict, ensure_ascii=False, default=str),
            "frozen_at": fields.Datetime.now(),
            "frozen_by": self.env.uid,
        })
