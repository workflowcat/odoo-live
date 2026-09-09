from odoo import fields, models


class UaEmployeePriorJob(models.Model):
    _name = "ua.employee.prior.job"
    _description = "Попереднє місце роботи"
    _order = "date_from desc"

    employee_id = fields.Many2one("hr.employee", string="Працівник", required=True, ondelete="cascade")
    company_name = fields.Char("Підприємство", required=True)
    job_title = fields.Char("Посада")
    date_from = fields.Date("З")
    date_to = fields.Date("По")
    note = fields.Char("Примітка")
