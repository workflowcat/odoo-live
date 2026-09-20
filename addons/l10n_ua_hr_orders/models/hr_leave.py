# -*- coding: utf-8 -*-
"""Наказ про відпустку (В-2) з боку hr.leave: проведення відсутності створює й проводить наказ,
відмова чи скасування вже проведеної відсутності - скасовує наказ.

Коди видів роботи з l10n_ua_average/data/leave_types.xml: VAC, SICK, UNPAID, STUDY, CHILD_VAC,
TRIP, CHILD3, SICK_CARE, MAT. Наказовими вважаються усі, крім SICK (тимчасова непрацездатність
не потребує наказу за КЗпП) і TRIP (відрядження вже має власний вид наказу "trip" у ua.hr.order,
що оформлюється окремо, а не через hr.leave).

Коли наказ сам створює відпустку (ua.hr.order._post_leave), він виставляє контекстний прапорець
"ua_order_posting", щоб цей гак не намагався провести другий наказ на ту саму відпустку."""
from odoo import _, fields, models

ORDER_WORTHY_LEAVE_CODES = {"VAC", "UNPAID", "MAT", "STUDY", "CHILD_VAC", "CHILD3", "SICK_CARE"}


def is_leave_type_order_worthy(leave_type):
    """True, коли вид відпустки/відсутності leave_type (hr.leave.type) має код із
    ORDER_WORTHY_LEAVE_CODES - тобто потребує кадрового наказу за КЗпП (див. докстрінг модуля).
    Єдине джерело правди для цієї перевірки: викликається і з боку hr.leave (_ua_order_worthy),
    і з боку ua.hr.order (форма/дозвіл на проведення наказу типу "leave")."""
    code = leave_type.work_entry_type_id.code
    return bool(code) and code in ORDER_WORTHY_LEAVE_CODES


class HrLeave(models.Model):
    _inherit = "hr.leave"

    ua_order_id = fields.Many2one("ua.hr.order", "Наказ", readonly=True, copy=False)

    def _ua_order_worthy(self):
        self.ensure_one()
        return is_leave_type_order_worthy(self.holiday_status_id)

    def _ua_create_order(self):
        self.ensure_one()
        order = self.env["ua.hr.order"].sudo().create({
            "order_type": "leave",
            "employee_id": self.employee_id.id,
            "company_id": self.employee_id.company_id.id,
            "date": fields.Date.context_today(self),
            "date_from": self.request_date_from or self.date_from,
            "date_to": self.request_date_to or self.date_to,
            "leave_type_id": self.holiday_status_id.id,
            "sick_number": self.ua_sick_number,
            "basis": _("Заява %s") % self.employee_id.name,
            "leave_id": self.id,
        })
        order.action_post()
        self.ua_order_id = order.id
        return order

    def _action_validate(self, check_state=True):
        res = super()._action_validate(check_state=check_state)
        if not self.env.context.get("ua_order_posting"):
            for leave in self:
                if leave.ua_order_id or not leave._ua_order_worthy():
                    continue
                leave._ua_create_order()
        return res

    def _ua_cancel_linked_orders(self):
        orders = self.mapped("ua_order_id").filtered(lambda o: o.state in ("posted", "acknowledged"))
        for order in orders:
            order.write({"state": "cancelled"})
            order.message_post(body=_("Наказ скасовано: відпустку скасовано або відхилено."))

    def action_refuse(self):
        if not self.env.context.get("ua_order_posting"):
            self._ua_cancel_linked_orders()
        return super().action_refuse()

    def _force_cancel(self, reason=None, msg_subtype="mail.mt_comment", notify_responsibles=True):
        if not self.env.context.get("ua_order_posting"):
            self._ua_cancel_linked_orders()
        return super()._force_cancel(reason=reason, msg_subtype=msg_subtype, notify_responsibles=notify_responsibles)
