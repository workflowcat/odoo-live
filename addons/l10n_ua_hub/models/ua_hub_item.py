from odoo import _, fields, models
from odoo.exceptions import UserError


class UaHubItem(models.Model):
    _name = "ua.hub.item"
    _description = "Команда головної панелі"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    section_id = fields.Many2one("ua.hub.section", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    action_xmlid = fields.Char(required=True, string="Xmlid дії", help="Наприклад payroll.hr_payslip_run_action")
    description = fields.Char(translate=True)
    active = fields.Boolean(default=True)
    available = fields.Boolean(compute="_compute_available", string="Доступна")

    def _compute_available(self):
        for item in self:
            item.available = item._get_available()

    def _get_available(self):
        """Чи існує дія за xmlid і чи має поточний користувач доступ до її моделі."""
        self.ensure_one()
        xmlid = self.action_xmlid
        if not xmlid or "." not in xmlid:
            return False
        record = self.env.ref(xmlid, raise_if_not_found=False)
        if not record:
            return False
        # читання полів самої дії (res_model тощо) не повинно залежати від прав
        # користувача на ir.actions.*, тому дивимось на дію через sudo
        record = record.sudo()
        if record._name == "ir.actions.client":
            return True
        res_model = False
        if record._name == "ir.actions.act_window":
            res_model = record.res_model
        elif record._name == "ir.actions.report":
            res_model = record.model
        elif record._name == "ir.actions.server":
            res_model = record.model_id.model if record.model_id else False
        if not res_model:
            return record._name == "ir.actions.server"
        if res_model not in self.env:
            return False
        return self.env[res_model].has_access("read")

    def action_open(self):
        self.ensure_one()
        record = self.env.ref(self.action_xmlid, raise_if_not_found=False)
        if not record:
            raise UserError(_("Команда недоступна: %s") % self.action_xmlid)
        action = record.sudo().read()[0]
        return action
