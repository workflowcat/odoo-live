"""Контрагент рядка виписки за кодом ЄДРПОУ (ДРФО), коли за IBAN його не знайшли."""
from odoo import models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _statement_line_import_update_hook(self, st_line_vals, speeddict):
        code = st_line_vals.pop("ua_partner_code", None)
        super()._statement_line_import_update_hook(st_line_vals, speeddict)
        if code and not st_line_vals.get("partner_id"):
            partner = self._ua_partner_by_code(code, speeddict)
            if partner:
                st_line_vals["partner_id"] = partner

    def _ua_partner_by_code(self, code, speeddict):
        cache = speeddict.setdefault("ua_code", {})
        if code not in cache:
            partners = self.env["res.partner"].search([
                "|", ("company_registry", "=", code), ("vat", "=", code),
                ("company_id", "in", (False, self.company_id.id)),
                ("parent_id", "=", False),
            ], limit=2)
            # Два контрагенти з одним кодом - не вгадуємо, рядок лишається бухгалтеру.
            cache[code] = partners.id if len(partners) == 1 else False
        return cache[code]
