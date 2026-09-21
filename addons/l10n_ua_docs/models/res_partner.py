"""Реквізити контрагента для української первинки.

ЄДРПОУ / РНОКПП - нативний `company_registry`, ІПН платника ПДВ - нативний
`vat`, статус платника ПДВ уже дає `l10n_ua_vat` (`x_vat_status`). Тут лише
фактична адреса (в Odoo адреса одна, а на папері часто дві) і підписант.
"""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_ua_actual_address = fields.Char(
        "Фактична адреса",
        help="Заповнюють, коли фактична адреса відрізняється від тієї, що в ЄДР. "
             "Порожнє поле означає, що адреси збігаються.")
    x_ua_signatory_name = fields.Char(
        "Підписант (ПІБ)",
        help="Хто підписує акти і накладні з боку контрагента.")
    x_ua_signatory_basis = fields.Char(
        "Діє на підставі",
        help="Статуту, довіреності № ... від ..., наказу.")

    def _ua_docs_address(self):
        """Адреса одним рядком: індекс, місто, вулиця."""
        self.ensure_one()
        parts = [self.zip, self.city, self.street, self.street2]
        return ", ".join(p.strip() for p in parts if p and p.strip())
