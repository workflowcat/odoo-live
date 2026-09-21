"""Ознака ФОП на компанії і ставка єдиного податку за датою."""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_fop = fields.Boolean(
        "ФОП на єдиному податку",
        help="Компанія - фізична особа-підприємець на спрощеній системі. "
             "Дохід рахується касовим методом: за надходженням коштів, "
             "а не за рахунками (п. 292.1 і п. 292.6 ПКУ).",
    )
    ua_fop_group = fields.Selection(
        [("3", "3 група")],
        "Група ЄП",
        default="3",
        help="Підтримана лише 3 група. У 1, 2 і 4 груп інша база "
             "(фіксована ставка або площа), це окремий модуль.",
    )
    ua_fop_vat_payer = fields.Boolean(
        "Платник ПДВ",
        help="3 група платника ПДВ платить ЄП за ставкою 3 % доходу, "
             "неплатник - 5 % (п. 293.3 ПКУ).",
    )

    def _ua_fop_ep_rate(self, on_date):
        """Ставка єдиного податку 3 групи на дату, %."""
        self.ensure_one()
        key = "fop_ep_rate_3_vat" if self.ua_fop_vat_payer else "fop_ep_rate_3"
        return self.env["ua.fop.param"].get(key, on_date, self)
