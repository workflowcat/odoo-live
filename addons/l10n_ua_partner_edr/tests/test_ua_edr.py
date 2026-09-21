"""Заповнення картки контрагента з ЄДР.

У мережу тут ніхто не ходить: підміняємо bp.bridge.call - єдине місце, через
яке модуль спілкується із зовнішнім світом. Відповідь мосту зроблена такою ж
за формою, як справжня.

Запуск: docker compose run ... --test-tags=ua_edr
"""
import os
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

BRIDGE = "odoo.addons.bp_bridge.models.bridge.Bridge.call"


def registry_payload(**over):
    data = {
        "kind": "company",
        "registry": {
            "full_name": "ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ПРОМІНЬ»",
            "short_name": "ТОВ «ПРОМІНЬ»",
            "status": "зареєстровано",
            "registration_date": "2015-03-12",
            "kved": "62.01 Комп'ютерне програмування",
            "head": "Коваленко Іван Іванович",
            "head_role": "Директор",
            "capital": 100000.0,
            "vat_status": "платник ПДВ",
            "vat_code": "321654987654",
            "address": "79022, Львівська обл., місто Львів, вулиця Городоцька, будинок 174",
            "email": "office@promin.ua",
            "phone": "+380322001122",
        },
        "checks": [],
    }
    data["registry"].update(over.pop("registry", {}))
    data.update(over)
    return data


@tagged("post_install", "-at_install", "ua_edr")
class TestUaPartnerEdr(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "32165498", "company_registry": "32165498", "is_company": True,
        })

    @staticmethod
    def _answer(status, data, calls=None):
        def fake(self, method, path, payload=None, params=None, timeout=60):
            if calls is not None:
                calls.append(path)
            return status, data
        return fake

    # ------------------------------------------------------------------
    # 1. Поля лягають у картку: назва, повна назва, адреса, КВЕД, керівник, стан.
    # ------------------------------------------------------------------
    def test_01_fields_mapped(self):
        with patch(BRIDGE, self._answer(200, registry_payload())):
            self.partner.action_fill_from_edr()
        self.assertEqual(self.partner.name, "ТОВ «ПРОМІНЬ»")
        self.assertIn("ТОВАРИСТВО", self.partner.ua_edr_full_name)
        self.assertEqual(self.partner.ua_edr_status, "зареєстровано")
        self.assertEqual(str(self.partner.ua_edr_registration_date), "2015-03-12")
        self.assertEqual(self.partner.ua_kved, "62.01 Комп'ютерне програмування")
        self.assertEqual(self.partner.ua_edr_head, "Коваленко Іван Іванович")
        self.assertEqual(self.partner.ua_edr_kind, "company")
        self.assertAlmostEqual(self.partner.ua_edr_capital, 100000.0, delta=0.005)
        self.assertEqual(self.partner.vat, "321654987654")
        self.assertEqual(self.partner.country_id, self.env.ref("base.ua"))
        self.assertTrue(self.partner.ua_edr_synced_at)
        # адреса розібрана на індекс, місто і вулицю
        self.assertEqual(self.partner.zip, "79022")
        self.assertEqual(self.partner.city, "Львів")
        self.assertEqual(self.partner.street, "вулиця Городоцька, будинок 174")
        # керівник став контактною особою
        director = self.partner.child_ids.filtered(
            lambda c: c.name == "Коваленко Іван Іванович")
        self.assertEqual(len(director), 1)
        self.assertEqual(director.function, "Директор")

    # ------------------------------------------------------------------
    # 2. Компанії в реєстрі немає - зрозуміла помилка, картка не змінюється.
    # ------------------------------------------------------------------
    def test_02_not_found(self):
        with patch(BRIDGE, self._answer(404, {"error": "not found"})):
            with self.assertRaises(UserError):
                self.partner.action_fill_from_edr()
        self.assertFalse(self.partner.ua_edr_status)

    # ------------------------------------------------------------------
    # 3. Припинена юрособа: стан і маркер високого ризику видно в картці.
    # ------------------------------------------------------------------
    def test_03_terminated_flagged(self):
        data = registry_payload(
            registry={"status": "припинено"},
            checks=[
                {"present": True, "severity": "high", "title": "Припинено",
                 "detail": "юрособу припинено 2024-08-01"},
                {"present": True, "severity": "warn", "title": "Судові справи",
                 "detail": "3 справи за рік"},
                {"present": False, "severity": "high", "title": "Санкції",
                 "detail": "немає"},
            ])
        with patch(BRIDGE, self._answer(200, data)):
            self.partner.action_fill_from_edr()
        self.assertEqual(self.partner.ua_edr_status, "припинено")
        checks = self.partner.ua_edr_checks
        self.assertIn("! Припинено", checks)
        self.assertIn("? Судові справи", checks)
        # маркер, якого немає, у картку не пишемо
        self.assertNotIn("Санкції", checks)
        body = self.partner.message_ids[0].body
        self.assertIn("Маркерів високого ризику: 1", body)

    # ------------------------------------------------------------------
    # 4. Міст не налаштовано - зрозуміла помилка, а не трейсбек requests.
    # ------------------------------------------------------------------
    def test_04_no_token(self):
        self.env["ir.config_parameter"].sudo().search([
            ("key", "in", ("bp_bridge.url", "bp_bridge.token",
                           "bp_kyc.bridge_url", "bp_kyc.bridge_token"))]).unlink()
        with patch.dict(os.environ, {"BP_BRIDGE_URL": "", "BP_BRIDGE_TOKEN": ""}):
            with self.assertRaises(UserError):
                self.partner.action_fill_from_edr()

    # ------------------------------------------------------------------
    # 5. Повторний запит нічого не дублює і не затирає уточнене руками.
    # ------------------------------------------------------------------
    def test_05_idempotent(self):
        calls = []
        with patch(BRIDGE, self._answer(200, registry_payload(), calls)):
            self.partner.action_fill_from_edr()
            self.partner.street = "вулиця Городоцька, будинок 174-А"
            self.partner.action_fill_from_edr()
        self.assertEqual(calls, ["/api/odb/screen/32165498", "/api/odb/screen/32165498"])
        self.assertEqual(len(self.partner.child_ids), 1, "керівника створено двічі")
        # уточнену вручну адресу другий запит не переписав
        self.assertEqual(self.partner.street, "вулиця Городоцька, будинок 174-А")
        self.assertEqual(self.partner.name, "ТОВ «ПРОМІНЬ»")

    # ------------------------------------------------------------------
    # 6. Код не схожий на ЄДРПОУ чи РНОКПП - у міст навіть не йдемо.
    # ------------------------------------------------------------------
    def test_06_bad_code(self):
        calls = []
        bad = self.env["res.partner"].create({"name": "Без коду", "is_company": True})
        with patch(BRIDGE, self._answer(200, registry_payload(), calls)):
            with self.assertRaises(UserError):
                bad.action_fill_from_edr()
            bad.company_registry = "123"
            with self.assertRaises(UserError):
                bad.action_fill_from_edr()
        self.assertEqual(calls, [])

    # ------------------------------------------------------------------
    # 7. ФОП за РНОКПП через майстра: контрагента створено і заповнено.
    # ------------------------------------------------------------------
    def test_07_wizard_creates_fop(self):
        data = registry_payload(
            kind="fop",
            registry={"full_name": "Коваленко Іван Іванович", "short_name": "",
                      "head": "", "vat_status": "", "vat_code": ""})
        wizard = self.env["ua.partner.edr.wizard"].create({"code": "2233445566"})
        with patch(BRIDGE, self._answer(200, data)):
            action = wizard.action_create()
        partner = self.env["res.partner"].browse(action["res_id"])
        self.assertEqual(partner.company_registry, "2233445566")
        self.assertEqual(partner.ua_edr_kind, "fop")
        self.assertEqual(partner.name, "Коваленко Іван Іванович")
        self.assertFalse(partner.child_ids)
