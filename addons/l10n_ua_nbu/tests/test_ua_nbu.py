# -*- coding: utf-8 -*-
"""Курси НБУ: перевертання курсу, кратність, дірки в датах, діапазон.

Мережі в тестах немає: підміняємо _nbu_fetch, який єдиний ходить у
bank.gov.ua. Усі очікувані числа пораховані руками, арифметика в коментарі
поруч. Живу перевірку API робимо окремо, поза набором тестів.
"""
import datetime
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

PATH = (
    "odoo.addons.l10n_ua_nbu.models.res_currency_rate_provider_nbu"
    ".ResCurrencyRateProviderNBU._nbu_fetch"
)


def row(date, cc, rate, units=1, rate_per_unit=None):
    """Рядок у тому вигляді, в якому його віддає exchange_site."""
    return {
        "exchangedate": date,
        "cc": cc,
        "rate": rate,
        "units": units,
        "rate_per_unit": rate_per_unit if rate_per_unit is not None else rate / units,
    }


@tagged("post_install", "-at_install", "ua_nbu")
class TestUaNbu(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref("base.UAH")
        cls.usd = cls.env.ref("base.USD")
        cls.eur = cls.env.ref("base.EUR")
        cls.jpy = cls.env.ref("base.JPY")
        (cls.uah + cls.usd + cls.eur + cls.jpy).write({"active": True})
        cls.company = cls.env["res.company"].create({
            "name": "ТОВ Гривня",
            "currency_id": cls.uah.id,
        })
        cls.provider = cls.env["res.currency.rate.provider"].create({
            "service": "NBU",
            "company_id": cls.company.id,
            "currency_ids": [(6, 0, (cls.usd + cls.eur).ids)],
            "interval_type": "days",
            "interval_number": 1,
        })

    # --- 1. Курс перевертається: НБУ дає грн за долар, Odoo тримає долари за гривню.
    def test_01_rate_is_inverted(self):
        fetched = {"USD": [row("15.09.2026", "USD", 44.618)]}
        with patch(PATH, lambda self, cur, d1, d2: fetched.get(cur, [])):
            content = self.provider._obtain_rates(
                "UAH", ["USD"], datetime.date(2026, 9, 15), datetime.date(2026, 9, 15)
            )
        # 1 / 44.618 = 0.02241247...
        self.assertAlmostEqual(content["2026-09-15"]["USD"], 1 / 44.618, places=10)

    # --- 2. Кратність: єну НБУ котирує за 10 одиниць.
    def test_02_units(self):
        # rate 2.877 за 10 єн -> 0.2877 грн за єну -> курс Odoo 1/0.2877 = 3.47584...
        fetched = {"JPY": [row("17.09.2026", "JPY", 2.877, units=10)]}
        with patch(PATH, lambda self, cur, d1, d2: fetched.get(cur, [])):
            content = self.provider._obtain_rates(
                "UAH", ["JPY"], datetime.date(2026, 9, 17), datetime.date(2026, 9, 17)
            )
        self.assertAlmostEqual(content["2026-09-17"]["JPY"], 1 / 0.2877, places=10)

    # --- 3. Дірка в датах: за 16.09 рядка немає, курс за цей день не зʼявляється.
    def test_03_missing_day(self):
        fetched = {"USD": [
            row("15.09.2026", "USD", 44.618),
            row("17.09.2026", "USD", 44.6021),
        ]}
        with patch(PATH, lambda self, cur, d1, d2: fetched.get(cur, [])):
            content = self.provider._obtain_rates(
                "UAH", ["USD"], datetime.date(2026, 9, 15), datetime.date(2026, 9, 17)
            )
        self.assertEqual(sorted(content), ["2026-09-15", "2026-09-17"])

    # --- 4. Валюта, якої НБУ не котирує, не ламає відповідь.
    def test_04_unsupported_currency(self):
        calls = []

        def fake(self, currency, date_from, date_to):
            calls.append(currency)
            return [row("15.09.2026", "USD", 44.618)] if currency == "USD" else []

        with patch(PATH, fake):
            content = self.provider._obtain_rates(
                "UAH",
                ["USD", "XYZ"],
                datetime.date(2026, 9, 15),
                datetime.date(2026, 9, 15),
            )
        self.assertEqual(calls, ["USD"])  # по XYZ у НБУ навіть не ходимо
        self.assertEqual(list(content["2026-09-15"]), ["USD"])
        self.assertNotIn("XYZ", self.provider._get_supported_currencies())
        self.assertIn("USD", self.provider._get_supported_currencies())

    # --- 5. Діапазон дат передається в API у форматі YYYYMMDD.
    def test_05_date_range_passed(self):
        seen = {}

        def fake(self, currency, date_from, date_to):
            seen[currency] = (date_from, date_to)
            return [row("15.09.2026", "USD", 44.618)]

        with patch(PATH, fake):
            content = self.provider._obtain_rates(
                "UAH", ["USD"], datetime.date(2026, 9, 15), datetime.date(2026, 9, 19)
            )
        self.assertEqual(
            seen["USD"], (datetime.date(2026, 9, 15), datetime.date(2026, 9, 19))
        )
        self.assertEqual(list(content), ["2026-09-15"])

    # --- 6. Провайдер зʼявляється для гривневої компанії і не зʼявляється для іншої.
    def test_06_provider_for_uah_company(self):
        from odoo.addons.l10n_ua_nbu.hooks import create_nbu_providers

        uah_company = self.env["res.company"].create({
            "name": "ТОВ Друга гривня",
            "currency_id": self.uah.id,
        })
        usd_company = self.env["res.company"].create({
            "name": "LLC Dollar",
            "currency_id": self.usd.id,
        })
        created = create_nbu_providers(self.env, uah_company + usd_company)
        self.assertEqual(created.company_id, uah_company)
        self.assertTrue(created.daily)  # щодня
        self.assertEqual(
            sorted(created.currency_ids.mapped("name")), ["EUR", "GBP", "PLN", "USD"]
        )
        # повторний виклик нічого не дублює
        self.assertFalse(create_nbu_providers(self.env, uah_company))

    # --- 7. Повний прохід _update: курс лягає в res.currency.rate.
    def test_07_update_writes_rate(self):
        fetched = {"USD": [row("15.09.2026", "USD", 44.618)]}
        with patch(PATH, lambda self, cur, d1, d2: fetched.get(cur, [])):
            self.provider._update(
                datetime.date(2026, 9, 15), datetime.date(2026, 9, 15)
            )
        rate = self.env["res.currency.rate"].search([
            ("company_id", "=", self.company.id),
            ("currency_id", "=", self.usd.id),
            ("name", "=", "2026-09-15"),
        ])
        self.assertEqual(len(rate), 1)
        # 1 / 44.618 = 0.0224125 (округлення поля rate - 6 знаків і далі)
        self.assertAlmostEqual(rate.rate, 1 / 44.618, places=8)

    # --- 8. Валюта компанії не гривня: курс рахується через гривню.
    def test_08_non_uah_base(self):
        fetched = {
            "USD": [row("15.09.2026", "USD", 44.618)],
            "EUR": [row("15.09.2026", "EUR", 52.5)],
        }
        with patch(PATH, lambda self, cur, d1, d2: fetched.get(cur, [])):
            content = self.provider._obtain_rates(
                "EUR",
                ["USD"],
                datetime.date(2026, 9, 15),
                datetime.date(2026, 9, 15),
            )
        # доларів за євро = 52.5 / 44.618 = 1.176654...
        self.assertAlmostEqual(content["2026-09-15"]["USD"], 52.5 / 44.618, places=10)
        self.assertNotIn("EUR", content["2026-09-15"])
