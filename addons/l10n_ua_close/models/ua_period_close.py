"""Регламентні операції закриття місяця - те, що в 1С робить обробка «Закриття місяця».

Порядок сталий. Кожна операція - проводка, позначена місяцем і видом
(`account.move.ua_close_id`, `ua_close_kind`), тож операцію видно, її можна скасувати і
провести знову:

1. Амортизація: проводяться рядки амортизації місяця з OCA account_asset_management
   (якщо модуль активів стоїть).
2. Переоцінка валюти (П(С)БО 21): залишки валютних банківських рахунків і відкриті валютні
   борги покупців і постачальників - за курсом на останній день місяця. Аванси - немонетарні
   статті, їх не переоцінюють. Різниця йде на 714 або 945, а першого числа наступного місяця
   проводка сторнується: курсову різницю при оплаті Odoo рахує сам від курсу документа, і
   без сторно вона потрапила б у звіт двічі.
3. Загальновиробничі витрати: документ розподілу ЗВВ з l10n_ua_mrp (231 і 901 за нормальною
   потужністю) або, без виробництва, усе сальдо 91 на 901.
4. Фінансовий результат: сальдо рахунків класів 7 і 9 - на 791, 792, 793.
5. Останній місяць фінансового року: сальдо 79 на 441 (прибуток) або 442 (збиток).

Проводки 4 і 5 ідуть в окремий журнал «Закриття періоду» (код CLS). Ф2 і Ф2-м цей журнал
пропускають: доходи і витрати у звіті - обороти без закриття, як у 1С. Проводка 3 - не
закриття, а перенесення витрат у собівартість, тому вона в звичайному журналі і Ф2 її бачить.
"""
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

CLOSING_JOURNAL_CODE = "CLS"

OPERATIONS = ("depreciation", "fx", "overhead", "result", "year")
TITLES = {
    "depreciation": "Нарахування амортизації",
    "fx": "Переоцінка валютних коштів і боргів",
    "overhead": "Загальновиробничі витрати (91)",
    "result": "Фінансовий результат: класи 7 і 9 на 79",
    "year": "Закриття року: 79 на 44",
}
# Перші дві цифри рахунку класу 7 або 9 -> субрахунок 79 (Інструкція до плану рахунків, 291).
RESULT_MAP = {
    "70": "791", "71": "791", "90": "791", "92": "791", "93": "791", "94": "791", "98": "791",
    "72": "792", "73": "792", "95": "792", "96": "792",
    "74": "793", "75": "793", "76": "793", "97": "793", "99": "793",
}
# Наш короткий код -> xmlid шаблону ua_psbo.
ACCOUNTS = {
    "791": "ua_psbp_791", "792": "ua_psbp_792", "793": "ua_psbp_793",
    "441": "ua_psbp_441", "442": "ua_psbp_442", "901": "ua_psbp_901",
    "714": "ua_psbp_714", "945": "ua_psbp_945",
}
STATE_WORDS = {"done": "проведено", "todo": "до проведення", "skip": "нічого проводити",
               "stale": "застаріло"}
STATE_CLASS = {"done": "text-success", "todo": "", "skip": "text-muted", "stale": "text-warning"}


def _money(value):
    return ("%.2f" % value).replace(".", ",")


class UaPeriodClose(models.Model):
    _inherit = "ua.period.close"

    ua_close_move_ids = fields.One2many("account.move", "ua_close_id", "Проводки операцій",
                                        readonly=True)
    ua_operations_html = fields.Html("Регламентні операції", compute="_compute_ua_operations",
                                     sanitize=False)
    ua_operations_pending = fields.Boolean("Є операції до проведення",
                                           compute="_compute_ua_operations")

    # ------------------------------------------------------------------ рахунки і журнали
    @api.model
    def _ua_close_account(self, company, code):
        """Рахунок плану за нашим кодом: за xmlid шаблону, інакше за кодом (701 і 701000)."""
        account = self.env["account.chart.template"].with_company(company).ref(
            ACCOUNTS[code], raise_if_not_found=False)
        if account:
            return account
        for candidate in self.env["account.account"].with_company(company).search(
                [("code", "=like", code + "%"), ("company_ids", "in", company.ids)], order="code"):
            if candidate.code == code or candidate.code.rstrip("0") == code:
                return candidate
        raise UserError(_("У плані рахунків компанії «%(company)s» немає рахунку %(code)s.",
                          company=company.name, code=code))

    @api.model
    def _ua_closing_journal(self, company):
        """Журнал «Закриття періоду» (CLS): його проводки Ф2 пропускає."""
        Journal = self.env["account.journal"].sudo()
        journal = Journal.search([("company_id", "=", company.id),
                                  ("code", "=", CLOSING_JOURNAL_CODE)], limit=1)
        if not journal:
            journal = Journal.create({"name": "Закриття періоду", "code": CLOSING_JOURNAL_CODE,
                                      "type": "general", "company_id": company.id,
                                      "show_on_dashboard": False})
        return journal.sudo(False)

    @api.model
    def _ua_general_journal(self, company):
        journal = self.env["account.journal"].search([
            ("company_id", "=", company.id), ("type", "=", "general"),
            ("code", "!=", CLOSING_JOURNAL_CODE)], order="sequence, id", limit=1)
        if not journal:
            raise UserError(_("У компанії «%s» немає журналу загальних операцій.") % company.name)
        return journal

    @api.model
    def _ua_balances(self, company, prefixes, last):
        """Сальдо рахунків із кодами на `prefixes` на кінець дня `last`: [(рахунок, сальдо)]."""
        codes = ["|"] * (len(prefixes) - 1) + [("code", "=like", p + "%") for p in prefixes]
        accounts = self.env["account.account"].with_company(company).search(
            [("company_ids", "in", company.ids)] + codes)
        if not accounts:
            return []
        groups = self.env["account.move.line"]._read_group(
            [("account_id", "in", accounts.ids), ("company_id", "=", company.id),
             ("parent_state", "=", "posted"), ("date", "<=", last)],
            ["account_id"], ["balance:sum"])
        currency = company.currency_id
        return [(account, currency.round(balance)) for account, balance in groups
                if not currency.is_zero(balance)]

    # ------------------------------------------------------------------ що треба провести
    @api.model
    def _ua_asset_lines(self, company, first, last):
        if "account.asset.line" not in self.env:
            return None
        return self.env["account.asset.line"].search([
            ("asset_id.company_id", "=", company.id), ("asset_id.state", "=", "open"),
            ("type", "=", "depreciate"), ("init_entry", "=", False), ("move_check", "=", False),
            ("line_date", ">=", first), ("line_date", "<=", last)])

    @api.model
    def _ua_fx_items(self, company, last):
        """Різниці переоцінки на `last`: [{account, partner, currency, diff}].

        Банк: залишок у валюті рахунку за курсом мінус залишок у гривні. Борги: залишок
        валютного рядка покупця чи постачальника на цей день (оплати після нього не
        рахуються) за курсом мінус його залишок у гривні. Рядки оплат і виписок - аванси,
        вони не переоцінюються."""
        currency = company.currency_id
        Line = self.env["account.move.line"]
        items = []
        journals = self.env["account.journal"].search([
            ("company_id", "=", company.id), ("type", "in", ("bank", "cash")),
            ("currency_id", "not in", (False, currency.id))])
        for journal in journals:
            account = journal.default_account_id
            if not account:
                continue
            [(amount_currency, balance)] = Line._read_group(
                [("account_id", "=", account.id), ("company_id", "=", company.id),
                 ("parent_state", "=", "posted"), ("date", "<=", last),
                 ("currency_id", "=", journal.currency_id.id)],
                [], ["amount_currency:sum", "balance:sum"])
            target = journal.currency_id._convert(amount_currency or 0.0, currency, company, last)
            diff = currency.round(target - (balance or 0.0))
            if not currency.is_zero(diff):
                items.append({"account": account, "partner": self.env["res.partner"],
                              "currency": journal.currency_id, "diff": diff})

        lines = Line.search([
            ("company_id", "=", company.id), ("parent_state", "=", "posted"),
            ("date", "<=", last),
            ("account_id.account_type", "in", ("asset_receivable", "liability_payable")),
            ("currency_id", "not in", (False, currency.id)),
            ("move_id.origin_payment_id", "=", False), ("move_id.statement_line_id", "=", False),
            ("move_id.ua_close_kind", "=", False),
            "|", "|", ("reconciled", "=", False),
            ("matched_debit_ids.max_date", ">", last), ("matched_credit_ids.max_date", ">", last),
        ])
        groups = defaultdict(float)
        for line in lines:
            residual_currency, residual = line.amount_residual_currency, line.amount_residual
            # Заліки після `last` повертаємо: на цей день борг ще був.
            for partial in line.matched_debit_ids.filtered(lambda p: p.max_date > last):
                residual_currency -= partial.credit_amount_currency
                residual -= partial.amount
            for partial in line.matched_credit_ids.filtered(lambda p: p.max_date > last):
                residual_currency += partial.debit_amount_currency
                residual += partial.amount
            if line.currency_id.is_zero(residual_currency):
                continue
            target = line.currency_id._convert(residual_currency, currency, company, last)
            groups[(line.account_id, line.partner_id, line.currency_id)] += target - residual
        for (account, partner, line_currency), diff in groups.items():
            diff = currency.round(diff)
            if not currency.is_zero(diff):
                items.append({"account": account, "partner": partner, "currency": line_currency,
                              "diff": diff})
        return items

    @api.model
    def _ua_overhead_allocation(self, company, first, last):
        """Проведений документ розподілу ЗВВ за місяць (l10n_ua_mrp), якщо такий є."""
        if "ua.zvv.allocation" not in self.env:
            return None
        return self.env["ua.zvv.allocation"].search([
            ("company_id", "=", company.id), ("state", "=", "posted"),
            ("date_from", "<=", last), ("date_to", ">=", first)], limit=1)

    @api.model
    def operation_rows(self, company, year, month):
        """Регламентні операції місяця по порядку: що проведено і що ще треба провести.

        Рядок: key, title, state (done | todo | skip | stale), text, amount, move_ids.
        stale - фінансовий результат проведено, але після нього в класах 7 і 9 з'явились
        нові суми: операції треба скасувати і провести знову."""
        company = self._as_company(company)
        year, month = int(year), int(month)
        first, last = self._bounds(year, month)
        rec = self.search([("company_id", "=", company.id), ("year", "=", year),
                           ("month", "=", month), ("kind", "=", "month")], limit=1)
        moves = rec.ua_close_move_ids.filtered(lambda m: m.state == "posted")
        currency = company.currency_id
        year_end = month == int(company.fiscalyear_last_month or 12)
        rows = []
        for key in OPERATIONS:
            if key == "year" and not year_end:
                continue
            own = moves.filtered(lambda m, key=key: m.ua_close_kind == key)
            row = {"key": key, "title": TITLES[key], "state": "skip", "amount": 0.0,
                   "move_ids": own.ids, "text": ""}
            if own:
                row["state"] = "done"
                row["amount"] = sum(own.mapped("amount_total"))
                row["text"] = _("проведено: %(count)s проводк., %(amount)s грн",
                                count=len(own), amount=_money(row["amount"]))
            if key == "depreciation":
                lines = self._ua_asset_lines(company, first, last)
                if lines is None:
                    row["text"] = row["text"] or _("модуль основних засобів не встановлено")
                elif lines:
                    row.update(state="todo", amount=sum(lines.mapped("amount")),
                               text=_("рядків амортизації: %(count)s, %(amount)s грн",
                                      count=len(lines), amount=_money(sum(lines.mapped("amount")))))
            elif key == "fx" and not own:
                items = self._ua_fx_items(company, last)
                if items:
                    gain = sum(i["diff"] for i in items if i["diff"] > 0)
                    loss = -sum(i["diff"] for i in items if i["diff"] < 0)
                    row.update(state="todo", amount=gain + loss,
                               text=_("позитивна різниця %(gain)s грн, негативна %(loss)s грн "
                                      "за курсом на %(day)s", gain=_money(gain), loss=_money(loss),
                                      day=last.strftime("%d.%m.%Y")))
            elif key == "overhead" and not own:
                allocation = self._ua_overhead_allocation(company, first, last)
                if allocation:
                    row.update(state="done", amount=allocation.amount_base,
                               text=_("розподіл ЗВВ %s проведено вручну") % allocation.name)
                else:
                    total = sum(b for _a, b in self._ua_balances(company, ["91"], last))
                    if not currency.is_zero(total):
                        row.update(state="todo", amount=total,
                                   text=_("сальдо 91: %s грн") % _money(total))
            elif key == "result":
                total = self._ua_balances(company, list(RESULT_MAP), last)
                if total:
                    amount = sum(abs(b) for _a, b in total)
                    if own:
                        row["state"] = "stale"
                        row["text"] += _("; після закриття в класах 7 і 9 з'явилось ще "
                                         "%s грн - скасуйте операції і проведіть знову") % _money(amount)
                    else:
                        row.update(state="todo", amount=amount,
                                   text=_("рахунків із сальдо: %(count)s, оборот закриття "
                                          "%(amount)s грн", count=len(total), amount=_money(amount)))
            elif key == "year" and not own:
                pending = self._ua_balances(company, list(RESULT_MAP) + ["79"], last)
                net = sum(b for _a, b in pending)
                if not currency.is_zero(net):
                    row.update(state="todo", amount=abs(net),
                               text=_("%(what)s %(amount)s грн на %(account)s",
                                      what=_("прибуток") if net < 0 else _("збиток"),
                                      amount=_money(abs(net)),
                                      account="441" if net < 0 else "442"))
            if row["state"] == "skip" and not row["text"]:
                row["text"] = _("нічого проводити")
            rows.append(row)
        return rows

    @api.depends("year", "month", "kind", "state", "ua_close_move_ids")
    def _compute_ua_operations(self):
        for rec in self:
            if rec.kind != "month" or not rec.id or not rec.year or not rec.month:
                rec.ua_operations_html = False
                rec.ua_operations_pending = False
                continue
            rows = self.operation_rows(rec.company_id, rec.year, rec.month)
            rec.ua_operations_pending = rec.state != "closed" and any(
                row["state"] in ("todo", "stale") for row in rows)
            items = [Markup('<li class="%s"><b>%s</b> - %s: %s</li>') % (
                STATE_CLASS[row["state"]], escape(row["title"]), STATE_WORDS[row["state"]],
                escape(row["text"])) for row in rows]
            rec.ua_operations_html = Markup('<ol class="o_ua_operations">%s</ol>') % Markup(
                "").join(items)

    @api.model
    def plan(self, company, year, month):
        """План закриття ще й нагадує про непроведені регламентні операції: після дати
        блокування провести їх у цьому місяці вже не вийде."""
        rows = super().plan(company, year, month)
        company = self._as_company(company)
        closed = self.search_count([("company_id", "=", company.id), ("year", "=", int(year)),
                                    ("month", "=", int(month)), ("kind", "=", "month"),
                                    ("state", "=", "closed")])
        if closed:
            return rows
        pending = [row["title"] for row in self.operation_rows(company, year, month)
                   if row["state"] in ("todo", "stale")]
        if pending:
            rows.insert(1, {
                "text": _("Регламентні операції не проведені: %s. Проведіть їх кнопкою "
                          "«Регламентні операції» до закриття - після дати блокування провести "
                          "їх у цьому місяці вже не можна.") % ", ".join(pending).lower(),
                "level": "warn",
            })
        return rows

    # ------------------------------------------------------------------ проведення
    def _ua_check_operations(self):
        self.ensure_one()
        if self.kind != "month":
            raise UserError(_("Регламентні операції проводять за місяць, не за квартал чи рік."))
        if self.state == "closed":
            raise UserError(_("Місяць %s закрито. Відкрийте його, щоб змінити операції.") % self.name)
        company = self.company_id
        first, last = self._bounds(self.year, self.month)
        lock = max(filter(None, [company.fiscalyear_lock_date, company.hard_lock_date]),
                   default=None)
        if lock and lock >= first:
            raise UserError(_("Облік компанії заблоковано по %s: проводити в цьому місяці не "
                              "можна.") % lock.strftime("%d.%m.%Y"))
        later = self.env["account.move"].search([
            ("company_id", "=", company.id), ("ua_close_kind", "in", ("result", "year")),
            ("date", ">", last)], order="date", limit=1)
        if later:
            raise UserError(_("Регламентні операції проведено вже за пізніший місяць (%s). "
                              "Спершу скасуйте їх там.") % later.ua_close_id.name)
        return first, last

    def _ua_mark(self, moves, kind):
        moves.write({"ua_close_id": self.id, "ua_close_kind": kind})

    def _ua_post_entry(self, journal, last, ref, lines, kind):
        move = self.env["account.move"].create({
            "journal_id": journal.id, "company_id": self.company_id.id, "date": last,
            "ref": ref, "move_type": "entry", "line_ids": [(0, 0, line) for line in lines],
            "ua_close_id": self.id, "ua_close_kind": kind,
        })
        move.action_post()
        return move

    def _ua_run_depreciation(self, first, last):
        lines = self._ua_asset_lines(self.company_id, first, last)
        if lines:
            self._ua_mark(self.env["account.move"].browse(lines.create_move()), "depreciation")

    def _ua_run_fx(self, first, last):
        company = self.company_id
        items = self._ua_fx_items(company, last)
        if not items:
            return
        day = last.strftime("%d.%m.%Y")
        lines = [{
            "account_id": item["account"].id, "partner_id": item["partner"].id or False,
            "currency_id": item["currency"].id, "amount_currency": 0.0,
            "balance": item["diff"],
            "name": _("Переоцінка %(currency)s за курсом на %(day)s",
                      currency=item["currency"].name, day=day),
        } for item in items]
        gain = company.currency_id.round(sum(i["diff"] for i in items if i["diff"] > 0))
        loss = company.currency_id.round(sum(i["diff"] for i in items if i["diff"] < 0))
        if gain:
            account = company.income_currency_exchange_account_id or self._ua_close_account(
                company, "714")
            lines.append({"account_id": account.id, "balance": -gain,
                          "name": _("Позитивна курсова різниця на %s") % day})
        if loss:
            account = company.expense_currency_exchange_account_id or self._ua_close_account(
                company, "945")
            lines.append({"account_id": account.id, "balance": -loss,
                          "name": _("Негативна курсова різниця на %s") % day})
        journal = company.currency_exchange_journal_id or self._ua_general_journal(company)
        move = self._ua_post_entry(journal, last, _("Переоцінка валютних статей на %s") % day,
                                   lines, "fx")
        reverse = move._reverse_moves([{
            "date": last + timedelta(days=1),
            "ref": _("Сторно переоцінки на %s") % day,
        }], cancel=True)
        self._ua_mark(reverse, "fx_reverse")

    def _ua_run_overhead(self, first, last):
        company = self.company_id
        if self._ua_overhead_allocation(company, first, last):
            return
        if "ua.zvv.allocation" in self.env:
            Allocation = self.env["ua.zvv.allocation"]
            previous = Allocation.search([("company_id", "=", company.id),
                                          ("state", "=", "posted")], order="date_from desc",
                                         limit=1)
            # Норми беремо з попереднього розподілу; без нього нормальна потужність 0 -
            # усі постійні ЗВВ нерозподілені, тобто на 901 (п. 16 П(С)БО 16).
            allocation = Allocation.create({
                "company_id": company.id, "date_from": first,
                "normal_hours": previous.normal_hours if previous else 0.0,
                "fixed_share": previous.fixed_share if previous else 100.0,
                "note": _("Закриття місяця %s") % self.name,
            })
            allocation.action_compute()
            if company.currency_id.is_zero(allocation.amount_base):
                allocation.unlink()
                return
            allocation.action_post()
            self._ua_mark(allocation.move_id, "overhead")
            return
        balances = self._ua_balances(company, ["91"], last)
        total = sum(balance for _account, balance in balances)
        if company.currency_id.is_zero(total):
            return
        lines = [{"account_id": account.id, "balance": -balance,
                  "name": _("Списання загальновиробничих витрат")} for account, balance in balances]
        lines.append({"account_id": self._ua_close_account(company, "901").id, "balance": total,
                      "name": _("Загальновиробничі витрати в собівартість реалізації")})
        self._ua_post_entry(self._ua_general_journal(company), last,
                            _("Закриття 91 за %s") % self.name, lines, "overhead")

    def _ua_run_result(self, first, last):
        company = self.company_id
        balances = self._ua_balances(company, list(RESULT_MAP), last)
        if not balances:
            return
        lines, per_target = [], defaultdict(float)
        for account, balance in balances:
            target = RESULT_MAP[account.code[:2]]
            per_target[target] += balance
            lines.append({"account_id": account.id, "balance": -balance,
                          "name": _("Закриття на %s") % target})
        for target, amount in sorted(per_target.items()):
            if not company.currency_id.is_zero(amount):
                lines.append({"account_id": self._ua_close_account(company, target).id,
                              "balance": company.currency_id.round(amount),
                              "name": _("Фінансовий результат за %s") % self.name})
        self._ua_post_entry(self._ua_closing_journal(company), last,
                            _("Фінансовий результат за %s") % self.name, lines, "result")

    def _ua_run_year(self, first, last):
        company = self.company_id
        if self.month != int(company.fiscalyear_last_month or 12):
            return
        balances = self._ua_balances(company, ["79"], last)
        net = company.currency_id.round(sum(balance for _account, balance in balances))
        if company.currency_id.is_zero(net):
            return
        lines = [{"account_id": account.id, "balance": -balance,
                  "name": _("Закриття 79 за рік")} for account, balance in balances]
        # Кредитове сальдо 79 - прибуток (441), дебетове - збиток (442).
        target = self._ua_close_account(company, "441" if net < 0 else "442")
        lines.append({"account_id": target.id, "balance": net,
                      "name": _("Прибуток за %s рік") % self.year if net < 0
                      else _("Збиток за %s рік") % self.year})
        self._ua_post_entry(self._ua_closing_journal(company), last,
                            _("Закриття року %s") % self.year, lines, "year")

    def run_operations(self):
        """Провести регламентні операції місяця, які ще не проведені, по порядку."""
        self.ensure_one()
        rec = self.with_company(self.company_id)
        first, last = rec._ua_check_operations()
        done = set(rec.ua_close_move_ids.filtered(lambda m: m.state == "posted")
                   .mapped("ua_close_kind"))
        for key in OPERATIONS:
            # Амортизацію проводимо щоразу: рядки, додані після першого проведення, теж мають
            # потрапити в місяць, а вже проведені вона не чіпає.
            if key == "depreciation" or key not in done:
                getattr(rec, "_ua_run_" + key)(first, last)
        self.invalidate_recordset()
        return True

    def undo_operations(self):
        """Скасувати регламентні операції місяця: проводки видаляються, рядки амортизації
        знову чекають проведення, документ розподілу ЗВВ видаляється."""
        self.ensure_one()
        rec = self.with_company(self.company_id)
        rec._ua_check_operations()
        moves = rec.ua_close_move_ids
        if "account.asset.line" in self.env:
            asset_lines = self.env["account.asset.line"].search([("move_id", "in", moves.ids)])
            for line in asset_lines:
                move = line.move_id
                move.button_draft()
                move.with_context(force_delete=True, unlink_from_asset=True).unlink()
                line.with_context(unlink_from_asset=True).update_asset_line_after_unlink_move()
            moves = moves.exists()
        if "ua.zvv.allocation" in self.env:
            allocations = self.env["ua.zvv.allocation"].search([("move_id", "in", moves.ids)])
            allocation_moves = allocations.move_id
            allocations.write({"state": "draft", "move_id": False})
            allocations.unlink()
            allocation_moves.button_draft()
            allocation_moves.with_context(force_delete=True).unlink()
            moves = moves.exists()
        moves.filtered(lambda m: m.state == "posted").button_draft()
        moves.with_context(force_delete=True).unlink()
        self.invalidate_recordset()
        return True

    def _ua_done(self, message):
        """Повідомлення і перечитана форма: кнопки й список операцій змінились."""
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": message, "type": "success", "sticky": False,
                           "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_ua_run_operations(self):
        self.run_operations()
        return self._ua_done(_("Регламентні операції за %s проведено.") % self.name)

    def action_ua_undo_operations(self):
        self.undo_operations()
        return self._ua_done(_("Регламентні операції за %s скасовано.") % self.name)
