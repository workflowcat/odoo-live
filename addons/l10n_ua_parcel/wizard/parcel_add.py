"""Додати відправлення: вставити номери як є - з листа постачальника, таблиці чи месенджера."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models import parcel_core as core


class UaParcelAdd(models.TransientModel):
    _name = "ua.parcel.add"
    _description = "Додати відправлення"

    text = fields.Text("Номери", required=True,
                       help="Один чи кілька номерів через пробіл, кому чи з нового рядка. Решту тексту "
                            "листа можна лишити: беремо лише схожі на номери слова.")
    carrier_id = fields.Many2one("ua.parcel.carrier", "Перевізник",
                                 help="Порожньо - визначимо за номером (Нова пошта, Укрпошта, S10).")
    direction = fields.Selection([("in", "До нас"), ("out", "Від нас")], "Напрям", required=True, default="in")
    partner_id = fields.Many2one("res.partner", "Від кого чи кому")
    description = fields.Char("Що всередині")
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user)
    purchase_id = fields.Many2one("purchase.order", "Замовлення постачальнику")
    picking_id = fields.Many2one("stock.picking", "Складський документ")
    origin = fields.Char("Інший документ")
    preview = fields.Text("Що знайдено", compute="_compute_preview")

    @api.depends("text", "carrier_id")
    def _compute_preview(self):
        Carrier = self.env["ua.parcel.carrier"]
        for wizard in self:
            lines = []
            for number in wizard._numbers():
                carrier = wizard.carrier_id or Carrier._ua_detect(number)
                lines.append("%s - %s" % (number, carrier.name if carrier else _("перевізника не впізнано")))
            wizard.preview = "\n".join(lines) or False

    def _numbers(self):
        numbers = core.find_numbers(self.text)
        if not self.carrier_id:
            numbers = [n for n in numbers if not core.looks_like_phone(n)]
        return numbers

    def action_add(self):
        self.ensure_one()
        numbers = self._numbers()
        if not numbers:
            raise UserError(_("У тексті немає номерів відправлень."))
        Carrier, Parcel = self.env["ua.parcel.carrier"], self.env["ua.parcel"]
        pairs, unknown = [], []
        for number in numbers:
            carrier = self.carrier_id or Carrier._ua_detect(number)
            if carrier:
                pairs.append((number, carrier))
            else:
                unknown.append(number)
        if unknown:
            raise UserError(_("Не впізнали перевізника для: %s. Оберіть перевізника вручну або "
                              "додайте шаблон номера в його картку.") % ", ".join(unknown))
        links = {k: v for k, v in (("purchase_id", self.purchase_id.id), ("picking_id", self.picking_id.id),
                                   ("partner_id", self.partner_id.id), ("origin", self.origin),
                                   ("description", self.description)) if v}
        result = Parcel.browse()
        to_create = []
        for number, carrier in pairs:
            existing = Parcel.search([("name", "=", number), ("carrier_id", "=", carrier.id),
                                      ("company_id", "=", self.env.company.id)], limit=1)
            if existing:
                # Той самий номер з іншого листа - лише дописуємо зв'язки, яких бракувало.
                existing.write({k: v for k, v in links.items() if not existing[k]})
                result |= existing
            else:
                to_create.append(dict(links, name=number, carrier_id=carrier.id, direction=self.direction,
                                      user_id=self.user_id.id))
        created = Parcel.create(to_create) if to_create else Parcel
        created._ua_track()
        result |= created
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_parcel.action_ua_parcel")
        if len(result) == 1:
            action.update({"res_id": result.id, "view_mode": "form", "views": [(False, "form")]})
        else:
            action["domain"] = [("id", "in", result.ids)]
        return action
