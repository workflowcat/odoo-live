# -*- coding: utf-8 -*-
"""Застосунок на телефоні (INT-01): web manifest Odoo 19 CE з нашими ярликами. Тег `ua_mobile`.

Застосунок ставиться з браузера телефона («Установити застосунок» / «На початковий екран»).
Ярлики - ключові дії зі смартфона; людина бачить лише ті, до чиїх меню має доступ.
"""
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "ua_mobile")
class TestMobileApp(HttpCase):

    def _manifest(self):
        response = self.url_open("/web/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_manifest_has_our_shortcuts_first(self):
        self.authenticate("admin", "admin")
        manifest = self._manifest()
        self.assertEqual(manifest["display"], "standalone", "відкривається як застосунок, без рядка адреси")
        names = [shortcut["name"] for shortcut in manifest["shortcuts"]]
        self.assertEqual(names[:3], ["Сканування", "Заявки на оплату", "Відсутності"])
        self.assertTrue(all(shortcut["url"].startswith("/odoo?menu_id=") for shortcut in manifest["shortcuts"]))

    def test_no_shortcuts_without_login(self):
        manifest = self._manifest()
        self.assertFalse([s for s in manifest.get("shortcuts", []) if s["name"] == "Сканування"],
                         "без входу ярликів наших меню немає")
