from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    kyc_case_ids = fields.One2many("kyc.case", "partner_id", "Справи KYC")
    kyc_case_count = fields.Integer(compute="_compute_kyc")
    kyc_decision = fields.Selection([("cleared", "Погоджено"), ("flagged", "З умовами"), ("rejected", "Відхилено")],
                                    "KYC", compute="_compute_kyc")
    kyc_risk = fields.Selection([("low", "Низький"), ("medium", "Середній"), ("high", "Високий"), ("critical", "Критичний")],
                                "Ризик KYC", compute="_compute_kyc")

    @api.depends("kyc_case_ids.decision", "kyc_case_ids.risk")
    def _compute_kyc(self):
        for p in self:
            cases = p.kyc_case_ids.sorted("create_date", reverse=True)
            p.kyc_case_count = len(cases)
            last = cases[:1]
            p.kyc_decision = last.decision if last else False
            p.kyc_risk = last.risk if last else False

    def action_open_kyc_cases(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": "Справи KYC", "res_model": "kyc.case",
                "view_mode": "kanban,list,form", "domain": [("partner_id", "=", self.id)],
                "context": {"default_partner_id": self.id, "default_code": self.company_registry or ""}}

    def action_new_kyc_case(self):
        self.ensure_one()
        case = self.env["kyc.case"].create({"partner_id": self.id, "code": self.company_registry or "",
                                             "kind": "company" if self.is_company else "person"})
        return {"type": "ir.actions.act_window", "res_model": "kyc.case", "res_id": case.id, "view_mode": "form"}
