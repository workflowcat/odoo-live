# -*- coding: utf-8 -*-
"""Відомість нарахування амортизації за місяць.

Регістр, який бухгалтер підшиває до проводки: за який місяць, по яких
об'єктах, скільки нараховано, на який рахунок витрат. Власних рядків не
тримає - читає рядки амортизації OCA (account.asset.line) за місяць.

Сама відомість - запис: складена відомість лишається в базі, щоб її можна було
відкрити тією самою сторінкою. Пункт меню відкриває список відомостей, кнопка
«Сформувати» в шапці списку питає місяць діалогом.
"""
import calendar

from odoo import api, fields, models

MONTHS = [
    ("1", "січень"), ("2", "лютий"), ("3", "березень"), ("4", "квітень"),
    ("5", "травень"), ("6", "червень"), ("7", "липень"), ("8", "серпень"),
    ("9", "вересень"), ("10", "жовтень"), ("11", "листопад"), ("12", "грудень"),
]


class UaDepreciationSheet(models.Model):
    _name = "ua.depreciation.sheet"
    _description = "Відомість нарахування амортизації за місяць"
    _order = "year desc, month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company",
        string="Компанія",
        required=True,
        default=lambda self: self.env.company,
    )
    year = fields.Integer(
        string="Рік",
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    month = fields.Selection(
        selection=MONTHS,
        string="Місяць",
        required=True,
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    only_posted = fields.Boolean(
        string="Лише проведені",
        default=False,
        help="Без галочки у відомість потрапляють і заплановані рядки "
             "таблиці амортизації, ще не проведені в облік.",
    )
    date_from = fields.Date(string="З", compute="_compute_dates")
    date_to = fields.Date(string="По", compute="_compute_dates")

    total_amount = fields.Float("Нараховано, разом", compute="_compute_total", store=True)
    line_count = fields.Integer("Об'єктів", compute="_compute_total", store=True)

    @api.depends("year", "month")
    def _compute_name(self):
        for sheet in self:
            sheet.name = "Відомість амортизації за %s %s" % (sheet.month_name(), sheet.year or "")

    @api.depends("year", "month", "only_posted", "company_id")
    def _compute_total(self):
        for sheet in self:
            rows = sheet.sheet_rows()
            sheet.total_amount = round(sum(row["amount"] for row in rows), 2)
            sheet.line_count = len(rows)

    def action_compose(self):
        """Кнопка «Скласти» в діалозі: відкрити складену відомість сторінкою."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "ua.depreciation.sheet",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref("l10n_ua_assets.view_ua_depreciation_sheet_form").id, "form")],
            "target": "current",
        }

    def action_ask(self):
        """Кнопка «Сформувати» в шапці списку: діалог параметрів нової відомості."""
        return {
            "type": "ir.actions.act_window",
            "name": "Відомість нарахування амортизації",
            "res_model": "ua.depreciation.sheet",
            "view_mode": "form",
            "views": [(self.env.ref("l10n_ua_assets.view_ua_depreciation_sheet_ask").id, "form")],
            "target": "new",
        }

    def action_compute(self):
        """«Перерахувати»: рядки читаються з таблиці амортизації щоразу, тому тут
        досить оновити підсумки відомості."""
        self._compute_total()
        return True

    @api.depends("year", "month")
    def _compute_dates(self):
        for sheet in self:
            year, month = sheet.year or 1, int(sheet.month or 1)
            last = calendar.monthrange(year, month)[1]
            sheet.date_from = fields.Date.to_date("%04d-%02d-01" % (year, month))
            sheet.date_to = fields.Date.to_date("%04d-%02d-%02d" % (year, month, last))

    def _lines(self):
        """Рядки амортизації за місяць, відсортовані за інвентарним номером."""
        self.ensure_one()
        domain = [
            ("type", "=", "depreciate"),
            ("line_date", ">=", self.date_from),
            ("line_date", "<=", self.date_to),
            ("asset_id.company_id", "=", self.company_id.id),
        ]
        if self.only_posted:
            domain.append(("move_check", "=", True))
        lines = self.env["account.asset.line"].search(domain)
        return lines.sorted(key=lambda l: (l.asset_id.code or "", l.asset_id.name))

    def sheet_rows(self):
        """Готові рядки відомості для друку."""
        self.ensure_one()
        rows = []
        for line in self._lines():
            asset = line.asset_id
            rows.append({
                "code": asset.code or "",
                "name": asset.name,
                "group": dict(
                    asset.profile_id._fields["ua_tax_group"].selection
                ).get(asset.profile_id.ua_tax_group, ""),
                "purchase_value": asset.purchase_value,
                "amount": line.amount,
                "depreciated": line.depreciated_value + line.amount,
                "residual": line.remaining_value,
                "expense": asset.profile_id.account_expense_depreciation_id.code or "",
                "depreciation": asset.profile_id.account_depreciation_id.code or "",
                "posted": line.move_check,
            })
        return rows

    def total(self):
        self.ensure_one()
        return sum(row["amount"] for row in self.sheet_rows())

    def month_name(self):
        self.ensure_one()
        return dict(MONTHS).get(self.month, "")

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            "l10n_ua_assets.action_report_ua_depreciation_sheet"
        ).report_action(self)
