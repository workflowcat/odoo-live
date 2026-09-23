"""Робоче місце звітності: один прогін (ua.report.run) на звіт+період, з перевірками (ua.report.check)
перед формуванням. Формування файлів не дублює логіку - викликає наявні майстри/документи модулів
l10n_ua_payroll_reports і l10n_ua_hr_docs / l10n_ua_hr_orders і забирає в себе готові вкладення."""
import base64
import calendar
import json
import re
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_screen.models.ua_screen import MONTHS_UA

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


def _target(model, domain=None, res_id=None):
    """Фрагмент рядка перевірки: запис(и), які вона стосується.

    Кожна перевірка, що називає записи, має ціль - hr.employee, hr.payslip, res.company тощо
    (домен або конкретний res_id). Перевірка не про записи (напр. валідність XML) ціллю має сам
    прогін (ua.report.run), а не порожню ціль."""
    return {
        "target_model": model,
        "target_domain": json.dumps(domain) if domain is not None else False,
        "target_res_id": res_id or False,
    }


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
    def _run_vals(self, report_code, company, year, quarter=None, month=None, date_=None):
        vals = {"report_code": report_code, "company_id": company.id, "year": year}
        if report_code == "j05":
            vals["month"] = month
            vals["quarter"] = quarter or ((month - 1) // 3 + 1 if month else False)
        elif report_code in ("j30", "pfu", "timesheet", "trial", "ledger"):
            vals["month"] = month
        elif report_code == "staff":
            vals["date"] = date_
        return vals

    @api.model
    def _find_run(self, report_code, company, year, quarter=None, month=None, date_=None):
        """Наявний прогін періоду або порожній набір. Нічого не створює."""
        key = _period_key_value(report_code, year, quarter, month, date_)
        return self.search([("report_code", "=", report_code), ("company_id", "=", company.id),
                            ("period_key", "=", key)], limit=1)

    @api.model
    def _find_or_create(self, report_code, company, year, quarter=None, month=None, date_=None):
        run = self._find_run(report_code, company, year, quarter=quarter, month=month, date_=date_)
        if run:
            return run
        run = self.create(self._run_vals(report_code, company, year, quarter, month, date_))
        run.action_refresh()
        return run

    @api.model
    def ensure_run(self, report_code=None, year=None, quarter=None, month=None, date=None, run_id=None):
        """Створити прогін періоду, якщо його ще немає, і повернути його id.

        Єдиний вхід, який прогін створює на вимогу клієнта. Екран сам по собі
        (`get_screen_data`) не пише нічого: місяць без прогону показується порожнім,
        а запис з'являється тоді, коли бухгалтер натискає «Перерахувати» чи «Сформувати»."""
        if run_id:
            run = self.browse(int(run_id)).exists()
            if run:
                return run.id
        company = self.env.company
        today = fields.Date.context_today(self)
        report_code = report_code or REPORTS[0][0]
        run = self._find_or_create(
            report_code, company,
            int(year) if year else today.year,
            quarter=int(quarter) if quarter else ((today.month - 1) // 3 + 1),
            month=int(month) if month else today.month,
            date_=fields.Date.to_date(date) if date else today,
        )
        return run.id

    # ------------------------------------------------------------------ дії
    def action_refresh(self):
        # ua.report.check не редагується з UI (ir.model.access.csv забороняє create/write/unlink
        # звичайним користувачам) - рядки перевірок пише лише цей метод, через sudo().
        Check = self.env["ua.report.check"].sudo()
        for run in self:
            run.check_ids.sudo().unlink()
            rows = run._build_checks()
            for i, row in enumerate(rows, 1):
                row.setdefault("sequence", i * 10)
                row["run_id"] = run.id
            Check.create(rows)
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
        done_slips = self.env["hr.payslip"].search([
            ("company_id", "=", c.id), ("date_from", ">=", d1), ("date_from", "<=", d2), ("state", "=", "done"),
        ])
        if not done_slips and draft_slips:
            level = "error"
            detail = "Проведених листків у періоді немає"
        elif draft_slips:
            level = "warn"
            detail = "Листків-чернеток: %s" % len(draft_slips)
        else:
            level = "ok"
            detail = "Чернеток немає"
        yield dict({
            "code": "period_closed", "title": "Чернетки листків у періоді",
            "level": level,
            "detail": detail,
            "value": str(len(draft_slips)),
        }, **_target("hr.payslip", domain=[("company_id", "=", c.id), ("date_from", ">=", str(d1)), ("date_from", "<=", str(d2)),
                                          ("state", "in", ("draft", "verify"))]))

        emps = self.env["hr.employee"].search([("company_id", "=", c.id), ("active", "=", True)])
        bad = emps.filtered(lambda e: not (e.sudo().ua_rnokpp and len(e.sudo().ua_rnokpp) == 10 and e.sudo().ua_rnokpp.isdigit()))
        yield dict({
            "code": "rnokpp", "title": "Усі РНОКПП заповнені і мають 10 цифр",
            "level": "ok" if not bad else "error",
            "detail": "Усі заповнені" if not bad else "Без коректного РНОКПП: %s" % ", ".join(bad.mapped("name")[:5]),
            "value": str(len(bad)),
        }, **_target("hr.employee", domain=[("id", "in", (bad or emps).ids)]))

        missing = []
        if not c.company_registry:
            missing.append("ЄДРПОУ")
        if not c.ua_sti_code:
            missing.append("код ДПІ")
        if not c.ua_director_name:
            missing.append("керівник")
        yield dict({
            "code": "company_signers", "title": "Компанія має ЄДРПОУ, код ДПІ і підписантів",
            "level": "ok" if not missing else "error",
            "detail": "Заповнено" if not missing else "Немає: %s" % ", ".join(missing),
            "value": "",
        }, **_target("res.company", res_id=c.id))

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
        payslip_domain = [("company_id", "=", c.id), ("state", "=", "done"),
                          ("date_from", ">=", str(self._period_bounds()[0])), ("date_to", "<=", str(self._period_bounds()[1]))]
        yield dict({
            "code": "j05_d1_amount", "title": "Сума нарахувань у Д1 дорівнює сумі листків за квартал",
            "level": "ok" if abs(d1_total - expected_d1) <= AMOUNT_TOLERANCE else "error",
            "detail": "Д1: %s, листки (без ФОП): %s" % (self._m(d1_total), self._m(expected_d1)), "value": self._m(d1_total),
        }, **_target("hr.payslip", domain=payslip_domain))

        d1_esv_total = round(d1_esv_total, 2)
        esv_total = round(esv_total, 2)
        yield dict({
            "code": "j05_d1_esv", "title": "ЄСВ у Д1 дорівнює нарахованому ЄСВ",
            "level": "ok" if abs(d1_esv_total - esv_total) <= AMOUNT_TOLERANCE else "error",
            "detail": "Д1: %s, нараховано: %s" % (self._m(d1_esv_total), self._m(esv_total)), "value": self._m(d1_esv_total),
        }, **_target("hr.payslip", domain=payslip_domain))

        fourdf_gross = round(fourdf_gross, 2)
        yield dict({
            "code": "j05_4df_amount", "title": "Сума 4ДФ дорівнює сумі листків",
            "level": "ok" if abs(fourdf_gross - round(gross_total, 2)) <= AMOUNT_TOLERANCE else "error",
            "detail": "4ДФ: %s, листки: %s" % (self._m(fourdf_gross), self._m(gross_total)), "value": self._m(fourdf_gross),
        }, **_target("hr.payslip", domain=payslip_domain))

        d1, d2 = self._period_bounds()
        order_domain = [("company_id", "=", c.id), ("order_type", "in", ("hire", "dismissal")),
                        ("state", "in", ("posted", "acknowledged")), ("date", ">=", str(d1)), ("date", "<=", str(d2))]
        order_count = self.env["ua.hr.order"].search_count(order_domain)
        yield dict({
            "code": "j05_d5_count", "title": "Кількість рядків Д5 дорівнює кількості прийнять і звільнень за наказами",
            "level": "ok" if d5_count == order_count else "warn",
            "detail": "Д5: %s, наказів: %s" % (d5_count, order_count), "value": str(d5_count),
        }, **_target("ua.hr.order", domain=order_domain))

        yield dict({
            "code": "j05_xsd", "title": "XML валідний за XSD",
            "level": "ok" if not xml_errors else "error",
            "detail": "Валідний" if not xml_errors else "; ".join(xml_errors[:5]), "value": str(len(xml_errors)),
        }, **_target("ua.report.run", res_id=self.id))

    # ------------------------------------------------------------------ перевірки: j30
    def _checks_j30(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        version_domain = [("employee_id.company_id", "=", c.id), ("contract_date_start", ">=", str(d1)), ("contract_date_start", "<=", str(d2))]
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2),
        ])
        if not versions:
            yield dict({
                "code": "j30_none", "title": "Прийняті працівники в періоді",
                "level": "warn", "detail": "Немає прийнятих працівників у цьому періоді - подавати повідомлення нема про кого",
                "value": "0",
            }, **_target("hr.version", domain=version_domain))
            return
        missing_order = self.env["hr.employee"]
        for v in versions:
            order = self.env["ua.hr.order"].search([
                ("employee_id", "=", v.employee_id.id), ("order_type", "=", "hire"),
                ("state", "in", ("posted", "acknowledged")), ("date_from", "=", v.contract_date_start),
            ], limit=1)
            if not order:
                missing_order |= v.employee_id
        yield dict({
            "code": "j30_orders", "title": "Усі працівники повідомлення прийняті в періоді і мають наказ",
            "level": "ok" if not missing_order else "error",
            "detail": "Усі мають наказ" if not missing_order else "Без наказу: %s" % ", ".join(missing_order.mapped("name")),
            "value": str(len(versions)),
        }, **_target("hr.employee", domain=[("id", "in", (missing_order or versions.mapped("employee_id")).ids)]))

        today = fields.Date.context_today(self)
        late = versions.filtered(lambda v: v.contract_date_start and today > v.contract_date_start)
        yield dict({
            "code": "j30_timing", "title": "Дата подання не пізніша за перший робочий день",
            "level": "ok" if not late else "warn",
            "detail": "У строк" if not late else "Запізнення для %s версій контракту" % len(late),
            "value": str(len(late)),
        }, **_target("hr.version", domain=[("id", "in", (late or versions).ids)]))

    # ------------------------------------------------------------------ перевірки: pfu
    def _checks_pfu(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        run_rec = self.env["hr.payslip.run"].search([("company_id", "=", c.id), ("date_start", ">=", d1), ("date_start", "<=", d2)], limit=1)
        if not run_rec:
            yield dict({
                "code": "pfu_run", "title": "Пакет листків періоду знайдено", "level": "error",
                "detail": "Немає пакета листків за цей місяць", "value": "",
            }, **_target("hr.payslip.run", domain=[("company_id", "=", c.id), ("date_start", ">=", str(d1)), ("date_start", "<=", str(d2))]))
            return
        claim = self.env["ua.pfu.claim"].search([("payslip_run_id", "=", run_rec.id)], limit=1)
        if not claim or not claim.line_ids:
            yield dict({
                "code": "pfu_lines", "title": "Рядки заяви-розрахунку заповнені", "level": "warn",
                "detail": "Заяву ще не заповнено (натисніть «Перерахувати»)", "value": "0",
            }, **_target("hr.payslip.run", res_id=run_rec.id))
            return
        no_number = claim.line_ids.filtered(lambda l: not l.sick_number)
        yield dict({
            "code": "pfu_sick_number", "title": "У кожному рядку є номер е-лікарняного",
            "level": "ok" if not no_number else "error",
            "detail": "Заповнено" if not no_number else "Без номера: %s рядків" % len(no_number),
            "value": str(len(no_number)),
        }, **_target("ua.pfu.claim", res_id=claim.id))
        lines = run_rec.slip_ids.mapped("line_ids")
        slip_total = round(sum(lines.filtered(lambda l: l.code in ("SICK_PFU", "MAT")).mapped("total")), 2)
        claim_total = round(sum(claim.line_ids.mapped("amount")), 2)
        yield dict({
            "code": "pfu_amounts", "title": "Суми дорівнюють рядкам листків SICK_PFU і MAT",
            "level": "ok" if abs(claim_total - slip_total) <= AMOUNT_TOLERANCE else "error",
            "detail": "Заява: %s, листки: %s" % (self._m(claim_total), self._m(slip_total)), "value": self._m(claim_total),
        }, **_target("ua.pfu.claim", res_id=claim.id))

    # ------------------------------------------------------------------ перевірки: timesheet
    def _checks_timesheet(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        version_domain = [("employee_id.company_id", "=", c.id), ("contract_date_start", "<=", str(d2)),
                          "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", str(d1))]
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", c.id), ("contract_date_start", "<=", d2),
            "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", d1),
        ])
        staff_count = len(versions.filtered(lambda v: (v.employee_id.ua_contract_kind or "employment") == "employment").mapped("employee_id"))
        sheet = self.env["ua.timesheet.sheet"].search([("company_id", "=", c.id), ("year", "=", self.year), ("month", "=", self.month), ("department_id", "=", False)], limit=1)
        row_count = len(sheet.line_ids) if sheet else 0
        row_target = _target("ua.timesheet.sheet", res_id=sheet.id) if sheet else _target("hr.version", domain=version_domain)
        yield dict({
            "code": "timesheet_rows", "title": "Кількість рядків дорівнює кількості працівників у штаті",
            "level": "ok" if row_count == staff_count else "warn",
            "detail": "Табель: %s, у штаті: %s" % (row_count, staff_count), "value": str(row_count),
        }, **row_target)
        if sheet:
            days_sheet = sum(sheet.line_ids.mapped("days_worked"))
            slips = self.env["hr.payslip"].search([("company_id", "=", c.id), ("date_from", ">=", d1), ("date_from", "<=", d2), ("state", "=", "done")])
            days_slips = sum(slips.mapped("worked_days_line_ids").filtered(lambda w: w.code == "WORK100").mapped("number_of_days"))
            yield dict({
                "code": "timesheet_days", "title": "Сума відпрацьованих днів збігається з листками",
                "level": "ok" if abs(days_sheet - days_slips) <= 0.5 else "warn",
                "detail": "Табель: %s, листки: %s" % (days_sheet, days_slips), "value": str(days_sheet),
            }, **_target("ua.timesheet.sheet", res_id=sheet.id))

    # ------------------------------------------------------------------ перевірки: staff
    def _checks_staff(self):
        self.ensure_one()
        c = self.company_id
        sheet = self.env["ua.staff.list"].search([("company_id", "=", c.id), ("date", "=", self.date)], limit=1)
        if not sheet:
            yield dict({
                "code": "staff_missing", "title": "Документ штатного розпису існує", "level": "warn",
                "detail": "Ще не сформовано (натисніть «Перерахувати»)", "value": "",
            }, **_target("hr.employee", domain=[("company_id", "=", c.id), ("active", "=", True)]))
            return
        no_kp = sheet.line_ids.filtered(lambda l: not l.kp_code)
        yield dict({
            "code": "staff_kp", "title": "Усі посади мають код КП",
            "level": "ok" if not no_kp else "warn",
            "detail": "Заповнено" if not no_kp else "Без коду КП: %s" % len(no_kp), "value": str(len(no_kp)),
        }, **_target("ua.staff.list", res_id=sheet.id))
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
        yield dict({
            "code": "staff_fund", "title": "Фонд дорівнює сумі окладів чинних версій",
            "level": "ok" if abs(fund - wage_sum) <= 0.01 else "warn",
            "detail": "Штатний розпис: %s, розрахунок: %s" % (self._m(fund), self._m(wage_sum)), "value": self._m(fund),
        }, **_target("ua.staff.list", res_id=sheet.id))

    # ------------------------------------------------------------------ перевірки: orders
    def _checks_orders(self):
        self.ensure_one()
        c = self.company_id
        d1, d2 = self._period_bounds()
        orders = self.env["ua.hr.order"].search([("company_id", "=", c.id), ("date", ">=", d1), ("date", "<=", d2)])
        drafts = orders.filtered(lambda o: o.state == "draft")
        yield dict({
            "code": "orders_draft", "title": "Усі накази періоду проведені",
            "level": "ok" if not drafts else "warn",
            "detail": "Немає чернеток" if not drafts else "Чернеток: %s" % len(drafts), "value": str(len(drafts)),
        }, **_target("ua.hr.order", domain=[("id", "in", (drafts or orders).ids)]))

        posted = orders.filtered(lambda o: o.state in ("posted", "acknowledged") and o.name)
        for register in ("k1", "v2"):
            regs = posted.filtered(lambda o: o.register == register)
            nums = sorted(int(m.group()) for m in (re.match(r"\d+", o.name or "") for o in regs) if m)
            # реєстри К-1/В-2 наскрізні (не обнуляються щороку), тож рахуємо прогалини від першого
            # номера цього року, а не від 1 - інакше номери минулих років завжди «бракуватимуть»
            gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in nums] if len(nums) > 1 else []
            yield dict({
                "code": "orders_gaps_%s" % register, "title": "Немає прогалин у нумерації (%s)" % register,
                "level": "ok" if not gaps else "warn",
                "detail": "Прогалин немає" if not gaps else "Пропущені номери: %s" % gaps, "value": str(len(gaps)),
            }, **_target("ua.hr.order", domain=[("company_id", "=", c.id), ("register", "=", register), ("date", ">=", str(d1)), ("date", "<=", str(d2))]))

        not_ack = orders.filtered(lambda o: o.state == "posted")
        yield dict({
            "code": "orders_ack", "title": "Усі проведені накази мають ознайомлення",
            "level": "ok" if not not_ack else "warn",
            "detail": "Усі ознайомлені" if not not_ack else "Без ознайомлення: %s" % len(not_ack), "value": str(len(not_ack)),
        }, **_target("ua.hr.order", domain=[("id", "in", (not_ack or orders).ids)]))

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
        """Журнал реєстрації за рік, по одному файлу на реєстр.

        Майстра журналу більше немає (2026-09-22): журнал - це самі накази, тому звіт
        рендериться просто з їхнього переліку за рік і реєстр."""
        self.ensure_one()
        c = self.company_id
        Order = self.env["ua.hr.order"]
        labels = dict(Order._fields["register"].selection)
        atts = self.env["ir.attachment"]
        for register in ("k1", "v2"):
            orders = Order.search([
                ("company_id", "=", c.id), ("register", "=", register),
                ("date", ">=", "%s-01-01" % self.year), ("date", "<=", "%s-12-31" % self.year),
            ], order="date, name")
            if not orders:
                continue
            atts |= self._render_pdf("l10n_ua_hr_orders.action_report_ua_hr_order_register", orders,
                                     name="%s_%s_%s.pdf" % (labels.get(register), self.year, register))
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

    # ------------------------------------------------------------------ спільні помічники
    # Форматування суми лишається тут: ним підписані і деталі перевірок нижче, і таблиця
    # «Дані» екрана (l10n_ua_reporting_ui), щоб число скрізь виглядало однаково.
    @staticmethod
    def _m(value):
        """Українське форматування суми: 1 194 649,69"""
        return "{:,.2f}".format(value or 0.0).replace(",", "\u00a0").replace(".", ",")

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
        move_domain = [("company_id", "=", self.company_id.id), ("state", "=", "draft"), ("date", ">=", str(d1)), ("date", "<=", str(d2))]
        drafts = self.env["account.move"].search_count([
            ("company_id", "=", self.company_id.id), ("state", "=", "draft"),
            ("date", ">=", d1), ("date", "<=", d2)])
        checks.append(dict({"code": "moves_draft", "title": "Усі проводки періоду проведені",
                       "level": "ok" if not drafts else "warn",
                       "detail": "Чернеток проводок: %s" % drafts, "value": str(drafts)},
                      **_target("account.move", domain=move_domain)))
        total_d = total_c = 0.0
        for code, name, slip_codes, side, scope in PAYROLL_ACCOUNTS:
            account = self._account_by_code(code)
            if not account:
                checks.append(dict({"code": "acc_%s" % code, "title": "Рахунок %s є в плані" % code, "level": "error",
                               "detail": "Рахунку немає", "value": "-"}, **_target("ua.report.run", res_id=self.id)))
                continue
            debit, credit = self._turnover(account, d1, d2)
            total_d += debit
            total_c += credit
            expected = self._slip_amount(d1, d2, slip_codes, scope)
            actual = credit if side == "credit" else debit
            diff = round(actual - expected, 2)
            line_domain = [("account_id", "=", account.id), ("parent_state", "=", "posted"),
                           ("date", ">=", str(d1)), ("date", "<=", str(d2)), ("company_id", "=", self.company_id.id)]
            checks.append(dict({
                "code": "turnover_%s" % code,
                "title": "Оборот %s (%s) дорівнює листкам" % (code, name),
                "level": "ok" if abs(diff) <= 0.01 else "error",
                "detail": "Проводки: %s; листки: %s; різниця: %s" % (self._m(actual), self._m(expected), self._m(diff)),
                "value": self._m(actual),
            }, **_target("account.move.line", domain=line_domain)))
        all_lines_domain = [("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
                            ("date", ">=", str(d1)), ("date", "<=", str(d2))]
        all_lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("parent_state", "=", "posted"),
            ("date", ">=", d1), ("date", "<=", d2)])
        sd, sc = round(sum(all_lines.mapped("debit")), 2), round(sum(all_lines.mapped("credit")), 2)
        checks.append(dict({"code": "balance", "title": "Дебет дорівнює кредиту за період",
                       "level": "ok" if abs(sd - sc) <= 0.01 else "error",
                       "detail": "Дебет %s, кредит %s" % (self._m(sd), self._m(sc)), "value": self._m(sd)},
                      **_target("account.move.line", domain=all_lines_domain)))
        unrec_domain = [("company_id", "=", self.company_id.id), ("is_reconciled", "=", False), ("date", ">=", str(d1)), ("date", "<=", str(d2))]
        unrec = self.env["account.bank.statement.line"].search_count([
            ("company_id", "=", self.company_id.id), ("is_reconciled", "=", False),
            ("date", ">=", d1), ("date", "<=", d2)])
        checks.append(dict({"code": "unreconciled", "title": "Рядки виписки звірені",
                       "level": "ok" if not unrec else "warn",
                       "detail": "Незвірених рядків: %s" % unrec, "value": str(unrec)},
                      **_target("account.bank.statement.line", domain=unrec_domain)))
        return checks

    def _checks_trial(self):
        return self._checks_accounting()

    def _checks_ledger(self):
        return self._checks_accounting()

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



class UaReportCheck(models.Model):
    """Рядок перевірки звітного прогону. Лише для читання з UI - рядки пише сам прогін
    (action_refresh(), через sudo()); ir.model.access.csv забороняє create/write/unlink звичайним
    користувачам, форма і список (якщо відкриті технічно) також readonly."""
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
    # ціль перевірки: запис(и), яких вона стосується - hr.employee, hr.payslip, res.company тощо.
    # Кожна перевірка, що називає записи, має ціль; та, що не про записи (напр. валідність XML),
    # ціллю має сам прогін (ua.report.run). Заповнюється кодом, що будує перевірку - див. _target().
    target_model = fields.Char()
    target_domain = fields.Text(help="Домен цілі, JSON-список.")
    target_res_id = fields.Integer()

