# -*- coding: utf-8 -*-
"""Норматив робочих місць для осіб з інвалідністю і цільовий внесок за квартал (з 2026 року).

Порядок розрахунку (ст. 19 Закону № 875-XII у редакції Закону № 4219-IX, порядок № 268; числа - поля
документа, перевіряйте чинну редакцію):
1. Середньооблікова кількість штатних працівників за квартал - сума місячних з табелів, поділена на 3
   (той самий розрахунок, що в l10n_ua_headcount), у цілих одиницях за математичним округленням.
2. Норматив: менше 8 - немає; 8-25 - одне місце; понад 25 - відсоток (4 %) від цілої кількості,
   округлений математично.
3. Працівник з інвалідністю зараховується в місяці, коли він штатний (трудовий договір, основне місце
   роботи), а нарахована за місяць зарплата (GROSS проведених листків) більша за мінімальну. Його частка
   в місяці - як у середньообліковій (дні на обліку чи години неповної ставки); I група - за двох.
   Кількість за квартал - сума місячних / 3, у цілих одиницях.
4. Незайняті місця - норматив мінус зараховані, не менше нуля.
5. Середня зарплата - фонд кварталу (GROSS штатних працівників без лікарняних) / середньооблікову / 3.
6. Внесок - 40 % середньої зарплати x 3 місяці x незайняті місця x коефіцієнт воєнного стану (0,5).
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

STATES = [("draft", "Чернетка"), ("done", "Затверджено")]
QUARTERS = [("1", "I квартал"), ("2", "II квартал"), ("3", "III квартал"), ("4", "IV квартал")]
GROUPS = {"1": "I", "2": "II", "3": "III"}
ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV"}


def _half_up(value):
    return int(float_round(value, 0, rounding_method="HALF-UP"))


class UaDisabilityQuota(models.Model):
    _name = "ua.disability.quota"
    _description = "Норматив робочих місць для осіб з інвалідністю"
    _inherit = ["mail.thread"]
    _order = "year desc, quarter desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("Рік", required=True, default=lambda s: fields.Date.context_today(s).year, tracking=True)
    quarter = fields.Selection(QUARTERS, "Квартал", required=True, tracking=True,
                               default=lambda s: str((fields.Date.context_today(s).month - 1) // 3 + 1))
    date_from = fields.Date("З", compute="_compute_dates", store=True)
    date_to = fields.Date("По", compute="_compute_dates", store=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)

    # Правила - числа закону, перевіряйте чинну редакцію.
    excluded_codes = fields.Char("Коди табеля поза середньообліковою", default="ВП,ДД", required=True)
    small_from = fields.Integer("Норматив з (працівників)", default=8, required=True)
    small_to = fields.Integer("Одне місце до (працівників)", default=25, required=True)
    quota_percent = fields.Float("Норматив понад цю кількість, %", default=4.0, required=True)
    double_group_1 = fields.Boolean("I група - за двох", default=True)
    wage_excluded_codes = fields.Char(
        "Коди листка поза фондом оплати праці", default="SICK_EMP,SICK_PFU,SICK_CARE_PAY",
        help="Рядки розрахункового листка, які не входять у фонд для середньої зарплати (порядок № 268).")
    contribution_percent = fields.Float("Внесок, % середньої зарплати", default=40.0, required=True)
    contribution_months = fields.Integer("Місяців у розрахунку внеску", default=3, required=True)
    martial_factor = fields.Float("Коефіцієнт воєнного стану", default=0.5, digits=(16, 2), required=True,
                                  help="Частка внеску на час воєнного стану (за джерелами - п. 3 розд. II "
                                       "Закону № 4219-IX). 1 - без зменшення.")

    # Результати.
    min_wage = fields.Monetary("Мінімальна зарплата", readonly=True)
    month_averages = fields.Char("Середньооблікова за місяцями", readonly=True)
    headcount = fields.Float("Середньооблікова за квартал", digits=(16, 2), readonly=True)
    headcount_int = fields.Integer("Середньооблікова, цілих", readonly=True)
    norm = fields.Integer("Норматив, місць", readonly=True)
    disabled = fields.Float("Зараховано осіб з інвалідністю", digits=(16, 2), readonly=True)
    disabled_int = fields.Integer("Зараховано, цілих", readonly=True)
    shortfall = fields.Integer("Незайнятих місць", readonly=True)
    wage_fund = fields.Monetary("Фонд оплати праці за квартал", readonly=True)
    average_wage = fields.Monetary("Середня місячна зарплата", readonly=True)
    contribution = fields.Monetary("Цільовий внесок", readonly=True)
    line_ids = fields.One2many("ua.disability.quota.line", "quota_id", "Працівники з інвалідністю")
    check_text = fields.Text("Зауваження", readonly=True)
    computed_at = fields.Datetime("Розраховано", readonly=True)

    @api.depends("year", "quarter")
    def _compute_dates(self):
        for doc in self:
            if doc.year and doc.quarter:
                doc.date_from = date(doc.year, 3 * int(doc.quarter) - 2, 1)
                doc.date_to = doc.date_from + relativedelta(months=3, days=-1)
            else:
                doc.date_from = doc.date_to = False

    @api.depends("year", "quarter")
    def _compute_name(self):
        for doc in self:
            doc.name = _("Норматив для осіб з інвалідністю, %(q)s квартал %(y)s") % {
                "q": ROMAN.get(doc.quarter, ""), "y": doc.year}

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError(_("Видалити можна лише чернетку."))

    # ------------------------------------------------------------------ правила
    def ua_norm(self, headcount_int):
        """Кількість місць за нормативом для цілої середньооблікової кількості."""
        self.ensure_one()
        if headcount_int < self.small_from:
            return 0
        if headcount_int <= self.small_to:
            return 1
        return _half_up(headcount_int * self.quota_percent / 100.0)

    @staticmethod
    def _codes(text):
        return {code.strip() for code in (text or "").split(",") if code.strip()}

    def _ua_wages(self, d1, d2):
        """Нараховано за місяць на працівника: GROSS проведених листків без кодів поза фондом."""
        excluded = self._codes(self.wage_excluded_codes)
        wages = {}
        slips = self.env["hr.payslip"].sudo().search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date_to", ">=", d1), ("date_to", "<=", d2)])
        for slip in slips:
            gross = sum(slip.line_ids.filtered(lambda l: l.code == "GROSS").mapped("total"))
            outside = sum(slip.line_ids.filtered(lambda l: l.code in excluded).mapped("total"))
            wages.setdefault(slip.employee_id.id, [0.0, 0.0])
            wages[slip.employee_id.id][0] += gross
            wages[slip.employee_id.id][1] += gross - outside
        return wages

    # ------------------------------------------------------------------ розрахунок
    def action_compute(self):
        Sheet = self.env["ua.timesheet.sheet"]
        Headcount = self.env["ua.headcount.report"]
        Param = self.env["ua.payroll.param"]
        for doc in self:
            if doc.state == "done":
                raise UserError(_("Затверджений розрахунок не перераховують: поверніть його в чернетку."))
            doc.line_ids.unlink()
            excluded = self._codes(doc.excluded_codes)
            notes, lines, averages = [], [], []
            disabled_total = wage_fund = 0.0
            min_wage = Param.get("min_wage", doc.date_to, doc.company_id)
            start = doc.date_from
            while start <= doc.date_to:
                sheet = Sheet._ua_ensure_for(doc.company_id, start.year, start.month)
                if sheet.state != "confirmed":
                    notes.append(_("Табель %s не затверджено.") % start.strftime("%m.%Y"))
                frame = Headcount._ua_frame(sheet)
                averages.append(Headcount._ua_month_values(sheet, excluded)["average"])
                wages = doc._ua_wages(frame["d1"], frame["d2"])
                for line in sheet.line_ids:
                    employee = line.employee_id.sudo()
                    wage = wages.get(employee.id, [0.0, 0.0])
                    wage_fund += wage[1]
                    group = employee.ua_disability_group or "none"
                    if group == "none":
                        continue
                    part, _days, share = Headcount._ua_line_share(line, frame, excluded)
                    reasons = []
                    if not employee.ua_main_job:
                        reasons.append(_("не основне місце роботи"))
                    if doc.currency_id.compare_amounts(wage[0], min_wage) <= 0:
                        reasons.append(_("нараховано %(wage).2f - не більше мінімальної %(min).2f")
                                       % {"wage": wage[0], "min": min_wage})
                    weight = 2 if group == "1" and doc.double_group_1 else 1
                    units = 0.0 if reasons else share * weight
                    disabled_total += units
                    lines.append({
                        "quota_id": doc.id, "month_start": start, "employee_id": employee.id,
                        "disability_group": group, "part_time": part, "share": float_round(share, 4),
                        "wage": wage[0], "weight": weight, "units": float_round(units, 4),
                        "counted": not reasons, "reason": "; ".join(reasons),
                    })
                start += relativedelta(months=1)
            months = len(averages) or 1
            headcount = sum(averages) / months
            headcount_int = _half_up(headcount)
            norm = doc.ua_norm(headcount_int)
            disabled = disabled_total / months
            disabled_int = _half_up(disabled)
            shortfall = max(norm - disabled_int, 0)
            average_wage = wage_fund / headcount / months if headcount else 0.0
            contribution = (doc.contribution_percent / 100.0 * average_wage * doc.contribution_months
                            * shortfall * doc.martial_factor)
            if shortfall and doc.currency_id.is_zero(wage_fund):
                notes.append(_("Немає проведених розрахункових листків за квартал: середню зарплату і внесок "
                               "не пораховано."))
            uncounted = [l for l in lines if not l["counted"]]
            if uncounted:
                notes.append(_("Не зараховано в нормативі: %s.") % ", ".join(sorted({
                    "%s (%s)" % (self.env["hr.employee"].browse(l["employee_id"]).name,
                                 l["month_start"].strftime("%m.%Y")) for l in uncounted})))
            self.env["ua.disability.quota.line"].create(lines)
            doc.write({
                "min_wage": min_wage,
                "month_averages": " / ".join("%.2f" % a for a in averages),
                "headcount": float_round(headcount, 2), "headcount_int": headcount_int, "norm": norm,
                "disabled": float_round(disabled, 2), "disabled_int": disabled_int, "shortfall": shortfall,
                "wage_fund": float_round(wage_fund, 2), "average_wage": float_round(average_wage, 2),
                "contribution": float_round(contribution, 2),
                "check_text": "\n".join(notes) or False, "computed_at": fields.Datetime.now(),
            })
        return True

    def action_done(self):
        for doc in self:
            if not doc.computed_at:
                raise UserError(_("Спершу розрахуйте норматив."))
            doc.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_disability_quota.action_report_ua_disability_quota").report_action(self)

    def ua_money(self, value):
        self.ensure_one()
        return "{:,.2f}".format(value or 0.0).replace(",", " ").replace(".", ",")

    def ua_group(self, line):
        return GROUPS.get(line.disability_group, "")


class UaDisabilityQuotaLine(models.Model):
    _name = "ua.disability.quota.line"
    _description = "Працівник з інвалідністю в розрахунку нормативу"
    _order = "month_start, employee_id, id"

    quota_id = fields.Many2one("ua.disability.quota", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="quota_id.company_id", store=True)
    currency_id = fields.Many2one(related="quota_id.currency_id")
    month_start = fields.Date("Місяць", required=True)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    disability_group = fields.Selection([("1", "I"), ("2", "II"), ("3", "III")], "Група")
    part_time = fields.Boolean("Неповна ставка")
    share = fields.Float("Частка в середньообліковій", digits=(16, 4))
    wage = fields.Monetary("Нараховано за місяць")
    weight = fields.Integer("Рахується як")
    units = fields.Float("Зараховано", digits=(16, 4))
    counted = fields.Boolean("Зараховано в нормативі")
    reason = fields.Char("Чому ні")
