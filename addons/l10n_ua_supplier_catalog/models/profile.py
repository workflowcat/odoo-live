"""Профіль прайсу: як читати таблицю конкретного постачальника.

Колонки шукаються за словами в заголовку (перше слово, що трапилось у клітинці).
Ціна може бути з ПДВ чи без, за одиницю з колонки «Од.», за упаковку з колонки
«Фасовка», за 100 чи 1000 штук. Профіль один раз налаштовується і далі
використовується для кожного нового прайсу цього постачальника.
"""
from odoo import api, fields, models

PRICE_PER = [("unit", "За одиницю з таблиці"), ("pack", "За упаковку з колонки фасовки"),
             ("hundred", "За 100 одиниць"), ("thousand", "За 1000 одиниць")]
DIVISOR = {"hundred": 100.0, "thousand": 1000.0}


class UaSupplierPriceProfile(models.Model):
    _name = "ua.supplier.price.profile"
    _description = "Профіль прайсу постачальника"
    _order = "partner_id, name"

    name = fields.Char("Назва профілю", required=True, default="Основний прайс")
    partner_id = fields.Many2one("res.partner", "Постачальник", required=True, index=True,
                                 ondelete="cascade")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    col_code = fields.Char("Колонка коду", default="артикул, код, sku",
                           help="Слова із заголовка через кому; перша колонка, де трапилось "
                                "слово, вважається колонкою коду постачальника.")
    col_name = fields.Char("Колонка назви", default="найменування, назва, товар, номенклатура")
    col_price = fields.Char("Колонка ціни", default="ціна, цена, price, вартість")
    col_unit = fields.Char("Колонка одиниці", default="од., од, ед., unit")
    col_pack = fields.Char("Колонка фасовки", default="фасовка, упаковка, уп., кратність, pack")
    col_stock = fields.Char("Колонка залишку", default="залишок, наявність, остаток, stock")
    price_vat = fields.Selection([("incl", "З ПДВ"), ("excl", "Без ПДВ")], "Ціна в прайсі",
                                 default="incl", required=True)
    vat_rate = fields.Float("Ставка ПДВ, %", default=20.0)
    price_per = fields.Selection(PRICE_PER, "Ціна вказана", default="unit", required=True)
    default_pack = fields.Float("Фасовка за замовчуванням", default=1.0,
                                help="Скільки одиниць в упаковці, коли колонки фасовки немає.")
    currency_id = fields.Many2one("res.currency", "Валюта", required=True,
                                  default=lambda self: self.env.company.currency_id)
    delay = fields.Integer("Строк поставки, днів", default=3)
    website = fields.Char("Сайт постачальника")
    note = fields.Text("Примітка")
    import_ids = fields.One2many("ua.supplier.price.import", "profile_id", "Завантаження")
    last_import = fields.Date("Останній прайс", compute="_compute_last_import")
    import_count = fields.Integer("Прайсів", compute="_compute_last_import")

    @api.depends("import_ids.date", "import_ids.state")
    def _compute_last_import(self):
        for rec in self:
            done = rec.import_ids.filtered(lambda i: i.state == "applied")
            rec.last_import = max(done.mapped("date")) if done else False
            rec.import_count = len(rec.import_ids)

    def _ua_words(self, field):
        return tuple(w.strip().lower() for w in (self[field] or "").split(",") if w.strip())

    def _ua_net(self, price):
        """Ціна без ПДВ."""
        self.ensure_one()
        if self.price_vat == "incl" and self.vat_rate:
            return price / (1.0 + self.vat_rate / 100.0)
        return price

    def _ua_per_unit(self, price, pack):
        """(ціна за одиницю, мінімальна кількість) з ціни рядка і фасовки."""
        self.ensure_one()
        if self.price_per == "pack" and pack and pack > 1:
            return price / pack, pack
        if self.price_per in DIVISOR:
            return price / DIVISOR[self.price_per], DIVISOR[self.price_per]
        return price, 0.0

    def action_new_import(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "ua.supplier.price.import",
                "view_mode": "form", "context": {"default_profile_id": self.id}}

    def action_imports(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Прайси: %s" % self.partner_id.name,
                "res_model": "ua.supplier.price.import", "view_mode": "list,form",
                "domain": [("profile_id", "=", self.id)],
                "context": {"default_profile_id": self.id}}
