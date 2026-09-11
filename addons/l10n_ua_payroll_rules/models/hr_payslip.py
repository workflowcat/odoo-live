from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from odoo import models
from odoo.addons.payroll.models.base_browsable import BaseBrowsableObject


def ua_round(value, digits=2):
    """Округлення грошей: пів копійки вгору (ROUND_HALF_UP).

    Вбудований round() Python округлює до парного: round(0.125, 2) дає 0,12.
    Для грошей це неправильно. Тут значення переводиться в Decimal через рядок,
    тому двійкова похибка float не тягнеться далі, і половина завжди йде вгору."""
    if value is None:
        return 0.0
    quant = Decimal(1).scaleb(-int(digits))
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    def _get_tools_dict(self):
        """Функції, доступні у формулах правил. r2 - округлення грошей."""
        tools = super()._get_tools_dict()
        tools["r2"] = ua_round
        return tools

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
            "aid_charity_limit": p.get("aid_charity_limit", 0.0),
            "gift_limit_share": p.get("gift_limit_share", 0.0),
            "aid_used_year": self._ua_aid_used_year(),
            "mat_cover_days": 0,   # l10n_ua_average перевизначає
            "time_ratio": -1.0,    # l10n_ua_hr_docs ставить частку часу із затвердженого табеля
        }

    def _ua_aid_used_year(self):
        """Скільки неоподатковуваної матеріальної допомоги працівник уже отримав цього року.

        Межа за пп. 170.7.3 ПКУ - річна, тому дивимось усі проведені листки року, крім цього."""
        if not self.employee_id or not self.date_from:
            return 0.0
        year_start = self.date_from.replace(month=1, day=1)
        lines = self.env["hr.payslip.line"].sudo().search([
            ("slip_id.employee_id", "=", self.employee_id.id),
            ("slip_id.state", "=", "done"),
            ("slip_id.date_from", ">=", year_start),
            ("slip_id.date_from", "<", self.date_from),
            ("code", "=", "AID_FREE"),
        ])
        return ua_round(sum(lines.mapped("total")))

    def _ua_worked_share(self, values):
        """Частка відпрацьованого часу за рядками відпрацьованих днів листка."""
        lines = self.worked_days_line_ids
        work = sum(line.number_of_days for line in lines if line.code == "WORK100")
        other = sum(abs(line.number_of_days) for line in lines if line.code != "WORK100")
        days = work - other
        total = values.get("month_workdays") or work or 1.0
        return max(min(days, total), 0.0) / (total or 1.0)

    def _ua_min_sal_target(self, values):
        """Мінімальна зарплата за ст. 3-1 ЗУ про оплату праці, пропорційно ставці і часу.

        Норму часу беремо із затвердженого табеля (time_ratio), інакше з рядків
        відпрацьованих днів. Для ЦПХ і ФОП доплата не застосовується."""
        if values.get("contract_kind") != "employment":
            return 0.0
        share = values.get("time_ratio", -1.0)
        if share is None or share < 0:
            share = self._ua_worked_share(values)
        share = max(min(share, 1.0), 0.0)
        return ua_round(values["min_wage"] * values.get("fte", 1.0) * share)

    def get_payroll_dict(self, contracts):
        res = super().get_payroll_dict(contracts)
        values = self._ua_payroll_values(contracts)
        values["min_sal_target"] = self._ua_min_sal_target(values)
        res["ua"] = BaseBrowsableObject(values)
        return res
