"""Звіт із праці: форми 1-ПВ (місячна) і 1-ПВ (квартальна), наказ Держстату від 15.04.2024 № 117.

Звідки цифри:
- фонд оплати праці - проведені розрахункові листки періоду (період листка починається в місяці),
  кожен рядок листка за класом свого правила (hr.salary.rule.ua_pv_class): основна, додаткова,
  заохочувальні, договори ЦПХ, поза фондом; лікарняні, декретні, добові, вихідна допомога - поза
  фондом;
- штатні працівники - трудовий договір і основне місце роботи; зовнішні сумісники - трудовий
  договір без основного місця; ЦПХ і гіг - окремо; ФОП не рахуються зовсім;
- мобілізовані (відсутність «Військова служба за призовом» у місяці) - у фонді всіх працівників
  (1020), але не у фонді штатних (1070) і не в розділі III квартальної;
- середньооблікова (1040) - з табеля П-5: кожен штатний працівник на обліку в день - одиниця,
  неповна ставка теж ціла одиниця (так вимагає бланк); у вихідний - як у попередній робочий день;
  без відпусток у зв'язку з вагітністю і для догляду за дитиною (ВП, ДД) і днів військової служби;
- відпрацьовані людино-години (1060) - факт годин штатних працівників з табеля;
- прийняті і звільнені - дати трудових договорів; причина звільнення - з підстави в договорі.
Суми - у тисячах гривень з одним знаком після коми; кількість і години - цілі.
"""
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

from .hr_salary_rule import ADDITIONAL, FUND, INCENTIVE

MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень",
          "вересень", "жовтень", "листопад", "грудень"]
NOT_ON_BOOKS = ("", "-")
OUT_OF_AVERAGE = ("ВП", "ДД")
MIL_CODE = "MIL"
# Пункти статей КЗпП, звільнення за якими - плинність кадрів (рядок 3060): власне бажання,
# згода сторін, невідповідність посаді, порушення дисципліни. Наша оцінка: ч. 1 ст. 38, коли
# працівник не може продовжувати роботу, теж іде сюди - підстава в договорі цього не розрізняє.
TURNOVER = {("38", None), ("36", "1"), ("40", "2"), ("40", "3"), ("40", "4"), ("40", "7"), ("40", "8"),
            ("41", "1")}


def _thousands(amount):
    return float_round((amount or 0.0) / 1000.0, 1)


def _basis_article(text):
    """(стаття, пункт) з підстави звільнення: «п. 1 ст. 40 КЗпП» -> ("40", "1")."""
    text = (text or "").lower().replace(" ", " ")
    article = re.search(r"ст(?:атт[іяі])?\.?\s*(\d+)", text)
    point = re.search(r"(?:п(?:ункт[ау]?)?\.?)\s*(\d+)", text)
    return (article.group(1) if article else None, point.group(1) if point else None)


class UaLabourReport(models.Model):
    _name = "ua.labour.report"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Звіт із праці (1-ПВ)"
    _order = "date_from desc, kind, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    kind = fields.Selection([("month", "1-ПВ (місячна)"), ("quarter", "1-ПВ (квартальна)")], "Форма",
                            required=True, default="month", tracking=True)
    year = fields.Integer("Рік", required=True, default=lambda s: fields.Date.context_today(s).year)
    period = fields.Integer("Місяць або квартал", required=True, default=lambda s: fields.Date.context_today(s).month,
                            help="Для місячної форми - номер місяця 1-12, для квартальної - номер кварталу 1-4.")
    date_from = fields.Date("З", compute="_compute_dates", store=True)
    date_to = fields.Date("По", compute="_compute_dates", store=True)
    state = fields.Selection([("draft", "Чернетка"), ("done", "Затверджено")], "Стан", default="draft",
                             required=True, readonly=True, copy=False, tracking=True)
    computed_at = fields.Datetime("Пораховано", readonly=True, copy=False)
    note = fields.Text("Пояснення до відхилень",
                       help="Основна причина, якщо середньооблікова змінилась на 25 % і більше або середня "
                            "зарплата - на 10 % і більше порівняно з попереднім періодом.")

    # ---- 1-ПВ (місячна) -----------------------------------------------------------------
    r1020 = fields.Float("1020 Фонд оплати праці усіх працівників, тис. грн", digits=(16, 1))
    r1030 = fields.Float("1030 ПДФО з фонду оплати праці усіх працівників, тис. грн", digits=(16, 1))
    r1040 = fields.Integer("1040 Середньооблікова кількість штатних працівників, осіб")
    r1060 = fields.Integer("1060 Відпрацьовано штатними працівниками, люд.-год")
    r1070 = fields.Float("1070 Фонд оплати праці штатних працівників, тис. грн", digits=(16, 1))

    # ---- 1-ПВ (квартальна), розділ I -----------------------------------------------------
    r3020 = fields.Integer("3020 Прийнято штатних працівників")
    r3040 = fields.Integer("3040 Звільнено штатних працівників")
    r3050 = fields.Integer("3050 з них через зміни в організації виробництва і праці")
    r3060 = fields.Integer("3060 з них через плинність кадрів")
    r3070 = fields.Integer("3070 Облікова кількість штатних працівників на кінець періоду")
    r3080 = fields.Integer("3080 з них на неповному робочому часі (на 31 грудня)")
    r3090 = fields.Integer("3090 у відпустці у зв'язку з вагітністю та пологами (на 31 грудня)")
    r3100 = fields.Integer("3100 у відпустці для догляду за дитиною (на 31 грудня)")
    # розділ II: години і люди; невідпрацьований час з ініціативи роботодавця - вписується вручну
    r4080_hours = fields.Integer("4080 Відпустки без збереження зарплати (простій), люд.-год")
    r4080_people = fields.Integer("4080 ... осіб")
    r4090_hours = fields.Integer("4090 Неповний час з економічних причин, люд.-год")
    r4090_people = fields.Integer("4090 ... осіб")
    r4100_hours = fields.Integer("4100 Страйки, люд.-год")
    r4100_people = fields.Integer("4100 ... осіб")
    # розділ III
    r5010 = fields.Float("5010 Фонд оплати праці штатних працівників, усього, тис. грн", digits=(16, 1))
    r5020 = fields.Float("5020 Фонд основної заробітної плати", digits=(16, 1))
    r5030 = fields.Float("5030 Фонд додаткової заробітної плати", digits=(16, 1))
    r5040 = fields.Float("5040 надбавки та доплати", digits=(16, 1))
    r5050 = fields.Float("5050 премії систематичні", digits=(16, 1))
    r5051 = fields.Float("5051 індексація", digits=(16, 1))
    r5052 = fields.Float("5052 компенсація за затримку виплати", digits=(16, 1))
    r5060 = fields.Float("5060 Заохочувальні та компенсаційні виплати", digits=(16, 1))
    r5070 = fields.Float("5070 матеріальна допомога", digits=(16, 1))
    r5080 = fields.Float("5080 соціальні пільги", digits=(16, 1))
    r5090 = fields.Float("5090 Оплата за невідпрацьований час", digits=(16, 1))
    # розділ IV: 1 - середньооблікова, 2 - фонд, 3 - люд.-год
    r7010_1 = fields.Integer("7010 Жінки: середньооблікова")
    r7010_2 = fields.Float("7010 Жінки: фонд, тис. грн", digits=(16, 1))
    r7010_3 = fields.Integer("7010 Жінки: відпрацьовано, люд.-год")
    r7030_1 = fields.Integer("7030 Зовнішні сумісники: середня кількість")
    r7030_2 = fields.Float("7030 Зовнішні сумісники: фонд, тис. грн", digits=(16, 1))
    r7040_1 = fields.Integer("7040 Договори ЦПХ: середня кількість")
    r7040_2 = fields.Float("7040 Договори ЦПХ: фонд, тис. грн", digits=(16, 1))
    # розділ V (на 31 грудня) - вписується вручну, береться з минулорічного звіту
    r8010 = fields.Integer("8010 Колективних договорів, од.")
    r8020 = fields.Integer("8020 Працівників, охоплених колективними договорами")
    r8030 = fields.Float("8030 Мінімальна місячна ставка за колективним договором, грн", digits=(16, 2))
    r8040 = fields.Float("8040 Мінімальна місячна ставка за галузевою угодою, грн", digits=(16, 2))

    _period_uniq = models.Constraint("unique(company_id, kind, year, period)",
                                     "Звіт із праці за цей період у компанії вже є.")

    # ---- період -------------------------------------------------------------------------
    @api.depends("kind", "year", "period")
    def _compute_dates(self):
        for rep in self:
            if not rep.year or not rep.period:
                rep.date_from = rep.date_to = False
                continue
            first = rep.period if rep.kind == "month" else (rep.period - 1) * 3 + 1
            months = 1 if rep.kind == "month" else 3
            if not 1 <= first <= 12:
                rep.date_from = rep.date_to = False
                continue
            rep.date_from = date(rep.year, first, 1)
            rep.date_to = rep.date_from + relativedelta(months=months, days=-1)

    @api.depends("kind", "year", "period")
    def _compute_name(self):
        for rep in self:
            if rep.kind == "month" and 1 <= (rep.period or 0) <= 12:
                rep.name = "1-ПВ (місячна) за %s %s" % (MONTHS[rep.period - 1], rep.year)
            else:
                rep.name = "1-ПВ (квартальна) за %s квартал %s" % (rep.period, rep.year)

    @api.constrains("kind", "period")
    def _check_period(self):
        for rep in self:
            top = 12 if rep.kind == "month" else 4
            if not 1 <= rep.period <= top:
                raise UserError(_("Період має бути від 1 до %s.") % top)

    def _month_starts(self):
        self.ensure_one()
        starts, day = [], self.date_from
        while day <= self.date_to:
            starts.append(day)
            day += relativedelta(months=1)
        return starts

    def _is_year_end(self):
        self.ensure_one()
        return self.kind == "quarter" and self.period == 4

    # ---- хто є хто -----------------------------------------------------------------------
    @staticmethod
    def _kind(employee):
        return employee.sudo().ua_contract_kind or "employment"

    def _is_staff(self, employee):
        return self._kind(employee) == "employment" and employee.sudo().ua_main_job

    def _is_external(self, employee):
        return self._kind(employee) == "employment" and not employee.sudo().ua_main_job

    def _mil_days(self, employees, d1, d2):
        """{працівник: множина днів військової служби} у межах d1..d2."""
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "in", employees.ids), ("state", "=", "validate"),
            ("holiday_status_id.work_entry_type_id.code", "=", MIL_CODE),
            ("request_date_from", "<=", d2), ("request_date_to", ">=", d1)])
        out = {}
        for leave in leaves:
            day = max(leave.request_date_from, d1)
            while day <= min(leave.request_date_to, d2):
                out.setdefault(leave.employee_id, set()).add(day)
                day += timedelta(days=1)
        return out

    # ---- листки ----------------------------------------------------------------------------
    def _slips(self, d1, d2, states=("done",)):
        return self.env["hr.payslip"].sudo().search([
            ("company_id", "=", self.company_id.id), ("date_from", ">=", d1), ("date_from", "<=", d2),
            ("state", "in", list(states)), ("credit_note", "=", False)])

    @staticmethod
    def _slip_parts(slip):
        """Суми листка за класами: {клас: сума, "unworked": сума, "pdfo": сума, "gross": сума}."""
        parts = {"unworked": 0.0, "pdfo": 0.0, "gross": 0.0}
        for line in slip.line_ids:
            if line.code == "PDFO":
                parts["pdfo"] += abs(line.total)
                continue
            if line.code == "GROSS":
                parts["gross"] += line.total
                continue
            cls, unworked = line.salary_rule_id._ua_pv_effective()
            if cls == "none":
                continue
            parts[cls] = parts.get(cls, 0.0) + line.total
            if unworked:
                parts["unworked"] += line.total
        return parts

    @staticmethod
    def _fund(parts):
        return sum(parts.get(cls, 0.0) for cls in FUND)

    # ---- табель ----------------------------------------------------------------------------
    def _timesheet_month(self, start, staff_filter):
        """З табеля місяця: (середньооблікова дробом, години, облікова на кінець, коди останнього дня).

        staff_filter(employee) -> bool відбирає людей. Кожна людина на обліку - одиниця на день."""
        Sheet = self.env["ua.timesheet.sheet"]
        sheet = Sheet._ua_ensure_for(self.company_id, start.year, start.month)
        frame = self.env["ua.headcount.report"]._ua_frame(sheet)
        lines = sheet.line_ids.filtered(lambda l: staff_filter(l.employee_id))
        mil = self._mil_days(lines.employee_id, frame["d1"], frame["d2"])
        person_days, hours, on_books, last_codes = 0, 0.0, 0, {}
        for line in lines:
            cells = line._day_cells(frame["days"])
            served = mil.get(line.employee_id, set())
            for index in range(frame["days"]):
                source = frame["source"][index]
                code = cells[source]
                if code in NOT_ON_BOOKS or code in OUT_OF_AVERAGE:
                    continue
                if frame["d1"] + timedelta(days=source) in served:
                    continue
                person_days += 1
            hours += line.hours
            last = cells[-1]
            if last not in NOT_ON_BOOKS:
                on_books += 1
                last_codes[line.employee_id] = last
        return person_days / frame["days"], hours, on_books, last_codes, sheet

    def _average(self, values):
        return int(float_round(sum(values) / (len(values) or 1), 0, rounding_method="HALF-UP"))

    # ---- рух кадрів -----------------------------------------------------------------------
    def _moves(self):
        """(прийнято, звільнено, через зміни в організації, через плинність) штатних за період."""
        Headcount = self.env["ua.headcount.report"]
        employees = self.env["hr.employee"].sudo().with_context(active_test=False).search(
            [("company_id", "=", self.company_id.id)])
        hired = dismissed = organisation = turnover = 0
        for employee in employees.filtered(self._is_staff):
            came, left = Headcount._ua_moves(employee, self.date_from, self.date_to)
            hired += came
            dismissed += left
            if not left:
                continue
            ended = employee.version_ids.filtered(
                lambda v: v.contract_date_end and self.date_from <= v.contract_date_end <= self.date_to)
            basis = next((v.ua_dismissal_basis for v in ended if v.ua_dismissal_basis), "")
            article, point = _basis_article(basis)
            if (article, point) == ("40", "1"):
                organisation += left
            elif (article, point) in TURNOVER or (article, None) in TURNOVER:
                turnover += left
        return hired, dismissed, organisation, turnover

    # ---- розрахунок ------------------------------------------------------------------------
    def action_compute(self):
        for rep in self:
            if rep.state != "draft":
                raise UserError(_("Затверджений звіт не перераховують: поверніть його в чернетку."))
            values = rep._compute_month() if rep.kind == "month" else rep._compute_quarter()
            values["computed_at"] = fields.Datetime.now()
            rep.write(values)
        return True

    def _compute_month(self):
        self.ensure_one()
        start = self.date_from
        slips = self._slips(self.date_from, self.date_to)
        served = self._mil_days(slips.employee_id, self.date_from, self.date_to)
        all_fund = staff_fund = pdfo = 0.0
        for slip in slips:
            employee = slip.employee_id
            if self._kind(employee) == "fop":
                continue
            parts = self._slip_parts(slip)
            fund = self._fund(parts)
            paid = fund + parts.get("civil", 0.0)
            all_fund += paid
            if parts["gross"] > 0 and paid:
                pdfo += parts["pdfo"] * min(paid / parts["gross"], 1.0)
            if self._is_staff(employee) and employee not in served:
                staff_fund += fund
        average, hours, _on_books, _codes, _sheet = self._timesheet_month(start, self._is_staff)
        return {
            "r1020": _thousands(all_fund), "r1030": _thousands(pdfo),
            "r1040": int(float_round(average, 0, rounding_method="HALF-UP")),
            "r1060": int(float_round(hours, 0, rounding_method="HALF-UP")),
            "r1070": _thousands(staff_fund),
        }

    def _compute_quarter(self):
        self.ensure_one()
        vals = {}
        hired, dismissed, organisation, turnover = self._moves()
        vals.update(r3020=hired, r3040=dismissed, r3050=organisation, r3060=turnover)

        staff_avg, women_avg, women_hours, on_books_end, last_codes = [], [], 0.0, 0, {}
        external_counts, civil_counts = [], []
        for start in self._month_starts():
            average, _hours, on_books, codes, _sheet = self._timesheet_month(start, self._is_staff)
            staff_avg.append(average)
            w_average, w_hours, _w, _c, _s = self._timesheet_month(
                start, lambda e: self._is_staff(e) and e.sudo().sex == "female")
            women_avg.append(w_average)
            women_hours += w_hours
            on_books_end, last_codes = on_books, codes
            end = start + relativedelta(months=1, days=-1)
            month_slips = self._slips(start, end)
            external_counts.append(len(month_slips.employee_id.filtered(self._is_external)))
            civil_counts.append(len(month_slips.employee_id.filtered(
                lambda e: self._kind(e) in ("gph", "gig"))))
        vals["r3070"] = on_books_end
        if self._is_year_end():
            staff_end = self.env["hr.employee"].browse([e.id for e in last_codes])
            vals["r3080"] = len(staff_end.filtered(lambda e: float(e.sudo().ua_fte or "1") < 1))
            vals["r3090"] = sum(1 for code in last_codes.values() if code == "ВП")
            vals["r3100"] = sum(1 for code in last_codes.values() if code == "ДД")
            previous = self.search([("company_id", "=", self.company_id.id), ("kind", "=", "quarter"),
                                    ("period", "=", 4), ("year", "=", self.year - 1)], limit=1)
            if previous and not any((self.r8010, self.r8020, self.r8030, self.r8040)):
                vals.update(r8010=previous.r8010, r8020=previous.r8020, r8030=previous.r8030, r8040=previous.r8040)
        else:
            vals.update(r3080=0, r3090=0, r3100=0)

        slips = self._slips(self.date_from, self.date_to)
        served = self._mil_days(slips.employee_id, self.date_from, self.date_to)
        sums = {cls: 0.0 for cls in FUND}
        unworked = women_fund = external_fund = civil_fund = 0.0
        for slip in slips:
            employee = slip.employee_id
            parts = self._slip_parts(slip)
            if self._is_staff(employee) and employee not in served:
                for cls in FUND:
                    sums[cls] += parts.get(cls, 0.0)
                unworked += parts["unworked"]
                if employee.sudo().sex == "female":
                    women_fund += self._fund(parts)
            elif self._is_external(employee):
                external_fund += self._fund(parts)
            if self._kind(employee) in ("gph", "gig"):
                civil_fund += parts.get("civil", 0.0)
        basic = sums["basic"]
        additional = sum(sums[cls] for cls in ADDITIONAL)
        incentive = sum(sums[cls] for cls in INCENTIVE)
        r5020, r5030, r5060 = _thousands(basic), _thousands(additional), _thousands(incentive)
        vals.update(
            r5020=r5020, r5030=r5030, r5060=r5060, r5010=float_round(r5020 + r5030 + r5060, 1),
            r5040=_thousands(sums["allowance"]), r5050=_thousands(sums["bonus"]),
            r5051=_thousands(sums["index"]), r5052=_thousands(sums["late"]),
            r5070=_thousands(sums["aid"]), r5080=_thousands(sums["social"]), r5090=_thousands(unworked),
            r7010_1=self._average(women_avg), r7010_2=_thousands(women_fund),
            r7010_3=int(float_round(women_hours, 0, rounding_method="HALF-UP")),
            r7030_1=self._average(external_counts), r7030_2=_thousands(external_fund),
            r7040_1=self._average(civil_counts), r7040_2=_thousands(civil_fund),
        )
        return vals

    # ---- перевірки -------------------------------------------------------------------------
    def _previous(self):
        self.ensure_one()
        if self.kind == "month":
            year, period = (self.year, self.period - 1) if self.period > 1 else (self.year - 1, 12)
        else:
            year, period = (self.year, self.period - 1) if self.period > 1 else (self.year - 1, 4)
        return self.search([("company_id", "=", self.company_id.id), ("kind", "=", self.kind),
                            ("year", "=", year), ("period", "=", period)], limit=1)

    def _checks(self):
        self.ensure_one()
        out = []
        if not self.computed_at:
            return [self._check_warn("Звіт ще не пораховано: натисніть «Порахувати».")]
        unposted = self._slips(self.date_from, self.date_to, states=("draft", "verify"))
        if unposted:
            out.append(self._check_warn("Є непроведені листки періоду: їх у звіті немає.", len(unposted),
                                        self._target_records(unposted)))
        sheets = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company_id.id), ("department_id", "=", False),
            ("year", "=", self.year), ("month", "in", [d.month for d in self._month_starts()]),
            ("state", "!=", "confirmed")])
        if sheets:
            out.append(self._check_warn("Табель періоду не затверджено: середньооблікова і години можуть змінитися.",
                                        len(sheets), self._target_records(sheets)))
        if self.kind == "month":
            if self.r1070 > self.r1020:
                out.append(self._check_error("Фонд штатних (1070) більший за фонд усіх працівників (1020)."))
            if self.r1020 and self.r1030 > float_round(self.r1020 * 0.18, 1) + 0.1:
                out.append(self._check_error("ПДФО (1030) більший за 18 % фонду (1020).",
                                             "%.1f з %.1f" % (self.r1030, self.r1020)))
            previous = self._previous()
            if previous and previous.r1040:
                change = abs(self.r1040 - previous.r1040) / previous.r1040
                if change >= 0.25 and not self.note:
                    out.append(self._check_warn("Середньооблікова змінилась на 25 % і більше: потрібне пояснення.",
                                                "%d -> %d" % (previous.r1040, self.r1040)))
            if previous and previous.r1040 and self.r1040:
                before = previous.r1070 / previous.r1040
                now = self.r1070 / self.r1040
                if before and abs(now - before) / before >= 0.10 and not self.note:
                    out.append(self._check_warn("Середня зарплата змінилась на 10 % і більше: потрібне пояснення.",
                                                "%.0f -> %.0f грн" % (before * 1000, now * 1000)))
        else:
            if self.r3050 + self.r3060 > self.r3040:
                out.append(self._check_error("Звільнених з причин (3050 + 3060) більше, ніж усього (3040)."))
            if abs(self.r5010 - (self.r5020 + self.r5030 + self.r5060)) > 0.05:
                out.append(self._check_error("5010 не дорівнює 5020 + 5030 + 5060."))
            parts = self.r5040 + self.r5050 + self.r5051 + self.r5052
            if parts > self.r5030 + 0.05:
                out.append(self._check_error("Підрядки 5040-5052 більші за додаткову зарплату (5030)."))
            months = self.search([("company_id", "=", self.company_id.id), ("kind", "=", "month"),
                                  ("year", "=", self.year),
                                  ("period", "in", [d.month for d in self._month_starts()])])
            if len(months) == 3 and self.r5010 + 0.05 < sum(months.mapped("r1070")):
                out.append(self._check_warn("Фонд за квартал (5010) менший за суму місячних 1070.",
                                            "%.1f < %.1f" % (self.r5010, sum(months.mapped("r1070")))))
            if self._is_year_end() and self.r8010 and not (self.r8020 and self.r8030):
                out.append(self._check_error("Є колективний договір (8010), але не заповнено 8020 або 8030."))
        if not out:
            out.append(self._check_ok("Перевірки пройдено."))
        return out

    # ---- дії ---------------------------------------------------------------------------------
    def action_done(self):
        for rep in self:
            if not rep.computed_at:
                raise UserError(_("Спершу порахуйте звіт."))
        self.write({"state": "done"})
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_labour_stat.action_report_ua_labour").report_action(self)

    def ua_number(self, value, digits=1):
        return ("{:,.%df}" % digits).format(value or 0.0).replace(",", " ").replace(".", ",")
