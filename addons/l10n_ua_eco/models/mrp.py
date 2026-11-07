"""Ревізія на специфікації, у замовленні на виробництво і в паспорті виробу."""
from odoo import api, fields, models

from .ua_eco import revision_label


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    ua_revision = fields.Integer("Зміна №", default=0, copy=False, readonly=True,
                                 help="Номер конструкторської зміни: 0 - перший випуск.")
    ua_eco_id = fields.Many2one("ua.eco", "Створено повідомленням", copy=False, readonly=True)
    ua_previous_bom_id = fields.Many2one("mrp.bom", "Попередня ревізія", copy=False,
                                         readonly=True)
    ua_successor_eco_id = fields.Many2one("ua.eco", "Замінено повідомленням", copy=False,
                                          readonly=True)

    @api.depends("ua_revision")
    def _compute_display_name(self):
        super()._compute_display_name()
        for bom in self:
            if bom.ua_revision:
                bom.display_name = "%s (%s)" % (bom.display_name, revision_label(bom.ua_revision))


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_bom_revision = fields.Integer("Зміна специфікації", related="bom_id.ua_revision",
                                     store=True)


class StockLot(models.Model):
    _inherit = "stock.lot"

    ua_bom_revision = fields.Integer("Зміна специфікації", compute="_compute_ua_bom_revision")
    ua_bom_eco_id = fields.Many2one("ua.eco", "Повідомлення про зміну",
                                    compute="_compute_ua_bom_revision")

    @api.depends("ua_production_id")
    def _compute_ua_bom_revision(self):
        for lot in self:
            bom = lot.ua_production_id.bom_id
            lot.ua_bom_revision = bom.ua_revision
            lot.ua_bom_eco_id = bom.ua_eco_id

    def _ua_revision_text(self):
        self.ensure_one()
        if not self.ua_production_id.bom_id:
            return ""
        text = revision_label(self.ua_bom_revision)
        if self.ua_bom_eco_id:
            text += " (%s)" % self.ua_bom_eco_id.name
        return text
