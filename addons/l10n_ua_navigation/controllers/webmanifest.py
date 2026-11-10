"""Застосунок на телефоні: ярлики ключових дій.

Odoo 19 CE уже віддає web manifest і service worker: у Chrome на Android це «Установити
застосунок», у Safari на iPhone - «На початковий екран». Застосунок відкривається без рядка
адреси, як рідний. Тут додаємо свої ярлики (довге натискання на іконку): дії, які роблять
зі смартфона. Ярлик показуємо лише тоді, коли людина бачить цей пункт меню.
"""
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.web.controllers.webmanifest import WebManifest

# xml id пункту меню, назва ярлика, що він робить
UA_SHORTCUTS = [
    ("l10n_ua_navigation.menu_ua_scan_stock", "Сканування", "Прийняти, відвантажити чи перемістити товар зі сканером"),
    ("l10n_ua_payment_request.menu_ua_payment_request", "Заявки на оплату", "Подати чи погодити заявку на оплату"),
    ("l10n_ua_navigation.menu_ua_hr_leaves", "Відсутності", "Заява на відпустку, лікарняний, відрядження"),
]
ICON = {"sizes": "192x192", "src": "/web/static/img/odoo-icon-192x192.png", "type": "image/png"}


class UaWebManifest(WebManifest):

    def _ua_shortcuts(self):
        try:
            visible = request.env["ir.ui.menu"]._visible_menu_ids()
        except AccessError:
            return []
        shortcuts = []
        for xmlid, name, description in UA_SHORTCUTS:
            menu = request.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu.id in visible:
                shortcuts.append({"name": name, "url": "/odoo?menu_id=%s" % menu.id,
                                  "description": description, "icons": [ICON]})
        return shortcuts

    def _get_shortcuts(self):
        # Android показує перші чотири ярлики: наші - першими
        return self._ua_shortcuts() + super()._get_shortcuts()
