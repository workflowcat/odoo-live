"""Суми затверджених актів гіг-спеціаліста - рядками введення GIG і GIG_BONUS у листку."""
from odoo import _, fields, models
from odoo.exceptions import UserError

from .ua_gig_act import GIG, GIG_BONUS

NAMES = {GIG: "Винагорода за гіг-контрактом", GIG_BONUS: "Премія гіг-спеціалісту"}


class HrPayslipInput(models.Model):
    _inherit = "hr.payslip.input"

    ua_gig_auto = fields.Boolean(
        "З акта гіг-спеціаліста", readonly=True, copy=False,
        help="Суму вписав акт гіг-спеціаліста; при перерахунку листка вона оновлюється.")


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_gig_amounts(self):
        """{GIG: сума, GIG_BONUS: сума} затверджених актів, чий кінець періоду в періоді листка."""
        self.ensure_one()
        acts = self.env["ua.gig.act"].sudo().search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "confirmed"),
            ("company_id", "=", self.company_id.id),
            ("date_to", ">=", self.date_from), ("date_to", "<=", self.date_to)])
        currency = self.company_id.currency_id
        return {GIG: currency.round(sum(acts.mapped("amount"))),
                GIG_BONUS: currency.round(sum(acts.mapped("bonus")))}

    def _ua_sync_gig_inputs(self):
        Input = self.env["hr.payslip.input"].sudo()
        for slip in self.filtered(lambda s: s.state in ("draft", "verify")):
            for code, amount in slip._ua_gig_amounts().items():
                rows = slip.input_line_ids.filtered(lambda line, c=code: line.code == c)
                auto = rows.filtered("ua_gig_auto")
                if not amount:
                    auto.unlink()
                    continue
                manual = (rows - auto).filtered(lambda line: line.amount)
                if manual:
                    raise UserError(_(
                        "%(name)s: у листку вже є ручна сума «%(line)s», а за період затверджено акт. "
                        "Приберіть одну з двох, щоб не заплатити двічі.",
                        name=slip.employee_id.name, line=NAMES[code]))
                target = auto[:1] or rows[:1]
                if target:
                    target.sudo().write({"amount": amount, "ua_gig_auto": True})
                    (rows - target).unlink()
                else:
                    Input.create({
                        "payslip_id": slip.id, "contract_id": slip.contract_id.id, "code": code,
                        "name": NAMES[code], "amount": amount, "ua_gig_auto": True,
                    })

    def compute_sheet(self):
        self._ua_sync_gig_inputs()
        return super().compute_sheet()
