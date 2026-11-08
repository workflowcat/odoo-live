# -*- coding: utf-8 -*-
"""Середньооблікова кількість штатних працівників (Інструкція зі статистики кількості працівників,
наказ Держкомстату № 286).

Місяць береться з табеля П-5 компанії (без підрозділу):
- день, у який працівник на обліку, - код у табелі не «-»; у вихідний (субота, неділя) - коди
  попереднього робочого дня місяця (облікова кількість за вихідний дорівнює попередньому робочому
  дню); якщо місяць починається з вихідних - коди самого дня;
- працівника з кодом зі списку виключень (типово ВП - відпустка у зв'язку з вагітністю та пологами,
  ДД - відпустка для догляду за дитиною) у цей день не рахують;
- працівники на неповній ставці - пропорційно часу: відпрацьовані години / 8 / робочі дні місяця;
- середньооблікова за місяць - сума людино-днів / календарні дні + еквівалент неповного часу.
Квартал, рік чи інший період - сума місячних, поділена на кількість місяців періоду (і тоді, коли
компанія працювала не весь період). Правила і коди - перевіряйте чинну редакцію інструкції.
"""
import calendar
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

STATES = [("draft", "Чернетка"), ("done", "Затверджено")]
FULL_DAY_HOURS = 8.0  # як у табелі: година повної ставки на день
NOT_ON_BOOKS = ("", "-")


def _quarter_start(today):
    return date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)


class UaHeadcountReport(models.Model):
    _name = "ua.headcount.report"
    _description = "Середньооблікова кількість штатних працівників"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    date_from = fields.Date("Перший місяць", required=True, tracking=True,
                            default=lambda s: _quarter_start(fields.Date.context_today(s)))
    date_to = fields.Date("Останній місяць", required=True, tracking=True,
                          default=lambda s: _quarter_start(fields.Date.context_today(s))
                          + relativedelta(months=3, days=-1))
    excluded_codes = fields.Char(
        "Коди табеля поза середньообліковою", default="ВП,ДД", required=True,
        help="Через кому. Типово ВП (відпустка у зв'язку з вагітністю та пологами) і ДД (відпустка для "
             "догляду за дитиною): такі працівники є в обліковій кількості, але не в середньообліковій. "
             "Перевіряйте чинну редакцію інструкції.")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    month_ids = fields.One2many("ua.headcount.month", "report_id", "Місяці")
    months = fields.Integer("Місяців у періоді", compute="_compute_months")
    average = fields.Float("Середньооблікова за період", digits=(16, 2), readonly=True)
    average_int = fields.Integer("Середньооблікова за період, цілих", readonly=True)
    on_books_end = fields.Integer("Облікова на кінець періоду", readonly=True)
    hired = fields.Integer("Прийнято за період", readonly=True)
    dismissed = fields.Integer("Звільнено за період", readonly=True)
    hours = fields.Float("Відпрацьовано людино-годин", readonly=True)
    check_text = fields.Text("Зауваження", readonly=True)
    computed_at = fields.Datetime("Розраховано", readonly=True)

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for rep in self:
            if rep.date_from and rep.date_to:
                rep.name = "Середньооблікова %s - %s" % (rep.date_from.strftime("%m.%Y"), rep.date_to.strftime("%m.%Y"))
            else:
                rep.name = "Середньооблікова"

    @api.depends("date_from", "date_to")
    def _compute_months(self):
        for rep in self:
            rep.months = len(rep._ua_month_starts()) if rep.date_from and rep.date_to else 0

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rep in self:
            if rep.date_from.day != 1:
                raise ValidationError(_("Період починається з першого дня місяця."))
            if rep.date_to.day != calendar.monthrange(rep.date_to.year, rep.date_to.month)[1]:
                raise ValidationError(_("Період закінчується останнім днем місяця."))
            if rep.date_from > rep.date_to:
                raise ValidationError(_("Початок періоду пізніше за кінець."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(rep.state != "draft" for rep in self):
            raise UserError(_("Видалити можна лише чернетку."))

    def _ua_month_starts(self):
        self.ensure_one()
        starts, day = [], self.date_from
        while day <= self.date_to:
            starts.append(day)
            day += relativedelta(months=1)
        return starts

    def _ua_excluded(self):
        return {code.strip() for code in (self.excluded_codes or "").split(",") if code.strip()}

    # ------------------------------------------------------------------ розрахунок
    def action_compute(self):
        Sheet = self.env["ua.timesheet.sheet"]
        for rep in self:
            if rep.state == "done":
                raise UserError(_("Затверджений звіт не перераховують: поверніть його в чернетку."))
            rep.month_ids.unlink()
            excluded = rep._ua_excluded()
            values, notes = [], []
            for start in rep._ua_month_starts():
                sheet = Sheet._ua_ensure_for(rep.company_id, start.year, start.month)
                if sheet.state != "confirmed":
                    notes.append(_("Табель %(month)s не затверджено: числа можуть змінитися.")
                                 % {"month": start.strftime("%m.%Y")})
                values.append(dict(rep._ua_month_values(sheet, excluded), report_id=rep.id,
                                   month_start=start, timesheet_id=sheet.id))
            months = self.env["ua.headcount.month"].create(values)
            total = sum(months.mapped("average"))
            count = len(months) or 1
            rep.write({
                "average": float_round(total / count, 2),
                "average_int": int(float_round(total / count, 0, rounding_method="HALF-UP")),
                "on_books_end": months[-1:].on_books_end,
                "hired": sum(months.mapped("hired")),
                "dismissed": sum(months.mapped("dismissed")),
                "hours": sum(months.mapped("hours")),
                "check_text": "\n".join(notes) or False,
                "computed_at": fields.Datetime.now(),
            })
        return True

    def _ua_month_values(self, sheet, excluded):
        """Числа одного місяця з рядків табеля."""
        d1, d2 = sheet._period()
        days = d2.day
        source, last_working = [], None
        for i in range(days):
            weekend = (d1 + timedelta(days=i)).weekday() >= 5
            if not weekend:
                last_working = i
            source.append(last_working if weekend and last_working is not None else i)
        working_days = sum(1 for i in range(days) if (d1 + timedelta(days=i)).weekday() < 5)

        person_days = part_hours = 0.0
        on_books_end = excluded_end = part_count = hired = dismissed = 0
        for line in sheet.line_ids:
            employee = line.employee_id.sudo()
            cells = line._day_cells(days)
            if cells[-1] not in NOT_ON_BOOKS:
                on_books_end += 1
                excluded_end += cells[-1] in excluded
            if float(employee.ua_fte or "1") < 1:
                part_count += 1
                part_hours += line.hours
            else:
                person_days += sum(1 for i in range(days)
                                   if cells[source[i]] not in NOT_ON_BOOKS and cells[source[i]] not in excluded)
            came, left = self._ua_moves(employee, d1, d2)
            hired += came
            dismissed += left
        part_equiv = part_hours / FULL_DAY_HOURS / working_days if working_days else 0.0
        average = person_days / days + part_equiv
        return {
            "days": days, "working_days": working_days, "person_days": person_days,
            "full_average": float_round(person_days / days, 2), "part_count": part_count,
            "part_hours": part_hours, "part_equiv": float_round(part_equiv, 2),
            "average": float_round(average, 2),
            "average_int": int(float_round(average, 0, rounding_method="HALF-UP")),
            "on_books_end": on_books_end, "excluded_end": excluded_end,
            "hired": hired, "dismissed": dismissed, "hours": sum(sheet.line_ids.mapped("hours")),
        }

    @api.model
    def _ua_moves(self, employee, d1, d2):
        """Прийнятий і звільнений у місяці: початок трудового договору без договору напередодні,
        кінець - без договору наступного дня (переведення між версіями не рахується)."""
        periods = [(v.contract_date_start, v.contract_date_end or date.max)
                   for v in employee.version_ids if v.contract_date_start]

        def covered(day):
            return any(a <= day <= b for a, b in periods)

        came = sum(1 for a, _b in periods if d1 <= a <= d2 and not covered(a - timedelta(days=1)))
        left = sum(1 for _a, b in periods if d1 <= b <= d2 and not covered(b + timedelta(days=1)))
        return came, left

    def action_done(self):
        for rep in self:
            if not rep.month_ids:
                raise UserError(_("Спершу розрахуйте звіт."))
            rep.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_headcount.action_report_ua_headcount").report_action(self)

    def ua_number(self, value, digits=2):
        """Число для друку: дві цифри після коми, кома як роздільник."""
        self.ensure_one()
        return ("{:.%df}" % digits).format(value or 0.0).replace(".", ",")


class UaHeadcountMonth(models.Model):
    _name = "ua.headcount.month"
    _description = "Середньооблікова кількість за місяць"
    _order = "month_start, id"

    report_id = fields.Many2one("ua.headcount.report", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="report_id.company_id", store=True)
    month_start = fields.Date("Місяць", required=True)
    timesheet_id = fields.Many2one("ua.timesheet.sheet", "Табель", readonly=True)
    days = fields.Integer("Календарних днів")
    working_days = fields.Integer("Робочих днів")
    person_days = fields.Float("Людино-днів повної ставки")
    full_average = fields.Float("Повна ставка, середня", digits=(16, 2))
    part_count = fields.Integer("Працівників на неповній ставці")
    part_hours = fields.Float("Годин неповної ставки")
    part_equiv = fields.Float("Неповна ставка в перерахунку", digits=(16, 2))
    average = fields.Float("Середньооблікова", digits=(16, 2))
    average_int = fields.Integer("Середньооблікова, цілих")
    on_books_end = fields.Integer("Облікова на кінець місяця")
    excluded_end = fields.Integer("З них поза середньообліковою")
    hired = fields.Integer("Прийнято")
    dismissed = fields.Integer("Звільнено")
    hours = fields.Float("Відпрацьовано людино-годин")
