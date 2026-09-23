"""Оборотно-сальдова відомість.

Числа беремо з того самого запиту, що й оборотний баланс OCA
(report.account_financial_report.trial_balance._get_data): сальдо на початок,
обороти Дт і Кт за період, сальдо на кінець по кожному рахунку. Цей запит уже
вміє те, що самому писати довго й легко зіпсувати: рахунки класів 7-9 беруть
сальдо не з початку часів, а з початку фінансового року, а прибуток минулих
періодів зводиться на рахунок нерозподіленого прибутку.

Наше тут - подання, а не рахунок:
* розгорнуте сальдо в окремі колонки Дт і Кт (в Odoo сальдо одне число зі знаком);
* групування за класами плану і за першими цифрами коду;
* контрольний рядок: Σ обороту Дт має дорівнювати Σ обороту Кт.

Задокументоване спрощення: розгортаємо сальдо за знаком сальдо рахунку в цілому,
без розгортання по субконто. Рахунок 631 із дебіторкою одного постачальника і
кредиторкою іншого покаже згорнуте сальдо; щоб побачити розгорнуте - картка
рахунку з фільтром партнера.
"""
from odoo import api, fields, models
from odoo.tools import date_utils

TRIAL_BALANCE = "report.account_financial_report.trial_balance"
DETAIL_PREFIX = {"c3": 3, "c2": 2, "c1": 1}


class UaOsvReport(models.Model):
    _name = "ua.osv.report"
    _inherit = "ua.ledger.base"
    _description = "Оборотно-сальдова відомість"
    _order = "date_from desc, id desc"
    _ua_result_view = "l10n_ua_ledger.view_ua_osv_report_form"
    _ua_ask_view = "l10n_ua_ledger.view_ua_osv_report_ask"

    name = fields.Char("Назва", compute="_compute_name", store=True)

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for osv in self:
            osv.name = "Оборотно-сальдова відомість %s" % osv._ua_period_label()

    detail = fields.Selection(
        [
            ("account", "За рахунками"),
            ("c3", "Субрахунки (3 цифри)"),
            ("c2", "Групи (2 цифри)"),
            ("c1", "Класи (1 цифра)"),
        ],
        "Деталізація", required=True, default="account",
    )
    skip_zero = fields.Boolean(
        "Сховати порожні рядки", default=True,
        help="Не показувати рахунки, де і сальдо, і обороти нульові.",
    )
    line_ids = fields.One2many("ua.osv.line", "osv_id", "Рядки", readonly=True)

    total_open_debit = fields.Monetary("Сальдо на початок, Дт", currency_field="currency_id")
    total_open_credit = fields.Monetary("Сальдо на початок, Кт", currency_field="currency_id")
    total_debit = fields.Monetary("Оборот Дт", currency_field="currency_id")
    total_credit = fields.Monetary("Оборот Кт", currency_field="currency_id")
    total_close_debit = fields.Monetary("Сальдо на кінець, Дт", currency_field="currency_id")
    total_close_credit = fields.Monetary("Сальдо на кінець, Кт", currency_field="currency_id")
    control_ok = fields.Boolean("Оборот Дт = оборот Кт", readonly=True)

    # ------------------------------------------------------------------
    def _unaffected_earnings_account(self):
        """Рахунок нерозподіленого прибутку: на нього OCA зводить минулі періоди."""
        self.ensure_one()
        account_model = self.env["account.account"]
        return account_model.search(
            [
                *account_model._check_company_domain(self.company_id),
                ("account_type", "=", "equity_unaffected"),
            ],
            limit=1,
        )

    def _trial_balance_data(self):
        """Виклик запиту OCA. Повертає (підсумки по рахунках, дані рахунків)."""
        self.ensure_one()
        company = self.company_id
        fy_start, _fy_end = date_utils.get_fiscal_year(
            self.date_from,
            day=company.fiscalyear_last_day,
            month=int(company.fiscalyear_last_month),
        )
        total_amount, accounts_data, _partners = self.env[TRIAL_BALANCE]._get_data(
            account_ids=[],
            journal_ids=[],
            partner_ids=[],
            company_id=company.id,
            date_to=self.date_to,
            date_from=self.date_from,
            foreign_currency=False,
            only_posted_moves=True,
            show_partner_details=False,
            hide_account_at_0=self.skip_zero,
            unaffected_earnings_account=self._unaffected_earnings_account().id,
            fy_start_date=fy_start,
            grouped_by=False,
        )
        return total_amount, accounts_data

    @api.model
    def _split_balance(self, balance):
        """Розгорнути сальдо за знаком: додатне - Дт, від'ємне - Кт."""
        if balance > 0:
            return round(balance, 2), 0.0
        if balance < 0:
            return 0.0, round(-balance, 2)
        return 0.0, 0.0

    def action_compute(self):
        for osv in self:
            total_amount, accounts_data = osv._trial_balance_data()
            prefix_len = DETAIL_PREFIX.get(osv.detail)
            buckets = {}
            for account_id, amounts in total_amount.items():
                info = accounts_data.get(account_id) or {}
                account = osv.env["account.account"].browse(account_id)
                code = osv._acc_code(account) or info.get("code") or ""
                if prefix_len:
                    key = code[:prefix_len]
                    name = (
                        osv._class_name(key) if prefix_len == 1 else "Рахунки %s*" % key
                    )
                    bucket = buckets.setdefault(
                        key,
                        {"code": key, "name": name, "account": False,
                         "open": 0.0, "debit": 0.0, "credit": 0.0},
                    )
                else:
                    bucket = buckets.setdefault(
                        account_id,
                        {"code": code, "name": info.get("name") or account.name,
                         "account": account_id,
                         "open": 0.0, "debit": 0.0, "credit": 0.0},
                    )
                bucket["open"] += amounts.get("initial_balance", 0.0)
                bucket["debit"] += amounts.get("debit", 0.0)
                bucket["credit"] += amounts.get("credit", 0.0)

            commands = [(5, 0, 0)]
            totals = dict.fromkeys(
                ("open_debit", "open_credit", "debit", "credit", "close_debit", "close_credit"), 0.0
            )
            sequence = 0
            for key in sorted(buckets, key=lambda k: buckets[k]["code"]):
                values = buckets[key]
                opening = round(values["open"], 2)
                debit = round(values["debit"], 2)
                credit = round(values["credit"], 2)
                closing = round(opening + debit - credit, 2)
                if osv.skip_zero and not any(
                    abs(number) >= 0.005 for number in (opening, debit, credit, closing)
                ):
                    continue
                open_debit, open_credit = osv._split_balance(opening)
                close_debit, close_credit = osv._split_balance(closing)
                for name, number in (
                    ("open_debit", open_debit), ("open_credit", open_credit),
                    ("debit", debit), ("credit", credit),
                    ("close_debit", close_debit), ("close_credit", close_credit),
                ):
                    totals[name] = round(totals[name] + number, 2)
                commands.append((0, 0, {
                    "sequence": sequence,
                    "account_id": values["account"],
                    "code": values["code"],
                    "name": values["name"],
                    "class_name": osv._class_name(values["code"]),
                    "open_debit": open_debit,
                    "open_credit": open_credit,
                    "debit": debit,
                    "credit": credit,
                    "close_debit": close_debit,
                    "close_credit": close_credit,
                }))
                sequence += 1

            osv.write({
                "line_ids": commands,
                "total_open_debit": totals["open_debit"],
                "total_open_credit": totals["open_credit"],
                "total_debit": totals["debit"],
                "total_credit": totals["credit"],
                "total_close_debit": totals["close_debit"],
                "total_close_credit": totals["close_credit"],
                "control_ok": abs(totals["debit"] - totals["credit"]) < 0.01,
            })
        return True

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_compute()
        return self.env.ref("l10n_ua_ledger.action_report_ua_osv_xlsx").report_action(self)


class UaOsvLine(models.Model):
    _name = "ua.osv.line"
    _description = "Рядок оборотно-сальдової відомості"
    _order = "sequence, id"

    osv_id = fields.Many2one("ua.osv.report", "Відомість", required=True, ondelete="cascade")
    currency_id = fields.Many2one("res.currency", related="osv_id.currency_id")
    sequence = fields.Integer("№")
    account_id = fields.Many2one("account.account", "Рахунок плану")
    code = fields.Char("Код")
    name = fields.Char("Рахунок")
    class_name = fields.Char("Клас")
    open_debit = fields.Monetary("Сальдо на початок, Дт", currency_field="currency_id")
    open_credit = fields.Monetary("Сальдо на початок, Кт", currency_field="currency_id")
    debit = fields.Monetary("Оборот Дт", currency_field="currency_id")
    credit = fields.Monetary("Оборот Кт", currency_field="currency_id")
    close_debit = fields.Monetary("Сальдо на кінець, Дт", currency_field="currency_id")
    close_credit = fields.Monetary("Сальдо на кінець, Кт", currency_field="currency_id")

    def action_open_card(self):
        """З рядка відомості - у картку цього рахунку за той самий період."""
        self.ensure_one()
        if not self.account_id:
            return False
        card = self.env["ua.account.card"].create({
            "company_id": self.osv_id.company_id.id,
            "date_from": self.osv_id.date_from,
            "date_to": self.osv_id.date_to,
            "account_id": self.account_id.id,
        })
        card.action_compute()
        return {
            "type": "ir.actions.act_window",
            "name": card.display_name,
            "res_model": "ua.account.card",
            "res_id": card.id,
            "view_mode": "form",
            "views": [(self.env.ref("l10n_ua_ledger.view_ua_account_card_form").id, "form")],
            "target": "current",
        }
