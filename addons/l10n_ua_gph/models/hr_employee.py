from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # Довідкова сума з поточної версії контракту (у виконавців за ЦПХ/ФОП оклад версії
    # зазвичай 0 - реальна сума йде щомісяця окремим входом розрахункового листка GPH/FOP_PAY,
    # тому це лише орієнтир для списку «Договори ЦПХ», не джерело нарахування).
    ua_gph_contract_amount = fields.Monetary(
        "Сума за договором", compute="_compute_ua_gph_contract_amount", groups="hr.group_hr_user",
        currency_field="ua_gph_currency_id")
    ua_gph_currency_id = fields.Many2one(
        "res.currency", compute="_compute_ua_gph_contract_amount", groups="hr.group_hr_user")

    @api.depends("current_version_id.wage", "company_id.currency_id")
    def _compute_ua_gph_contract_amount(self):
        for emp in self:
            emp.ua_gph_contract_amount = emp.current_version_id.wage or 0.0
            emp.ua_gph_currency_id = emp.company_id.currency_id
