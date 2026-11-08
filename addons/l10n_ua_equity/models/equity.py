# -*- coding: utf-8 -*-
"""Звіт про власний капітал (форма № 4, НП(С)БО 1).

Графи - складові капіталу за рахунками, як рядки 1400-1430 балансу: 3 зареєстрований (40),
4 у дооцінках (41), 5 додатковий (42), 6 резервний (43), 7 нерозподілений прибуток (44, 999999 і
незакритий результат рахунків класів 7-9), 8 неоплачений (46), 9 вилучений (45), 10 разом. Сума -
кредит мінус дебет: неоплачений і вилучений капітал виходять зі знаком мінус, як у балансі.

Рядок форми для кожного рядка проводки на рахунку капіталу, за першим, що знайдеться:
1. рядок форми на самому рядку проводки;
2. рядок форми на проводці (так позначають коригування 4005, 4010, 4090);
3. правило: рахунок капіталу, бік (дебет чи кредит) і кореспондентний рахунок - рахунок на
   протилежному боці тієї самої проводки. Діє найточніше правило (найдовші коди), правило
   компанії важить більше за спільне;
4. 4290 «Інші зміни в капіталі» - такі рухи звіт показує окремо, щоб бухгалтер вибрав рядок.

Фінансовий результат (рахунки класів 7-9, як у рядку 1420 балансу) іде в рядок 4100 графи 7
однією сумою. Закриття 79 на 44 - рух усередині графи 7 у тому самому рядку 4100, тож прибуток не
двоїться, хоч би рахунок 79 закривали щомісяця, щороку чи ніколи.

4095 = 4000 + 4005 + 4010 + 4090; 4295 - сума рядків 4100-4291 (4111-4116 входять у 4110 і окремо
не додаються); 4300 = 4095 + 4295 і має дорівнювати сальдо рахунків капіталу на кінець періоду
(рядки 1400-1495 балансу). Коди рядків - форма № 4 у редакції наказу Мінфіну № 73 (2013) зі
змінами; перевіряйте чинну редакцію перед поданням.
"""
from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Графи 3-9: ключ, назва, початки кодів рахунків.
COLUMNS = [
    ("registered", "Зареєстрований (пайовий) капітал", ("40",)),
    ("revaluation", "Капітал у дооцінках", ("41",)),
    ("additional", "Додатковий капітал", ("42",)),
    ("reserve", "Резервний капітал", ("43",)),
    ("retained", "Нерозподілений прибуток (непокритий збиток)", ("44", "999999")),
    ("unpaid", "Неоплачений капітал", ("46",)),
    ("withdrawn", "Вилучений капітал", ("45",)),
]
COLUMN_KEYS = [key for key, _label, _prefixes in COLUMNS]
COLUMN_SELECTION = [(key, label) for key, label, _prefixes in COLUMNS]
# Рахунки фінансового результату - як у рядку 1420 форми № 1 (l10n_ua_finrep).
RESULT_PREFIXES = ("7", "8", "90", "91", "92", "93", "94", "95", "96", "97", "98",
                   "999001", "999002", "999997", "999998")

# Рядки форми: код, назва, вид, рядок, у який входить.
ROWS = [
    ("4000", "Залишок на початок року", "opening", None),
    ("", "Коригування:", "section", None),
    ("4005", "Зміна облікової політики", "adjust", None),
    ("4010", "Виправлення помилок", "adjust", None),
    ("4090", "Інші зміни", "adjust", None),
    ("4095", "Скоригований залишок на початок року", "total", None),
    ("4100", "Чистий прибуток (збиток) за звітний період", "item", None),
    ("4110", "Інший сукупний дохід за звітний період", "item", None),
    ("4111", "Дооцінка (уцінка) необоротних активів", "sub", "4110"),
    ("4112", "Дооцінка (уцінка) фінансових інструментів", "sub", "4110"),
    ("4113", "Накопичені курсові різниці", "sub", "4110"),
    ("4114", "Частка іншого сукупного доходу асоційованих і спільних підприємств", "sub", "4110"),
    ("4116", "Інший сукупний дохід", "sub", "4110"),
    ("", "Розподіл прибутку:", "section", None),
    ("4200", "Виплати власникам (дивіденди)", "item", None),
    ("4205", "Спрямування прибутку до зареєстрованого капіталу", "item", None),
    ("4210", "Відрахування до резервного капіталу", "item", None),
    ("4215", "Сума чистого прибутку, належна до бюджету відповідно до законодавства", "item", None),
    ("4220", "Сума чистого прибутку на створення спеціальних (цільових) фондів", "item", None),
    ("4225", "Сума чистого прибутку на матеріальне заохочення", "item", None),
    ("", "Внески учасників:", "section", None),
    ("4240", "Внески до капіталу", "item", None),
    ("4245", "Погашення заборгованості з капіталу", "item", None),
    ("", "Вилучення капіталу:", "section", None),
    ("4260", "Викуп акцій (часток)", "item", None),
    ("4265", "Перепродаж викуплених акцій (часток)", "item", None),
    ("4270", "Анулювання викуплених акцій (часток)", "item", None),
    ("4275", "Вилучення частки в капіталі", "item", None),
    ("4280", "Зменшення номінальної вартості акцій", "item", None),
    ("4290", "Інші зміни в капіталі", "item", None),
    ("4291", "Придбання (продаж) неконтрольованої частки в дочірньому підприємстві", "item", None),
    ("4295", "Разом змін у капіталі", "total", None),
    ("4300", "Залишок на кінець року", "total", None),
]
ROW_SELECTION = [(code, "%s %s" % (code, name)) for code, name, kind, _parent in ROWS
                 if kind in ("adjust", "item", "sub")]
ADJUST_ROWS = [code for code, _name, kind, _parent in ROWS if kind == "adjust"]
CHANGE_ROWS = [code for code, _name, kind, _parent in ROWS if kind in ("item", "sub")]
FALLBACK_ROW = "4290"
RESULT_ROW = "4100"
# Рядки, де графа 10 має бути нулем: перерозподіл усередині капіталу.
ZERO_TOTAL_ROWS = ("4205", "4210")
SIDES = [("any", "Будь-який"), ("debit", "Дебет"), ("credit", "Кредит")]
SOURCES = [
    ("line", "Рядок на рядку проводки"),
    ("move", "Рядок на проводці"),
    ("rule", "Правило"),
    ("result", "Фінансовий результат"),
    ("fallback", "Без правила"),
]


def ua_column_of(code):
    """Графа форми для рахунку капіталу; None - не капітал."""
    code = code or ""
    for key, _label, prefixes in COLUMNS:
        if code.startswith(prefixes):
            return key
    return None


def ua_is_result(code):
    return bool(code) and ua_column_of(code) is None and code.startswith(RESULT_PREFIXES)


class UaEquityRule(models.Model):
    _name = "ua.equity.rule"
    _description = "Правило рядка форми № 4 за рахунком"
    _order = "sequence, account_prefix, counter_prefix"

    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", string="Компанія",
        help="Порожньо - для всіх компаній. Правило компанії важить більше за спільне.")
    account_prefix = fields.Char(
        "Рахунок капіталу (початок коду)", required=True, help="Напр. 44 - усі рахунки 441, 442, 443.")
    side = fields.Selection(
        SIDES, string="Бік", required=True, default="any",
        help="Дебет чи кредит рахунку капіталу в цьому русі.")
    counter_prefix = fields.Char(
        "Кор. рахунок (початок коду)",
        help="Рахунок на протилежному боці тієї самої проводки. Порожньо - будь-який.")
    row = fields.Selection(ROW_SELECTION, string="Рядок форми", required=True)
    note = fields.Char("Примітка")

    @api.constrains("account_prefix", "counter_prefix")
    def _check_prefix(self):
        for rule in self:
            for value in (rule.account_prefix, rule.counter_prefix):
                if value and not value.strip().isdigit():
                    raise ValidationError(_("Початок коду рахунку - лише цифри: %s") % value)
            if not ua_column_of(rule.account_prefix.strip()):
                raise ValidationError(_("Правило форми № 4 - лише для рахунків капіталу 40-46: %s")
                                      % rule.account_prefix)

    @api.model
    def ua_pick(self, rules, company, code, side, counter_codes):
        """Найточніше правило: найдовші коди, далі з боком, далі правило компанії."""
        best, best_key = self.browse(), None
        for rule in rules:
            prefix = rule.account_prefix.strip()
            if not code.startswith(prefix):
                continue
            if rule.side != "any" and rule.side != side:
                continue
            if rule.company_id and rule.company_id != company:
                continue
            counter = (rule.counter_prefix or "").strip()
            if counter and not any(c.startswith(counter) for c in counter_codes):
                continue
            key = (len(prefix) + len(counter), rule.side != "any", bool(rule.company_id), -rule.sequence)
            if best_key is None or key > best_key:
                best, best_key = rule, key
        return best


class UaEquityStatement(models.Model):
    _name = "ua.equity.statement"
    _description = "Звіт про власний капітал (форма № 4)"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(
        "З", required=True, tracking=True,
        default=lambda self: (fields.Date.context_today(self) - relativedelta(years=1)).replace(month=1, day=1))
    date_to = fields.Date(
        "По", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1) - timedelta(days=1))
    state = fields.Selection(
        [("draft", "Чернетка"), ("done", "Затверджено")], default="draft", required=True, tracking=True)
    line_ids = fields.One2many(
        "ua.equity.statement.line", "statement_id", string="Звітний рік",
        domain=[("period", "=", "current")])
    line_prev_ids = fields.One2many(
        "ua.equity.statement.line", "statement_id", string="Попередній рік",
        domain=[("period", "=", "previous")])
    entry_ids = fields.One2many("ua.equity.statement.entry", "statement_id", string="Розшифровка")
    opening = fields.Monetary("Капітал на початок (4000)", currency_field="currency_id", readonly=True)
    closing = fields.Monetary("Капітал на кінець (4300)", currency_field="currency_id", readonly=True)
    book_closing = fields.Monetary(
        "Капітал за обліком на кінець", currency_field="currency_id", readonly=True,
        help="Сальдо рахунків 40-46 і незакритий фінансовий результат: рядок 1495 балансу.")
    profit = fields.Monetary(
        "Чистий результат (4100)", currency_field="currency_id", readonly=True,
        help="Має дорівнювати рядку 2350 (2355) звіту про фінансові результати.")
    check_text = fields.Text("Зауваження", readonly=True)
    fallback_count = fields.Integer("Рухів без правила", compute="_compute_fallback")
    computed_at = fields.Datetime("Розраховано", readonly=True)

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for st in self:
            if st.date_from and st.date_to:
                st.name = "Ф4 %s - %s" % (st.date_from.strftime("%d.%m.%Y"), st.date_to.strftime("%d.%m.%Y"))
            else:
                st.name = "Ф4"

    @api.depends("entry_ids.source", "entry_ids.period")
    def _compute_fallback(self):
        for st in self:
            st.fallback_count = len(st.entry_ids.filtered(
                lambda e: e.period == "current" and e.source == "fallback"))

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for st in self:
            if st.date_from and st.date_to and st.date_from > st.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    # ------------------------------------------------------------------ розрахунок
    def _ua_accounts(self):
        """Рахунки капіталу і фінансового результату компанії: {рахунок: графа або 'result'}."""
        Account = self.env["account.account"].with_company(self.company_id)
        prefixes = [p for _key, _label, ps in COLUMNS for p in ps] + list(RESULT_PREFIXES)
        domain = ["|"] * (len(prefixes) - 1) + [("code", "=like", p + "%") for p in prefixes]
        result = {}
        for account in Account.search(domain + [("company_ids", "in", self.company_id.id)]):
            column = ua_column_of(account.code)
            if column:
                result[account] = column
            elif ua_is_result(account.code):
                result[account] = "result"
        return result

    def _ua_balances_before(self, accounts, day):
        """Капітал за графами до дня (не включно): кредит мінус дебет."""
        totals = dict.fromkeys(COLUMN_KEYS, 0.0)
        if not accounts:
            return totals
        by_id = {account.id: column for account, column in accounts.items()}
        groups = self.env["account.move.line"]._read_group(
            [("account_id", "in", list(by_id)), ("parent_state", "=", "posted"),
             ("company_id", "=", self.company_id.id), ("date", "<", day)],
            groupby=["account_id"], aggregates=["balance:sum"])
        for account, balance in groups:
            column = by_id[account.id]
            totals["retained" if column == "result" else column] -= balance or 0.0
        return totals

    def _ua_row_for(self, line, rules):
        """Рядок форми, джерело і правило для рядка проводки на рахунку капіталу."""
        if line.ua_equity_row:
            return line.ua_equity_row, "line", False
        if line.move_id.ua_equity_row:
            return line.move_id.ua_equity_row, "move", False
        currency = self.company_id.currency_id
        debit = line.balance > 0
        counters = [other.account_id.code or "" for other in line.move_id.line_ids
                    if other != line and not currency.is_zero(other.balance) and (other.balance > 0) != debit]
        rule = self.env["ua.equity.rule"].ua_pick(
            rules, self.company_id, line.account_id.code or "", "debit" if debit else "credit", counters)
        if rule:
            return rule.row, "rule", rule
        return FALLBACK_ROW, "fallback", False

    def _ua_entries(self, date_from, date_to, period, accounts=None):
        """Рухи капіталу за період: список значень для рядків розшифровки."""
        accounts = accounts if accounts is not None else self._ua_accounts()
        equity = [a.id for a, column in accounts.items() if column != "result"]
        result_ids = [a.id for a, column in accounts.items() if column == "result"]
        currency = self.company_id.currency_id
        base = [("parent_state", "=", "posted"), ("company_id", "=", self.company_id.id),
                ("date", ">=", date_from), ("date", "<=", date_to)]
        rules = self.env["ua.equity.rule"].search([("company_id", "in", [False, self.company_id.id])])
        entries = []
        lines = self.env["account.move.line"].search(base + [("account_id", "in", equity)], order="date, move_id, id")
        for line in lines:
            if currency.is_zero(line.balance):
                continue
            row, source, rule = self._ua_row_for(line, rules)
            counters = sorted({other.account_id.code for other in line.move_id.line_ids
                               if (other.balance > 0) != (line.balance > 0) and not currency.is_zero(other.balance)})
            entries.append({
                "statement_id": self.id, "period": period, "row": row,
                "column": ua_column_of(line.account_id.code), "move_id": line.move_id.id,
                "move_line_id": line.id, "date": line.date, "partner_id": line.partner_id.id,
                "account_id": line.account_id.id, "counter_codes": ", ".join(c for c in counters if c),
                "source": source, "rule_id": rule.id if rule else False, "amount": -line.balance,
            })
        if result_ids:
            groups = self.env["account.move.line"]._read_group(
                base + [("account_id", "in", result_ids)], aggregates=["balance:sum"])
            result = -((groups[0][0] or 0.0) if groups else 0.0)
            if not currency.is_zero(result):
                entries.append({
                    "statement_id": self.id, "period": period, "row": RESULT_ROW, "column": "retained",
                    "date": date_to, "source": "result", "amount": result,
                    "counter_codes": _("рахунки класів 7-9"),
                })
        return entries

    def _ua_form_lines(self, period, entries, opening):
        """Рядки форми одного року: суми за графами і разом."""
        cells = defaultdict(lambda: dict.fromkeys(COLUMN_KEYS, 0.0))
        for values in entries:
            cells[values["row"]][values["column"]] += values["amount"]
        children = defaultdict(list)
        for code, _name, _kind, parent in ROWS:
            if parent:
                children[parent].append(code)

        def shown(code):
            amounts = dict(cells[code])
            for child in children[code]:
                for key in COLUMN_KEYS:
                    amounts[key] += cells[child][key]
            return amounts

        def add(*parts):
            return {key: sum(part[key] for part in parts) for key in COLUMN_KEYS}

        adjusted = add(opening, *[cells[code] for code in ADJUST_ROWS])
        changes = add(*[cells[code] for code in CHANGE_ROWS])
        fixed = {"4000": opening, "4095": adjusted, "4295": changes, "4300": add(adjusted, changes)}
        rows, seq = [], 0
        for code, name, kind, _parent in ROWS:
            seq += 10
            values = {"period": period, "sequence": seq, "code": code, "name": name, "row_kind": kind}
            if kind != "section":
                amounts = fixed.get(code) or shown(code)
                values.update({"amount_" + key: amounts[key] for key in COLUMN_KEYS})
                values["amount_total"] = sum(amounts.values())
            rows.append(values)
        return rows

    def action_compute(self):
        for st in self:
            if st.state == "done":
                raise UserError(_("Затверджений звіт не перераховують: поверніть його в чернетку."))
            st.entry_ids.unlink()
            (st.line_ids | st.line_prev_ids).unlink()
            accounts = st._ua_accounts()
            prev_from = st.date_from - relativedelta(years=1)
            prev_to = st.date_to - relativedelta(years=1)
            current = st._ua_entries(st.date_from, st.date_to, "current", accounts)
            previous = st._ua_entries(prev_from, prev_to, "previous", accounts)
            self.env["ua.equity.statement.entry"].create(current + previous)
            rows = st._ua_form_lines("current", current, st._ua_balances_before(accounts, st.date_from)) + \
                st._ua_form_lines("previous", previous, st._ua_balances_before(accounts, prev_from))
            self.env["ua.equity.statement.line"].create([dict(row, statement_id=st.id) for row in rows])
            st.invalidate_recordset(["line_ids", "line_prev_ids", "entry_ids"])
            book = st._ua_balances_before(accounts, st.date_to + timedelta(days=1))
            lines = {line.code: line for line in st.line_ids}
            st.write({
                "opening": lines["4000"].amount_total, "closing": lines["4300"].amount_total,
                "book_closing": sum(book.values()), "profit": lines["4100"].amount_total,
                "check_text": st._ua_check_text(lines, book), "computed_at": fields.Datetime.now(),
            })
        return True

    def _ua_check_text(self, lines, book):
        """Зауваження до розрахованого звіту: порожньо - усе гаразд."""
        currency = self.company_id.currency_id
        notes = []
        for code in ZERO_TOTAL_ROWS:
            if not currency.is_zero(lines[code].amount_total):
                notes.append(_("Рядок %(code)s, графа 10: %(amount).2f замість нуля - це перерозподіл "
                               "усередині капіталу, обидва боки мають бути в одному рядку.")
                             % {"code": code, "amount": lines[code].amount_total})
        labels = dict(COLUMN_SELECTION)
        for key in COLUMN_KEYS:
            if currency.compare_amounts(lines["4300"]["amount_" + key], book[key]):
                notes.append(_("Графа «%(column)s»: на кінець %(report).2f, за обліком %(book).2f.")
                             % {"column": labels[key], "report": lines["4300"]["amount_" + key],
                                "book": book[key]})
        return "\n".join(notes) or False

    def action_done(self):
        for st in self:
            if not st.line_ids:
                raise UserError(_("Спершу розрахуйте звіт."))
            if st.currency_id.compare_amounts(st.closing, st.book_closing):
                raise UserError(_(
                    "Капітал на кінець за звітом (%(report).2f) не дорівнює сальдо рахунків капіталу "
                    "(%(book).2f). Перерахуйте звіт.") % {"report": st.closing, "book": st.book_closing})
            st.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_open_fallback(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Рухи капіталу без правила"),
            "res_model": "ua.equity.statement.entry", "view_mode": "list,form",
            "domain": [("statement_id", "=", self.id), ("period", "=", "current"), ("source", "=", "fallback")],
        }

    def action_print(self):
        return self.env.ref("l10n_ua_equity.action_report_ua_equity").report_action(self)

    # ------------------------------------------------------------------ друк
    def ua_columns(self):
        return COLUMN_SELECTION

    def ua_rows(self, period="current"):
        """Рядки для друку: назва, код, вид, суми граф 3-9, разом."""
        self.ensure_one()
        lines = self.line_ids if period == "current" else self.line_prev_ids
        return [(line.name, line.code, line.row_kind,
                 [line["amount_" + key] for key in COLUMN_KEYS], line.amount_total)
                for line in lines.sorted("sequence")]

    def ua_money(self, value):
        """Сума для форми: від'ємна в дужках, нуль - прочерк."""
        self.ensure_one()
        if self.currency_id.is_zero(value or 0.0):
            return "-"
        text = "{:,.2f}".format(abs(value)).replace(",", " ")
        return "(%s)" % text if value < 0 else text


class UaEquityStatementLine(models.Model):
    _name = "ua.equity.statement.line"
    _description = "Рядок форми № 4"
    _order = "period, sequence, id"

    statement_id = fields.Many2one("ua.equity.statement", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="statement_id.company_id", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")
    period = fields.Selection(
        [("current", "Звітний рік"), ("previous", "Попередній рік")], required=True, default="current")
    sequence = fields.Integer()
    code = fields.Char("Код рядка")
    name = fields.Char("Стаття", required=True)
    row_kind = fields.Selection(
        [("section", "Розділ"), ("opening", "Залишок"), ("adjust", "Коригування"), ("item", "Рядок"),
         ("sub", "У тому числі"), ("total", "Підсумок")], string="Вид", required=True, default="item")
    amount_registered = fields.Monetary("Зареєстрований капітал", currency_field="currency_id")
    amount_revaluation = fields.Monetary("Капітал у дооцінках", currency_field="currency_id")
    amount_additional = fields.Monetary("Додатковий капітал", currency_field="currency_id")
    amount_reserve = fields.Monetary("Резервний капітал", currency_field="currency_id")
    amount_retained = fields.Monetary("Нерозподілений прибуток", currency_field="currency_id")
    amount_unpaid = fields.Monetary("Неоплачений капітал", currency_field="currency_id")
    amount_withdrawn = fields.Monetary("Вилучений капітал", currency_field="currency_id")
    amount_total = fields.Monetary("Всього", currency_field="currency_id")

    def action_open_entries(self):
        self.ensure_one()
        codes = [self.code] + [code for code, _n, _k, parent in ROWS if parent == self.code]
        return {
            "type": "ir.actions.act_window", "name": "%s %s" % (self.code or "", self.name),
            "res_model": "ua.equity.statement.entry", "view_mode": "list,form",
            "domain": [("statement_id", "=", self.statement_id.id), ("period", "=", self.period),
                       ("row", "in", codes)],
            "context": {"search_default_g_column": 1},
        }


class UaEquityStatementEntry(models.Model):
    _name = "ua.equity.statement.entry"
    _description = "Рух капіталу в розшифровці форми № 4"
    _order = "period, date, id"

    statement_id = fields.Many2one("ua.equity.statement", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="statement_id.company_id", store=True)
    currency_id = fields.Many2one(related="statement_id.currency_id")
    period = fields.Selection(
        [("current", "Звітний рік"), ("previous", "Попередній рік")], required=True, default="current")
    row = fields.Selection(ROW_SELECTION, string="Рядок форми", required=True)
    column = fields.Selection(COLUMN_SELECTION, string="Графа", required=True)
    move_id = fields.Many2one("account.move", string="Проводка", ondelete="cascade")
    move_line_id = fields.Many2one("account.move.line", string="Рядок проводки", ondelete="cascade")
    date = fields.Date("Дата")
    partner_id = fields.Many2one("res.partner", string="Контрагент")
    account_id = fields.Many2one("account.account", string="Рахунок капіталу")
    counter_codes = fields.Char("Кор. рахунки")
    source = fields.Selection(SOURCES, string="Звідки рядок", required=True)
    rule_id = fields.Many2one("ua.equity.rule", string="Правило")
    amount = fields.Monetary(
        "Сума", currency_field="currency_id", help="Збільшення капіталу зі знаком плюс, зменшення - мінус.")

    def action_set_row(self, row):
        """Записати рядок форми на рядок проводки: наступний розрахунок візьме його першим."""
        if row not in dict(ROW_SELECTION):
            raise UserError(_("Немає такого рядка форми № 4: %s") % row)
        for entry in self:
            if not entry.move_line_id:
                raise UserError(_("Фінансовий результат іде в рядок 4100: його рядок не змінюють."))
            entry.move_line_id.sudo().ua_equity_row = row
            entry.write({"row": row, "source": "line"})
        return True
