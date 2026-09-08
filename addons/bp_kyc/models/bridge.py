"""One door to the outside world: the odoo-live Worker. Odoo holds one token, no vendor keys."""
import json
import logging
import os

import requests

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Bridge(models.AbstractModel):
    _name = "bp.bridge"
    _description = "Міст інтеграцій (odoo-live Worker)"

    def _settings(self):
        icp = self.env["ir.config_parameter"].sudo()
        url = os.environ.get("BP_BRIDGE_URL") or icp.get_param("bp_kyc.bridge_url") or ""
        token = os.environ.get("BP_BRIDGE_TOKEN") or icp.get_param("bp_kyc.bridge_token") or ""
        if not url or not token:
            raise UserError("Міст інтеграцій не налаштовано: задайте BP_BRIDGE_URL і BP_BRIDGE_TOKEN "
                            "(змінні середовища або параметри bp_kyc.bridge_url / bp_kyc.bridge_token).")
        return url.rstrip("/"), token

    def call(self, method, path, payload=None, params=None, timeout=60):
        url, token = self._settings()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "X-Author": self.env.user.name}
        try:
            r = requests.request(method, f"{url}{path}", headers=headers, params=params,
                                 data=json.dumps(payload) if payload is not None else None, timeout=timeout)
        except requests.RequestException as e:
            raise UserError(f"Міст недоступний: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:500]}
        if r.status_code >= 400:
            _logger.warning("bridge %s %s -> %s %s", method, path, r.status_code, data)
        return r.status_code, data
