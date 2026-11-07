"""Взаємозалік: зарахування зустрічних однорідних вимог з одним контрагентом (ст. 601 ЦКУ).

Дві сторони документа:
  receivable - контрагент винен компанії: відкритий дебет на рахунку покупців (361);
  payable    - компанія винна контрагенту: відкритий кредит на рахунку постачальників (631).
Заповнення бере відкриті суми з обох боків (лише гривневі, за договором, якщо обрано),
найстаріші першими, і розподіляє меншу з двох сум. Проведення документа - одне: Дт
рахунку постачальника Кт рахунку покупця на кожен закритий документ; кожен його рядок
зводиться з тим рядком, який закриває, тож борги зменшуються в звичних звітах Odoo.

Скасування розводить звірку і скасовує проведення: борги повертаються як були.
Документ можна скласти й з готовими рядками (так робить комісійна торгівля): тоді
заповнення не потрібне, проведення те саме.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.l10n_ua_docs.models.tools import amount_in_words
from odoo.addons.l10n_ua_contract.models.tools import settlement_accounts

SIDES = [("receivable", "Борг контрагента"), ("payable", "Борг компанії")]
DOC_LABELS = {
    "out_invoice": "Реалізація",
    "out_refund": "Повернення від покупця",
    "in_invoice": "Надходження",
    "in_refund": "Повернення постачальнику",
}


class UaDebtOffset(models.Model):
    _name = "ua.debt.offset"
    _description = "Взаємозалік з контрагентом"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, tracking=True,
                                 domain="[('parent_id', '=', False)]")
    receivable_contract_id = fields.Many2one(
        "ua.contract", "Договір, за яким винен контрагент", check_company=True,
        domain="[('partner_id', '=', partner_id)]",
        help="Порожньо - борги контрагента за всіма договорами.")
    payable_contract_id = fields.Many2one(
        "ua.contract", "Договір, за яким винна компанія", check_company=True,
        domain="[('partner_id', '=', partner_id)]",
        help="Порожньо - борги компанії за всіма договорами.")
    amount_limit = fields.Monetary("Зарахувати не більше",
                                   help="Порожньо - уся менша з двох сум.")
    journal_id = fields.Many2one(
        "account.journal", "Журнал", required=True, check_company=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env["account.journal"].search(
            [*self.env["account.journal"]._check_company_domain(self.env.company),
             ("type", "=", "general")], limit=1))
    line_ids = fields.One2many("ua.debt.offset.line", "offset_id", "Документи", copy=False)
    receivable_total = fields.Monetary("Зараховано боргу контрагента",
                                       compute="_compute_totals", store=True)
    payable_total = fields.Monetary("Зараховано боргу компанії",
                                    compute="_compute_totals", store=True)
    amount = fields.Monetary("Сума заліку", compute="_compute_totals", store=True)
    move_id = fields.Many2one("account.move", "Проведення", readonly=True, copy=False,
                              check_company=True)
    state = fields.Selection([("draft", "Чернетка"), ("posted", "Проведено"), ("cancel", "Скасовано")],
                             "Стан", required=True, default="draft", tracking=True, copy=False)
    note = fields.Text("Примітка", help="Друкується в акті після переліку документів.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id).next_by_code(
                    "ua.debt.offset", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    @api.depends("line_ids.amount", "line_ids.side")
    def _compute_totals(self):
        for offset in self:
            offset.receivable_total = sum(
                offset.line_ids.filtered(lambda l: l.side == "receivable").mapped("amount"))
            offset.payable_total = sum(
                offset.line_ids.filtered(lambda l: l.side == "payable").mapped("amount"))
            offset.amount = min(offset.receivable_total, offset.payable_total)

    @api.constrains("partner_id", "receivable_contract_id", "payable_contract_id")
    def _check_contracts(self):
        for offset in self:
            for contract in offset.receivable_contract_id | offset.payable_contract_id:
                if contract.partner_id.commercial_partner_id != offset.partner_id.commercial_partner_id:
                    raise ValidationError(_("Договір %s укладено з іншим контрагентом.")
                                          % contract.display_name)

    def unlink(self):
        if any(offset.state == "posted" for offset in self):
            raise UserError(_("Проведений взаємозалік не видаляють: його скасовують."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Відкриті суми
    # ------------------------------------------------------------------
    def _open_lines(self, side):
        """Відкриті рядки однієї сторони, найстаріші першими."""
        self.ensure_one()
        account_type = "asset_receivable" if side == "receivable" else "liability_payable"
        contract = self.receivable_contract_id if side == "receivable" else self.payable_contract_id
        domain = [
            ("company_id", "=", self.company_id.id),
            ("partner_id.commercial_partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", account_type),
            ("account_id", "in", settlement_accounts(self.env, self.company_id).ids),
            ("reconciled", "=", False),
            ("currency_id", "=", self.currency_id.id),
            ("amount_residual", ">" if side == "receivable" else "<", 0.0),
        ]
        if contract:
            domain.append(("ua_contract_id", "=", contract.id))
        lines = self.env["account.move.line"].search(domain)
        return lines.sorted(lambda l: (l.date_maturity or l.date, l.date, l.id))

    def open_amounts(self):
        """Скільки зараз відкрито з кожного боку: (борг контрагента, борг компанії)."""
        self.ensure_one()
        return (sum(self._open_lines("receivable").mapped("amount_residual")),
                -sum(self._open_lines("payable").mapped("amount_residual")))

    @staticmethod
    def document_label(move):
        number = move.ref if move.move_type in ("in_invoice", "in_refund") and move.ref else move.name
        label = DOC_LABELS.get(move.move_type, "Операція")
        return "%s № %s" % (label, number) if number and number != "/" else label

    def _allocate(self, side, total):
        rows, left = [], total
        for line in self._open_lines(side):
            if self.currency_id.compare_amounts(left, 0.0) <= 0:
                break
            amount = min(abs(line.amount_residual), left)
            rows.append((0, 0, {"side": side, "move_line_id": line.id, "amount": amount}))
            left = self.currency_id.round(left - amount)
        return rows

    def action_fill(self):
        """Заповнити документ відкритими сумами обох сторін."""
        for offset in self:
            if offset.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            owed_to_us, owed_by_us = offset.open_amounts()
            total = min(owed_to_us, owed_by_us)
            if offset.amount_limit:
                total = min(total, offset.amount_limit)
            if offset.currency_id.compare_amounts(total, 0.0) <= 0:
                raise UserError(_(
                    "Зараховувати нічого: контрагент винен %(them)s, компанія винна %(us)s.",
                    them=offset.money(owed_to_us), us=offset.money(owed_by_us)))
            offset.line_ids = [(5, 0, 0)] + offset._allocate("receivable", total) \
                + offset._allocate("payable", total)
        return True

    # ------------------------------------------------------------------
    # Проведення
    # ------------------------------------------------------------------
    def _check_ready(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Провести можна лише чернетку."))
        cur = self.currency_id
        if cur.compare_amounts(self.receivable_total, 0.0) <= 0:
            raise UserError(_("У документі немає сум до заліку."))
        if cur.compare_amounts(self.receivable_total, self.payable_total):
            raise UserError(_(
                "Сторони не рівні: борг контрагента %(them)s, борг компанії %(us)s.",
                them=self.money(self.receivable_total), us=self.money(self.payable_total)))
        partner = self.partner_id.commercial_partner_id
        for line in self.line_ids:
            source = line.move_line_id
            if source.partner_id.commercial_partner_id != partner or source.company_id != self.company_id:
                raise UserError(_("%s - документ іншого контрагента.") % line.document)
            if source.currency_id != cur:
                raise UserError(_("%s - валютний борг, у залік не береться.") % line.document)
            open_amount = source.amount_residual if line.side == "receivable" else -source.amount_residual
            if cur.compare_amounts(line.amount, 0.0) <= 0 or cur.compare_amounts(line.amount, open_amount) > 0:
                raise UserError(_(
                    "%(doc)s: відкрито %(open)s, а до заліку %(amount)s. Заповніть документ знову.",
                    doc=line.document, open=self.money(max(open_amount, 0.0)),
                    amount=self.money(line.amount)))

    def action_post(self):
        for offset in self:
            offset._check_ready()
            partner = offset.partner_id.commercial_partner_id
            label = _("Взаємозалік %s") % offset.name
            move_lines = []
            for line in offset.line_ids:
                debit = line.amount if line.side == "payable" else 0.0
                move_lines.append((0, 0, {
                    "name": "%s: %s" % (label, line.document),
                    "account_id": line.move_line_id.account_id.id,
                    "partner_id": partner.id,
                    "ua_contract_id": line.move_line_id.ua_contract_id.id or False,
                    "debit": debit, "credit": line.amount - debit,
                }))
            move = self.env["account.move"].create({
                "move_type": "entry", "journal_id": offset.journal_id.id,
                "company_id": offset.company_id.id, "date": offset.date, "ref": label,
                "partner_id": partner.id, "line_ids": move_lines,
            })
            pairs = list(zip(offset.line_ids, move.line_ids.sorted("id")))
            for line, new in pairs:
                # договір рядка - як у боргу, який він закриває (див. l10n_ua_contract)
                if new.ua_contract_id != line.move_line_id.ua_contract_id:
                    new.ua_contract_id = line.move_line_id.ua_contract_id
            move.action_post()
            for line, new in pairs:
                (new | line.move_line_id).reconcile()
            offset.write({"move_id": move.id, "state": "posted"})
            offset.message_post(body=_("Зараховано %s, проведення %s.")
                                % (offset.money(offset.amount), move.name))
        return True

    def action_cancel(self):
        for offset in self:
            if offset.move_id:
                move = offset.move_id
                move.line_ids.remove_move_reconcile()
                if move.state == "posted":
                    move.button_draft()
                move.button_cancel()
        self.write({"state": "cancel"})
        return True

    def action_reset_draft(self):
        self.filtered(lambda o: o.state == "cancel").write({"state": "draft", "move_id": False})
        return True

    def action_open_move(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "account.move",
                "res_id": self.move_id.id, "view_mode": "form"}

    def action_print(self):
        return self.env.ref("l10n_ua_offset.action_report_ua_debt_offset").report_action(self)

    # ------------------------------------------------------------------
    # Друк
    # ------------------------------------------------------------------
    @api.model
    def money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    def amount_words(self):
        self.ensure_one()
        return amount_in_words(self.currency_id, self.amount)

    def side_lines(self, side):
        return self.line_ids.filtered(lambda l: l.side == side)


class UaDebtOffsetLine(models.Model):
    _name = "ua.debt.offset.line"
    _description = "Документ у взаємозаліку"
    _order = "offset_id, side desc, date, id"

    offset_id = fields.Many2one("ua.debt.offset", "Взаємозалік", required=True, index=True,
                                ondelete="cascade")
    company_id = fields.Many2one(related="offset_id.company_id", store=True)
    currency_id = fields.Many2one(related="offset_id.currency_id")
    side = fields.Selection(SIDES, "Сторона", required=True)
    move_line_id = fields.Many2one(
        "account.move.line", "Рядок боргу", required=True, ondelete="restrict",
        domain="[('company_id', '=', company_id), ('reconciled', '=', False), "
               "('parent_state', '=', 'posted'), "
               "('account_id.account_type', 'in', ('asset_receivable', 'liability_payable'))]")
    move_id = fields.Many2one(related="move_line_id.move_id", string="Документ")
    date = fields.Date(related="move_line_id.date", store=True)
    contract_id = fields.Many2one(related="move_line_id.ua_contract_id", string="Договір")
    document = fields.Char("Документ", compute="_compute_document")
    total = fields.Monetary("Сума документа", compute="_compute_document")
    amount = fields.Monetary("До заліку", required=True)

    @api.depends("move_line_id")
    def _compute_document(self):
        for line in self:
            move = line.move_line_id.move_id
            line.document = self.env["ua.debt.offset"].document_label(move) if move else ""
            line.total = abs(line.move_line_id.balance)

    @api.constrains("side", "move_line_id")
    def _check_side(self):
        for line in self:
            account_type = line.move_line_id.account_id.account_type
            if (line.side == "receivable") != (account_type == "asset_receivable"):
                raise ValidationError(_("%s стоїть не на тій стороні заліку.") % line.document)
