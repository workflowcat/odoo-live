# -*- coding: utf-8 -*-
"""Встановлення цін на вигаданих товарах.

Роздріб: націнка 30 %, до гривні; опт: 15 %, до 10 копійок.
Кавоварка: собівартість 77,30, ціна в картці 90 -> роздріб 100,49 -> 100; опт 88,895 -> 88,90.
Фільтр: 40 і 50 -> роздріб 52, опт 46.
- До 10.01.2026 діє ціна з картки, з 10.01 - нова; 01.02 роздріб кавоварки 105.
- Документ з ранішою датою не перекриває пізнішу ціну; скасування повертає попередню.

Запуск: тег ua_price_set.
"""
from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_price_set.models.price_set import ua_round_price


@tagged("post_install", "-at_install", "ua_price_set")
class TestUaPriceSet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Pricelist = cls.env["product.pricelist"]
        cls.retail = Pricelist.create({"name": "Роздріб (тест)", "ua_price_kind": "retail", "ua_markup": 30,
                                       "ua_rounding": "1"})
        cls.wholesale = Pricelist.create({"name": "Опт (тест)", "ua_price_kind": "wholesale", "ua_markup": 15,
                                          "ua_rounding": "0.1"})
        cls.categ = cls.env["product.category"].create({"name": "Кавові товари (тест)"})
        Product = cls.env["product.product"]
        cls.maker = Product.create({"name": "Кавоварка (тест)", "default_code": "K-1", "categ_id": cls.categ.id,
                                    "standard_price": 77.30, "list_price": 90, "sale_ok": True})
        cls.filter = Product.create({"name": "Фільтр (тест)", "default_code": "K-2", "categ_id": cls.categ.id,
                                     "standard_price": 40, "list_price": 50, "sale_ok": True})
        cls.Order = cls.env["ua.price.order"]

    def _price(self, pricelist, product, day):
        return pricelist._get_product_price(product, 1.0, date=datetime.combine(day, datetime.min.time()))

    def _order(self, day, pricelists, prices=None):
        order = self.Order.create({"date": day, "pricelist_ids": [(6, 0, pricelists.ids)], "categ_id": self.categ.id})
        order.action_fill_category()
        if prices is None:
            order.action_compute()
        else:
            for line in order.line_ids:
                line.new_price = prices.get((line.pricelist_id, line.product_id), 0.0)
        return order

    def test_00_rounding(self):
        self.assertEqual(ua_round_price(100.49, "1"), 100.0)
        self.assertEqual(ua_round_price(100.5, "1"), 101.0)
        self.assertEqual(ua_round_price(88.895, "0.1"), 88.9)
        self.assertEqual(ua_round_price(100.49, "99"), 100.99)
        self.assertEqual(ua_round_price(101.0, "99"), 101.99)
        self.assertEqual(ua_round_price(12.3, "5"), 10.0)
        self.assertEqual(ua_round_price(12.345, False), 12.35)

    def test_01_set_prices_and_history(self):
        january = self._order(date(2026, 1, 10), self.retail | self.wholesale)
        self.assertTrue(january.name.startswith("ВЦ/"))
        lines = {(line.pricelist_id, line.product_id): line for line in january.line_ids}
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[(self.retail, self.maker)].old_price, 90.0)
        self.assertEqual(lines[(self.retail, self.maker)].cost, 77.30)
        self.assertEqual({key: line.new_price for key, line in lines.items()}, {
            (self.retail, self.maker): 100.0, (self.retail, self.filter): 52.0,
            (self.wholesale, self.maker): 88.9, (self.wholesale, self.filter): 46.0})
        self.assertAlmostEqual(lines[(self.retail, self.maker)].change, 11.11, places=2)
        january.action_done()
        self.assertEqual(january.state, "done")
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 1, 9)), 90.0)
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 1, 10)), 100.0)
        self.assertEqual(self._price(self.wholesale, self.filter, date(2026, 3, 1)), 46.0)

        february = self._order(date(2026, 2, 1), self.retail, {(self.retail, self.maker): 105.0})
        self.assertEqual({l.product_id: l.old_price for l in february.line_ids}, {self.maker: 100.0, self.filter: 52.0})
        february.action_done()
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 1, 31)), 100.0)
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 2, 5)), 105.0)
        self.assertEqual(self._price(self.retail, self.filter, date(2026, 2, 5)), 52.0, "без нової ціни не чіпаємо")

        early = self._order(date(2026, 1, 20), self.retail, {(self.retail, self.maker): 99.0})
        with self.assertRaises(UserError, msg="пізніша ціна вже є"):
            early.action_done()
        with self.assertRaises(UserError, msg="новіший документ не скасовано"):
            january.action_cancel()

        february.action_cancel()
        self.assertEqual(february.state, "cancel")
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 2, 5)), 100.0)
        early.action_done()
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 1, 25)), 99.0)
        self.assertEqual(self._price(self.retail, self.maker, date(2026, 1, 15)), 100.0)
        with self.assertRaises(UserError):
            early.unlink()
        february.action_draft()
        self.assertEqual(february.state, "draft")

        html = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_ua_price_set.report_ua_price_order", january.ids)[0].decode()
        for text in ("НАКАЗ ПРО ВСТАНОВЛЕННЯ ЦІН", "10.01.2026", "Роздріб (тест)", "Кавоварка (тест)", "100.00", "88.90"):
            self.assertIn(text, html)
        labels = january.action_labels()
        self.assertEqual(labels["res_model"], "ua.price.label.wizard")
        self.assertEqual(labels["context"]["default_pricelist_id"], self.retail.id)

    def test_02_fill_from_pricelist_and_rights(self):
        order = self._order(date(2026, 1, 10), self.retail)
        order.action_done()
        again = self.Order.create({"date": date(2026, 3, 1), "pricelist_ids": [(6, 0, self.retail.ids)]})
        again.action_fill_pricelist()
        self.assertEqual(set(again.line_ids.product_id.ids), {self.maker.id, self.filter.id})
        self.assertEqual(sorted(again.line_ids.mapped("old_price")), [52.0, 100.0])
        with self.assertRaises(UserError, msg="немає нових цін"):
            again.action_done()
        empty = self.Order.create({"date": date(2026, 3, 1), "pricelist_ids": [(6, 0, self.retail.ids)]})
        with self.assertRaises(UserError):
            empty.action_fill_category()
