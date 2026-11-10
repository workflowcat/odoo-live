"""Місяць звітності листка: у Д1 і 4ДФ якого місяця він показується."""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _first_day(value):
    return fields.Date.to_date(value).replace(day=1) if value else value


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    ua_report_month = fields.Date(
        "Місяць звітності", compute="_compute_ua_report_month", store=True, readonly=False, precompute=True,
        copy=False, index=True,
        help="Місяць, в об'єднаній звітності якого показується листок. Типово - місяць періоду листка. "
             "Листок-коригування за минулий місяць, проведений пізніше, звітуйте поточним місяцем: "
             "лікарняні й декретні з нього підуть у Д1 рядком за свій місяць з кодом типу нарахувань 13.")

    @api.depends("date_from")
    def _compute_ua_report_month(self):
        for slip in self:
            slip.ua_report_month = _first_day(slip.date_from)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("ua_report_month"):
                vals["ua_report_month"] = _first_day(vals["ua_report_month"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("ua_report_month"):
            vals = dict(vals, ua_report_month=_first_day(vals["ua_report_month"]))
        return super().write(vals)

    @api.constrains("ua_report_month", "date_from")
    def _check_ua_report_month(self):
        for slip in self:
            if slip.ua_report_month and slip.date_from and slip.ua_report_month < _first_day(slip.date_from):
                raise ValidationError(_("Листок не звітують раніше за місяць його періоду."))
            if slip.ua_report_month and slip.date_from and slip.ua_report_month > _first_day(slip.date_from) + relativedelta(months=12):
                raise ValidationError(_("Місяць звітності - не пізніше ніж за рік після періоду листка."))
