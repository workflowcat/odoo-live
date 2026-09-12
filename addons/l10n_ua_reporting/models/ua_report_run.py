"""Робоче місце звітності: один прогін (ua.report.run) на звіт+період, з перевірками (ua.report.check)
перед формуванням. Формування файлів не дублює логіку - викликає наявні майстри/документи модулів
l10n_ua_payroll_reports і l10n_ua_hr_docs / l10n_ua_hr_orders і забирає в себе готові вкладення."""
import base64
import calendar
import re
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from odoo.addons.l10n_ua_dashboard.models.ua_dashboard import MONTHS_UA

REPORTS = [
    ("j05", "Об'єднана звітність (J0500111 + Д1 + 4ДФ + Д5)"),
    ("j30", "Повідомлення про прийняття (J3001005)"),
    ("pfu", "Заява-розрахунок ПФУ"),
    ("trial", "Оборотно-сальдова відомість"),
    ("ledger", "Головна книга"),
    ("timesheet", "Табель П-5"),
    ("staff", "Штатний розпис"),
    ("orders", "Журнал реєстрації наказів"),
]
PERIOD_TYPE = {"j05": "month", "j30": "month", "pfu": "month", "timesheet": "month", "staff": "date", "orders": "year",
               "trial": "month", "ledger": "month"}
# ключові рахунки зарплати для звірки з листками: код рахунку -> (назва, код правила листка, бік)
PAYROLL_ACCOUNTS = [("661", "Розрахунки за заробітною платою", ("GROSS", "MAT"), "credit", "no_fop"),
                    ("6411", "ПДФО", ("PDFO",), "credit", "all"),
                    ("6415", "Військовий збір", ("VZ",), "credit", "all"),
                    ("651", "ЄСВ", ("ESV",), "credit", "all"),
                    ("6851", "Розрахунки з іншими кредиторами (ФОП, аліменти)", ("FOP", "ALIM"), "credit", "all")]
STATES = [("draft", "Чернетка"), ("checked", "Перевірено"), ("generated", "Сформовано"), ("submitted", "Подано")]
APPENDIX_LABELS = {"001": "Основна декларація (J0500111)", "101": "Додаток 1 (Д1)", "104": "Додаток 4ДФ", "105": "Додаток 5 (Д5)"}
ROWNUM_RE = re.compile(rb'ROWNUM="(\d+)"')
# Допуск для звірки сум, зібраних із незалежно округлених рядків (Д1/4ДФ/ПФУ): той самий поріг
# (0,05), що ua_report_wizard.py вже використовує для власного коригування округлення ЄСВ (G20) -
# рядки Д1 за вагітність/пологи розбиваються на місячні сегменти, кожен окремо r2(), і сума часток
# може відрізнятися від суми листка на 1-2 копійки навіть без жодної помилки в даних.
AMOUNT_TOLERANCE = 0.05


def _period_key_value(report_code, year, quarter, month, date_):
    if report_code == "j05" and not month and quarter:
        return "%s-Q%s" % (year, quarter)          # старі квартальні прогони лишаються як є
    if report_code in ("j05", "j30", "pfu", "timesheet", "trial", "ledger"):
        return "%s-%02d" % (year, month or 0)
    if report_code == "staff":
        return "%s-%s" % (year, date_.isoformat() if date_ else "")
    return str(year)          # orders: рік


class UaReportRun(models.Model):
    _name = "ua.report.run"
    _inherit = ["mail.thread"]
    _description = "Звітний прогін"
    _order = "year desc, quarter desc, month desc, date desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    report_code = fields.Selection(REPORTS, "Звіт", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", required=True, default=lambda s: date.today().year)
    quarter = fields.Integer("Квартал")
    month = fields.Integer("Місяць")
    date = fields.Date("Дата")
    period_key = fields.Char(compute="_compute_period_key", store=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True, copy=False)
    check_ids = fields.One2many("ua.report.check", "run_id", "Перевірки")
    attachment_ids = fields.Many2many("ir.attachment", "ua_report_run_attachment_rel", "run_id", "attachment_id", string="Файли")
    receipt_ids = fields.Many2many("ir.attachment", "ua_report_run_receipt_rel", "run_id", "attachment_id", string="Квитанції")
    doc_kind = fields.Selection(
        [("HZ", "Звітний"), ("HZN", "Звітний новий"), ("HZU", "Уточнюючий")],
        "Тип розрахунку", default="HZ", required=True, tracking=True,
        help="Звітний новий подають до кінця строку, уточнюючий - після. В обох випадках у додатках "
             "лишаються тільки змінені рядки: старий з ознакою 1, новий з ознакою 0.")
    base_run_id = fields.Many2one("ua.report.run", "Виправляє прогін", readonly=True, copy=False)
    correction_no = fields.Integer("Номер коригування", default=0, readonly=True, copy=False)
    correction_ids = fields.One2many("ua.report.run", "base_run_id", "Коригування")
    submitted_date = fields.Date("Дата подання", readonly=True, copy=False)
    submitted_by = fields.Many2one("res.users", "Подав", readonly=True, copy=False)
    note = fields.Text("Примітка")

    _period_uniq = models.Constraint("unique(company_id, report_code, period_key)", "Прогін для цього звіту і періоду вже існує.")

    # ------------------------------------------------------------------ обчислювані поля
    @api.depends("report_code", "year", "quarter", "month", "date", "doc_kind", "correction_no")
    def _compute_period_key(self):
        for run in self:
            key = _period_key_value(run.report_code, run.year, run.quarter, run.month, run.date)
            if run.doc_kind and run.doc_kind != "HZ":
                key = "%s-%s-%s" % (key, run.doc_kind.lower(), run.correction_no or 1)
            run.period_key = key

    @api.depends("report_code", "year", "quarter", "month", "date")
    def _compute_name(self):
        names = dict(REPORTS)
        for run in self:
            base = names.get(run.report_code, "")
            if run.report_code == "j05" and not run.month and run.quarter:
                run.name = _("%(base)s, %(q)s квартал %(y)s") % {"base": base, "q": run.quarter, "y": run.year}
                if run.doc_kind and run.doc_kind != "HZ":
                    label = dict(run._fields["doc_kind"].selection).get(run.doc_kind, "")
                    run.name = "%s (%s %s)" % (run.name, label.lower(), run.correction_no or 1)
            elif run.report_code in ("j30", "pfu", "timesheet", "trial", "ledger") and run.month:
                run.name = "%s, %s %s" % (base, MONTHS_UA.get(run.month, "").capitalize(), run.year)
            elif run.report_code == "staff" and run.date:
                run.name = "%s на %s" % (base, run.date.strftime("%d.%m.%Y"))
            elif run.report_code == "orders":
                run.name = "%s, %s" % (base, run.year)
            else:
                run.name = base

    # ------------------------------------------------------------------ періоди
    def _report_months(self):
        """Місяці періоду прогону.

        Податковий розрахунок подається щомісяця (з липня 2026 року для податкових агентів).
        Старі квартальні прогони читаються як три місяці кварталу."""
        self.ensure_one()
        if self.month:
            return [self.month]
        if self.quarter:
            m1 = (self.quarter - 1) * 3 + 1
            return [m1, m1 + 1, m1 + 2]
        return [self.month or 1]

    def _quarter_months(self):
        return self._report_months()

    def _period_bounds(self):
        """Перший і останній день періоду прогону, залежно від типу звіту."""
        self.ensure_one()
        if self.report_code == "j05":
            months = self._report_months()
            d1 = date(self.year, months[0], 1)
            d2 = date(self.year, months[-1], calendar.monthrange(self.year, months[-1])[1])
        elif self.report_code == "orders":
            d1, d2 = date(self.year, 1, 1), date(self.year, 12, 31)
        elif self.report_code == "staff":
            d1 = d2 = self.date or date(self.year, 1, 1)
        else:
            d1 = date(self.year, self.month, 1)
            d2 = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        return d1, d2

    @api.model
    def _find_or_create(self, report_code, company, year, quarter=None, month=None, date_=None):
        key = _period_key_value(report_code, year, quarter, month, date_)
        run = self.search([("report_code", "=", report_code), ("company_id", "=", company.id), ("period_key", "=", key)], limit=1)
        if run:
            return run
        vals = {"report_code": report_code, "company_id": company.id, "year": year}
        if report_code == "j05":
            vals["month"] = month
            vals["quarter"] = quarter or ((month - 1) // 3 + 1 if month else False)
        elif report_code in ("j30", "pfu", "timesheet", "trial", "ledger"):
            vals["month"] = month
        elif report_code == "staff":
            vals["date"] = date_
        run = self.create(vals)
        run.action_refresh()
        return run

    def _periods_for(self, report_code, company):
        today = fields.Date.context_today(self)
        out = []
        if report_code in ("j05", "j30", "pfu", "timesheet", "trial", "ledger"):
            y, m = today.year, today.month
            for _i in range(6):
                out.append({"key": "%s-%02d" % (y, m), "label": "%s %s" % (MONTHS_UA.get(m, "").capitalize(), y), "year": y, "month": m})
                m -= 1
                if m == 0:
                    m, y = 12, y - 1
        elif report_code == "orders":
            y = today.year
            for _i in range(6):
                out.append({"key": str(y), "label": "%s рік" % y, "year": y})
                y -= 1
        elif report_code == "staff":
            existing = self.env["ua.staff.list"].search([("company_id", "=", company.id)], order="date desc", limit=5).mapped("date")
            dates = sorted(set(existing) | {today}, reverse=True)[:6]
            for d in dates:
                out.append({"key": d.isoformat(), "label": d.strftime("%d.%m.%Y"), "year": d.year, "date": d.isoformat()})
        out.reverse()
        for p in out:
            key = p["key"]
            run = self.search([("report_code", "=", report_code), ("company_id", "=", company.id), ("period_key", "=", key)], limit=1)
            p["run_id"] = run.id if run else False
            p["state"] = run.state if run else False
        return out

    @api.model
    def _history(self, report_code, company):
        if not report_code:
            return []
        runs = self.search([("report_code", "=", report_code), ("company_id", "=", company.id)], order="id desc", limit=10)
        return [{"id": r.id, "name": r.name, "state": r.state, "files": len(r.attachment_ids)} for r in runs]

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, run_id=None, report_code=None, year=None, quarter=None, month=None, date=None):
        company = self.env.company
        today = fields.Date.context_today(self)
        run = self.browse(run_id).exists() if run_id else self.browse()
        if not run:
            report_code = report_code or REPORTS[0][0]
            y = int(year) if year else today.year
            q = int(quarter) if quarter else ((today.month - 1) // 3 + 1)
            m = int(month) if month else today.month
            d_ = fields.Date.to_date(date) if date else today
            run = self._find_or_create(report_code, company, y, quarter=q, month=m, date_=d_)
        reports = [{"code": code, "name": name, "period_type": PERIOD_TYPE[code]} for code, name in REPORTS]
        periods = self._periods_for(run.report_code, company)
        return {
            "reports": reports,
            "periods": periods,
            "run": run._screen_data(),
            "checks": [c._screen_data() for c in run.check_ids],
            "summary": run._summary(),
            "appendices": run._appendices(),
            "history": self._history(run.report_code, company),
        }

    def _screen_data(self):
        self.ensure_one()
        return {
            "id": self.id, "name": self.name, "report_code": self.report_code, "state": self.state,
            "year": self.year, "quarter": self.quarter or False, "month": self.month or False,
            "date": self.date.isoformat() if self.date else False,
            "submitted_date": self.submitted_date.isoformat() if self.submitted_date else False,
            "submitted_by": self.submitted_by.name or "",
            "doc_kind": self.doc_kind,
            "doc_kind_label": dict(self._fields["doc_kind"].selection).get(self.doc_kind, ""),
            "base_run": self.base_run_id.name or "",
            "corrections": [{"id": r.id, "name": r.name, "state": r.state} for r in self.correction_ids],
            "can_correct": self.report_code == "j05" and self.state in ("generated", "submitted"),
            "files": [{"id": a.id, "name": a.name, "mimetype": a.mimetype} for a in self.attachment_ids],
            "receipts": [{"id": a.id, "name": a.name, "mimetype": a.mimetype} for a in self.receipt_ids],
            "note": self.note or "",
        }

    def _appendices(self):
        self.ensure_one()
        if self.report_code != "j05":
            return []
        rows = []
        for att in self.attachment_ids.filtered(lambda a: a.name and a.name.upper().endswith(".XML")):
            sub = next((s for s in APPENDIX_LABELS if ("J05%s" % s) in att.name), None)
            label = APPENDIX_LABELS.get(sub, att.name)
            content = base64.b64decode(att.datas or b"")
            nums = ROWNUM_RE.findall(content)
            row_count = max((int(n) for n in nums), default=0)
            rows.append({"attachment_id": att.id, "name": att.name, "label": label, "rows": row_count, "state": "сформовано"})
        return rows

    # ------------------------------------------------------------------ дії
    def action_refresh(self):
        for run in self:
            run.check_ids.unlink()
            rows = run._build_checks()
            for i, row in enumerate(rows, 1):
                row.setdefault("sequence", i * 10)
            run.check_ids = [(0, 0, row) for row in rows]
            run.state = "draft" if any(r["level"] == "error" for r in rows) else "checked"
        return True

    def action_generate(self):
        for run in self:
            run.action_refresh()
            errors = run.check_ids.filtered(lambda c: c.level == "error")
            if errors:
                raise UserError(_("Є помилки перевірки, які треба виправити:\n%s") % "\n".join(
                    "- %s: %s" % (c.title, c.detail or "") for c in errors))
            method = getattr(run, "_generate_%s" % run.report_code)
            atts = method()
            run.write({"attachment_ids": [(6, 0, atts.ids)], "state": "generated"})
            run.message_post(body=_("Сформовано файлів: %s.") % len(atts))
        return True

    def action_mark_submitted(self):
        for run in self:
            if run.state != "generated":
                raise UserError(_("Позначити поданим можна лише сформований звіт."))
            run.write({"state": "submitted", "submitted_date": fields.Date.context_today(self), "submitted_by": self.env.user.id})
            run.message_post(body=_("Звіт позначено поданим."))
        return True

    def action_reset(self):
        self.write({"state": "draft"})
        return True

    # ------------------------------------------------------------------ перевірки: спільні
    def _build_checks(self):
        self.ensure_one()
        rows = list(self._common_checks())
        method = getattr(self, "_checks_%s" % self.report_code, None)
        if method:
            rows += list(method())
        return rows

    def _common_checks(self):
        self.ensure_one()
        d1, d2 = self._period_bounds()
        c = self.company_id

        draft_slips = self.env["hr.payslip"].search([
            ("company_id", "=", c.id), ("date_from", ">=", d1), ("date_from", "<=", d2), ("state", "in", ("draft", "verify")),
        ])
        yield {
            "code": "period_closed", "title": "Чернетки листків у періоді",
            "level": "ok" if not draft_slips else "warn",
            "detail": "Чернеток немає" if not draft_slips else "Листків-чернеток: %s" % len(draft_slips),
            "value": str(len(draft_slips)),
            "action_model": "hr.payslip" if draft_slips else "", "action_domain": str([("id", "in", draft_slips.ids)]) if draft_slips else "",
        }

        emps = self.env["hr.employee"].search([("company_id", "=", c.id), ("active", "=", True)])
        bad = emps.filtered(lambda e: not (e.sudo().ua_rnokpp and len(e.sudo().ua_rnokpp) == 10 and e.sudo().ua_rnokpp.isdigit()))
        yield {
            "code": "rnokpp", "title": "Усі РНОКПП заповнені і мають 10 цифр",
            "level": "ok" if not bad else "error",
            "detail": "Усі заповнені" if not bad else "Без коректного РНОКПП: %s" % ", ".join(bad.mapped("name")[:5]),
            "value": str(len(bad)),
            "action_model": "hr.employee" if bad else "", "action_domain": str([("id", "in", bad.ids)]) if bad else "",
        }

        missing = []
        if not c.company_registry:
            missing.append("ЄДРПОУ")
        if not c.ua_sti_code:
            missing.append("код ДПІ")
        if not c.ua_director_name:
            missing.append("керівник")
        yield {
            "code": "company_signers", "title": "Компанія має ЄДРПОУ, код ДПІ і підписантів",
            "level": "ok" if not missing else "error",
            "detail": "Заповнено" if not missing else "Немає: %s" % ", ".join(missing),
            "value": "", "action_model": "res.company", "action_domain": str([("id", "=", c.id)]),
        }

    # ------------------------------------------------------------------ перевірки: j05
    def _checks_j05(self):
        self.ensure_one()
        c = self.company_id
        Wizard = self.env["ua.payroll.report.wizard"]
        X = self.env["ua.dps.xml"]
        gross_total = gross_total_d1 = mat_total = esv_total = 0.0
        d1_total = d1_esv_total = fourdf_gross = 0.0
        d5_count = 0
        xml_errors = []
        today = fields.Date.context_today(self)
        for m in self._report_months():
            md1, md2 = date(self.year, m, 1), date(self.year, m, calendar.monthrange(self.year, m)[1])
            slips = self.env["hr.payslip"].search([("company_id", "=", c.id), ("state", "=", "done"), ("date_from", ">=", md1), ("date_to", "<=", md2)])
            lines = slips.mapped("line_ids")
            gross_total += sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total"))
            # виплати поза зарплатою: у 4ДФ окремими ознаками, у Д1 їх немає
            other_codes = ("AID_FREE", "AID_TAX", "GIFT_FREE", "GIFT_TAX", "SEVERANCE", "COMP_TOOL")
            gross_total += sum(lines.filtered(lambda l: l.code in other_codes).mapped("total"))
            # ФОП-підрядники не потрапляють у Д1 (лише в 4ДФ з ознакою 157) - для звірки Д1 їх виключаємо
            non_fop = slips.filtered(lambda s: (s.employee_id.sudo().ua_contract_kind or "employment") != "fop")
            gross_total_d1 += sum(non_fop.mapped("line_ids").filtered(lambda l: l.code == "GROSS").mapped("total"))
            mat_total += sum(lines.filtered(lambda l: l.code == "MAT").mapped("total"))
            esv_total += sum(lines.filtered(lambda l: l.code == "ESV").mapped("total"))
            if not slips:
                continue
            w = Wizard.new({"company_id": c.id, "year": self.year, "month": m, "doc_type": "HZ", "number": 1,
                            "with_d1": True, "with_4df": True, "with_d5": True, "fill_date": today})
            try:
                params = self.env["ua.payroll.param"].get_all(md2, c)
                persons, all_rows = [], []
                for slip in w._payslips():
                    rows, p = w._person_rows(slip, params)
                    all_rows += rows
                    persons.append(p)
                d1_total += sum(r["G16"] for r in all_rows)
                d1_esv_total += sum(r["G20"] for r in all_rows)
                fourdf_gross += sum(p["gross"] + p.get("other_income", 0.0) for p in persons)
                d5_count += len(w._d5_rows())
                if all_rows:
                    _fn, data = X.build(c, "J05", "101", "11", 1, m, self.year, w._build_d1(all_rows), c_doc_cnt=1, c_doc_stan=1, fill_date=today)
                    xml_errors += ["%s (%s): %s" % (MONTHS_UA.get(m, m), "Д1", e) for e in X.validate(data, "J0510111")]
            except Exception as exc:  # noqa: BLE001 - перевірка не має падати, лише повідомляти
                xml_errors.append("%s: %s" % (MONTHS_UA.get(m, m), exc))

        expected_d1 = round(gross_total_d1 + mat_total, 2)
        d1_total = round(d1_total, 2)
        yield {
            "code": "j05_d1_amount", "title": "Сума нарахувань у Д1 дорівнює сумі листків за квартал",
            "level": "ok" if abs(d1_total - expected_d1) <= AMOUNT_TOLERANCE else "error",
            "detail": "Д1: %s, листки (без ФОП): %s" % (self._m(d1_total), self._m(expected_d1)), "value": self._m(d1_total),
            "action_model": "hr.payslip", "action_domain": str([("company_id", "=", c.id), ("state", "=", "done")]),
        }

        d1_esv_total = round(d1_esv_total, 2)
        esv_total = round(esv_total, 2)
        yield {
            "code": "j05_d1_esv", "title": "ЄСВ у Д1 дорівнює нарахованому ЄСВ",
            "level": "ok" if abs(d1_esv_total - esv_total) <= AMOUNT_TOLERANCE else "error",
            "detail": "Д1: %s, нараховано: %s" % (self._m(d1_esv_total), self._m(esv_total)), "value": self._m(d1_esv_total),
            "action_model": "hr.payslip", "action_domain": str([("company_id", "=", c.id), ("state", "=", "done")]),
        }

        fourdf_gross = round(fourdf_gross, 2)
        yield {
            "code": "j05_4df_amount", "title": "Сума 4ДФ дорівнює сумі листків",
            "level": "ok" if abs(fourdf_gross - round(gross_total, 2)) <= AMOUNT_TOLERANCE else "error",
            "detail": "4ДФ: %s, листки: %s" % (self._m(fourdf_gross), self._m(gross_total)), "value": self._m(fourdf_gross),
            "action_model": "hr.payslip", "action_domain": str([("company_id", "=", c.id), ("state", "=", "done")]),
        }

        d1, d2 = self._period_bounds()
        order_count = self.env["ua.hr.order"].search_count([
            ("company_id", "=", c.id), ("order_type", "in", ("hire", "dismissal")),
            ("state", "in", ("posted", "acknowledged")), ("date", ">=", d1), ("date", "<=", d2),
        ])
        yield {
            "code": "j05_d5_count", "title": "Кількість рядків Д5 дорівнює кількості прийнять і звільнень за наказами",
            "level": "ok" if d5_count == order_count else "warn",
            "detail": "Д5: %s, наказів: %s" % (d5_count, order_count), "value": str(d5_count),
            "action_model": "ua.hr.order", "action_domain": str([
                ("company_id", "=", c.id), ("order_type", "in", ("hire", "dismissal")), ("date", ">=", d1), ("date", "<=", d2)]),
        }

        yield {
            "code": "j05_xsd", "title": "XML валідний за XSD",
            "level": "ok" if not xml_errors else "error",
            "detail": "Валідний" if not xml_errors else "; ".join(xml_errors[:5]), "value": str(len(xml_errors)),
            "action_model": "", "action_domain": "",
        }

    # ------------------------------------------------------------------ перевірки: j30
    def _checks_j30(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2),
        ])
        if not versions:
            yield {
                "code": "j30_none", "title": "Прийняті працівники в періоді",
                "level": "warn", "detail": "Немає прийнятих працівників у цьому періоді - подавати повідомлення нема про кого",
                "value": "0", "action_model": "", "action_domain": "",
            }
            return
        missing_order = self.env["hr.employee"]
        for v in versions:
            order = self.env["ua.hr.order"].search([
                ("employee_id", "=", v.employee_id.id), ("order_type", "=", "hire"),
                ("state", "in", ("posted", "acknowledged")), ("date_from", "=", v.contract_date_start),
            ], limit=1)
            if not order:
                missing_order |= v.employee_id
        yield {
            "code": "j30_orders", "title": "Усі працівники повідомлення прийняті в періоді і мають наказ",
            "level": "ok" if not missing_order else "error",
            "detail": "Усі мають наказ" if not missing_order else "Без наказу: %s" % ", ".join(missing_order.mapped("name")),
            "value": str(len(versions)),
            "action_model": "hr.employee" if missing_order else "", "action_domain": str([("id", "in", missing_order.ids)]) if missing_order else "",
        }

        today = fields.Date.context_today(self)
        late = versions.filtered(lambda v: v.contract_date_start and today > v.contract_date_start)
        yield {
            "code": "j30_timing", "title": "Дата подання не пізніша за перший робочий день",
            "level": "ok" if not late else "warn",
            "detail": "У строк" if not late else "Запізнення для %s версій контракту" % len(late),
            "value": str(len(late)),
            "action_model": "hr.version" if late else "", "action_domain": str([("id", "in", late.ids)]) if late else "",
        }

    # ------------------------------------------------------------------ перевірки: pfu
    def _checks_pfu(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        run_rec = self.env["hr.payslip.run"].search([("company_id", "=", c.id), ("date_start", ">=", d1), ("date_start", "<=", d2)], limit=1)
        if not run_rec:
            yield {
                "code": "pfu_run", "title": "Пакет листків періоду знайдено", "level": "error",
                "detail": "Немає пакета листків за цей місяць", "value": "",
                "action_model": "hr.payslip.run", "action_domain": str([("company_id", "=", c.id)]),
            }
            return
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", run_rec.id)], limit=1)
        if not claim or not claim.line_ids:
            yield {
                "code": "pfu_lines", "title": "Рядки заяви-розрахунку заповнені", "level": "warn",
                "detail": "Заяву ще не заповнено (натисніть «Перерахувати»)", "value": "0",
                "action_model": "hr.payslip.run", "action_domain": str([("id", "=", run_rec.id)]),
            }
            return
        no_number = claim.line_ids.filtered(lambda l: not l.sick_number)
        yield {
            "code": "pfu_sick_number", "title": "У кожному рядку є номер е-лікарняного",
            "level": "ok" if not no_number else "error",
            "detail": "Заповнено" if not no_number else "Без номера: %s рядків" % len(no_number),
            "value": str(len(no_number)),
            "action_model": "ua.pfu.claim" if no_number else "", "action_domain": str([("id", "=", claim.id)]) if no_number else "",
        }
        lines = run_rec.slip_ids.mapped("line_ids")
        slip_total = round(sum(lines.filtered(lambda l: l.code in ("SICK_PFU", "MAT")).mapped("total")), 2)
        claim_total = round(sum(claim.line_ids.mapped("amount")), 2)
        yield {
            "code": "pfu_amounts", "title": "Суми дорівнюють рядкам листків SICK_PFU і MAT",
            "level": "ok" if abs(claim_total - slip_total) <= AMOUNT_TOLERANCE else "error",
            "detail": "Заява: %s, листки: %s" % (self._m(claim_total), self._m(slip_total)), "value": self._m(claim_total),
            "action_model": "ua.pfu.claim", "action_domain": str([("id", "=", claim.id)]),
        }

    # ------------------------------------------------------------------ перевірки: timesheet
    def _checks_timesheet(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", "<=", d2),
            "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", d1),
        ])
        staff_count = len(versions.filtered(lambda v: (v.employee_id.ua_contract_kind or "employment") == "employment").mapped("employee_id"))
        sheet = self.env["ua.timesheet.sheet"].search([("company_id", "=", c.id), ("year", "=", self.year), ("month", "=", self.month), ("department_id", "=", False)], limit=1)
        row_count = len(sheet.line_ids) if sheet else 0
        yield {
            "code": "timesheet_rows", "title": "Кількість рядків дорівнює кількості працівників у штаті",
            "level": "ok" if row_count == staff_count else "warn",
            "detail": "Табель: %s, у штаті: %s" % (row_count, staff_count), "value": str(row_count),
            "action_model": "ua.timesheet.sheet" if sheet else "", "action_domain": str([("id", "=", sheet.id)]) if sheet else "",
        }
        if sheet:
            days_sheet = sum(sheet.line_ids.mapped("days_worked"))
            slips = self.env["hr.payslip"].search([("company_id", "=", c.id), ("date_from", ">=", d1), ("date_from", "<=", d2), ("state", "=", "done")])
            days_slips = sum(slips.mapped("worked_days_line_ids").filtered(lambda w: w.code == "WORK100").mapped("number_of_days"))
            yield {
                "code": "timesheet_days", "title": "Сума відпрацьованих днів збігається з листками",
                "level": "ok" if abs(days_sheet - days_slips) <= 0.5 else "warn",
                "detail": "Табель: %s, листки: %s" % (days_sheet, days_slips), "value": str(days_sheet),
                "action_model": "ua.timesheet.sheet", "action_domain": str([("id", "=", sheet.id)]),
            }

    # ------------------------------------------------------------------ перевірки: staff
    def _checks_staff(self):
        self.ensure_one()
        c = self.company_id
        sheet = self.env["ua.staff.list"].search([("company_id", "=", c.id), ("date", "=", self.date)], limit=1)
        if not sheet:
            yield {
                "code": "staff_missing", "title": "Документ штатного розпису існує", "level": "warn",
                "detail": "Ще не сформовано (натисніть «Перерахувати»)", "value": "",
                "action_model": "", "action_domain": "",
            }
            return
        no_kp = sheet.line_ids.filtered(lambda l: not l.kp_code)
        yield {
            "code": "staff_kp", "title": "Усі посади мають код КП",
            "level": "ok" if not no_kp else "warn",
            "detail": "Заповнено" if not no_kp else "Без коду КП: %s" % len(no_kp), "value": str(len(no_kp)),
            "action_model": "ua.staff.list" if no_kp else "", "action_domain": str([("id", "=", sheet.id)]) if no_kp else "",
        }
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", "<=", self.date), ("date_version", "<=", self.date),
            "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", self.date),
        ], order="employee_id, date_version desc")
        seen, wage_sum = set(), 0.0
        for v in versions:
            if (v.employee_id.ua_contract_kind or "employment") != "employment" or v.employee_id.id in seen:
                continue
            seen.add(v.employee_id.id)
            wage_sum += v.wage * float(v.employee_id.ua_fte or "1")
        wage_sum = round(wage_sum, 2)
        fund = round(sheet.total_fund, 2)
        yield {
            "code": "staff_fund", "title": "Фонд дорівнює сумі окладів чинних версій",
            "level": "ok" if abs(fund - wage_sum) <= 0.01 else "warn",
            "detail": "Штатний розпис: %s, розрахунок: %s" % (self._m(fund), self._m(wage_sum)), "value": self._m(fund),
            "action_model": "ua.staff.list", "action_domain": str([("id", "=", sheet.id)]),
        }

    # ------------------------------------------------------------------ перевірки: orders
    def _checks_orders(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        orders = self.env["ua.hr.order"].search([("company_id", "=", c.id), ("date", ">=", d1), ("date", "<=", d2)])
        drafts = orders.filtered(lambda o: o.state == "draft")
        yield {
            "code": "orders_draft", "title": "Усі накази періоду проведені",
            "level": "ok" if not drafts else "warn",
            "detail": "Немає чернеток" if not drafts else "Чернеток: %s" % len(drafts), "value": str(len(drafts)),
            "action_model": "ua.hr.order" if drafts else "", "action_domain": str([("id", "in", drafts.ids)]) if drafts else "",
        }

        posted = orders.filtered(lambda o: o.state in ("posted", "acknowledged") and o.name)
        for register in ("k1", "v2"):
            regs = posted.filtered(lambda o: o.register == register)
            nums = sorted(int(m.group()) for m in (re.match(r"\d+", o.name or "") for o in regs) if m)
            # реєстри К-1/В-2 наскрізні (не обнуляються щороку), тож рахуємо прогалини від першого
            # номера цього року, а не від 1 - інакше номери минулих років завжди «бракуватимуть»
            gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in nums] if len(nums) > 1 else []
            yield {
                "code": "orders_gaps_%s" % register, "title": "Немає прогалин у нумерації (%s)" % register,
                "level": "ok" if not gaps else "warn",
                "detail": "Прогалин немає" if not gaps else "Пропущені номери: %s" % gaps, "value": str(len(gaps)),
                "action_model": "ua.hr.order" if gaps else "",
                "action_domain": str([("company_id", "=", c.id), ("register", "=", register), ("date", ">=", d1), ("date", "<=", d2)]) if gaps else "",
            }

        not_ack = orders.filtered(lambda o: o.state == "posted")
        yield {
            "code": "orders_ack", "title": "Усі проведені накази мають ознайомлення",
            "level": "ok" if not not_ack else "warn",
            "detail": "Усі ознайомлені" if not not_ack else "Без ознайомлення: %s" % len(not_ack), "value": str(len(not_ack)),
            "action_model": "ua.hr.order" if not_ack else "", "action_domain": str([("id", "in", not_ack.ids)]) if not_ack else "",
        }

    # ------------------------------------------------------------------ формування: j05
    def _base_files_for_month(self, month):
        """Файли Д1 і 4ДФ поданого розрахунку за конкретний місяць кварталу.

        Місяць і рік зашиті в імені файлу ДПС перед кодом ДПІ: ...<тип періоду><ММ><РРРР><ДПІ>.XML
        """
        self.ensure_one()
        if not self.base_run_id:
            return self.env["ir.attachment"]
        pattern = re.compile(r"1%02d%d\d{4}\.XML$" % (month, self.year), re.IGNORECASE)
        return self.base_run_id.attachment_ids.filtered(
            lambda att: ("J0510111" in (att.name or "") or "J0510411" in (att.name or "")) and pattern.search(att.name or ""))

    @api.model
    def create_correction(self, run_id, kind="HZU"):
        """Виклик з екрана: зробити коригування і повернути id нового прогону."""
        run = self.browse(int(run_id)).action_create_correction(kind)
        return {"id": run.id, "name": run.name}

    def action_create_correction(self, kind="HZU"):
        """Новий прогін-коригування на основі поданого: рядки на вилучення беруться з його файлів."""
        self.ensure_one()
        if self.report_code != "j05":
            raise UserError(_("Коригування зроблено для об'єднаної звітності."))
        if self.state not in ("generated", "submitted"):
            raise UserError(_("Коригувати можна лише сформований або поданий розрахунок."))
        if kind not in ("HZN", "HZU"):
            raise UserError(_("Тип коригування: звітний новий або уточнюючий."))
        base = self.base_run_id or self
        number = max(base.correction_ids.mapped("correction_no") or [0]) + 1
        run = self.create({
            "report_code": "j05", "company_id": self.company_id.id, "year": self.year,
            "month": self.month, "quarter": self.quarter,
            "doc_kind": kind, "base_run_id": base.id, "correction_no": number,
        })
        run.message_post(body=_("Коригування до «%s»") % base.name)
        return run

    def _generate_j05(self):
        self.ensure_one()
        c = self.company_id
        Wizard = self.env["ua.payroll.report.wizard"]
        atts = self.env["ir.attachment"]
        notes = []
        for m in self._report_months():
            values = {"company_id": c.id, "year": self.year, "month": m, "doc_type": self.doc_kind or "HZ", "number": 1,
                      "with_d1": True, "with_4df": True, "with_d5": True, "fill_date": fields.Date.context_today(self)}
            if self.doc_kind in ("HZN", "HZU"):
                base_files = self._base_files_for_month(m)
                if not base_files:
                    notes.append("%s: немає файлів поданого розрахунку" % MONTHS_UA.get(m, m))
                    continue
                values["base_attachment_ids"] = [(6, 0, base_files.ids)]
            w = Wizard.create(values)
            try:
                w.action_generate()
            except UserError as exc:
                notes.append("%s: %s" % (MONTHS_UA.get(m, m), exc))
                continue
            atts |= w.result_ids
        if not atts:
            raise UserError(_("Не вдалося сформувати жодного файлу: %s") % "; ".join(notes))
        atts.write({"res_model": self._name, "res_id": self.id})
        if notes:
            self.message_post(body=_("Пропущено місяці без підтверджених листків: %s") % "; ".join(notes))
        return atts

    # ------------------------------------------------------------------ формування: j30
    def _generate_j30(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2),
        ])
        employees = versions.mapped("employee_id")
        if not employees:
            raise UserError(_("Немає прийнятих працівників за цей період."))
        w = self.env["ua.hire.notice.wizard"].create({
            "company_id": c.id, "employee_ids": [(6, 0, employees.ids)], "notice_type": "H01", "number": 1,
            "fill_date": fields.Date.context_today(self), "citizenship_ua": True,
        })
        w.action_generate()
        atts = self.env["ir.attachment"].search([("res_model", "=", "ua.hire.notice.wizard"), ("res_id", "=", w.id)])
        atts.write({"res_model": self._name, "res_id": self.id})
        return atts

    # ------------------------------------------------------------------ формування: pfu / timesheet / staff (PDF)
    def _generate_pfu(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        run_rec = self.env["hr.payslip.run"].search([("company_id", "=", c.id), ("date_start", ">=", d1), ("date_start", "<=", d2)], limit=1)
        if not run_rec:
            raise UserError(_("Немає пакета листків за цей місяць."))
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", run_rec.id)], limit=1)
        if not claim:
            claim = self.env["ua.pfu.claim"].create({"payslip_run_id": run_rec.id, "company_id": c.id})
        if claim.state == "draft":
            claim.action_refill()
        return self._render_pdf("l10n_ua_hr_docs.action_report_ua_pfu_claim", claim)

    def _generate_timesheet(self):
        self.ensure_one()
        c = self.company_id
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", c.id), ("year", "=", self.year), ("month", "=", self.month), ("department_id", "=", False)], limit=1)
        if not sheet:
            sheet = self.env["ua.timesheet.sheet"].create({"company_id": c.id, "year": self.year, "month": self.month})
        if sheet.state == "draft":
            sheet.action_refill()
        return self._render_pdf("l10n_ua_hr_docs.action_report_ua_timesheet", sheet)

    def _generate_staff(self):
        self.ensure_one()
        c = self.company_id
        sheet = self.env["ua.staff.list"].search([("company_id", "=", c.id), ("date", "=", self.date)], limit=1)
        if not sheet:
            sheet = self.env["ua.staff.list"].create({"company_id": c.id, "date": self.date})
        if sheet.state == "draft":
            sheet.action_refill()
        return self._render_pdf("l10n_ua_hr_docs.action_report_ua_staff_list", sheet)

    def _generate_orders(self):
        self.ensure_one()
        c = self.company_id
        atts = self.env["ir.attachment"]
        for register in ("k1", "v2"):
            w = self.env["ua.hr.order.register.wizard"].create({"company_id": c.id, "year": self.year, "register": register})
            atts |= self._render_pdf("l10n_ua_hr_orders.action_report_ua_hr_order_register", w,
                                     name="%s_%s_%s.pdf" % (dict(w._fields["register"].selection).get(register), self.year, register))
        return atts

    def _render_pdf(self, report_xmlid, doc, name=None):
        """Рендер QWeb-звіту в PDF через існуючу дію звіту, вкладення на цей прогін."""
        self.ensure_one()
        data, _fmt = self.env["ir.actions.report"]._render_qweb_pdf(report_xmlid, res_ids=doc.ids)
        return self.env["ir.attachment"].create({
            "name": name or "%s.pdf" % (doc.display_name or doc.name),
            "datas": base64.b64encode(data), "mimetype": "application/pdf",
            "res_model": self._name, "res_id": self.id,
        })

    # ------------------------------------------------------------------ дані для таблиці «Дані»
    @staticmethod
    def _m(value):
        """Українське форматування суми: 1 194 649,69"""
        return "{:,.2f}".format(value or 0.0).replace(",", "\u00a0").replace(".", ",")

    def _summary(self):
        self.ensure_one()
        method = getattr(self, "_summary_%s" % self.report_code, None)
        data = method() if method else {"columns": [], "rows": [], "total": None}
        data.setdefault("money", [])
        data.setdefault("targets", [])
        # targets вирівнюємо по rows: клік по рядку веде в запис, який правлять
        rows = data.get("rows") or []
        targets = list(data["targets"])
        while len(targets) < len(rows):
            targets.append(False)
        data["targets"] = targets[:len(rows)]
        return data

    def _slip_target(self, d1, d2, employee=None, name=""):
        """Ціль кліку: листки періоду, за потреби одного працівника."""
        domain = [("company_id", "=", self.company_id.id),
                  ("date_from", ">=", str(d1)), ("date_from", "<=", str(d2)),
                  ("state", "!=", "cancel")]
        if employee:
            domain.append(("employee_id", "=", employee.id))
        return {"model": "hr.payslip", "domain": domain, "name": name or "Листки"}


    # ---- бухгалтерські звіти: ОСВ і головна книга ----------------------------------------
    def _month_range(self):
        if not self.month:
            raise UserError(_("У прогоні не вказано місяць."))
        d1 = date(self.year, self.month, 1)
        d2 = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        return d1, d2

    def _account_by_code(self, code):
        Account = self.env["account.account"].with_company(self.company_id)
        return Account.search([("code", "=", code), ("company_ids", "in", self.company_id.ids)], limit=1) or \
            Account.search([("code", "=like", code + "%"), ("company_ids", "in", self.company_id.ids)], order="code", limit=1)

    def _turnover(self, account, d1, d2):
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted"),
            ("date", ">=", d1), ("date", "<=", d2), ("company_id", "=", self.company_id.id)])
        return round(sum(lines.mapped("debit")), 2), round(sum(lines.mapped("credit")), 2)

    def _balance_before(self, account, d1):
        lines = self.env["account.move.line"].search([
            ("account_id", "=", account.id), ("parent_state", "=", "posted"),
            ("date", "<", d1), ("company_id", "=", self.company_id.id)])
        return round(sum(lines.mapped("debit")) - sum(lines.mapped("credit")), 2)

    def _slip_amount(self, d1, d2, codes, scope="all"):
        """Сума рядків листків за кодами. scope=no_fop прибирає ФОП-підрядників: їх оплата йде на 6851, не на 661."""
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date_from", ">=", d1), ("date_to", "<=", d2)])
        if scope == "no_fop":
            slips = slips.filtered(lambda s: (s.employee_id.sudo().ua_contract_kind or "employment") != "fop")
        lines = slips.mapped("line_ids").filtered(lambda l: l.code in codes)
        # знак у листку різний (нарахування додатні, утримання відʼємні), а в проводці це один бік
        return round(sum(abs(l.total) for l in lines), 2)

    def _checks_accounting(self):
        """Спільні перевірки для ОСВ і головної книги: проводки зарплати проти листків."""
        self.ensure_one()
        d1, d2 = self._month_range()
        checks = []
        drafts = self.env["account.move"].search_count([
            ("company_id", "=", self.company_id.id), ("state", "=", "draft"),
            ("date", ">=", d1), ("date", "<=", d2)])
        checks.append({"code": "moves_draft", "title": "Усі проводки періоду проведені",
                       "level": "ok" if not drafts else "warn",
                       "detail": "Чернеток проводок: %s" % drafts, "value": str(drafts),
                       "action_model": "account.move" if drafts else False,
                       "action_domain": str([("state", "=", "draft"), ("date", ">=", str(d1)), ("date", "<=", str(d2))]) if drafts else False})
        total_d = total_c = 0.0
        for code, name, slip_codes, side, scope in PAYROLL_ACCOUNTS:
            account = self._account_by_code(code)
            if not account:
                checks.append({"code": "acc_%s" % code, "title": "Рахунок %s є в плані" % code, "level": "error",
                               "detail": "Рахунку немає", "value": "-"})
                continue
            debit, credit = self._turnover(account, d1, d2)
            total_d += debit
            total_c += credit
            expected = self._slip_amount(d1, d2, slip_codes, scope)
            actual = credit if side == "credit" else debit
            diff = round(actual - expected, 2)
            checks.append({
                "code": "turnover_%s" % code,
                "title": "Оборот %s (%s) дорівнює листкам" % (code, name),
                "level": "ok" if abs(diff) <= 0.01 else "error",
                "detail": "Проводки: %s; листки: %s; різниця: %s" % (self._m(actual), self._m(expected), self._m(diff)),
                "value": self._m(actual),
                "action_model": "account.move.line" if abs(diff) > 0.01 else False,
                "action_domain": str([("account_id", "=", account.id), ("date", ">=", str(d1)), ("date", "<=", str(d2))]) if abs(diff) > 0.01 else False})
        all_lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
            ("date", ">=", d1), ("date", "<=", d2)])
        sd, sc = round(sum(all_lines.mapped("debit")), 2), round(sum(all_lines.mapped("credit")), 2)
        checks.append({"code": "balance", "title": "Дебет дорівнює кредиту за період",
                       "level": "ok" if abs(sd - sc) <= 0.01 else "error",
                       "detail": "Дебет %s, кредит %s" % (self._m(sd), self._m(sc)), "value": self._m(sd)})
        unrec = self.env["account.bank.statement.line"].search_count([
            ("company_id", "=", self.company_id.id), ("is_reconciled", "=", False),
            ("date", ">=", d1), ("date", "<=", d2)])
        checks.append({"code": "unreconciled", "title": "Рядки виписки звірені",
                       "level": "ok" if not unrec else "warn",
                       "detail": "Незвірених рядків: %s" % unrec, "value": str(unrec),
                       "action_model": "account.bank.statement.line" if unrec else False,
                       "action_domain": str([("is_reconciled", "=", False), ("date", ">=", str(d1)), ("date", "<=", str(d2))]) if unrec else False})
        return checks

    def _checks_trial(self):
        return self._checks_accounting()

    def _checks_ledger(self):
        return self._checks_accounting()

    def _summary_accounting(self):
        d1, d2 = self._month_range()
        columns = ["Рахунок", "Назва", "Сальдо на початок", "Дебет", "Кредит", "Сальдо на кінець"]
        rows, targets = [], []
        codes = [c[0] for c in PAYROLL_ACCOUNTS] + ["311", "301", "471", "378", "6851", "92", "93", "23", "91"]
        seen = set()
        for code in codes:
            if code in seen:
                continue
            seen.add(code)
            account = self._account_by_code(code)
            if not account:
                continue
            debit, credit = self._turnover(account, d1, d2)
            if not debit and not credit:
                continue
            opening = self._balance_before(account, d1)
            rows.append([account.code, account.name, opening, debit, credit, round(opening + debit - credit, 2)])
            targets.append({"model": "account.move.line",
                            "domain": [("account_id", "=", account.id), ("parent_state", "=", "posted"),
                                       ("date", ">=", str(d1)), ("date", "<=", str(d2)),
                                       ("company_id", "=", self.company_id.id)],
                            "name": "%s %s" % (account.code, account.name)})
        total = ["Разом", "", round(sum(r[2] for r in rows), 2), round(sum(r[3] for r in rows), 2),
                 round(sum(r[4] for r in rows), 2), round(sum(r[5] for r in rows), 2)] if rows else None
        return {"columns": columns, "rows": rows, "total": total, "money": [2, 3, 4, 5], "targets": targets}

    def _summary_trial(self):
        return self._summary_accounting()

    def _summary_ledger(self):
        return self._summary_accounting()

    def _generate_accounting(self, wizard_model, report_name, file_name):
        self.ensure_one()
        d1, d2 = self._month_range()
        wiz = self.env[wizard_model].create({
            "company_id": self.company_id.id, "date_from": d1, "date_to": d2, "target_move": "posted",
        })
        if hasattr(wiz, "_set_default_wizard_values"):
            wiz._set_default_wizard_values()
        data = wiz._prepare_report_data()
        pdf, _dummy = self.env["ir.actions.report"]._render_qweb_pdf(report_name, [wiz.id], data=data)
        att = self.env["ir.attachment"].create({
            "name": file_name % (self.month, self.year), "type": "binary",
            "datas": base64.b64encode(pdf), "mimetype": "application/pdf",
            "res_model": self._name, "res_id": self.id})
        self.attachment_ids = [(4, att.id)]
        return att

    def _generate_trial(self):
        return self._generate_accounting("trial.balance.report.wizard", "account_financial_report.trial_balance",
                                         "Оборотно-сальдова відомість %02d.%s.pdf")

    def _generate_ledger(self):
        return self._generate_accounting("general.ledger.report.wizard", "account_financial_report.general_ledger",
                                         "Головна книга %02d.%s.pdf")

    def _summary_j05(self):
        c = self.company_id
        columns = ["Місяць", "Осіб", "Нараховано", "ПДФО", "ВЗ", "ЄСВ"]
        rows, targets = [], []
        totals = {"employees": 0, "gross": 0.0, "pdfo": 0.0, "vz": 0.0, "esv": 0.0}
        for m in self._report_months():
            d1, d2 = date(self.year, m, 1), date(self.year, m, calendar.monthrange(self.year, m)[1])
            slips = self.env["hr.payslip"].search([("company_id", "=", c.id), ("state", "=", "done"), ("date_from", ">=", d1), ("date_to", "<=", d2)])
            lines = slips.mapped("line_ids")
            row = {
                "employees": len(slips.mapped("employee_id")),
                "gross": round(sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total")), 2),
                "pdfo": round(abs(sum(lines.filtered(lambda l: l.code == "PDFO").mapped("total"))), 2),
                "vz": round(abs(sum(lines.filtered(lambda l: l.code == "VZ").mapped("total"))), 2),
                "esv": round(sum(lines.filtered(lambda l: l.code == "ESV").mapped("total")), 2),
            }
            rows.append(["%s %s" % (MONTHS_UA.get(m, "").capitalize(), self.year), row["employees"], row["gross"], row["pdfo"], row["vz"], row["esv"]])
            targets.append(self._slip_target(d1, d2, name="Листки · %s %s" % (MONTHS_UA.get(m, ""), self.year)))
            for k in totals:
                totals[k] += row[k]
        total = ["Разом", totals["employees"], round(totals["gross"], 2), round(totals["pdfo"], 2), round(totals["vz"], 2), round(totals["esv"], 2)]
        return {"columns": columns, "rows": rows, "total": total, "money": [2, 3, 4, 5], "targets": targets}

    def _summary_j30(self):
        d1, d2 = self._period_bounds()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", self.company_id.id), ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2)])
        rows = [[v.employee_id.name, v.contract_date_start.strftime("%d.%m.%Y"), v.job_title or v.ua_prof_name or "-"] for v in versions]
        targets = [{"model": "hr.employee", "res_id": v.employee_id.id, "name": v.employee_id.name} for v in versions]
        return {"columns": ["Працівник", "Дата прийняття", "Посада"], "rows": rows, "total": None, "targets": targets}

    def _summary_pfu(self):
        d1, d2 = self._period_bounds()
        run_rec = self.env["hr.payslip.run"].search([("company_id", "=", self.company_id.id), ("date_start", ">=", d1), ("date_start", "<=", d2)], limit=1)
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", run_rec.id)], limit=1) if run_rec else self.env["ua.pfu.claim"]
        kinds = dict(self.env["ua.pfu.claim.line"]._fields["kind"].selection)
        rows = [[l.employee_id.name, kinds.get(l.kind), l.sick_number or "-", l.days, round(l.amount, 2)] for l in claim.line_ids]
        targets = [self._slip_target(d1, d2, l.employee_id, l.employee_id.name) for l in claim.line_ids]
        total = ["Разом", "", "", sum(claim.line_ids.mapped("days")), round(sum(claim.line_ids.mapped("amount")), 2)] if claim and claim.line_ids else None
        return {"columns": ["Працівник", "Вид", "№ е-ЛН", "Днів", "Сума"], "rows": rows, "total": total,
                "money": [4], "targets": targets}

    def _summary_timesheet(self):
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", self.company_id.id), ("year", "=", self.year), ("month", "=", self.month), ("department_id", "=", False)], limit=1)
        rows = [[l.employee_id.name, l.job_title or "-", l.days_worked, l.days_vac, l.days_sick, l.days_unpaid] for l in sheet.line_ids] if sheet else []
        targets = ([{"model": "ua.timesheet.sheet", "res_id": sheet.id, "name": "Табель"}] * len(rows)) if sheet else []
        total = (["Разом", "", sum(sheet.line_ids.mapped("days_worked")), sum(sheet.line_ids.mapped("days_vac")),
                 sum(sheet.line_ids.mapped("days_sick")), sum(sheet.line_ids.mapped("days_unpaid"))]
                if sheet and sheet.line_ids else None)
        return {"columns": ["Працівник", "Посада", "Р", "В", "ТН", "НА"], "rows": rows, "total": total,
                "targets": targets}

    def _summary_staff(self):
        sheet = self.env["ua.staff.list"].search([("company_id", "=", self.company_id.id), ("date", "=", self.date)], limit=1)
        rows = [[l.department_id.name or "-", l.job_title, l.kp_code or "-", l.units, round(l.wage, 2), round(l.fund, 2)] for l in sheet.line_ids] if sheet else []
        targets = ([{"model": "ua.staff.list", "res_id": sheet.id, "name": "Штатний розпис"}] * len(rows)) if sheet else []
        total = ["Разом", "", "", sheet.total_units, "", round(sheet.total_fund, 2)] if sheet and sheet.line_ids else None
        return {"columns": ["Підрозділ", "Посада", "Код КП", "Штат. один.", "Оклад", "Фонд"], "rows": rows,
                "total": total, "money": [4, 5], "targets": targets}

    def _summary_orders(self):
        d1, d2 = self._period_bounds()
        Order = self.env["ua.hr.order"]
        orders = Order.search([("company_id", "=", self.company_id.id), ("date", ">=", d1), ("date", "<=", d2)], order="date")
        type_labels = dict(Order._fields["order_type"].selection)
        state_labels = dict(Order._fields["state"].selection)
        rows = [[o.name or "-", o.date.strftime("%d.%m.%Y"), type_labels.get(o.order_type), o.employee_id.name, state_labels.get(o.state)] for o in orders]
        targets = [{"model": "ua.hr.order", "res_id": o.id, "name": o.name or "Наказ"} for o in orders]
        return {"columns": ["№", "Дата", "Вид", "Працівник", "Стан"], "rows": rows, "total": None, "targets": targets}


class UaReportCheck(models.Model):
    _name = "ua.report.check"
    _description = "Перевірка звітного прогону"
    _order = "sequence, id"

    run_id = fields.Many2one("ua.report.run", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True)
    title = fields.Char(required=True)
    level = fields.Selection([("ok", "Ок"), ("warn", "Увага"), ("error", "Помилка")], required=True)
    detail = fields.Char()
    value = fields.Char()
    action_model = fields.Char()
    action_domain = fields.Char()

    def _screen_data(self):
        self.ensure_one()
        return {
            "id": self.id, "sequence": self.sequence, "code": self.code, "title": self.title,
            "level": self.level, "detail": self.detail or "", "value": self.value or "",
            "action_model": self.action_model or "", "action_domain": self.action_domain or "",
        }

    def action_open(self):
        self.ensure_one()
        if not self.action_model:
            return False
        domain = safe_eval(self.action_domain or "[]")
        return {
            "type": "ir.actions.act_window", "res_model": self.action_model, "domain": domain,
            "views": [[False, "list"], [False, "form"]], "name": self.title, "target": "current",
        }
