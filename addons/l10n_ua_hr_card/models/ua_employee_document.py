"""Документ працівника: український опис (тип, строк дії, підпис, звіт) над одним вкладенням.

Скан документа - це звичайне `ir.attachment` на картці працівника (`res_model="hr.employee"`),
рівно те сховище, яке показує OCA `hr_employee_document`: кнопка «Документи» на картці і його
правила доступу (працівник бачить свої вкладення) працюють на наших документах без жодного
рядка коду з нашого боку. Раніше файл лежав вкладенням самої моделі `ua.employee.document`
(`res_model="ua.employee.document"`) - для OCA його не існувало, і те саме сховище було двома.

Своїм лишається те, чого upstream не має взагалі: український перелік типів, строк дії з
попередженням за 30 днів, стан підпису, посилання на наказ і на звіт для передруку. Моделі
документа в OCA/hr 19.0 немає - там лише кнопка і права, - тому запис лишається нашим.
"""
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
    attachment_id = fields.Many2one("ir.attachment", "Вкладення", copy=False, readonly=True,
                                    ondelete="set null",
                                    help="Скан документа на картці працівника; його ж показує "
                                         "кнопка «Документи» (OCA hr_employee_document).")
    file = fields.Binary("Файл", compute="_compute_file", inverse="_inverse_file")
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

    # -- скан як вкладення картки працівника ------------------------------------------------------
    @api.depends("attachment_id")
    def _compute_file(self):
        for doc in self:
            doc.file = doc.attachment_id.sudo().datas if doc.attachment_id else False

    def _inverse_file(self):
        Attachment = self.env["ir.attachment"].sudo()
        for doc in self:
            attachment = doc.attachment_id.sudo()
            if not doc.file:
                if attachment:
                    attachment.unlink()
                doc.attachment_id = False
                continue
            values = doc._ua_attachment_values()
            values["datas"] = doc.file
            if attachment:
                attachment.write(values)
            else:
                doc.attachment_id = Attachment.create(values)

    def _ua_attachment_values(self):
        """Куди лягає скан: вкладення працівника, назване так, як документ."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        return {
            "name": self.filename or self.name or "документ",
            "res_model": "hr.employee",
            "res_id": employee.id,
            "company_id": employee.company_id.id or False,
        }

    def write(self, vals):
        res = super().write(vals)
        # перейменували документ або перевели його на іншого працівника - вкладення їде слідом
        if {"filename", "name", "employee_id"} & set(vals):
            for doc in self.filtered("attachment_id"):
                doc.attachment_id.sudo().write(doc._ua_attachment_values())
        return res

    def unlink(self):
        attachments = self.mapped("attachment_id").sudo()
        res = super().unlink()
        attachments.unlink()
        return res

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
        # "done" для ua_act (docs/payroll/action-model.md): один рядок на документ, ціль -
        # сам документ, щоб рядок наслідку на картці вів на нього.
        return {
            "done": [
                {
                    "text": _("Документ «%s» підписано.") % (doc.name or _("без назви")),
                    "target": {"res_model": "ua.employee.document", "res_id": doc.id},
                }
                for doc in self
            ],
        }

    def action_unmark_signed(self):
        """Чесний зворотний бік action_mark_signed - для вікна скасування «узгодження»
        (docs/payroll/action-model.md): знімає дату підпису й повертає документ у «на підпис».

        Відмовляє, коли підпис уже використано в спосіб, що робить тихий відкат нечесним:
        документ наказу (order_id - поле з l10n_ua_hr_orders, тут лише за наявності модуля),
        чий наказ уже ознайомлено. Ознайомлення (ua.hr.order.action_acknowledge) саме на
        підставі підпису цього документа пише order.ack_date/ack_user_id; тихе повернення
        документа в "на підпис" лишило б наказ "ознайомленим" без документа, що це
        підтверджує - двоє записів розійшлися б без сліду. Правильний шлях - спершу
        скасувати наказ (action_cancel, що й чистить ack_date), а вже тоді знімати підпис
        документа. Звичайні документи (без order_id, або чий наказ ще не ознайомлено)
        відкату не бояться - нижче них нічого не стоїть."""
        for doc in self:
            if doc.state != "signed":
                raise UserError(
                    _("Документ «%s» не підписано - скасовувати нема чого.") % (doc.name or _("без назви"))
                )
            if "order_id" in doc._fields and doc.order_id and doc.order_id.state == "acknowledged":
                raise UserError(_(
                    "Наказ «%s» вже ознайомлено на підставі цього документа. "
                    "Спершу скасуйте наказ - це так само очистить ознайомлення - а тоді "
                    "підпис документа можна буде зняти."
                ) % doc.order_id.display_name)
            doc.write({"state": "to_sign", "signed_date": False})
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
