from datetime import timedelta

from odoo import api, fields, models

TYPES = [
    ("passport", "Паспорт"),
    ("rnokpp", "РНОКПП"),
    ("diploma", "Диплом"),
    ("labor_book", "Трудова книжка"),
    ("military_id", "Військовий квиток"),
    ("medical", "Медична довідка"),
    ("contract", "Договір"),
    ("statement", "Заява"),
    ("other", "Інше"),
]
STATE = [("ok", "діє"), ("warning", "спливає"), ("expired", "прострочений")]


class UaEmployeeDocument(models.Model):
    _name = "ua.employee.document"
    _description = "Документ працівника"
    _order = "valid_until, date"

    employee_id = fields.Many2one("hr.employee", string="Працівник", required=True, ondelete="cascade")
    type = fields.Selection(TYPES, string="Тип", required=True, default="other")
    name = fields.Char("Назва", required=True)
    number = fields.Char("Номер")
    date = fields.Date("Дата")
    valid_until = fields.Date("Діє до")
    file = fields.Binary("Файл", attachment=True)
    filename = fields.Char("Ім'я файлу")
    note = fields.Char("Примітка")
    ua_doc_state = fields.Selection(STATE, string="Стан", compute="_compute_ua_doc_state")

    @api.depends("valid_until")
    def _compute_ua_doc_state(self):
        today = fields.Date.context_today(self)
        limit = today + timedelta(days=30)
        for doc in self:
            if not doc.valid_until:
                doc.ua_doc_state = "ok"
            elif doc.valid_until < today:
                doc.ua_doc_state = "expired"
            elif doc.valid_until <= limit:
                doc.ua_doc_state = "warning"
            else:
                doc.ua_doc_state = "ok"
