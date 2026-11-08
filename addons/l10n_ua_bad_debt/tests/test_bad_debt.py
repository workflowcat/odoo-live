# -*- coding: utf-8 -*-
"""Резерв сумнівних боргів на 31.12.2025 і 31.03.2026.

Групи: не прострочена 0 %, 1-90 днів 10 %, 91-180 - 30 %, 181-365 - 60 %, понад рік 100 %.
- Альфа 10 000, строк 20.12.2025: 11 днів, 10 % = 1 000.
- Бета 20 000, строк 01.08.2025, оплата 5 000 10.11.2025: 15 000, 152 дні, 30 % = 4 500.
- Гамма 5 000, строк 01.11.2024, оплачено 10.01.2026 - після дати, тож на 31.12 борг 5 000, 100 %.
- Дельта 3 000, строк 30.12.2025: банкрут, оцінено окремо - 3 000.
- Рахунок від 05.01.2026 у розрахунок на 31.12 не входить.
Разом 13 500: Дт 944 Кт 38. На 31.03.2026 Альфа і Гамма оплачені, Бета 242 дні - 60 % = 9 000,
Дельта 91 день - 30 % = 900, новий рахунок Альфи 7 000 від 05.01 - 85 днів, 10 % = 700;
разом 10 600, надлишок 2 900: Дт 38 Кт 719.

Запуск: тег ua_bad_debt.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_bad_debt")
class TestUaBadDebt(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.receivable = cls.env["account.account"].create({
            "code": "36199", "name": "Розрахунки з покупцями (тест)", "account_type": "asset_receivable",
            "reconcile": True})
        Partner = cls.env["res.partner"]
        cls.partners = {}
        for key in ("Альфа", "Бета", "Гамма", "Дельта"):
            partner = Partner.create({"name": "ТОВ %s (тест)" % key, "is_company": True})
            partner.property_account_receivable_id = cls.receivable
            cls.partners[key] = partner
        cls.inv = {
            "Альфа": cls._invoice("Альфа", 10000, date(2025, 12, 20)),
            "Бета": cls._invoice("Бета", 20000, date(2025, 8, 1)),
            "Гамма": cls._invoice("Гамма", 5000, date(2024, 11, 1)),
            "Дельта": cls._invoice("Дельта", 3000, date(2025, 12, 30)),
        }
        cls._invoice("Альфа", 7000, date(2026, 1, 5))
        cls._pay(cls.inv["Бета"], 5000, date(2025, 11, 10))
        cls._pay(cls.inv["Гамма"], 5000, date(2026, 1, 10))
        cls.Reserve = cls.env["ua.bad.debt.reserve"]

    @classmethod
    def _invoice(cls, key, amount, day):
        move = cls.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": cls.partners[key].id, "invoice_date": day,
            "invoice_date_due": day, "invoice_line_ids": [
                (0, 0, {"name": "Послуги (тест)", "quantity": 1, "price_unit": amount, "tax_ids": [(6, 0, [])]})]})
        move.action_post()
        return move

    @classmethod
    def _pay(cls, invoice, amount, day):
        cls.env["account.payment.register"].with_context(active_model="account.move", active_ids=invoice.ids).create(
            {"payment_date": day, "amount": amount}).action_create_payments()

    def _reserve(self, day, **pct):
        values = {"date": day, "receivable_account_ids": [(6, 0, self.receivable.ids)], "pct_current": 0,
                  "pct_d90": 10, "pct_d180": 30, "pct_d365": 60, "pct_over": 100}
        values.update(pct)
        record = self.Reserve.create(values)
        record.action_fill()
        return record

    def test_01_year_end_and_quarter(self):
        year_end = self._reserve(date(2025, 12, 31))
        lines = {line.partner_id.name: line for line in year_end.line_ids}
        self.assertEqual(sorted(lines), sorted(p.name for p in self.partners.values()))
        alpha, beta, gamma, delta = (lines["ТОВ %s (тест)" % k] for k in ("Альфа", "Бета", "Гамма", "Дельта"))
        self.assertEqual((alpha.days, alpha.bucket, alpha.reserve), (11, "d90", 1000.0))
        self.assertEqual((beta.residual, beta.days, beta.bucket, beta.reserve), (15000.0, 152, "d180", 4500.0))
        self.assertEqual((gamma.residual, gamma.bucket, gamma.reserve), (5000.0, "over", 5000.0))
        self.assertEqual(delta.reserve, 300.0)
        delta.write({"manual": True, "manual_reserve": 3000})
        with self.assertRaises(UserError, msg="без підстави"):
            year_end.action_post()
        delta.manual_reason = "Справа про банкрутство (тест)"
        year_end.action_fill()
        delta = year_end.line_ids.filtered(lambda l: l.partner_id == self.partners["Дельта"])
        self.assertTrue(delta.manual, "ручна оцінка лишається після перезаповнення")
        self.assertEqual(year_end.debt_total, 33000.0)
        self.assertEqual(year_end.reserve_total, 13500.0)

        year_end.action_post()
        self.assertEqual(year_end.adjustment, 13500.0 - year_end.reserve_before)
        move = year_end.move_id
        self.assertEqual(move.date, date(2025, 12, 31))
        debit = move.line_ids.filtered("debit")
        self.assertTrue(debit.account_id.code.startswith("94"))
        self.assertTrue(move.line_ids.filtered("credit").account_id.code.startswith("38"))
        self.assertEqual(debit.debit, year_end.adjustment)

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_bad_debt.report_ua_bad_debt", year_end.ids)[0].decode()
        for text in ("РОЗРАХУНОК РЕЗЕРВУ СУМНІВНИХ БОРГІВ", "31.12.2025", "91-180 днів", "4500.00",
                     "Оцінені окремо", "Справа про банкрутство (тест)", "13500.00"):
            self.assertIn(text, html)

        self._pay(self.inv["Альфа"], 10000, date(2026, 2, 1))
        quarter = self.Reserve.create({"date": date(2026, 3, 31), "receivable_account_ids": [(6, 0, self.receivable.ids)]})
        self.assertEqual((quarter.pct_d90, quarter.pct_d365), (10.0, 60.0), "відсотки з попереднього розрахунку")
        quarter.action_fill()
        self.assertEqual(sorted(quarter.line_ids.mapped("reserve")), [700.0, 900.0, 9000.0])
        self.assertEqual(quarter.reserve_total, 10600.0)
        quarter.action_post()
        self.assertEqual(quarter.adjustment, 10600.0 - quarter.reserve_before)
        self.assertEqual(quarter.reserve_before - year_end.reserve_before, 13500.0)
        self.assertTrue(quarter.move_id.line_ids.filtered("debit").account_id.code.startswith("38"))
        self.assertTrue(quarter.move_id.line_ids.filtered("credit").account_id.code.startswith("71"))

        with self.assertRaises(UserError):
            quarter.unlink()
        quarter.action_draft()
        self.assertFalse(quarter.move_id)
        self.assertEqual(quarter.state, "draft")
