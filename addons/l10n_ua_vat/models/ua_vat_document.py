# -*- coding: utf-8 -*-
"""Реєстр податкових накладних і розрахунків коригування.

У пісочниці ці документи жили в спільному реєстрі ua_docs_hub - хабі на всі
первинні документи компанії (акти, видаткові, рахунки). Тягнути сюди весь хаб
немає сенсу: ПДВ потрібні від нього рівно дві речі - запис про документ і його
зв'язок із проводкою. Тому тут свій вузький реєстр на два типи документів, без
PDF-конвеєра і версіонування.

Що реєстр знає:
* який це документ - податкова накладна (ПН) чи розрахунок коригування (РК);
* з якої проводки або рахунку він складений;
* коли його зареєстровано в ЄРПН, який граничний строк і скільки коштує
  прострочення;
* реквізити РК: причина коригування, первинна ПН, хто реєструє.
"""
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

# Умовні коди причин коригування (графа 2.1 розділу Б РК), довідник ДПС.
UA_ADJ_REASONS = [
    ("101", "101 - Зміна ціни"),
    ("102", "102 - Зміна кількості"),
    ("103", "103 - Повернення товару або авансових платежів"),
    ("104", "104 - Зміна номенклатури"),
    ("201", "201 - Коригування зведеної ПН (п.198.5 ПКУ)"),
    ("202", "202 - Коригування зведеної ПН (п.199.1 ПКУ)"),
    ("301", "301 - Виправлення помилки (п.24 Порядку №1307)"),
]

UA_DOC_KINDS = [
    ("tax_invoice", "Податкова накладна"),
    ("adjustment", "Розрахунок коригування"),
]


class UaVatDocument(models.Model):
    _name = "ua.vat.document"
    _description = "Податкова накладна / розрахунок коригування"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(string="Назва", required=True, copy=False)
    doc_kind = fields.Selection(
        UA_DOC_KINDS, string="Тип документа", required=True, index=True)
    move_id = fields.Many2one(
        "account.move",
        string="Проводка / рахунок",
        ondelete="cascade",
        index=True,
        help="Рахунок, з якого складено ПН, повернення, з якого складено РК, "
             "або службова проводка компенсуючих ПЗ.",
    )
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", string="Контрагент",
        related="move_id.partner_id", store=True)
    date = fields.Date(
        string="Дата складання", compute="_compute_date", store=True)

    # --- Реєстрація в ЄРПН -----------------------------------------------

    x_pn_registered_date = fields.Date(
        string="Зареєстровано в ЄРПН",
        copy=False,
        tracking=True,
        help="Дата реєстрації в ЄРПН. Зареєстрована до строку - без ризику; "
             "після - прострочення фіксується цією датою, а штраф лишається "
             "історичним фактом.",
    )
    state = fields.Selection(
        selection=[("draft", "Складено"), ("registered", "Зареєстровано")],
        string="Стан", compute="_compute_state", store=True)

    # --- Зведена (компенсуюча) ПН ----------------------------------------

    x_pn_consolidated = fields.Boolean(
        string="Зведена ПН",
        default=False,
        help="Зведена податкова накладна за п.198.5 або ст.199 ПКУ: "
             "складається не пізніше останнього дня звітного періоду, "
             "реєструється протягом 20 календарних днів після останнього дня "
             "місяця складання.",
    )
    x_pn_reason_type = fields.Char(
        string="Тип причини",
        size=2,
        help="Код типу причини зведеної ПН (Порядок №1307): 04 - постачання у "
             "межах балансу, 08 - необ'єктні операції, 09 - звільнені "
             "операції, 13 - негосподарське використання.",
    )

    # --- Реквізити РК -----------------------------------------------------

    x_adj_reason_code = fields.Selection(
        UA_ADJ_REASONS,
        string="Причина коригування",
        help="Умовний код причини коригування з довідника ДПС (графа 2.1 "
             "розділу Б РК).",
    )
    x_adj_pn_document_id = fields.Many2one(
        "ua.vat.document",
        string="Первинна ПН",
        domain=[("doc_kind", "=", "tax_invoice")],
        compute="_compute_x_adj_pn_document",
        store=True,
        readonly=False,
        help="Податкова накладна, яку коригує цей РК. Знаходиться за первинним "
             "рахунком повернення; можна змінити вручну.",
    )
    x_adj_direction = fields.Selection(
        selection=[("decrease", "Зменшення"), ("increase", "Збільшення")],
        string="Напрямок коригування",
        compute="_compute_x_adj_direction",
        store=True,
    )
    x_adj_registrant = fields.Selection(
        selection=[("buyer", "покупець"), ("seller", "продавець")],
        string="Реєструє",
        compute="_compute_x_adj_direction",
        store=True,
        help="п.192.1 ПКУ: зменшуючий РК реєструє покупець, збільшуючий - "
             "продавець.",
    )

    # --- Строк реєстрації і штраф (дзеркало рахунку) ----------------------

    x_pn_deadline = fields.Date(
        related="move_id.x_pn_deadline",
        string="Граничний строк реєстрації",
        store=True,
    )
    x_pn_overdue_days = fields.Integer(
        string="Прострочено, днів", compute="_compute_x_pn_mirror")
    x_pn_fine_est = fields.Monetary(
        string="Орієнтовний штраф",
        currency_field="currency_id",
        compute="_compute_x_pn_mirror",
    )

    @api.depends("move_id.invoice_date", "move_id.date", "x_pn_consolidated")
    def _compute_date(self):
        """Дата складання: для зведеної - дата проводки (останній день
        періоду), інакше - дата рахунку."""
        today = fields.Date.context_today(self)
        for doc in self:
            move = doc.move_id
            if not move:
                doc.date = today
                continue
            doc.date = (move.date if doc.x_pn_consolidated
                        else move.invoice_date) or move.date or today

    @api.depends("x_pn_registered_date")
    def _compute_state(self):
        for doc in self:
            doc.state = "registered" if doc.x_pn_registered_date else "draft"

    @api.depends("doc_kind", "move_id.reversed_entry_id")
    def _compute_x_adj_pn_document(self):
        """Первинна ПН для РК - податкова накладна первинного рахунку."""
        for doc in self:
            if doc.doc_kind != "adjustment" or doc.x_adj_pn_document_id:
                continue
            try:
                origin = doc.move_id.reversed_entry_id
                doc.x_adj_pn_document_id = origin.ua_vat_document_ids.filtered(
                    lambda d: d.doc_kind == "tax_invoice")[:1]
            except Exception:
                doc.x_adj_pn_document_id = False

    @api.depends("doc_kind", "move_id.move_type")
    def _compute_x_adj_direction(self):
        """РК із повернення - завжди зменшення, реєструє покупець
        (п.192.1 ПКУ). Решта випадків - збільшення, реєструє продавець."""
        for doc in self:
            direction, registrant = False, False
            if doc.doc_kind == "adjustment":
                if doc.move_id and doc.move_id.move_type == "out_refund":
                    direction, registrant = "decrease", "buyer"
                else:
                    direction, registrant = "increase", "seller"
            doc.x_adj_direction = direction
            doc.x_adj_registrant = registrant

    @api.depends("doc_kind", "move_id", "x_pn_registered_date",
                 "move_id.x_pn_overdue_days", "move_id.x_pn_fine_est")
    def _compute_x_pn_mirror(self):
        """Прострочення і штраф беремо з рахунку як є."""
        for doc in self:
            days, fine = 0, 0.0
            try:
                if doc.move_id:
                    days = doc.move_id.x_pn_overdue_days or 0
                    fine = doc.move_id.x_pn_fine_est or 0.0
            except Exception:
                days, fine = 0, 0.0
            doc.x_pn_overdue_days = days
            doc.x_pn_fine_est = fine

    # --- Дії ---------------------------------------------------------------

    def action_mark_pn_registered(self):
        """«Позначити зареєстрованою»: ставить сьогоднішню дату реєстрації,
        якщо її ще нема. Дату можна виправити вручну."""
        for doc in self:
            if not doc.x_pn_registered_date:
                doc.x_pn_registered_date = fields.Date.context_today(doc)
            doc.message_post(body="Зареєстровано в ЄРПН (%s)"
                                  % doc.x_pn_registered_date.strftime("%d.%m.%Y"))
        return True

    def _ua_pn_number(self):
        """Порядковий номер документа - числовий хвіст номера рахунку
        («РАХ-2026-0001» дає 1). Без рахунку - id запису."""
        self.ensure_one()
        source = (self.move_id.name if self.move_id else "") or ""
        match = re.search(r"(\d+)\s*$", source)
        return str(int(match.group(1))) if match else str(self.id)

    def _ua_check_kind(self, kind, what):
        self.ensure_one()
        if self.doc_kind != kind:
            raise UserError("Ця дія стосується лише %s." % what)
        if not self.move_id:
            raise UserError(
                "Документ не пов'язаний з рахунком або проводкою - немає даних "
                "для експорту.")
