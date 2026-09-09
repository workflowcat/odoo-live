from odoo import fields, models


class UaEmployeeChild(models.Model):
    _name = "ua.employee.child"
    _description = "Дитина працівника"
    _order = "birthday"

    employee_id = fields.Many2one("hr.employee", string="Працівник", required=True, ondelete="cascade")
    name = fields.Char("ПІБ дитини", required=True)
    birthday = fields.Date("Дата народження")
    note = fields.Char("Примітка")
