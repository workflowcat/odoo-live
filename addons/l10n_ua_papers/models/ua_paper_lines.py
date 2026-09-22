# -*- coding: utf-8 -*-
"""Стан документа на кожному рядку (task 4, spec-papers.md «Спершу дані, потім бланк»).

Режим «Дані» редагує рядки просто в списку (`editable="bottom"`), не форму. Щоб вузький
вигляд списку знав, коли можна правити, а коли ні, кожна модель рядка отримує пов'язане
поле `ua_paper_state` - стан документа, до якого рядок належить. Колонки вузького вигляду
(`views/ua_papers_line_views.xml`) стоять `readonly="ua_paper_state != 'draft'"`.

Модуль своїх даних не тримає (як і ua.papers) - це єдине поле, яке він додає до чужих
моделей, і лише тому, що правка рядків живе тут, в екрані «Папери».
"""
from odoo import fields, models


class UaTimesheetLine(models.Model):
    _inherit = "ua.timesheet.line"

    ua_paper_state = fields.Selection(related="sheet_id.state", string="Стан документа")


class UaStaffListLine(models.Model):
    _inherit = "ua.staff.list.line"

    ua_paper_state = fields.Selection(related="list_id.state", string="Стан документа")


class UaAdvanceLine(models.Model):
    _inherit = "ua.advance.line"

    ua_paper_state = fields.Selection(related="sheet_id.state", string="Стан документа")


class AccountPaymentLine(models.Model):
    _inherit = "account.payment.line"

    # Стан рядка доручення вже є пов'язаним полем OCA (`state`), але екран «Папери» питає
    # в усіх моделей рядків одне й те саме ім'я - лишаємо його і тут.
    ua_paper_state = fields.Selection(related="order_id.state", string="Стан документа")


class UaPfuClaimLine(models.Model):
    _inherit = "ua.pfu.claim.line"

    ua_paper_state = fields.Selection(related="claim_id.state", string="Стан документа")


class UaMilitaryListLine(models.Model):
    _inherit = "ua.military.list.line"

    ua_paper_state = fields.Selection(related="list_id.state", string="Стан документа")


class UaMilitaryReservedLine(models.Model):
    _inherit = "ua.military.reserved.line"

    ua_paper_state = fields.Selection(related="reserved_id.state", string="Стан документа")
