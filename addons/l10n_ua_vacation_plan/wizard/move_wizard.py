# -*- coding: utf-8 -*-
from odoo import fields, models


class UaVacationMoveWizard(models.TransientModel):
    _name = "ua.vacation.move.wizard"
    _description = "Перенесення відпустки з графіка"

    line_id = fields.Many2one("ua.vacation.plan.line", required=True, ondelete="cascade")
    date_from = fields.Date("Нові дати з", required=True)
    date_to = fields.Date("по", required=True)
    reason = fields.Char("Підстава", required=True,
                         help="Заява працівника, наказ, згода сторін (ст. 11 ЗУ «Про відпустки»).")

    def action_apply(self):
        self.ensure_one()
        self.line_id.action_move(self.date_from, self.date_to, self.reason)
        return {"type": "ir.actions.act_window_close"}
