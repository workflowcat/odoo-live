"""Чарівник «Консолідація групи»: збирає звіт mis_builder і нічого не рахує.

Консолідація тут - не окремий розрахунок, а набір колонок над готовим
шаблоном форми з l10n_ua_finrep:

    Компанія А | Компанія Б | Разом до елімінації | Елімінація ВГО | Консолідовано

Колонка компанії - звичайні «Actuals» з фільтром проводок по company_id
(поле `analytic_domain` колонки mis_builder). Колонка елімінації - ті самі
Actuals по всіх компаніях групи, але лише проводки, де контрагент є однією
з компаній групи, і лише на рахунках, які справді згортаються:

  * баланс (Ф1, Ф1-м) - взаємні розрахунки, класи 36, 37, 63, 68;
  * фінрезультати (Ф2, Ф2-м) - доходи і витрати, класи 7, 8, 9.

«Консолідовано» - колонка типу «сума колонок»: плюс кожна компанія, мінус
елімінація. Ніякої арифметики в Python: підсумок складає сам mis_builder.

Чому взаємні розрахунки згортаються самі собою. Дзеркальна пара «дебіторка
А - кредиторка Б» потрапляє в колонку елімінації двома рядками однакової
суми: дебетовим у актив і кредитовим у пасив. Віднімання такої колонки
знімає обидва рядки, і рівність Актив = Пасив не ламається. Якщо ж книги
компаній розійшлися (дзеркало не збігається з оригіналом), колонка
елімінації сама незбалансована, і контрольний рядок форми (1300 - 1900)
покаже рівно розбіжність звірки. Розбіжність не ховається - вона видима в
тому самому звіті.

Чого цей чарівник НЕ робить: не елімінує нереалізований прибуток у
запасах (товар, куплений усередині групи і не проданий назовні, лишається
в балансі за ціною продавця). Див. docs/base/spec-group-profit.md.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

# Шаблон форми і те, що в цій формі згортається.
FORM_SELECTION = [
    ("f1", "Ф1. Баланс (НП(С)БО 1)"),
    ("f2", "Ф2. Звіт про фінансові результати (НП(С)БО 1)"),
    ("f1m", "Ф1-м. Баланс (НП(С)БО 25)"),
    ("f2m", "Ф2-м. Звіт про фінансові результати (НП(С)БО 25)"),
]
REPORT_XMLID = {
    "f1": "l10n_ua_finrep.report_f1",
    "f2": "l10n_ua_finrep.report_f2",
    "f1m": "l10n_ua_finrep.report_f1m",
    "f2m": "l10n_ua_finrep.report_f2m",
}
# Баланс згортає взаємні розрахунки, фінрезультати - обороти доходів і витрат.
BALANCE_FORMS = ("f1", "f1m")
SETTLEMENT_PREFIXES = ("36", "37", "63", "68")
RESULT_PREFIXES = ("7", "8", "9")

TOTAL_LABEL = "Разом до елімінації"
ELIMINATION_LABEL = "Елімінація ВГО"
CONSOLIDATED_LABEL = "Консолідовано"


class UaGroupConsolidation(models.TransientModel):
    _name = "ua.group.consolidation"
    _description = "Консолідація групи компаній"

    def _default_companies(self):
        return self.env.companies

    def _default_date_from(self):
        return fields.Date.context_today(self).replace(month=1, day=1)

    def _default_date_to(self):
        return fields.Date.context_today(self)

    company_ids = fields.Many2many(
        "res.company",
        string="Компанії групи",
        required=True,
        default=_default_companies,
        help="Компанії, чиї книги зводяться. Внутрішньогруповими вважаються "
             "проводки, де контрагент - партнер однієї з цих компаній.",
    )
    form = fields.Selection(
        FORM_SELECTION,
        string="Форма",
        required=True,
        default="f1",
        help="Шаблон форми з l10n_ua_finrep, над яким будуються колонки.",
    )
    date_from = fields.Date(
        string="Період з", required=True, default=_default_date_from)
    date_to = fields.Date(
        string="Дата балансу / період по", required=True,
        default=_default_date_to,
        help="Для балансу важлива тільки ця дата: залишки рахуються на неї.")
    currency_id = fields.Many2one(
        "res.currency",
        string="Валюта звіту",
        default=lambda self: self.env.company.currency_id,
        help="Потрібна, якщо компанії групи ведуть облік у різних валютах.")

    # --- домени колонок -------------------------------------------------

    @api.model
    def _company_domain(self, company):
        return [("company_id", "=", company.id)]

    def _elimination_accounts(self):
        """Рахунки груп, що згортаються, по кожній компанії окремо.

        Код рахунку в Odoo 19 залежить від компанії (account.code.mapping),
        тому домен виду `account_id.code =like '63%'` знайшов би рахунки лише
        тієї компанії, що стоїть у контексті. Шукаємо компанія за компанією і
        кладемо в колонку готові id: звіт перезбирається чарівником, тож
        застаріти вони не встигають.
        """
        self.ensure_one()
        prefixes = (SETTLEMENT_PREFIXES if self.form in BALANCE_FORMS
                    else RESULT_PREFIXES)
        Account = self.env["account.account"]
        accounts = Account
        for company in self.company_ids:
            accounts |= Account.with_company(company).search([
                ("company_ids", "=", company.id),
                *(["|"] * (len(prefixes) - 1)),
                *[("code", "=like", prefix + "%") for prefix in prefixes],
            ])
        return accounts

    def _elimination_domain(self):
        """Проводки з контрагентом-компанією групи на рахунках, що згортаються."""
        self.ensure_one()
        partners = self.company_ids.partner_id
        if not partners:
            raise UserError(
                "У компаній групи немає партнерів - внутрішньогрупові обороти "
                "нічим не розпізнати.")
        accounts = self._elimination_accounts()
        if not accounts:
            raise UserError(
                "У плані рахунків компаній групи немає рахунків взаємних "
                "розрахунків або доходів і витрат - згортати нічого.")
        return [("partner_id", "in", partners.ids),
                ("account_id", "in", accounts.ids)]

    # --- складання звіту -------------------------------------------------

    def _period_values(self, name, sequence, domain):
        """Звичайна колонка «Actuals» з фіксованими датами і своїм доменом."""
        self.ensure_one()
        return {
            "name": name,
            "sequence": sequence,
            "source": "actuals",
            "mode": "fix",
            "manual_date_from": self.date_from,
            "manual_date_to": self.date_to,
            "analytic_domain": repr(domain),
        }

    def _sum_period_values(self, name, sequence, signed_periods):
        """Колонка «сума колонок»: [(знак, колонка), ...]."""
        return {
            "name": name,
            "sequence": sequence,
            "source": "sumcol",
            "mode": "none",
            "source_sumcol_ids": [
                (0, 0, {"period_to_sum_id": period.id, "sign": sign})
                for sign, period in signed_periods
            ],
        }

    def action_build(self):
        """Зібрати звіт і відкрити його. Повертає дію на mis.report.instance."""
        self.ensure_one()
        if len(self.company_ids) < 2:
            raise UserError(
                "Консолідація має сенс від двох компаній - оберіть щонайменше дві.")
        if self.date_from > self.date_to:
            raise UserError("Дата початку періоду пізніша за дату кінця.")
        report = self.env.ref(REPORT_XMLID[self.form])
        label = dict(FORM_SELECTION)[self.form].split(".")[0]
        instance = self.env["mis.report.instance"].create({
            "name": "Консолідація групи: %s на %s" % (
                label, fields.Date.to_string(self.date_to)),
            "report_id": report.id,
            "target_move": "posted",
            "multi_company": True,
            "company_id": False,
            "company_ids": [(6, 0, self.company_ids.ids)],
            "currency_id": self.currency_id.id or False,
            "ua_group_consolidation": True,
            "widget_show_settings_button": True,
            "display_columns_description": True,
        })
        companies = self.company_ids.sorted("id")
        company_periods = self.env["mis.report.instance.period"]
        for number, company in enumerate(companies, start=1):
            company_periods |= self.env["mis.report.instance.period"].create({
                "report_instance_id": instance.id,
                **self._period_values(
                    company.name, number * 10, self._company_domain(company)),
            })
        elimination = self.env["mis.report.instance.period"].create({
            "report_instance_id": instance.id,
            **self._period_values(
                ELIMINATION_LABEL, 900, self._elimination_domain()),
        })
        self.env["mis.report.instance.period"].create([
            {
                "report_instance_id": instance.id,
                **self._sum_period_values(
                    TOTAL_LABEL, 800,
                    [("+", period) for period in company_periods]),
            },
            {
                "report_instance_id": instance.id,
                **self._sum_period_values(
                    CONSOLIDATED_LABEL, 990,
                    [("+", period) for period in company_periods]
                    + [("-", elimination)]),
            },
        ])
        return {
            "type": "ir.actions.act_window",
            "name": instance.name,
            "res_model": "mis.report.instance",
            "res_id": instance.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "mis_builder.mis_report_instance_result_view_form").id,
            "target": "current",
            "context": dict(
                self.env.context, allowed_company_ids=self.company_ids.ids),
        }
