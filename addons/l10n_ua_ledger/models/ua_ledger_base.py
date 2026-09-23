"""Спільна основа трьох регістрів: період, компанія, вибірки з головної книги.

Регістри - записи: складений регістр лишається в базі зі своїми рядками, щоб
«ОСВ за серпень» можна було відкрити пізніше такою самою сторінкою, а не складати
наново. Рахують лише з account.move.line проведених документів обраної компанії.
Назви рахунків беруться з плану, тому українські назви дає план (модуль
l10n_ua_chart), а не цей модуль. Короткі коди (92, 661) теж дає план.

Шлях той самий в усіх трьох: пункт меню відкриває список складених регістрів,
кнопка «Сформувати» в шапці списку питає параметри діалогом, `action_compose()`
рахує і відкриває результат сторінкою.
"""
from odoo import fields, models

# Класи плану рахунків ПСБО за першою цифрою коду.
CLASS_NAMES = {
    "0": "Клас 0. Позабалансові рахунки",
    "1": "Клас 1. Необоротні активи",
    "2": "Клас 2. Запаси",
    "3": "Клас 3. Кошти, розрахунки та інші активи",
    "4": "Клас 4. Власний капітал і забезпечення",
    "5": "Клас 5. Довгострокові зобов'язання",
    "6": "Клас 6. Поточні зобов'язання",
    "7": "Клас 7. Доходи",
    "8": "Клас 8. Витрати за елементами",
    "9": "Клас 9. Витрати діяльності",
}


class UaLedgerBase(models.AbstractModel):
    _name = "ua.ledger.base"
    _description = "Регістри головної книги: спільна основа"

    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    date_from = fields.Date("Період з", required=True, default=lambda self: self._default_date_from())
    date_to = fields.Date("Період по", required=True, default=fields.Date.context_today)

    # Подання: сторінка результату (action_compose) і діалог параметрів (action_ask).
    # Ставить кожен регістр своїми xmlid.
    _ua_result_view = None
    _ua_ask_view = None

    def _default_date_from(self):
        return fields.Date.context_today(self).replace(day=1)

    def _ua_period_label(self):
        self.ensure_one()
        d1 = self.date_from.strftime("%d.%m.%Y") if self.date_from else ""
        d2 = self.date_to.strftime("%d.%m.%Y") if self.date_to else ""
        return "%s - %s" % (d1, d2)

    def action_compose(self):
        """Кнопка «Скласти» в діалозі параметрів: порахувати і відкрити результат сторінкою."""
        self.ensure_one()
        self.action_compute()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref(self._ua_result_view).id, "form")],
            "target": "current",
        }

    def action_ask(self):
        """Кнопка «Сформувати» в шапці списку: діалог параметрів нового регістра."""
        return {
            "type": "ir.actions.act_window",
            "name": self._description,
            "res_model": self._name,
            "view_mode": "form",
            "views": [(self.env.ref(self._ua_ask_view).id, "form")],
            "target": "new",
        }

    def _aml_domain(self, extra=None):
        """Проведені рядки обраної компанії."""
        self.ensure_one()
        return [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
        ] + (extra or [])

    def _acc_code(self, account):
        """Код рахунку в контексті компанії: коди залежать від компанії."""
        self.ensure_one()
        return account.with_company(self.company_id).code or ""

    def _class_name(self, code):
        return CLASS_NAMES.get((code or "")[:1], "Клас %s" % (code or "")[:1])

    def _opening_balance(self, extra):
        """Сальдо до початку періоду за заданим доповненням домену."""
        self.ensure_one()
        opening = 0.0
        for _account, debit, credit in self.env["account.move.line"]._read_group(
            self._aml_domain(extra + [("date", "<", self.date_from)]),
            groupby=["account_id"],
            aggregates=["debit:sum", "credit:sum"],
        ):
            opening += (debit or 0.0) - (credit or 0.0)
        return round(opening, 2)
