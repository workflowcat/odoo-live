# -*- coding: utf-8 -*-
"""Звіт про рух грошових коштів за прямим методом (форма № 3, НП(С)БО 1).

Гроші - рахунки з кодами, що починаються з префіксів звіту (типово 30, 31, 33: рядок 1165
балансу). Кожна проводка, де є такий рахунок, дає рух: кожен її рядок на інших рахунках - це
кореспондентний рахунок, і його сума з протилежним знаком - надходження (+) або витрачання (-).
Проводка лише між грошовими рахунками (з каси в банк, 333 -> 311) - внутрішнє переміщення,
у звіт не потрапляє.

Стаття для кожного руху, за першим, що знайдеться:
1. стаття на самому кореспондентному рядку проводки;
2. одна стаття на грошових рядках проводки;
3. стаття на проводці (і на рядку виписки, бо рядок виписки - це проводка);
4. стаття на платежі, з якого проводка;
5. правило за кодом кореспондентного рахунку (найдовший префікс, спершу правила компанії);
6. «Інші надходження» (3095) або «Інші витрачання» (3190) - такі рухи звіт показує окремо,
   щоб бухгалтер вибрав статтю.

Коди рядків - форма № 3 у редакції наказу Мінфіну № 73 (2013) зі змінами; перевіряйте чинну
редакцію перед поданням.
"""
from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

SECTIONS = [
    ("operating", "I. Рух коштів у результаті операційної діяльності"),
    ("investing", "II. Рух коштів у результаті інвестиційної діяльності"),
    ("financing", "III. Рух коштів у результаті фінансової діяльності"),
    ("fx", "Вплив зміни валютних курсів"),
]
KINDS = [("in", "Надходження"), ("out", "Витрачання")]
SOURCES = [
    ("line", "Стаття на рядку"),
    ("cash", "Стаття на грошовому рядку"),
    ("move", "Стаття на проводці"),
    ("payment", "Стаття на платежі"),
    ("rule", "Правило за рахунком"),
    ("fallback", "Без статті"),
]
# Підсумкові рядки: код, назва, розділ (None - весь звіт).
SECTION_TOTALS = {
    "operating": ("3195", "Чистий рух коштів від операційної діяльності"),
    "investing": ("3295", "Чистий рух коштів від інвестиційної діяльності"),
    "financing": ("3395", "Чистий рух коштів від фінансової діяльності"),
}
FALLBACK_IN = "3095"
FALLBACK_OUT = "3190"
FX_CODE = "3410"


def _prefixes(text):
    return [p.strip() for p in (text or "").replace(";", ",").split(",") if p.strip()]


class UaCashflowItem(models.Model):
    _name = "ua.cashflow.item"
    _description = "Стаття руху грошових коштів"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char("Код рядка", required=True)
    name = fields.Char("Назва", required=True)
    kind = fields.Selection(KINDS, string="Напрям", required=True)
    section = fields.Selection(SECTIONS, string="Розділ", required=True)
    parent_id = fields.Many2one(
        "ua.cashflow.item", string="У тому числі до рядка", ondelete="restrict",
        help="Рядок форми, у суму якого входить цей (3006 у 3005, 3116-3118 у 3115).")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Стаття з таким кодом рядка вже є.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for item in self:
            item.display_name = "%s %s" % (item.code or "", item.name or "")


class UaCashflowRule(models.Model):
    _name = "ua.cashflow.rule"
    _description = "Правило статті руху коштів за рахунком"
    _order = "sequence, account_prefix"

    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", string="Компанія",
        help="Порожньо - для всіх компаній. Правило компанії важить більше за спільне.")
    account_prefix = fields.Char(
        "Рахунок (початок коду)", required=True,
        help="Напр. 36 - усі рахунки, що починаються з 36. Діє найдовший збіг.")
    item_in_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття надходження", domain=[("kind", "=", "in")])
    item_out_id = fields.Many2one(
        "ua.cashflow.item", string="Стаття витрачання", domain=[("kind", "=", "out")])
    note = fields.Char("Примітка")

    @api.constrains("account_prefix")
    def _check_prefix(self):
        for rule in self:
            if not (rule.account_prefix or "").strip().isdigit():
                raise ValidationError(_("Початок коду рахунку - лише цифри: %s") % rule.account_prefix)

    @api.model
    def ua_match(self, company, code):
        """Правило з найдовшим префіксом коду рахунку; правило компанії перед спільним."""
        code = code or ""
        best, best_key = self.browse(), None
        for rule in self.search([("company_id", "in", [False, company.id])]):
            prefix = rule.account_prefix.strip()
            if not code.startswith(prefix):
                continue
            key = (len(prefix), 1 if rule.company_id else 0, -rule.sequence)
            if best_key is None or key > best_key:
                best, best_key = rule, key
        return best


class UaCashflowStatement(models.Model):
    _name = "ua.cashflow.statement"
    _description = "Звіт про рух грошових коштів (форма № 3)"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(
        "З", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(
        "По", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1) - timedelta(days=1))
    cash_prefixes = fields.Char(
        "Грошові рахунки", required=True, default="30,31,33",
        help="Початки кодів рахунків грошей і еквівалентів через кому: як у рядку 1165 балансу.")
    state = fields.Selection(
        [("draft", "Чернетка"), ("done", "Затверджено")], default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.cashflow.statement.line", "statement_id", string="Рядки форми")
    entry_ids = fields.One2many("ua.cashflow.statement.entry", "statement_id", string="Розшифровка")
    opening = fields.Monetary("Залишок на початок (3405)", currency_field="currency_id", readonly=True)
    closing = fields.Monetary("Залишок на кінець (3415)", currency_field="currency_id", readonly=True)
    book_closing = fields.Monetary(
        "Залишок за обліком на кінець", currency_field="currency_id", readonly=True,
        help="Сальдо грошових рахунків на кінець періоду: має дорівнювати рядку 3415.")
    unassigned_amount = fields.Monetary(
        "Рух без статті", currency_field="currency_id", compute="_compute_unassigned")
    unassigned_count = fields.Integer("Рухів без статті", compute="_compute_unassigned")
    computed_at = fields.Datetime("Розраховано", readonly=True)

    @api.depends("date_from", "date_to", "company_id")
    def _compute_name(self):
        for st in self:
            if st.date_from and st.date_to:
                st.name = "Ф3 %s - %s" % (st.date_from.strftime("%d.%m.%Y"), st.date_to.strftime("%d.%m.%Y"))
            else:
                st.name = "Ф3"

    @api.depends("entry_ids.source", "entry_ids.amount", "entry_ids.period")
    def _compute_unassigned(self):
        for st in self:
            todo = st.entry_ids.filtered(lambda e: e.period == "current" and e.source == "fallback")
            st.unassigned_amount = sum(abs(e.amount) for e in todo)
            st.unassigned_count = len(todo)

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for st in self:
            if st.date_from and st.date_to and st.date_from > st.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    # ------------------------------------------------------------------ розрахунок
    def _ua_is_cash(self, account):
        code = account.code or ""
        return any(code.startswith(p) for p in _prefixes(self.cash_prefixes))

    def _ua_cash_accounts(self):
        Account = self.env["account.account"].with_company(self.company_id)
        domain = ["|"] * (len(_prefixes(self.cash_prefixes)) - 1)
        for prefix in _prefixes(self.cash_prefixes):
            domain.append(("code", "=like", prefix + "%"))
        return Account.search(domain + [("company_ids", "in", self.company_id.id)])

    def _ua_balance_before(self, accounts, day):
        """Сальдо грошових рахунків до дня (не включно)."""
        if not accounts:
            return 0.0
        groups = self.env["account.move.line"]._read_group(
            [("account_id", "in", accounts.ids), ("parent_state", "=", "posted"),
             ("company_id", "=", self.company_id.id), ("date", "<", day)],
            aggregates=["balance:sum"])
        return (groups[0][0] or 0.0) if groups else 0.0

    def _ua_item_for(self, line, cash_lines, rule_cache):
        """Стаття і джерело для кореспондентного рядка проводки з грошима."""
        amount = -line.balance
        if line.ua_cashflow_item_id:
            return line.ua_cashflow_item_id, "line", False
        cash_items = cash_lines.ua_cashflow_item_id
        if len(cash_items) == 1:
            return cash_items, "cash", False
        move = line.move_id
        if move.ua_cashflow_item_id:
            return move.ua_cashflow_item_id, "move", False
        payment = move.origin_payment_id
        if payment and payment.ua_cashflow_item_id:
            return payment.ua_cashflow_item_id, "payment", False
        code = line.account_id.code or ""
        if code not in rule_cache:
            rule_cache[code] = self.env["ua.cashflow.rule"].ua_match(self.company_id, code)
        rule = rule_cache[code]
        item = rule and (rule.item_in_id if amount > 0 else rule.item_out_id)
        if item:
            return item, "rule", rule
        Item = self.env["ua.cashflow.item"]
        fallback = Item.search([("code", "=", FALLBACK_IN if amount > 0 else FALLBACK_OUT)], limit=1)
        return fallback, "fallback", rule or False

    def _ua_entries(self, date_from, date_to, period):
        """Рухи коштів за період: список значень для рядків розшифровки."""
        cash_accounts = self._ua_cash_accounts()
        if not cash_accounts:
            return []
        cash_lines = self.env["account.move.line"].search([
            ("account_id", "in", cash_accounts.ids), ("parent_state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("date", ">=", date_from), ("date", "<=", date_to)])
        result, rule_cache = [], {}
        for move in cash_lines.move_id.sorted(lambda m: (m.date, m.id)):
            move_cash = move.line_ids.filtered(lambda l: l.account_id in cash_accounts)
            others = move.line_ids - move_cash
            if self.company_id.currency_id.is_zero(sum(move_cash.mapped("balance"))) and \
                    all(self.company_id.currency_id.is_zero(l.balance) for l in others):
                continue
            for line in others:
                if self.company_id.currency_id.is_zero(line.balance):
                    continue
                item, source, rule = self._ua_item_for(line, move_cash, rule_cache)
                result.append({
                    "statement_id": self.id, "period": period, "move_id": move.id,
                    "move_line_id": line.id, "date": move.date, "partner_id": line.partner_id.id,
                    "account_id": line.account_id.id, "item_id": item.id, "source": source,
                    "rule_id": rule.id if rule else False, "amount": -line.balance,
                })
        return result

    def _ua_form_lines(self, totals_now, totals_prev, opening_now, opening_prev):
        """Рядки форми у порядку статей з підсумками розділів."""
        Item = self.env["ua.cashflow.item"]
        items = Item.with_context(active_test=False).search([])
        children = defaultdict(lambda: Item)
        for item in items:
            if item.parent_id:
                children[item.parent_id.id] |= item

        def shown(item, totals):
            # Зі знаком: надходження плюс, витрачання мінус (у друці - у дужках).
            return totals.get(item.id, 0.0) + sum(totals.get(c.id, 0.0) for c in children[item.id])

        def net(section, totals):
            return sum(totals.get(i.id, 0.0) for i in items if i.section == section)

        rows, seq = [], 0
        for section, label in SECTIONS:
            if section == "fx":
                continue
            seq += 10
            rows.append({"sequence": seq, "code": "", "name": label, "row_kind": "section"})
            for item in items.filtered(lambda i: i.section == section).sorted("code"):
                if not item.active and not (totals_now.get(item.id) or totals_prev.get(item.id)):
                    continue
                seq += 10
                rows.append({
                    "sequence": seq, "code": item.code, "name": item.name, "item_id": item.id,
                    "row_kind": "sub" if item.parent_id else "item",
                    "amount": shown(item, totals_now), "amount_prev": shown(item, totals_prev)})
            code, name = SECTION_TOTALS[section]
            seq += 10
            rows.append({"sequence": seq, "code": code, "name": name, "row_kind": "total",
                         "amount": net(section, totals_now), "amount_prev": net(section, totals_prev)})
        flow_now = sum(net(s, totals_now) for s in SECTION_TOTALS)
        flow_prev = sum(net(s, totals_prev) for s in SECTION_TOTALS)
        fx_now, fx_prev = net("fx", totals_now), net("fx", totals_prev)
        fx_item = items.filtered(lambda i: i.code == FX_CODE)[:1]
        tail = [
            ("3400", "Чистий рух грошових коштів за звітний період", flow_now, flow_prev, False),
            ("3405", "Залишок коштів на початок року", opening_now, opening_prev, False),
            (FX_CODE, "Вплив зміни валютних курсів на залишок коштів", fx_now, fx_prev, fx_item.id),
            ("3415", "Залишок коштів на кінець року", opening_now + flow_now + fx_now,
             opening_prev + flow_prev + fx_prev, False),
        ]
        for code, name, now, prev, item_id in tail:
            seq += 10
            rows.append({"sequence": seq, "code": code, "name": name, "row_kind": "total",
                         "amount": now, "amount_prev": prev, "item_id": item_id})
        return rows

    def action_compute(self):
        for st in self:
            if st.state == "done":
                raise UserError(_("Затверджений звіт не перераховують: поверніть його в чернетку."))
            prev_from = st.date_from - relativedelta(years=1)
            prev_to = st.date_to - relativedelta(years=1)
            st.entry_ids.unlink()
            st.line_ids.unlink()
            entries = st._ua_entries(st.date_from, st.date_to, "current") + \
                st._ua_entries(prev_from, prev_to, "previous")
            self.env["ua.cashflow.statement.entry"].create(entries)
            totals = {"current": defaultdict(float), "previous": defaultdict(float)}
            for values in entries:
                totals[values["period"]][values["item_id"]] += values["amount"]
            accounts = st._ua_cash_accounts()
            opening_now = st._ua_balance_before(accounts, st.date_from)
            opening_prev = st._ua_balance_before(accounts, prev_from)
            rows = st._ua_form_lines(totals["current"], totals["previous"], opening_now, opening_prev)
            st.line_ids = [(0, 0, row) for row in rows]
            closing_row = st.line_ids.filtered(lambda l: l.code == "3415")
            st.write({
                "opening": opening_now, "closing": closing_row.amount,
                "book_closing": st._ua_balance_before(accounts, st.date_to + timedelta(days=1)),
                "computed_at": fields.Datetime.now(),
            })
        return True

    def action_done(self):
        for st in self:
            if not st.line_ids:
                raise UserError(_("Спершу розрахуйте звіт."))
            if st.currency_id.compare_amounts(st.closing, st.book_closing):
                raise UserError(_(
                    "Залишок на кінець за звітом (%(report).2f) не дорівнює сальдо грошових рахунків "
                    "(%(book).2f). Перерахуйте звіт.") % {"report": st.closing, "book": st.book_closing})
            st.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_open_unassigned(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Рух без статті"),
            "res_model": "ua.cashflow.statement.entry", "view_mode": "list,form",
            "domain": [("statement_id", "=", self.id), ("period", "=", "current"), ("source", "=", "fallback")],
        }

    def action_print(self):
        return self.env.ref("l10n_ua_cashflow.action_report_ua_cashflow").report_action(self)

    # ------------------------------------------------------------------ друк
    def ua_rows(self):
        """Рядки для друку: назва, код, звітний, попередній, вид рядка."""
        self.ensure_one()
        return [(l.name, l.code, l.amount, l.amount_prev, l.row_kind) for l in self.line_ids.sorted("sequence")]

    def ua_money(self, value):
        """Сума для форми в гривнях з копійками: витрачання в дужках, нуль - прочерк."""
        self.ensure_one()
        if self.currency_id.is_zero(value or 0.0):
            return "-"
        text = "{:,.2f}".format(abs(value)).replace(",", " ")
        return "(%s)" % text if value < 0 else text


class UaCashflowStatementLine(models.Model):
    _name = "ua.cashflow.statement.line"
    _description = "Рядок форми № 3"
    _order = "sequence, id"

    statement_id = fields.Many2one("ua.cashflow.statement", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="statement_id.company_id", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")
    sequence = fields.Integer()
    code = fields.Char("Код рядка")
    name = fields.Char("Стаття", required=True)
    row_kind = fields.Selection(
        [("section", "Розділ"), ("item", "Стаття"), ("sub", "У тому числі"), ("total", "Підсумок")],
        string="Вид", required=True, default="item")
    item_id = fields.Many2one("ua.cashflow.item", string="Стаття руху")
    amount = fields.Monetary("За звітний період", currency_field="currency_id")
    amount_prev = fields.Monetary("За аналогічний період попереднього року", currency_field="currency_id")

    def action_open_entries(self):
        self.ensure_one()
        items = self.item_id | self.env["ua.cashflow.item"].search([("parent_id", "=", self.item_id.id)]) \
            if self.item_id else self.env["ua.cashflow.item"]
        domain = [("statement_id", "=", self.statement_id.id), ("period", "=", "current")]
        if items:
            domain.append(("item_id", "in", items.ids))
        return {
            "type": "ir.actions.act_window", "name": "%s %s" % (self.code or "", self.name),
            "res_model": "ua.cashflow.statement.entry", "view_mode": "list,form", "domain": domain,
        }


class UaCashflowStatementEntry(models.Model):
    _name = "ua.cashflow.statement.entry"
    _description = "Рух коштів у розшифровці форми № 3"
    _order = "date, id"

    statement_id = fields.Many2one("ua.cashflow.statement", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="statement_id.company_id", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")
    period = fields.Selection(
        [("current", "Звітний"), ("previous", "Попередній рік")], required=True, default="current")
    move_id = fields.Many2one("account.move", string="Проводка", ondelete="cascade")
    move_line_id = fields.Many2one("account.move.line", string="Рядок проводки", ondelete="cascade")
    date = fields.Date("Дата")
    partner_id = fields.Many2one("res.partner", string="Контрагент")
    account_id = fields.Many2one("account.account", string="Кор. рахунок")
    item_id = fields.Many2one("ua.cashflow.item", string="Стаття", required=True)
    source = fields.Selection(SOURCES, string="Звідки стаття", required=True)
    rule_id = fields.Many2one("ua.cashflow.rule", string="Правило")
    amount = fields.Monetary(
        "Сума", currency_field="currency_id", help="Надходження зі знаком плюс, витрачання - мінус.")

    def action_set_item(self, item):
        """Записати статтю на рядок проводки: наступний розрахунок візьме її першою."""
        for entry in self:
            entry.move_line_id.sudo().ua_cashflow_item_id = item
            entry.write({"item_id": item.id, "source": "line"})
        return True
