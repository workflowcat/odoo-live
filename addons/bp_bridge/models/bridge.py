"""Єдині двері назовні: Worker odoo-live. Odoo тримає один токен, ключів постачальників у нього немає."""
import json
import logging
import os
import re
from urllib.parse import urlsplit

import requests

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import str2bool

_logger = logging.getLogger(__name__)

# Міст має лише маршрути /api/...; інших методів наші модулі не шлють.
METHODS = ("GET", "POST", "PATCH")
PATH_OK = re.compile(r"/api/[A-Za-z0-9._~%/-]*")


class Bridge(models.AbstractModel):
    _name = "bp.bridge"
    _description = "Міст інтеграцій (odoo-live Worker)"

    def _settings(self):
        # Спершу змінні середовища, далі нові ключі bp_bridge.*, далі старі bp_kyc.* - на стендах вони вже є.
        icp = self.env["ir.config_parameter"].sudo()
        # Знешкоджена копія (odoo neutralize) у міст не ходить: токен у середовищі стенда міг лишитися.
        if str2bool(icp.get_param("database.is_neutralized") or "0", False) \
                and os.environ.get("BP_BRIDGE_ON_NEUTRALIZED") != "1":
            raise UserError("Міст інтеграцій вимкнено: це знешкоджена копія бази. "
                            "Щоб увімкнути, задайте BP_BRIDGE_ON_NEUTRALIZED=1.")
        url = (os.environ.get("BP_BRIDGE_URL") or icp.get_param("bp_bridge.url")
               or icp.get_param("bp_kyc.bridge_url") or "")
        token = (os.environ.get("BP_BRIDGE_TOKEN") or icp.get_param("bp_bridge.token")
                 or icp.get_param("bp_kyc.bridge_token") or "")
        if not url or not token:
            raise UserError("Міст інтеграцій не налаштовано: задайте BP_BRIDGE_URL і BP_BRIDGE_TOKEN "
                            "(змінні середовища або параметри bp_bridge.url / bp_bridge.token, "
                            "старі ключі bp_kyc.bridge_url / bp_kyc.bridge_token теж читаються).")
        return url.rstrip("/"), token

    def _target(self, url, method, path):
        """Повна адреса запиту або помилка. Токен піде лише на адресу з налаштувань:
        шлях починається з /api/, не містить «..» і не може змінити хост."""
        if method not in METHODS or not isinstance(path, str) or not PATH_OK.fullmatch(path) \
                or ".." in path or "//" in path:
            raise UserError("Міст інтеграцій: такий маршрут не дозволено.")
        full = f"{url}{path}"
        base, target = urlsplit(url), urlsplit(full)
        if base.scheme not in ("https", "http") or not base.hostname or base.username or base.password \
                or (target.scheme, target.hostname, target.port, target.username, target.password) \
                != (base.scheme, base.hostname, base.port, None, None) \
                or not target.path.startswith(base.path.rstrip("/") + "/api/"):
            raise UserError("Міст інтеграцій: адреса запиту не збігається з адресою моста.")
        return full

    def _call(self, method, path, payload=None, params=None, timeout=60):
        """Запит у міст із системним токеном. Метод приватний навмисно: ззовні (RPC)
        його викликати не можна, а право користувача перевіряє той, хто викликає, -
        дія на справі KYC, картці контрагента чи вхідному рахунку."""
        url, token = self._settings()
        full = self._target(url, method, path)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "X-Author": self.env.user.name}
        try:
            # Без переходів за переадресацією: токен не має піти на іншу адресу.
            r = requests.request(method, full, headers=headers, params=params,
                                 data=json.dumps(payload) if payload is not None else None,
                                 timeout=timeout, allow_redirects=False)
        except requests.RequestException as e:
            raise UserError(f"Міст недоступний: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:500]}
        if r.status_code >= 400:
            _logger.warning("bridge %s %s -> %s %s", method, path, r.status_code, data)
        return r.status_code, data
