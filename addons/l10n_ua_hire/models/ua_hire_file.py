# -*- coding: utf-8 -*-
from odoo import fields, models

DOC_TYPES = [
    ("statement", "Заява про прийняття"),
    ("passport", "Паспорт або ID-картка"),
    ("rnokpp", "РНОКПП"),
    ("military_id", "Військовий документ"),
    ("diploma", "Диплом"),
    ("labor_book", "Трудова книжка"),
    ("consent", "Згода на обробку персональних даних"),
    ("medical", "Медична довідка"),
    ("other", "Інше"),
]
EXTRACT_STATES = [("none", "не розпізнано"), ("done", "розпізнано"), ("failed", "помилка")]


class UaHireFile(models.Model):
    _name = "ua.hire.file"
    _description = "Файл справи прийняття"
    _order = "id"

    case_id = fields.Many2one("ua.hire.case", "Справа", required=True, ondelete="cascade", index=True)
    name = fields.Char("Назва", required=True)
    doc_type = fields.Selection(DOC_TYPES, "Вид документа", required=True, default="other")
    file = fields.Binary("Файл", attachment=True)
    filename = fields.Char("Ім'я файлу")
    extract_state = fields.Selection(EXTRACT_STATES, "Розпізнавання", default="none", required=True)
    extract_note = fields.Char("Примітка розпізнавання")

    def set_doc_type(self, doc_type):
        self.write({"doc_type": doc_type, "extract_state": "none"})
        return True
