"""Замовлення: звідки прийшло, для кого купуємо, на який рахунок витрат."""
from odoo import fields, models


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
