"""Ставка ввізного мита на товарі - підставляється в рядок декларації."""
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_customs_duty_rate = fields.Float(
        "Ставка ввізного мита, %", digits=(5, 2),
        help="Ставка за Митним тарифом для коду УКТ ЗЕД товару. Підставляється в митну "
             "декларацію; там її можна змінити, наприклад за пільгою чи угодою про ЗВТ.")
