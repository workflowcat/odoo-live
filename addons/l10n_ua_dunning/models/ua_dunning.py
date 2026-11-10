"""Нагадування покупцям про прострочений борг.

Рівень нагадування - поріг днів прострочки, тема і вступ листа. Рахунок покупця, у якого дата
оплати минула, досягає рівня з найбільшим порогом, не більшим за дні прострочки. Лист готується,
коли хоч один рахунок контрагента (за договором) досяг рівня, вищого за той, на якому про нього
вже нагадали; у листі - усі прострочені рахунки цього контрагента і договору. Поки лист у
чернетці, наступний прохід оновлює його, а не робить другий.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


def _uah(value):
    return ("{:,.2f}".format(value or 0.0)).replace(",", " ").replace(".", ",")


class UaDunningLevel(models.Model):
    _name = "ua.dunning.level"
    _description = "Рівень нагадування про борг"
    _order = "days, id"

    name = fields.Char("Назва", required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", "Компанія", help="Порожньо - для всіх компаній.")
    days = fields.Integer("Днів прострочки", required=True,
                          help="Рівень діє, коли від дати оплати рахунку минуло стільки днів або більше.")
    subject = fields.Char("Тема листа", required=True)
    intro = fields.Text("Текст листа", required=True, help="Іде перед таблицею рахунків.")
    auto_send = fields.Boolean("Надсилати без перегляду",
                               help="Щоденна задача надсилає такі листи сама, якщо в контрагента є пошта. "
                                    "Інакше лист чекає в чернетках.")

    _days_positive = models.Constraint("check(days > 0)", "Днів прострочки має бути більше нуля.")

    @api.model
    def _ua_levels(self, company):
        return self.search(["|", ("company_id", "=", False), ("company_id", "=", company.id)], order="days desc")

    @staticmethod
    def _ua_level_for(levels, overdue):
        """Рівень для прострочки в днях; levels - за спаданням днів."""
        for level in levels:
            if overdue >= level.days:
                return level
        return levels.browse()


class UaDunningLetter(models.Model):
    _name = "ua.dunning.letter"
    _inherit = ["mail.thread"]
    _description = "Нагадування про борг"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Валюта")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, tracking=True)
    contract_id = fields.Many2one("ua.contract", "Договір", check_company=True, tracking=True)
    level_id = fields.Many2one("ua.dunning.level", "Рівень", tracking=True)
    email_to = fields.Char(related="partner_id.email", string="Пошта")
    state = fields.Selection([("draft", "Чернетка"), ("sent", "Надіслано"), ("cancel", "Скасовано")], "Стан",
                             default="draft", required=True, readonly=True, copy=False, tracking=True)
    line_ids = fields.One2many("ua.dunning.letter.line", "letter_id", "Рахунки")
    amount_total = fields.Monetary("Борг, разом", compute="_compute_amount_total", store=True)
    subject = fields.Char("Тема")
    body_html = fields.Html("Текст листа", sanitize_style=True)
    sent_date = fields.Date("Надіслано", readonly=True, copy=False)

    @api.depends("line_ids.amount_residual")
    def _compute_amount_total(self):
        for letter in self:
            letter.amount_total = sum(letter.line_ids.mapped("amount_residual"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.dunning.letter") or "/"
        return super().create(vals_list)

    # ---- які рахунки прострочено ---------------------------------------------------------
    @api.model
    def _ua_overdue_domain(self, company, today):
        return [("company_id", "=", company.id), ("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                ("payment_state", "in", ("not_paid", "partial")), ("amount_residual", ">", 0),
                ("invoice_date_due", "<", today), ("ua_dunning_hold", "=", False),
                ("commercial_partner_id.ua_dunning_excluded", "=", False)]

    @api.model
    def _ua_groups(self, company, today, partner=None, contract=None):
        """{(контрагент, договір): прострочені рахунки}."""
        domain = self._ua_overdue_domain(company, today)
        if partner:
            domain.append(("commercial_partner_id", "=", partner.commercial_partner_id.id))
        if contract is not None:
            domain.append(("ua_contract_id", "=", contract.id if contract else False))
        groups = defaultdict(lambda: self.env["account.move"])
        for move in self.env["account.move"].search(domain, order="invoice_date_due, id"):
            groups[(move.commercial_partner_id, move.ua_contract_id)] |= move
        return groups

    def _ua_fill(self, moves, levels, today):
        """Рядки, рівень і текст листа з рахунків."""
        self.ensure_one()
        lines, top = [(5, 0, 0)], levels.browse()
        for move in moves:
            overdue = (today - move.invoice_date_due).days
            level = levels._ua_level_for(levels, overdue)
            if level and (not top or level.days > top.days):
                top = level
            lines.append((0, 0, {"move_id": move.id, "days_overdue": overdue, "level_id": level.id,
                                 "amount_residual": move.amount_residual_signed}))
        self.write({"line_ids": lines, "level_id": top.id, "date": today})
        self._ua_render()

    def _ua_render(self):
        for letter in self:
            level = letter.level_id or self.env["ua.dunning.level"]._ua_levels(letter.company_id)[-1:]
            letter.subject = "%s: %s" % (level.subject or _("Нагадування про оплату"), letter.company_id.name)
            letter.body_html = self.env["ir.qweb"]._render("l10n_ua_dunning.ua_dunning_letter_body", {
                "letter": letter, "intro": level.intro or "", "uah": _uah,
                "contract": letter.contract_id._ua_print_name() if letter.contract_id else ""})

    @api.model
    def _ua_generate(self, company=None, today=None):
        """Підготувати листи для компанії на дату. Повертає нові й оновлені чернетки."""
        today = today or fields.Date.context_today(self)
        letters = self.browse()
        for company in (company or self.env["res.company"].search([])):
            levels = self.env["ua.dunning.level"]._ua_levels(company)
            if not levels:
                continue
            for (partner, contract), moves in self._ua_groups(company, today).items():
                due = moves.filtered(lambda m: self._ua_needs_level(m, levels, today))
                if not due:
                    continue
                letter = self.search([("company_id", "=", company.id), ("partner_id", "=", partner.id),
                                      ("contract_id", "=", contract.id), ("state", "=", "draft")], limit=1)
                if not letter:
                    letter = self.create({"company_id": company.id, "partner_id": partner.id,
                                          "contract_id": contract.id, "date": today})
                letter._ua_fill(moves, levels, today)
                letters |= letter
        return letters

    @staticmethod
    def _ua_needs_level(move, levels, today):
        level = levels._ua_level_for(levels, (today - move.invoice_date_due).days)
        return bool(level) and (not move.ua_dunning_level_id or level.days > move.ua_dunning_level_id.days)

    @api.model
    def _ua_cron(self):
        letters = self._ua_generate()
        letters.filtered(lambda l: l.level_id.auto_send and l.partner_id.email)._ua_send()
        return letters

    # ---- дії ---------------------------------------------------------------------------
    def action_refresh(self):
        for letter in self.filtered(lambda l: l.state == "draft"):
            levels = self.env["ua.dunning.level"]._ua_levels(letter.company_id)
            today = fields.Date.context_today(self)
            groups = self._ua_groups(letter.company_id, today, letter.partner_id, letter.contract_id)
            letter._ua_fill(groups.get((letter.partner_id.commercial_partner_id, letter.contract_id),
                                       self.env["account.move"]), levels, today)
        return True

    def action_send(self):
        for letter in self:
            if letter.state != "draft":
                raise UserError(_("Надіслати можна лише чернетку."))
            if not letter.line_ids:
                raise UserError(_("У листі немає прострочених рахунків."))
            if not letter.partner_id.email:
                raise UserError(_("У контрагента %s немає пошти. Додайте її або надрукуйте лист.")
                                % letter.partner_id.display_name)
        self._ua_send()
        return True

    def _ua_send(self):
        for letter in self:
            letter.message_post(body=letter.body_html, subject=letter.subject, partner_ids=letter.partner_id.ids,
                                message_type="comment", subtype_xmlid="mail.mt_comment")
            letter._ua_mark_sent()
        return True

    def action_mark_sent(self):
        """Лист передано інакше (друк, месенджер): позначити рахунки так само, як після пошти."""
        for letter in self.filtered(lambda l: l.state == "draft"):
            letter._ua_mark_sent()
        return True

    def _ua_mark_sent(self):
        self.ensure_one()
        for line in self.line_ids.filtered("level_id"):
            current = line.move_id.ua_dunning_level_id
            if not current or line.level_id.days > current.days:
                line.move_id.sudo().write({"ua_dunning_level_id": line.level_id.id})
            line.move_id.sudo().ua_dunning_date = self.date
        self.write({"state": "sent", "sent_date": fields.Date.context_today(self)})

    def action_cancel(self):
        self.filtered(lambda l: l.state == "draft").write({"state": "cancel"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_dunning.action_report_ua_dunning_letter").report_action(self)


class UaDunningLetterLine(models.Model):
    _name = "ua.dunning.letter.line"
    _description = "Рахунок у нагадуванні про борг"
    _order = "days_overdue desc, id"

    letter_id = fields.Many2one("ua.dunning.letter", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="letter_id.currency_id")
    move_id = fields.Many2one("account.move", "Рахунок", required=True, ondelete="cascade")
    invoice_date = fields.Date(related="move_id.invoice_date", string="Дата рахунку")
    invoice_date_due = fields.Date(related="move_id.invoice_date_due", string="Оплатити до")
    days_overdue = fields.Integer("Днів прострочки")
    level_id = fields.Many2one("ua.dunning.level", "Рівень")
    amount_residual = fields.Monetary("Залишок боргу")
