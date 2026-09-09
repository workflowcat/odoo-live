from odoo import fields, models


class UaHubSection(models.Model):
    _name = "ua.hub.section"
    _description = "Розділ головної панелі"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, help="Технічний код розділу, використовується для посилань з даних")
    active = fields.Boolean(default=True)
    item_ids = fields.One2many("ua.hub.item", "section_id", string="Команди")

    _code_uniq = models.Constraint(
        "unique(code)",
        "Код розділу має бути унікальним.",
    )
