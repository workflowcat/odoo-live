from odoo import fields, models

SIDE = [("expense", "рахунок витрат підрозділу"), ("code", "рахунок за кодом")]


class UaPayrollAccountMap(models.Model):
    """Правило листка -> проводка. Дебет або кредит може бути рахунком витрат підрозділу працівника."""
    _name = "ua.payroll.account.map"
    _description = "Проводки зарплати (Україна)"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    rule_code = fields.Char("Код правила", required=True, help="Код правила листка: BASIC, VAC, PDFO, ESV…")
    name = fields.Char("Опис проводки", required=True)
    debit_side = fields.Selection(SIDE, "Дебет", default="expense", required=True)
    debit_code = fields.Char("Дебет, код рахунку", help="Якщо дебет - рахунок за кодом")
    credit_side = fields.Selection(SIDE, "Кредит", default="code", required=True)
    credit_code = fields.Char("Кредит, код рахунку", help="Якщо кредит - рахунок за кодом")
    company_id = fields.Many2one("res.company", "Компанія")
    active = fields.Boolean(default=True)
