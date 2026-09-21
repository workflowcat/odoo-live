# -*- coding: utf-8 -*-
"""Код УКТ ЗЕД і режим ПДВ товару."""
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_uktzed = fields.Char(
        string="Код УКТ ЗЕД",
        help="10-значний код за класифікатором УКТ ЗЕД. Обов'язковий у "
             "податковій накладній для товарних рядків.",
    )
    x_vat_relief_id = fields.Many2one(
        "ua.vat.relief",
        string="Підстава пільги (вручну)",
        help="Ручне закріплення підстави звільнення за товаром. Порожньо - "
             "підстава визначається за кодом УКТ ЗЕД у довіднику пільг.",
    )
    x_vat_relief_effective_id = fields.Many2one(
        "ua.vat.relief",
        string="Чинна підстава пільги",
        compute="_compute_x_vat_relief_effective",
        help="Підстава, за якою товар звільнено: ручний вибір або збіг коду "
             "УКТ ЗЕД із чинною активною пільгою.",
    )
    x_vat_treatment = fields.Selection(
        selection=[
            ("exempt", "Звільнено від ПДВ (пільга)"),
            ("zero_export", "0 % (експорт)"),
            ("standard", "Оподатковується (20 / 14 / 7 %)"),
        ],
        string="Режим ПДВ товару",
        compute="_compute_x_vat_treatment",
        store=True,
        default="standard",
        help="Звільнено - код УКТ ЗЕД збігається з чинною пільгою у довіднику. "
             "Експортну ставку 0 % визначає не товар, а покупець-нерезидент.",
    )

    def _ua_effective_relief(self):
        """Чинна підстава: ручний вибір або збіг коду УКТ ЗЕД."""
        self.ensure_one()
        try:
            return self.x_vat_relief_id or self.env["ua.vat.relief"]._match(
                self.x_uktzed)
        except Exception:
            return self.env["ua.vat.relief"]

    @api.depends("x_uktzed", "x_vat_relief_id")
    def _compute_x_vat_relief_effective(self):
        for tmpl in self:
            tmpl.x_vat_relief_effective_id = tmpl._ua_effective_relief()

    @api.depends("x_uktzed", "x_vat_relief_id")
    def _compute_x_vat_treatment(self):
        """Окремий compute від незбереженого поля, щоб Odoo не плутав
        store і non-store. Збій - стандартне оподаткування."""
        for tmpl in self:
            try:
                tmpl.x_vat_treatment = (
                    "exempt" if tmpl._ua_effective_relief() else "standard")
            except Exception:
                tmpl.x_vat_treatment = "standard"
