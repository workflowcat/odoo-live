"""ДК 021: повнота, ієрархія, пошук за кодом, код на рядку закупівлі."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "ua_dk021")
class TestDk021(TransactionCase):

    def test_01_full_classifier_loaded(self):
        Dk = self.env["ua.dk021"]
        self.assertEqual(Dk.search_count([]), 9458)
        self.assertEqual(Dk.search_count([("level", "=", 1)]), 45)

    def test_02_hierarchy(self):
        """03111000-2 (насіння) - клас 0311 - група 031 - розділ 03."""
        code = self.env["ua.dk021"].search([("code", "=", "03111000-2")])
        self.assertTrue(code)
        self.assertEqual(code.parent_id.code, "03110000-5")
        self.assertEqual(code.parent_id.parent_id.code, "03100000-2")
        self.assertEqual(code._ua_division().code, "03000000-1")
        self.assertEqual(code._ua_division().level, 1)
        self.assertFalse(code.is_service)
        self.assertTrue(self.env["ua.dk021"].search(
            [("code", "=", "72260000-5")]).is_service)

    def test_03_search_by_code_prefix(self):
        found = self.env["ua.dk021"].name_search("0311", limit=100)
        codes = [name.split(" ")[0] for _id, name in found]
        self.assertTrue(codes)
        self.assertTrue(all(c.startswith("0311") for c in codes))
        by_name = self.env["ua.dk021"].name_search("Насіння")
        self.assertTrue(by_name)

    def test_04_reload_is_idempotent(self):
        Dk = self.env["ua.dk021"]
        sample = Dk.search([("code", "=", "03111000-2")])
        parent = sample.parent_id
        sample.write({"name": "змінено вручну", "parent_id": False})
        Dk._ua_load()
        self.assertEqual(Dk.search_count([]), 9458)
        self.assertEqual(sample.parent_id, parent)
        self.assertNotEqual(sample.name, "змінено вручну")

    def test_05_code_flows_to_purchase_line(self):
        code = self.env["ua.dk021"].search([("code", "=", "30192000-1")])
        self.assertTrue(code)
        product = self.env["product.product"].create({
            "name": "Папір офісний", "ua_dk021_id": code.id})
        vendor = self.env["res.partner"].create({"name": "Постачальник канцтоварів"})
        order = self.env["purchase.order"].create({
            "partner_id": vendor.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_qty": 5,
                                   "price_unit": 120.0})],
        })
        self.assertEqual(order.order_line.ua_dk021_id, code)
