from datetime import datetime, time, timedelta

from odoo import models
from odoo.addons.payroll.models.base_browsable import BaseBrowsableObject


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _ua_month_workdays(self, contract):
        """Робочі дні періоду за графіком контракту. Святкові не віднімаються, поки holidays_per_year = 0 (воєнний стан)."""
        cal = contract.resource_calendar_id or self.employee_id.resource_calendar_id or self.company_id.resource_calendar_id
        if cal:
            data = cal.get_work_duration_data(datetime.combine(self.date_from, time.min),
                                              datetime.combine(self.date_to, time.max), compute_leaves=False)
            if data and data.get("days"):
                return data["days"]
        d, n = self.date_from, 0
        while d <= self.date_to:
            if d.weekday() < 5:
                n += 1
            d += timedelta(days=1)
        return n

    def _ua_payroll_values(self, contracts):
        """Значення для правил під префіксом payroll.ua. Інші модулі (середні, табель) доповнюють цей словник."""
        Param = self.env["ua.payroll.param"]
        emp = self.employee_id.sudo()
        p = Param.get_all(self.date_to, self.company_id)
        psp_mult = {"none": 0.0, "base": 1.0, "child": float(max(emp.ua_psp_children, 1)),
                    "child150": 1.5 * max(emp.ua_psp_children, 1), "s150": 1.5, "s200": 2.0}[emp.ua_psp or "none"]
        thr_mult = float(max(emp.ua_psp_children, 1)) if emp.ua_psp in ("child", "child150") else 1.0
        contract = contracts[:1]
        return {
            "min_wage": p["min_wage"], "living_wage": p["living_wage"],
            "pdfo_rate": p["pdfo_rate"], "vz_rate": p["vz_rate"],
            "esv_rate": p["esv_rate_disabled"] if emp.ua_esv_category == "disabled" else p["esv_rate"],
            "esv_max_base": p["min_wage"] * p["esv_max_multiplier"],
            "esv_min_applies": bool(emp.ua_main_job) and emp.ua_contract_kind == "employment",
            "psp_amount": p["psp_base"] * psp_mult,
            "psp_threshold": p["psp_threshold"] * thr_mult,
            "month_workdays": self._ua_month_workdays(contract) if contract else 0,
            "contract_kind": emp.ua_contract_kind or "employment",
            "holidays_per_year": p.get("holidays_per_year", 0.0),
            "fte": float(emp.ua_fte or "1"),
            "reserve_rate": p.get("reserve_rate", 0.0),
        }

    def get_payroll_dict(self, contracts):
        res = super().get_payroll_dict(contracts)
        res["ua"] = BaseBrowsableObject(self._ua_payroll_values(contracts))
        return res
