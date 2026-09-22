"""Замовлення: звідки прийшло, для кого купуємо, на який рахунок витрат, за яку ціну."""
from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    ua_request_id = fields.Many2one(
        comodel_name="purchase.request",
        string="Запит на закупівлю",
        readonly=True,
        index=True,
        help="Запит, з якого зроблено це замовлення. Ставиться чарівником "
             "«запит -> замовлення»; список замовлень можна групувати за ним.",
    )
    ua_department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Підрозділ",
        help="Підрозділ-замовник. Приходить із запиту, далі йде в рахунок.",
    )
    ua_expense_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Рахунок витрат",
        help="Рахунок витрат для рядків рахунку постачальника. Порожній - "
             "рахунок бере Odoo з товару або категорії.",
    )


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _prepare_account_move_line(self, move=False):
        """Рахунок витрат із замовлення перебиває рахунок з товару.

        Odoo 19 сам рахунок тут не ставить - його обчислює рядок проводки з
        товару чи категорії. Ставимо явно, і тоді обчислення не спрацьовує.
        Розділювачі і примітки не чіпаємо.
        """
        vals = super()._prepare_account_move_line(move=move)
        account = self.order_id.ua_expense_account_id
        if account and vals.get("display_type") == "product":
            vals["account_id"] = account.id
        return vals

    @api.model
    def _ua_has_supplierinfo(self, product, partner):
        """Чи є товар у каталозі саме цього постачальника.

        Те саме порівняння, що й у нативному обчисленні ціни: рядок каталогу
        заведено на контрагента або на його головну фірму.
        """
        if not product or not partner:
            return False
        partners = partner | partner.commercial_partner_id
        return bool(product.seller_ids.filtered(lambda s: s.partner_id in partners))

    @api.model
    def _ua_price_from_history(self, product, partner, company, currency=None):
        """Остання ціна одиниці цього товару в цього постачальника.

        Спершу підтверджене замовлення, потім проведений рахунок постачальника.
        Ціна переводиться в одиницю виміру товару і в потрібну валюту за курсом
        того дня, коли купували. Нуль означає «історії немає».
        """
        if not product or not partner or not company:
            return 0.0
        currency = currency or company.currency_id
        partners = (partner | partner.commercial_partner_id).ids
        line = self.sudo().search([
            ("product_id", "=", product.id),
            ("order_id.partner_id", "in", partners),
            ("company_id", "=", company.id),
            ("state", "in", ("purchase", "done")),
            ("price_unit", ">", 0.0),
        ], order="date_order desc, id desc", limit=1)
        if line:
            return self._ua_convert_price(
                line.product_uom_id, line.price_unit, product, line.currency_id,
                currency, company, line.date_order.date())
        bill_line = self.env["account.move.line"].sudo().search([
            ("product_id", "=", product.id),
            ("move_id.move_type", "=", "in_invoice"),
            ("move_id.partner_id", "in", partners),
            ("company_id", "=", company.id),
            ("parent_state", "=", "posted"),
            ("display_type", "=", "product"),
            ("price_unit", ">", 0.0),
        ], order="date desc, id desc", limit=1)
        if bill_line:
            return self._ua_convert_price(
                bill_line.product_uom_id, bill_line.price_unit, product,
                bill_line.currency_id, currency, company, bill_line.date)
        return 0.0

    @api.model
    def _ua_convert_price(self, uom, price, product, from_currency, to_currency,
                          company, date):
        if uom and uom != product.uom_id:
            price = uom._compute_price(price, product.uom_id)
        if from_currency and to_currency and from_currency != to_currency:
            price = from_currency._convert(price, to_currency, company, date)
        return price
