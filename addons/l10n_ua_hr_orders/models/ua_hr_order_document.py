"""Документ кадрового наказу: кожен проведений ua.hr.order отримує свій ua.employee.document
(kind "order") на підпис, і його підписання відмічається ознайомленням.

Правило чисто доменне, тому живе тут, у модулі наказів. Раніше воно стояло в екрані
l10n_ua_card_ui через побоювання циклу: мовляв, ua.employee.document оголошено в
l10n_ua_hr_card. Циклу немає - l10n_ua_hr_orders сам залежить від l10n_ua_hr_card, тож
поле order_id на документі додається звідси через _inherit.

Гачок ловить дію для КОЖНОГО виду наказу (прийняття, зміна окладу, переведення, відпустка,
звільнення, відрядження), не лише прийняття: справа прийняття (l10n_ua_hire) створює лише п'ять
документів пакета першого дня самостійно, а документ самого наказу - завжди цей гачок."""
from odoo import _, fields, models

ORDER_REPORT_XMLID = "l10n_ua_hr_orders.report_ua_hr_order"


class UaEmployeeDocumentOrder(models.Model):
    _inherit = "ua.employee.document"

    order_id = fields.Many2one("ua.hr.order", string="Наказ", ondelete="cascade")


class UaHrOrder(models.Model):
    _inherit = "ua.hr.order"

    def action_post(self):
        result = super().action_post()
        Doc = self.env["ua.employee.document"].sudo()
        for order in self:
            if Doc.search_count([("order_id", "=", order.id)]):
                continue  # ідемпотентно: повторне проведення (після скасування) не дублює документ
            Doc.create({
                "employee_id": order.employee_id.id,
                "type": "order",
                "name": order._order_ref_text() if order.name else _("Наказ про %s") % order.order_type,
                "state": "to_sign",
                "order_id": order.id,
                "report_xmlid": ORDER_REPORT_XMLID,
                "res_model": "ua.hr.order",
                "res_id": order.id,
            })
        return result

    def action_acknowledge(self):
        result = super().action_acknowledge()
        Doc = self.env["ua.employee.document"].sudo()
        for order in self:
            doc = Doc.search([("order_id", "=", order.id)], limit=1)
            if doc and doc.state != "not_needed":
                doc.write({"state": "signed", "signed_date": order.ack_date or fields.Date.context_today(order)})
        return result
