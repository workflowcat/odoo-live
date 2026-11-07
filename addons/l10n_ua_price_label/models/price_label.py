"""Цінники.

Ціна на ціннику - для покупця: з прайс-листа (або ціна продажу з картки) разом із податками
продажу товару. Для фасованого товару, у картці якого вказано вміст упаковки (0,5 кг, 0,9 л),
друкується ще ціна за 1 кг, 1 л чи 1 м - щоб покупець міг порівняти упаковки різного розміру.
Числа - українським записом: «1 240,00», незалежно від мови користувача.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.barcode import check_barcode_encoding

UNITS = [("kg", "кг"), ("l", "л"), ("m", "м")]
UOM_WORDS = {"uom.product_uom_unit": "шт", "uom.product_uom_kgm": "кг",
             "uom.product_uom_litre": "л", "uom.product_uom_meter": "м",
             "uom.product_uom_gram": "г"}


def ua_money(value):
    """1240.5 -> «1 240,50»."""
    return "{:,.2f}".format(value).replace(",", " ").replace(".", ",")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_label_content = fields.Float(
        "Вміст упаковки", digits=(16, 3),
        help="Скільки кілограмів, літрів чи метрів в одній одиниці продажу. Заповнено - на "
             "ціннику буде ціна за 1 кг, 1 л чи 1 м.")
    ua_label_unit = fields.Selection(UNITS, "Одиниця вмісту", default="kg")


class UaPriceLabelWizard(models.TransientModel):
    _name = "ua.price.label.wizard"
    _description = "Друк цінників"

    product_ids = fields.Many2many("product.product", string="Товари", required=True)
    pricelist_id = fields.Many2one("product.pricelist", "Прайс-лист",
                                   help="Порожньо - ціна продажу з картки товару.")
    copies = fields.Integer("Копій кожного", default=1, required=True)
    layout = fields.Selection([("a4", "Аркуш A4, 3 x 7"), ("roll", "Етикетка 58 x 40 мм")],
                              "Формат", default="a4", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        context = self.env.context
        ids = context.get("active_ids") or []
        if context.get("active_model") == "product.template" and ids:
            products = self.env["product.template"].browse(ids).product_variant_ids
        elif context.get("active_model") == "product.product" and ids:
            products = self.env["product.product"].browse(ids)
        else:
            products = self.env["product.product"]
        if products and "product_ids" in fields_list:
            values["product_ids"] = [(6, 0, products.ids)]
        return values

    def _price(self, product):
        self.ensure_one()
        if self.pricelist_id:
            price = self.pricelist_id._get_product_price(product, 1.0)
        else:
            price = product.lst_price
        company = self.company_id or self.env.company
        taxes = product.taxes_id.filtered(lambda t: t.company_id in company.parent_ids)
        if taxes:
            price = taxes.compute_all(price, company.currency_id, 1.0, product=product)[
                "total_included"]
        return company.currency_id.round(price)

    def _uom_word(self, product):
        for xmlid, word in UOM_WORDS.items():
            if product.uom_id == self.env.ref(xmlid, raise_if_not_found=False):
                return word
        return product.uom_id.name

    @staticmethod
    def _symbology(barcode):
        if barcode and check_barcode_encoding(barcode, "ean13"):
            return "EAN13"
        if barcode and check_barcode_encoding(barcode, "ean8"):
            return "EAN8"
        return "Code128"

    def label_rows(self):
        """Рядки цінників по порядку, з копіями: [{name, code, price, unit, unit_price,
        barcode, symbology, seller, date}]."""
        self.ensure_one()
        if self.copies < 1:
            raise UserError(_("Кількість копій - від однієї."))
        company = self.company_id or self.env.company
        today = fields.Date.context_today(self).strftime("%d.%m.%Y")
        units = dict(UNITS)
        rows = []
        for product in self.product_ids:
            price = self._price(product)
            content = product.ua_label_content
            unit_price = False
            if content and content > 0:
                unit_price = _("Ціна за 1 %(unit)s: %(price)s грн",
                               unit=units[product.ua_label_unit or "kg"],
                               price=ua_money(company.currency_id.round(price / content)))
            row = {
                "name": product.with_context(display_default_code=False).display_name,
                "code": product.default_code or "",
                "price": ua_money(price), "price_value": price,
                "unit": self._uom_word(product), "unit_price": unit_price,
                "barcode": product.barcode or "", "symbology": self._symbology(product.barcode),
                "seller": company.name, "date": today,
            }
            rows.extend(dict(row) for _copy in range(self.copies))
        return rows

    def action_print(self):
        self.ensure_one()
        if not self.product_ids:
            raise UserError(_("Оберіть товари для цінників."))
        report = "l10n_ua_price_label.action_report_ua_price_label" if self.layout == "a4" \
            else "l10n_ua_price_label.action_report_ua_price_label_roll"
        return self.env.ref(report).report_action(self)
