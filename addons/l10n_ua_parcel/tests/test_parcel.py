"""Відправлення без мережі: відповіді перевізників підставляємо замість запиту.

Відповіді зібрано за полями справжніх API: Нова пошта - getStatusDocuments (StatusCode,
Status, TrackingUpdateDate, DateFirstDayStorage, RedeliverySum), Укрпошта - список подій
(barcode, event, eventName, date, eventReason_id).
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

NP = "20450123456789"
UP = "0500100031143"
S10 = "LP123456789CN"


def np_row(code, text, when, **extra):
    row = {"Number": NP, "StatusCode": str(code), "Status": text, "TrackingUpdateDate": when,
           "CityRecipient": "Київ", "WarehouseRecipient": "Відділення №12", "CitySender": "Львів",
           "WarehouseSender": "Відділення №3", "DocumentCost": "95", "DocumentWeight": "2.5",
           "SeatsAmount": "1", "ScheduledDeliveryDate": "", "DateFirstDayStorage": "",
           "RedeliverySum": "", "RecipientDateTime": ""}
    row.update(extra)
    return {"success": True, "data": [row], "errors": []}


@tagged("post_install", "-at_install", "ua_parcel")
class TestUaParcel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.np = cls.env.ref("l10n_ua_parcel.carrier_novaposhta")
        cls.up = cls.env.ref("l10n_ua_parcel.carrier_ukrposhta")
        cls.supplier = cls.env["res.partner"].create({"name": "ТОВ «Приклад Мотори»", "is_company": True})
        product = cls.env["product.product"].create({"name": "Мотор 2807", "type": "consu",
                                                      "is_storable": True})
        cls.po = cls.env["purchase.order"].create({
            "partner_id": cls.supplier.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_qty": 40, "price_unit": 900})]})
        cls.po.button_confirm()
        cls.today = fields.Date.context_today(cls.env["ua.parcel"])
        cls.Carrier = cls.env.registry["ua.parcel.carrier"]

    def _add(self, text, **vals):
        wizard = self.env["ua.parcel.add"].with_context(
            **{"default_%s" % k: v for k, v in vals.items()}).create({"text": text})
        with patch.object(self.Carrier, "_ua_fetch", return_value={}):
            action = wizard.action_add()
        return self.env["ua.parcel"].search(action.get("domain") or [("id", "=", action.get("res_id"))])

    def test_01_paste_numbers(self):
        text = ("Добрий день, відправили двома посилками: ТТН 20 4501 2345 6789 і %s. "
                "Дзвоніть 0671234567, рахунок від 08.11.2026." % UP)
        wizard = self.env["ua.parcel.add"].create({"text": text})
        self.assertEqual(wizard.preview.count("\n"), 1)
        parcels = self._add(text, purchase_id=self.po.id)
        self.assertEqual(sorted(parcels.mapped("name")), sorted([NP, UP]))
        self.assertEqual(parcels.filtered(lambda p: p.name == NP).carrier_id, self.np)
        self.assertEqual(parcels.filtered(lambda p: p.name == UP).carrier_id, self.up)
        self.assertEqual(set(parcels.mapped("partner_id")), {self.supplier})
        self.assertEqual(set(parcels.mapped("direction")), {"in"})
        self.assertEqual(self.po.ua_parcel_count, 2)
        # Той самий номер ще раз - уже з приходу: дубля немає, документ дописано.
        picking = self.po.picking_ids[:1]
        again = self._add(NP, picking_id=picking.id)
        self.assertEqual(len(again), 1)
        self.assertEqual(again.picking_id, picking)
        self.assertEqual(self.env["ua.parcel"].search_count([("name", "=", NP)]), 1)
        self.assertEqual(picking.ua_parcel_count, 2)
        with self.assertRaises(Exception):
            self._add("ABC12345678")

    def test_02_nova_poshta_pickup_then_delivered(self):
        parcel = self._add(NP, purchase_id=self.po.id)
        storage = self.today + timedelta(days=4)
        arrived = np_row(7, "Прибув у відділення", "2026-11-07 14:20:11",
                         DateFirstDayStorage=storage.strftime("%Y-%m-%d"), RedeliverySum="1500")
        with patch.object(self.Carrier, "_ua_post", return_value=arrived) as post:
            parcel.action_ua_track()
            payload = post.call_args[0][1]
            self.assertEqual(payload["methodProperties"]["Documents"][0]["DocumentNumber"], NP)
            parcel.action_ua_track()
        self.assertEqual(parcel.state, "at_pickup")
        self.assertEqual(len(parcel.event_ids), 1, "той самий стан двічі - одна подія")
        self.assertEqual(parcel.event_ids.date, datetime(2026, 11, 7, 12, 20, 11), "київський час у UTC")
        self.assertEqual(parcel.storage_from, storage)
        self.assertEqual((parcel.cod_amount, parcel.cost, parcel.seats), (1500.0, 95.0, 1))
        self.assertEqual(parcel.to_place, "Київ, Відділення №12")
        self.assertTrue(parcel.attention)
        self.assertIn("Чекає у відділенні", parcel.attention_reason)
        activity = parcel.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.date_deadline, storage - timedelta(days=1))
        self.assertIn(NP, activity.summary)

        delivered = np_row(9, "Відправлення отримано", "2026-11-08 10:05:00",
                           RecipientDateTime="08.11.2026 10:05:00")
        with patch.object(self.Carrier, "_ua_post", return_value=delivered):
            parcel.action_ua_track()
        self.assertEqual((parcel.state, parcel.done, parcel.attention), ("delivered", True, False))
        self.assertEqual(len(parcel.event_ids), 2)
        self.assertEqual(parcel.delivered_date, datetime(2026, 11, 8, 8, 5))
        self.assertFalse(parcel.activity_ids)
        self.assertIn(NP, self.po.message_ids[0].body)

    def test_03_ukrposhta_history_customs_and_return(self):
        parcels = self._add("%s %s" % (UP, S10))
        with patch.object(self.Carrier, "_ua_post") as post:
            parcels.action_ua_track()
            post.assert_not_called()
        self.assertTrue(all(parcels.mapped("attention")))
        self.assertIn("токен", parcels[0].check_error)

        self.up.sudo().api_key = "test-token"
        rows = [
            {"barcode": UP, "step": 1, "date": "2026-11-01T10:00:00", "index": "79000", "name": "Львів 1",
             "event": 10100, "eventName": "Прийнято у відділенні", "eventReason_id": 1},
            {"barcode": UP, "step": 2, "date": "2026-11-03T09:00:00", "index": "01001", "name": "Київ 1",
             "event": 21700, "eventName": "Надійшло у відділення доставки", "eventReason_id": 1},
            {"barcode": UP, "step": 3, "date": "2026-11-06T16:30:00", "index": "79000", "name": "Львів 1",
             "event": 41000, "eventName": "Вручено", "eventReason": "відправнику", "eventReason_id": 10},
            {"barcode": S10, "step": 1, "date": "2026-11-04T08:00:00", "index": "01001", "name": "Київ ММПО",
             "event": 80800, "eventName": "Перебуває на митниці", "country": "UA", "eventReason_id": 1},
        ]
        with patch.object(self.Carrier, "_ua_post", return_value=rows) as post:
            parcels.action_ua_track()
            self.assertEqual(post.call_args[0][2], {"Authorization": "Bearer test-token"})
            parcels.action_ua_track()
        back = parcels.filtered(lambda p: p.name == UP)
        self.assertEqual((back.state, len(back.event_ids)), ("returned", 3))
        self.assertTrue(back.done)
        self.assertEqual(back.event_ids[0].text, "Вручено (відправнику)")
        customs = parcels.filtered(lambda p: p.name == S10)
        self.assertEqual(customs.state, "customs")
        self.assertEqual(customs.attention_reason, "На митниці")
        self.assertEqual(len(customs.activity_ids), 1)

    def test_04_attention_and_schedule(self):
        parcel = self._add(NP)
        now = fields.Datetime.now()
        parcel.write({"state": "in_transit", "last_event_date": now - timedelta(days=6)})
        self.assertIn("Без руху 6", parcel.attention_reason)
        parcel.write({"expected_date": self.today - timedelta(days=1)})
        self.assertIn("Запізнюється", parcel.attention_reason)
        parcel.action_ua_close()
        self.assertFalse(parcel.attention)

        fresh, stale = self._add(UP), self._add(S10)
        fresh.write({"last_check": now - timedelta(hours=1)})
        stale.write({"last_check": now - timedelta(hours=5)})
        calls = []

        def fake(carrier, parcels):
            calls.append(parcels.mapped("name"))
            return {}
        with patch.object(self.Carrier, "_ua_fetch", fake):
            self.env["ua.parcel"]._cron_ua_track()
        self.assertEqual(calls, [[S10]], "перевіряємо лише тих, кому настав час, і не закриті")

    def test_05_demo_connector(self):
        demo = self.env["ua.parcel.carrier"].create({
            "name": "Демо", "code": "demo", "connector": "demo", "number_pattern": r"DEMO\d{8}"})
        parcels = self._add("DEMO00000001 DEMO00000007")
        self.assertEqual(set(parcels.mapped("carrier_id")), {demo})
        old = fields.Datetime.now() - timedelta(days=10)
        self.env.cr.execute("UPDATE ua_parcel SET create_date = %s WHERE id IN %s", (old, tuple(parcels.ids)))
        parcels.invalidate_recordset(["create_date"])
        parcels.action_ua_track()
        parcels.action_ua_track()
        ok = parcels.filtered(lambda p: p.name.endswith("1"))
        back = parcels - ok
        self.assertEqual((ok.state, len(ok.event_ids)), ("delivered", 5))
        self.assertEqual((back.state, len(back.event_ids)), ("returned", 6))

    def test_06_summary(self):
        a, b = self._add(NP), self._add(UP)
        a.write({"state": "at_pickup"})
        b.write({"state": "in_transit", "direction": "out", "cod_amount": 1200})
        summary = self.env["ua.parcel"]._ua_summary([("id", "in", (a | b).ids)])
        self.assertEqual(summary["open"], 2)
        self.assertEqual(summary["attention"], 1)
        self.assertEqual(summary["cod_in_transit"], 1200)
        self.assertEqual({row["state"]: row["count"] for row in summary["by_state"]},
                         {"at_pickup": 1, "in_transit": 1})
