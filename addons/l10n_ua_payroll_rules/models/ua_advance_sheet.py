"""Авансова відомість: документ з рядками замість прямого запису в листки.

Майстер `ua.payroll.advance.wizard` лише створює документ і викликає `action_refill`.
Логіка розрахунку (частка відпрацьованих днів 1-15) жила у майстрі, тепер тут.
"""
import calendar
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class UaAdvanceSheet(models.Model):
    _name = "ua.advance.sheet"
    _description = "Авансова відомість"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _order = "year desc, month desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True, tracking=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("Рік", required=True, default=lambda s: date.today().year, tracking=True)
    month = fields.Integer("Місяць", required=True, default=lambda s: date.today().month, tracking=True)
    percent = fields.Float("Відсоток окладу", default=50.0, required=True)
    pay_date = fields.Date("Дата виплати")
    state = fields.Selection([("draft", "Чернетка"), ("confirmed", "Затверджено")], "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.advance.line", "sheet_id", string="Рядки")
    total = fields.Monetary("Разом", compute="_compute_total", store=True)

    @api.depends("year", "month")
    def _compute_name(self):
        for doc in self:
            doc.name = f"Аванс {doc.month:02d}.{doc.year}"

    @api.depends("line_ids.amount")
    def _compute_total(self):
        for doc in self:
            doc.total = sum(doc.line_ids.mapped("amount"))

    @staticmethod
    def _workdays(a, b):
        """Робочі дні (пн-пт) у проміжку [a, b]; під час воєнного стану святкових днів немає."""
        return sum(1 for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5) if b >= a else 0

    def _first_half_ratio(self, slip, h1, h2):
        """Частка відпрацьованих робочих днів [h1, h2] за графіком (запасний варіант, коли табеля місяця немає)."""
        v = slip.contract_id.sudo()
        a = max(h1, v.contract_date_start) if v.contract_date_start else h1
        b = min(h2, v.contract_date_end) if v.contract_date_end else h2
        total = self._workdays(h1, h2)
        worked = self._workdays(a, b)
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "=", slip.employee_id.id), ("state", "=", "validate"),
            ("date_from", "<=", fields.Datetime.to_datetime(h2) + timedelta(days=1)), ("date_to", ">=", fields.Datetime.to_datetime(h1)),
        ])
        for lv in leaves:
            la = max(a, lv.date_from.date()); lb = min(b, lv.date_to.date())
            worked -= self._workdays(la, lb)
        return max(worked, 0) / total if total else 0.0

    @staticmethod
    def _ts_days_to_date(ts_line, h1, h2):
        """Дні з кодом «Р» у табелі, у межах [h1, h2] (обидва в тому самому місяці, що й табель)."""
        cells = ts_line._day_cells(h2.day)
        return sum(1 for i in range(h1.day, h2.day + 1) if cells[i - 1] == "Р")

    @api.model
    def ua_compose(self, company, year=None, month=None, **params):
        """Нова авансова відомість місяця, одразу порахована."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        doc = self.create({"company_id": company.id, "year": int(year), "month": int(month)})
        doc.action_refill()
        return doc

    def action_compose_month(self):
        """Кнопка списку «Створити за місяць»: відомість поточного місяця, одразу порахована."""
        today = fields.Date.context_today(self)
        doc = self.ua_compose(self.env.company, today.year, today.month)
        return {"type": "ir.actions.act_window", "name": doc.name, "res_model": "ua.advance.sheet",
                "view_mode": "form", "res_id": doc.id, "target": "current"}

    def action_refill(self):
        """Видалити рядки і заповнити знову з чернеток листків місяця. Лише для чернетки документа.

        Джерело факту - затверджений табель місяця, якщо він є (ua.timesheet.sheet); інакше
        запасний варіант - робочі дні за графіком і відпустки, як раніше. Формули (ст. 115 КЗпП,
        аванс не менший за оплату фактично відпрацьованого часу; ст. 108 КЗпП, надбавка за нічні):
        оклад -> оклад × ставка × (дні факту до дня авансу / норма днів), не більше percent % окладу;
        погодинна -> ставка/год × факт годин до дня авансу; нічні години обох видів - +20 % ставки/год."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку відомості.")
            doc.line_ids.unlink()
            d1 = date(doc.year, doc.month, 1)
            last_day = calendar.monthrange(doc.year, doc.month)[1]
            d2 = date(doc.year, doc.month, last_day)
            terms = doc.company_id._ua_pay_terms()
            cutoff_day = min(max(terms["advance_day"] - 1, 1), last_day)
            h1, h2 = d1, date(doc.year, doc.month, cutoff_day)
            slips = self.env["hr.payslip"].search([
                ("company_id", "=", doc.company_id.id), ("state", "in", ("draft", "verify")),
                ("date_from", ">=", d1), ("date_to", "<=", d2),
            ])
            ts_sheet = self.env["ua.timesheet.sheet"].sudo().search([
                ("company_id", "=", doc.company_id.id), ("year", "=", doc.year), ("month", "=", doc.month),
                ("state", "=", "confirmed"),
            ], limit=1)
            ts_lines = {l.employee_id.id: l for l in ts_sheet.line_ids} if ts_sheet else {}
            lines = []
            for slip in slips:
                emp = slip.employee_id.sudo()
                if (emp.ua_contract_kind or "employment") != "employment":
                    continue
                contract = slip.contract_id.sudo()
                pay_type = contract.ua_pay_type or "monthly"
                wage = contract.wage or 0.0
                fte = float(emp.ua_fte or "1")
                ts_line = ts_lines.get(emp.id)
                night_amount = 0.0
                if pay_type == "hourly":
                    hour_rate = contract.ua_hour_rate or 0.0
                    if ts_line and ts_line.days_worked:
                        days_to_date = doc._ts_days_to_date(ts_line, h1, h2)
                        day_share = days_to_date / ts_line.days_worked
                    else:
                        day_share = doc._first_half_ratio(slip, h1, h2)
                    fact_hours = round((ts_line.hours if ts_line else 0.0) * day_share, 2)
                    night_hours = round((ts_line.night_hours if ts_line else 0.0) * day_share, 2)
                    ratio = day_share
                    amount = round(hour_rate * fact_hours, 2)
                    night_amount = round(hour_rate * night_hours * 0.20, 2)
                else:
                    if ts_line and ts_line.norm_days:
                        days_to_date = doc._ts_days_to_date(ts_line, h1, h2)
                        ratio = days_to_date / ts_line.norm_days
                        day_share = days_to_date / ts_line.days_worked if ts_line.days_worked else 0.0
                        night_hours = round((ts_line.night_hours or 0.0) * day_share, 2)
                        hour_rate = (wage / ts_line.norm_hours) if ts_line.norm_hours else 0.0
                        night_amount = round(hour_rate * night_hours * 0.20, 2)
                    else:
                        ratio = doc._first_half_ratio(slip, h1, h2)
                    amount = round(wage * fte * ratio, 2)
                    cap = round(wage * fte * doc.percent / 100.0, 2)
                    amount = min(amount, cap)
                amount = round(amount + night_amount, 2)
                if not amount:
                    continue
                lines.append((0, 0, {
                    "employee_id": emp.id, "payslip_id": slip.id,
                    "wage": wage, "fte": fte, "ratio": ratio, "amount": amount,
                }))
            doc.line_ids = lines
        return True

    def _check_slips_confirmable(self):
        """Перед записом входу ADVANCE листок має бути ще чернеткою (як його відібрав action_refill)."""
        for doc in self:
            for line in doc.line_ids:
                if line.payslip_id.state not in ("draft", "verify"):
                    raise UserError(f"Листок «{line.employee_id.name}» уже не чернетка. Дію скасовано.")

    def _check_slips_resettable(self):
        """compute_sheet() завжди переводить листок у 'verify' - це очікувано.
        Прибрати вхід можна, доки листок не проведений остаточно (не 'done'/'cancel')."""
        for doc in self:
            for line in doc.line_ids:
                if line.payslip_id.state not in ("draft", "verify"):
                    raise UserError(f"Листок «{line.employee_id.name}» уже проведений. Дію скасовано.")

    def action_confirm(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError("Уже затверджено.")
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
        self._check_slips_confirmable()
        Input = self.env["hr.payslip.input"]
        for doc in self:
            for line in doc.line_ids:
                slip = line.payslip_id
                inp = slip.input_line_ids.filtered(lambda l: l.code == "ADVANCE")[:1]
                if inp:
                    inp.amount = line.amount
                else:
                    Input.create({"payslip_id": slip.id, "code": "ADVANCE", "name": "Аванс (виплачено)",
                                  "amount": line.amount, "contract_id": slip.contract_id.id, "sequence": 5})
                slip.compute_sheet()
            doc.state = "confirmed"
        return True

    def action_draft(self):
        for doc in self:
            if doc.state != "confirmed":
                raise UserError("Документ не затверджений.")
        self._check_slips_resettable()
        for doc in self:
            for line in doc.line_ids:
                slip = line.payslip_id
                slip.input_line_ids.filtered(lambda l: l.code == "ADVANCE").unlink()
                slip.compute_sheet()
            doc.state = "draft"
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку відомості.")

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        if not self.line_ids:
            out.append(self._check_error("Немає рядків авансу", target=self._target_record(self)))
            return out
        if not (0 < self.percent <= 100):
            out.append(self._check_warn("Відсоток окладу поза межами 0-100", fact="%.1f%%" % self.percent))
        else:
            out.append(self._check_ok("Відсоток окладу", fact="%.1f%%" % self.percent))
        bad_ratio = self.line_ids.filtered(lambda l: l.ratio < 0 or l.ratio > 1)
        if bad_ratio:
            out.append(self._check_error(
                "Частка відпрацьованих днів (1-15) поза межами 0-1", fact=len(bad_ratio),
                target=self._target_records(bad_ratio, "ua.advance.line")))
        zero_worked = self.line_ids.filtered(lambda l: l.ratio == 0 and l.amount)
        if zero_worked:
            out.append(self._check_warn(
                "Сума нарахована при нульовій частці відпрацьованих днів", fact=len(zero_worked),
                target=self._target_records(zero_worked, "ua.advance.line")))
        if self.state == "draft":
            broken = self.line_ids.filtered(lambda l: l.payslip_id.state not in ("draft", "verify"))
            if broken:
                out.append(self._check_error(
                    "Листок уже проведений, а рядок авансу лишився в чернетці", fact=len(broken),
                    target=self._target_records(broken.mapped("payslip_id"), "hr.payslip")))
        out.append(self._check_ok("Рядків у відомості", fact=len(self.line_ids),
                                  target=self._target_records(self.line_ids, "ua.advance.line")))
        out.append(self._check_ok("Стан документа", fact=dict(self._fields["state"].selection).get(self.state, self.state)))
        return out


class UaAdvanceLine(models.Model):
    _name = "ua.advance.line"
    _description = "Рядок авансової відомості"
    _order = "id"

    sheet_id = fields.Many2one("ua.advance.sheet", "Відомість", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="sheet_id.company_id")
    currency_id = fields.Many2one(related="sheet_id.currency_id")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True)
    payslip_id = fields.Many2one("hr.payslip", "Листок", required=True, ondelete="cascade")
    wage = fields.Monetary("Оклад")
    fte = fields.Float("Ставка")
    ratio = fields.Float("Частка відпрацьованих днів 1-15")
    amount = fields.Monetary("Сума авансу")
    note = fields.Char("Примітка")
