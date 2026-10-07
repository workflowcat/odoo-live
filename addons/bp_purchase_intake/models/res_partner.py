import json

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .codes import digits, party_code_valid


class ResPartner(models.Model):
    _inherit = "res.partner"

    bp_supplier_status = fields.Selection([("unverified", "Не перевірено"), ("verified", "Перевірено")],
                                          "Статус постачальника", tracking=True, copy=False, index=True)
    bp_verified_by = fields.Many2one("res.users", "Перевірив", readonly=True, copy=False)
    bp_verified_at = fields.Datetime("Перевірено", readonly=True, copy=False)
    # Вхідні рахунки бачать закупівлі й бухгалтерія. Без groups картку контакту не міг
    # відкрити ніхто інший (завсклад, кадровик): читання поля падало на правах.
    bp_intake_id = fields.Many2one("bp.purchase.intake", "Створено з рахунку", readonly=True, copy=False,
                                   groups="purchase.group_purchase_user,account.group_account_invoice")
    bp_intake_count = fields.Integer("Вхідні рахунки", compute="_compute_bp_intake_count",
                                     groups="purchase.group_purchase_user,account.group_account_invoice")

    bp_registry_name = fields.Char("Повна назва (ЄДР)", readonly=True, copy=False)
    bp_registry_status = fields.Char("Стан (ЄДР)", readonly=True, copy=False)
    bp_registry_date = fields.Date("Дата реєстрації (ЄДР)", readonly=True, copy=False)
    bp_registry_address = fields.Char("Адреса (ЄДР)", readonly=True, copy=False)
    bp_registry_head = fields.Char("Керівник (ЄДР)", readonly=True, copy=False)
    bp_registry_kved = fields.Char("Основний КВЕД", readonly=True, copy=False)
    bp_registry_vat = fields.Char("ПДВ (ЄДР)", readonly=True, copy=False)
    bp_registry_markers = fields.Text("Маркери (ЄДР)", readonly=True, copy=False)
    bp_registry_checked_at = fields.Datetime("Дані ЄДР отримано", readonly=True, copy=False)

    def _compute_bp_intake_count(self):
        groups = self.env["bp.purchase.intake"]._read_group([("partner_id", "in", self.ids)], ["partner_id"], ["__count"])
        counts = {p.id: n for p, n in groups}
        for p in self:
            p.bp_intake_count = counts.get(p.id, 0)

    def action_bp_mark_verified(self):
        user = self.env.user
        if not (user.has_group("purchase.group_purchase_manager") or user.has_group("account.group_account_manager")):
            raise AccessError("Позначити постачальника перевіреним може керівник закупівель або бухгалтер-адміністратор.")
        for p in self:
            p.write({"bp_supplier_status": "verified", "bp_verified_by": user.id, "bp_verified_at": fields.Datetime.now()})
            p.message_post(body=f"Постачальника перевірено: {user.name}.")
        return True

    def action_bp_mark_unverified(self):
        self.write({"bp_supplier_status": "unverified", "bp_verified_by": False, "bp_verified_at": False})
        return True

    def action_bp_open_intakes(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Вхідні рахунки", "res_model": "bp.purchase.intake",
                "view_mode": "list,form", "domain": [("partner_id", "=", self.id)]}

    def action_bp_refresh_registry(self):
        for p in self:
            data, error = p._bp_registry_update()
            if error:
                p.message_post(body=f"ЄДР: {error}")
        return True

    def _bp_registry_update(self):
        """Pull ЄДР data through the bridge (OpenDataBot, cached 24 h). Returns (data, error)."""
        self.ensure_one()
        code = digits(self.company_registry)
        if not party_code_valid(code):
            return None, "код ЄДРПОУ/РНОКПП у картці відсутній або не проходить контрольну суму"
        try:
            status, data = self.env["bp.bridge"].call("GET", f"/api/odb/screen/{code}")
        except Exception as e:  # bridge not configured or unreachable: keep the partner, report it
            return None, str(e)
        if status != 200:
            return None, (data or {}).get("error") or f"відповідь моста {status}"
        reg = data.get("registry") or {}
        markers = [c for c in data.get("checks") or [] if c.get("present") and c.get("severity") in ("warn", "high")]
        vals = {
            "bp_registry_name": reg.get("full_name") or False,
            "bp_registry_status": reg.get("status") or False,
            "bp_registry_date": (reg.get("registration_date") or "")[:10] or False,
            "bp_registry_address": reg.get("address") or False,
            "bp_registry_head": reg.get("head") or False,
            "bp_registry_kved": reg.get("kved") or False,
            "bp_registry_vat": f"{reg.get('vat_status') or ''} {reg.get('vat_code') or ''}".strip() or False,
            "bp_registry_markers": "\n".join(f"{m.get('title')}: {m.get('detail')}" for m in markers) or "немає",
            "bp_registry_checked_at": fields.Datetime.now(),
        }
        if not self.street and reg.get("address"):
            vals["street"] = reg["address"]
        if not self.vat and reg.get("vat_code") and reg.get("vat_status") == "active":
            vals["vat"] = reg["vat_code"]
        if not self.email and reg.get("email"):
            vals["email"] = reg["email"]
        changed = any(str(self[k] or "") != str(v or "") for k, v in vals.items()
                      if k.startswith("bp_registry_") and k != "bp_registry_checked_at")
        self.write(vals)
        if changed:
            self.message_post(body=(f"Дані ЄДР{' (з кешу)' if data.get('cached') else ''}: {reg.get('full_name')}; "
                                    f"стан {reg.get('status')}; керівник {reg.get('head')}; ПДВ {vals['bp_registry_vat'] or 'немає'}; "
                                    f"маркери: {len(markers)}."))
        return data, None
