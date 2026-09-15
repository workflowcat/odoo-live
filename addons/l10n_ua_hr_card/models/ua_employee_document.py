import json
from datetime import timedelta
from urllib.parse import urlencode

from odoo import _, api, fields, models
from odoo.exceptions import UserError

TYPES = [
    ("passport", "Паспорт"),
    ("rnokpp", "РНОКПП"),
    ("diploma", "Диплом"),
    ("labor_book", "Трудова книжка"),
    ("military_id", "Військовий квиток"),
    ("medical", "Медична довідка"),
    ("contract", "Договір"),
    ("statement", "Заява"),
    ("nda", "Договір про нерозголошення"),
    ("consent", "Згода на обробку ПД"),
    ("ack", "Лист ознайомлення"),
    ("order", "Наказ"),
    ("other", "Інше"),
]
STATE = [("ok", "діє"), ("warning", "спливає"), ("expired", "прострочений")]
# Стан підпису: документи, що не потребують підпису (скани, довідки), лишаються "не потрібен".
SIGN_STATE = [
    ("to_sign", "На підпис"),
    ("signed", "Підписано"),
    ("not_needed", "Не потрібен"),
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
    ua_doc_state = fields.Selection(STATE, string="Стан", compute="_compute_ua_doc_state")

    # -- підпис -----------------------------------------------------------------------------------
    # Документи, що мають бути підписані (заява, трудовий договір, NDA, згода на обробку ПД,
    # лист ознайомлення, кожен кадровий наказ), проходять на_підпис -> підписано. Документи, що
    # підпису не потребують (скан паспорта тощо), лишаються "не потрібен".
    state = fields.Selection(SIGN_STATE, string="Стан підпису", default="not_needed", required=True)
    signed_date = fields.Date("Дата підпису")
    # order_id (Many2one ua.hr.order) живе в l10n_ua_card_ui, не тут: l10n_ua_hr_orders
    # залежить від l10n_ua_hr_card (не навпаки), тому пряме Many2one з цього модуля на
    # ua.hr.order дало б циклічну залежність. l10n_ua_card_ui тягне обидва - там і поле.
    # звіт, яким документ можна передрукувати: report_xmlid - "r" з /ua/print (xmlid QWeb-шаблону,
    # тобто report_name звіту, не xmlid самого ir.actions.report), res_model/res_id - запис-джерело
    # (справа прийняття для пакета першого дня, наказ для кожного кадрового наказу).
    report_xmlid = fields.Char("Звіт (xmlid)")
    res_model = fields.Char("Модель джерела")
    res_id = fields.Integer("ID джерела")

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

    def action_mark_signed(self):
        today = fields.Date.context_today(self)
        self.write({"state": "signed", "signed_date": today})
        return True

    def action_print(self):
        self.ensure_one()
        if not self.report_xmlid or not self.res_id:
            raise UserError(_("Для цього документа не налаштовано звіт для друку."))
        items = json.dumps([{"r": self.report_xmlid, "ids": [self.res_id], "t": self.name}], ensure_ascii=False)
        return {
            "type": "ir.actions.act_url",
            "target": "new",
            "url": "/ua/print?" + urlencode({"items": items}),
        }
