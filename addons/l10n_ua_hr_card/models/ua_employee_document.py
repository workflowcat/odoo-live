from odoo import fields, models

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
