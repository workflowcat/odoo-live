"""Сума затвердженого виробітку - рядком введення PIECE у розрахунковому листку."""
from odoo import _, fields, models
from odoo.exceptions import UserError

from .ua_piecework import PIECE


class HrPayslipInput(models.Model):
    _inherit = "hr.payslip.input"

    ua_piecework_auto = fields.Boolean(
        "З виробітку", readonly=True, copy=False,
        help="Суму вписав документ «Виробіток»; при перерахунку листка вона оновлюється.")


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_piecework_amount(self):
        self.ensure_one()
        lines = self.env["ua.piecework.line"].sudo().search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "confirmed"),
            ("company_id", "=", self.company_id.id),
            ("piecework_id.date_to", ">=", self.date_from),
            ("piecework_id.date_to", "<=", self.date_to),
        ])
        return self.company_id.currency_id.round(sum(lines.mapped("amount")))

    def _ua_sync_piecework_input(self):
        Input = self.env["hr.payslip.input"].sudo()
        for slip in self.filtered(lambda s: s.state in ("draft", "verify")):
            amount = slip._ua_piecework_amount()
            rows = slip.input_line_ids.filtered(lambda line: line.code == PIECE)
            auto = rows.filtered("ua_piecework_auto")
            if not amount:
                auto.unlink()
                continue
            manual = (rows - auto).filtered(lambda line: line.amount)
            if manual:
                raise UserError(_(
                    "%s: у листку вже є ручна сума «Відрядна оплата», а за період затверджено "
                    "виробіток. Приберіть одну з двох, щоб не заплатити двічі.") % slip.employee_id.name)
            target = auto[:1] or rows[:1]
            if target:
                target.sudo().write({"amount": amount, "ua_piecework_auto": True})
                (rows - target).unlink()
            else:
                Input.create({
                    "payslip_id": slip.id, "contract_id": slip.contract_id.id, "code": PIECE,
                    "name": _("Відрядна оплата"), "amount": amount, "ua_piecework_auto": True,
                })

    def compute_sheet(self):
        self._ua_sync_piecework_input()
        return super().compute_sheet()
