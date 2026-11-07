# -*- coding: utf-8 -*-
"""Цінники.

    батарейка AA: 120,00 з ПДВ у ціні                       -> «120,00», шт, EAN-13
    кава 0,5 кг: 1 000,00 без ПДВ + 20% = 1 200,00           -> «1 200,00», за 1 кг 2 400,00
    прайс-лист зі знижкою 10% на каву                        -> 1 080,00, за 1 кг 2 160,00

Запуск: чиста база, тег ua_price_label.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from ..models.price_label import ua_money


@tagged("post_install", "-at_install", "ua_price_label")
class TestUaPriceLabel(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ua")
    @AccountTestInvoicingCommon.setup_chart_template("ua_psbo")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.sudo().name = "ФОП Крамар (тест)"
        tax = dict(amount=20.0, amount_type="percent", type_tax_use="sale",
                   company_id=cls.company.id)
        cls.vat_in = cls.env["account.tax"].create(
            dict(tax, name="ПДВ 20% у ціні (тест)", price_include_override="tax_included"))
        cls.vat_out = cls.env["account.tax"].create(
            dict(tax, name="ПДВ 20% зверху (тест)", price_include_override="tax_excluded"))
        cls.battery = cls.env["product.product"].create({
            "name": "Батарейка AA (тест)", "default_code": "AA1", "list_price": 120.0,
            "barcode": "4820000000024", "taxes_id": [(6, 0, cls.vat_in.ids)]})
        cls.coffee = cls.env["product.product"].create({
            "name": "Кава мелена (тест)", "list_price": 1000.0, "barcode": "CF-500",
            "ua_label_content": 0.5, "ua_label_unit": "kg",
            "taxes_id": [(6, 0, cls.vat_out.ids)]})

    def _wizard(self, **vals):
        values = {"product_ids": [(6, 0, (self.battery | self.coffee).ids)]}
        values.update(vals)
        return self.env["ua.price.label.wizard"].create(values)

    def test_01_money_in_ukrainian(self):
        self.assertEqual(ua_money(120.0), "120,00")
        self.assertEqual(ua_money(1240.5), "1 240,50")
        self.assertEqual(ua_money(1234567.891), "1 234 567,89")

    def test_02_rows(self):
        battery, coffee = self._wizard().label_rows()
        self.assertEqual((battery["name"], battery["code"], battery["price"], battery["unit"],
                          battery["symbology"], battery["unit_price"]),
                         ("Батарейка AA (тест)", "AA1", "120,00", "шт", "EAN13", False))
        self.assertEqual(coffee["price"], "1 200,00", "ціна для покупця - з ПДВ")
        self.assertEqual(coffee["unit_price"], "Ціна за 1 кг: 2 400,00 грн")
        self.assertEqual(coffee["symbology"], "Code128")
        self.assertEqual(self.env["ua.price.label.wizard"]._symbology("4820000000025"), "Code128",
                         "EAN-13 з хибною контрольною цифрою друкується як Code 128")
        self.assertEqual(coffee["seller"], "ФОП Крамар (тест)")

    def test_03_pricelist_and_copies(self):
        pricelist = self.env["product.pricelist"].sudo().create({
            "name": "Знижка на каву (тест)",
            "item_ids": [(0, 0, {"applied_on": "0_product_variant", "product_id": self.coffee.id,
                                 "compute_price": "percentage", "percent_price": 10.0})]})
        rows = self._wizard(pricelist_id=pricelist.id, copies=3).label_rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["name"] for r in rows].count("Кава мелена (тест)"), 3)
        coffee = rows[-1]
        self.assertEqual(coffee["price"], "1 080,00")
        self.assertEqual(coffee["unit_price"], "Ціна за 1 кг: 2 160,00 грн")
        with self.assertRaises(UserError):
            self._wizard(copies=0).label_rows()

    def test_04_opens_from_product_list(self):
        wizard = self.env["ua.price.label.wizard"].with_context(
            active_model="product.template", active_ids=self.coffee.product_tmpl_id.ids).create({})
        self.assertEqual(wizard.product_ids, self.coffee)
        action = wizard.action_print()
        self.assertEqual(action["report_name"], "l10n_ua_price_label.report_ua_price_label")
        wizard.layout = "roll"
        self.assertEqual(wizard.action_print()["report_name"],
                         "l10n_ua_price_label.report_ua_price_label_roll")

    def test_05_print(self):
        wizard = self._wizard(copies=11)  # 22 цінники - два аркуші
        for report in ("l10n_ua_price_label.report_ua_price_label",
                       "l10n_ua_price_label.report_ua_price_label_roll"):
            html, _kind = self.env["ir.actions.report"]._render_qweb_html(report, wizard.ids)
            text = html.decode() if isinstance(html, bytes) else html
            for expected in ("Батарейка AA (тест)", "120,00", "1 200,00",
                             "Ціна за 1 кг: 2 400,00 грн", "ФОП Крамар (тест)"):
                self.assertIn(expected, text)
        self.assertEqual(text.count("ua-label\""), 22)
