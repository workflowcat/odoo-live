"""Розцінка на операції технологічної карти."""
from odoo import fields, models


class MrpRoutingWorkcenter(models.Model):
    _inherit = "mrp.routing.workcenter"

    ua_piece_rate = fields.Float(
        "Розцінка, грн за одиницю", digits="Product Price",
        help="Відрядна оплата за одну одиницю виробу на цій операції. Нуль - операція в "
             "виробіток не потрапляє (оплачується окладом або погодинно).")


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    ua_piecework_line_ids = fields.One2many("ua.piecework.line", "workorder_id", "Виробіток",
                                            readonly=True)
