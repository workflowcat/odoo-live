"""Річний план закупівель (Закон «Про публічні закупівлі» № 922-VIII, ст. 4).

Рядок плану - що купуємо: код ДК 021, очікувана вартість з ПДВ, процедура, місяць початку,
джерело фінансування. Предмет закупівлі товарів і послуг визначається за четвертою цифрою
коду ДК 021 (клас; порядок визначення предмета закупівлі, наказ Мінекономіки № 708 від
15.04.2020): рядки одного класу - один предмет, їхня вартість складається. Процедуру
вибирають за сумою предмета, тож якщо предмет розбито на частини під поріг, перевірка це
покаже. Роботи (розділ 45) - кожен рядок окремий предмет.

Пороги стоять на плані, а не в коді: під час воєнного стану діють особливості постанови
КМУ № 1178 від 12.10.2022, і їх змінюють. Значення за замовчуванням - заготовка, яку
звіряють із чинною редакцією; новий план бере пороги з попереднього плану компанії.

Затверджений план не правиться. Зміни - нова редакція з тими самими рядками: стара
лишається в історії, як вимагає оприлюднення змін до плану.
"""
import json
from collections import defaultdict
from datetime import date

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PROCEDURES = [
    ("open", "Відкриті торги з особливостями"),
    ("catalog", "Електронний каталог"),
    ("direct_report", "Без процедури, звіт про договір"),
    ("direct", "Без процедури і без звіту"),
    ("exception", "Договір за винятком, без торгів"),
]
STRONG = ("open", "catalog", "exception")
FUNDING = [
    ("own", "Власні кошти"), ("state", "Державний бюджет"), ("local", "Місцевий бюджет"),
    ("fund", "Цільовий фонд"), ("loan", "Кредит"), ("other", "Інше"),
]
MONTHS = [(str(n), name) for n, name in enumerate(
    ("січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень",
     "вересень", "жовтень", "листопад", "грудень"), start=1)]
KINDS = [("goods", "Товари"), ("services", "Послуги"), ("works", "Роботи")]
# Тип процедури в API Prozorro для файла плану; «без звіту» на майданчик не йде.
PROZORRO_TYPES = {"open": "aboveThreshold", "catalog": "priceQuotation",
                  "direct_report": "reporting", "exception": "reporting"}
# Заготовка порогів; див. довідку полів плану.
DEFAULT_OPEN_GOODS = 100000.0
DEFAULT_OPEN_WORKS = 1500000.0
DEFAULT_REPORT_FROM = 50000.0
ORDERED_STATES = ("purchase", "done")


def money(amount):
    """1 240 000,00 - сума для тексту перевірки й друку."""
    return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")


def subject_code(code):
    """Клас ДК 021 (чотири цифри) - ключ предмета закупівлі товарів і послуг."""
    return (code or "")[:4]


class UaProcurementPlan(models.Model):
    _name = "ua.procurement.plan"
    _inherit = ["mail.thread"]
    _description = "Річний план закупівель"
    _order = "year desc, revision desc, id desc"
    _check_company_auto = True

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Замовник", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("Рік", required=True, tracking=True,
                          default=lambda self: fields.Date.context_today(self).year)
    revision = fields.Integer("Редакція", default=1, readonly=True, copy=False)
    origin_id = fields.Many2one("ua.procurement.plan", "Попередня редакція", readonly=True,
                                copy=False)
    state = fields.Selection(
        [("draft", "Чернетка"), ("approved", "Затверджено"), ("superseded", "Замінено новою редакцією")],
        "Стан", default="draft", required=True, tracking=True, copy=False, index=True)
    date_approved = fields.Date("Затверджено", readonly=True, copy=False, tracking=True)
    approved_by_id = fields.Many2one("res.users", "Затвердив", readonly=True, copy=False)
    approval_doc = fields.Char(
        "Рішення про затвердження", tracking=True,
        help="Протокол тендерного комітету чи рішення уповноваженої особи: номер і дата.")
    open_goods = fields.Monetary(
        "Відкриті торги: товари і послуги від", default=lambda s: s._default_threshold("open_goods"),
        help="Предмет закупівлі товарів чи послуг такої вартості і більше купують відкритими "
             "торгами з особливостями (товари - також через електронний каталог). Звірте з "
             "чинною редакцією постанови КМУ № 1178 і Закону № 922-VIII.")
    open_works = fields.Monetary(
        "Відкриті торги: роботи від", default=lambda s: s._default_threshold("open_works"),
        help="Те саме для робіт. Звірте з чинною редакцією.")
    report_from = fields.Monetary(
        "Звіт про договір від", default=lambda s: s._default_threshold("report_from"),
        help="Договір без процедури на таку суму і більше оприлюднюють звітом про договір. "
             "Звірте з чинною редакцією.")
    line_ids = fields.One2many("ua.procurement.plan.line", "plan_id", "Рядки плану", copy=True)
    amount_total = fields.Monetary("Разом за планом", compute="_compute_amount_total", store=True)
    error_count = fields.Integer("Помилок", compute="_compute_check_counts")
    warn_count = fields.Integer("Попереджень", compute="_compute_check_counts")
    actual_html = fields.Html("План і замовлення", compute="_compute_actual_html", sanitize=False)
    note = fields.Text("Примітка")

    _one_live_plan = models.UniqueIndex(
        "(company_id, year) WHERE state != 'superseded'",
        "На цей рік у компанії вже є план. Зміни вносять новою редакцією.")

    @api.model
    def _default_threshold(self, field):
        previous = self.search([("company_id", "=", self.env.company.id)],
                               order="year desc, revision desc", limit=1)
        if previous:
            return previous[field]
        return {"open_goods": DEFAULT_OPEN_GOODS, "open_works": DEFAULT_OPEN_WORKS,
                "report_from": DEFAULT_REPORT_FROM}[field]

    @api.depends("year", "revision")
    def _compute_name(self):
        for plan in self:
            plan.name = _("Річний план закупівель на %(year)s рік, редакція %(rev)s",
                          year=plan.year, rev=plan.revision)

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for plan in self:
            plan.amount_total = sum(plan.line_ids.mapped("amount"))

    def _compute_check_counts(self):
        for plan in self:
            levels = [level for level, _text in plan._line_checks().values()]
            plan.error_count = levels.count("error")
            plan.warn_count = levels.count("warn")

    @api.constrains("year", "open_goods", "open_works", "report_from")
    def _check_values(self):
        for plan in self:
            if not 2000 <= plan.year <= 2100:
                raise ValidationError(_("Рік плану - чотири цифри."))
            if min(plan.open_goods, plan.open_works, plan.report_from) <= 0:
                raise ValidationError(_("Пороги плану мають бути більшими за нуль."))

    def unlink(self):
        if any(plan.state != "draft" for plan in self):
            raise UserError(_("Затверджений план і старі редакції не видаляють."))
        return super().unlink()

    # ---------------------------------------------------------------- предмети
    def subject_rows(self):
        """Предмети закупівлі: [{key, dk021, name, kind, total, threshold, lines}]."""
        self.ensure_one()
        groups = defaultdict(lambda: self.env["ua.procurement.plan.line"])
        for line in self.line_ids.filtered("dk021_id").sorted(lambda l: (l.dk021_id.code, l.id)):
            groups[line._subject_key()] |= line
        rows = []
        for key, lines in groups.items():
            first = lines[0]
            kind = first.kind
            rows.append({
                "key": key, "dk021": first._subject_dk021(), "kind": kind,
                "name": first.name if len(lines) == 1 else first._subject_dk021().name,
                "total": sum(lines.mapped("amount")), "lines": lines,
                "threshold": self.open_works if kind == "works" else self.open_goods,
                "procedures": set(lines.mapped("procedure")),
            })
        return rows

    def _ordered(self):
        """{клас ДК 021: сума підтверджених замовлень постачальникам за рік, у гривні}."""
        self.ensure_one()
        start, end = date(self.year, 1, 1), date(self.year, 12, 31)
        lines = self.env["purchase.order.line"].search([
            ("company_id", "=", self.company_id.id), ("order_id.state", "in", ORDERED_STATES),
            ("order_id.date_approve", ">=", fields.Datetime.to_datetime(start)),
            ("order_id.date_approve", "<", fields.Datetime.to_datetime(date(self.year + 1, 1, 1))),
            ("ua_dk021_id", "!=", False), ("display_type", "=", False)])
        totals = defaultdict(float)
        company_currency = self.company_id.currency_id
        for line in lines:
            amount = line.currency_id._convert(
                line.price_total, company_currency, self.company_id,
                line.order_id.date_approve.date() if line.order_id.date_approve else end)
            totals[subject_code(line.ua_dk021_id.code)] += amount
        return totals

    def actual_rows(self):
        """План проти замовлень за класами ДК 021: [{code, name, planned, ordered, left, level}]."""
        self.ensure_one()
        planned = defaultdict(float)
        names = {}
        for line in self.line_ids.filtered("dk021_id"):
            code = subject_code(line.dk021_id.code)
            planned[code] += line.amount
            names.setdefault(code, line._subject_dk021().display_name)
        ordered = self._ordered()
        Dk = self.env["ua.dk021"]
        rows = []
        for code in sorted(set(planned) | set(ordered)):
            plan, done = planned.get(code, 0.0), ordered.get(code, 0.0)
            if code not in names:
                names[code] = Dk.search([("code", "=like", code + "0000-%")], limit=1).display_name \
                    or code
            level = "error" if not plan else \
                "warn" if self.currency_id.compare_amounts(done, plan) > 0 else "ok"
            rows.append({"code": code, "name": names[code], "planned": plan, "ordered": done,
                         "left": plan - done, "level": level})
        return rows

    # ---------------------------------------------------------------- перевірки
    def _line_checks(self):
        """{id рядка: (рівень, текст)} для рядків цього плану."""
        self.ensure_one()
        result = {line.id: ("ok", "") for line in self.line_ids}
        over = {row["code"]: row for row in self.actual_rows() if row["level"] == "warn"} \
            if self.line_ids else {}

        def put(line, level, text):
            rank = {"ok": 0, "warn": 1, "error": 2}
            if rank[level] > rank[result[line.id][0]]:
                result[line.id] = (level, text)

        for row in self.subject_rows():
            subject = row["dk021"].code or row["key"]
            for line in row["lines"]:
                if row["total"] >= row["threshold"] and line.procedure not in STRONG:
                    put(line, "error", _(
                        "Предмет %(subject)s: %(total)s - від %(threshold)s потрібні відкриті "
                        "торги або каталог", subject=subject, total=money(row["total"]),
                        threshold=money(row["threshold"])))
                if line.procedure == "catalog" and line.kind != "goods":
                    put(line, "error", _("Електронний каталог - лише для товарів"))
                if line.procedure == "exception" and not (line.exception_reason or "").strip():
                    put(line, "error", _("Вкажіть підставу винятку: пункт постанови чи статтю закону"))
                if line.procedure == "direct" and row["total"] >= self.report_from:
                    put(line, "error", _("Від %s договір оприлюднюють звітом про договір")
                        % money(self.report_from))
                if len(row["procedures"]) > 1:
                    put(line, "warn", _("В одному предметі різні процедури: перевірте, чи не "
                                        "поділено предмет закупівлі"))
                done = over.get(subject_code(line.dk021_id.code))
                if done:
                    put(line, "warn", _("Замовлено %(ordered)s із запланованих %(planned)s: "
                                        "внесіть зміни до плану", ordered=money(done["ordered"]),
                                        planned=money(done["planned"])))
        return result

    @api.depends("line_ids.amount", "line_ids.dk021_id", "year")
    def _compute_actual_html(self):
        marks = {"ok": "", "warn": _("більше за план"), "error": _("немає в плані")}
        for plan in self:
            rows = plan.actual_rows() if plan.year else []
            if not rows:
                plan.actual_html = False
                continue
            body = Markup("").join(
                Markup("<tr class='%s'><td>%s</td><td class='text-end'>%s</td>"
                       "<td class='text-end'>%s</td><td class='text-end'>%s</td><td>%s</td></tr>") % (
                    {"ok": "", "warn": "text-warning", "error": "text-danger"}[row["level"]],
                    row["name"], money(row["planned"]), money(row["ordered"]),
                    money(row["left"]), marks[row["level"]])
                for row in rows)
            plan.actual_html = Markup(
                "<table class='table table-sm'><thead><tr><th>%s</th><th class='text-end'>%s</th>"
                "<th class='text-end'>%s</th><th class='text-end'>%s</th><th></th></tr></thead>"
                "<tbody>%s</tbody></table>") % (
                _("Клас ДК 021"), _("Заплановано"), _("Замовлено"), _("Залишок"), body)

    # ---------------------------------------------------------------- дії
    def action_approve(self):
        for plan in self:
            if plan.state != "draft":
                raise UserError(_("Затвердити можна лише чернетку."))
            if not plan.line_ids:
                raise UserError(_("У плані немає рядків."))
            errors = [text for level, text in plan._line_checks().values() if level == "error"]
            if errors:
                raise UserError(_("План не можна затвердити:\n%s") % "\n".join(
                    "- %s" % text for text in dict.fromkeys(errors)))
            plan.write({"state": "approved", "date_approved": fields.Date.context_today(plan),
                        "approved_by_id": self.env.user.id})
        return True

    def action_amend(self):
        """Зміни до затвердженого плану: нова редакція-чернетка з тими самими рядками."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError(_("Зміни вносять до затвердженого плану."))
        self.state = "superseded"
        self.flush_recordset(["state"])
        new = self.copy({"revision": self.revision + 1, "origin_id": self.id,
                         "approval_doc": False})
        new.message_post(body=_("Нова редакція плану замість редакції %s.") % self.revision)
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": new.id,
                "view_mode": "form"}

    @api.model
    def _money(self, amount):
        return money(amount)

    def action_print(self):
        return self.env.ref("l10n_ua_procurement_plan.action_report_ua_procurement_plan") \
            .report_action(self)

    def prozorro_plans(self):
        """Предмети плану у вигляді планів API Prozorro (без процедури і звіту - не йдуть)."""
        self.ensure_one()
        company = self.company_id
        plans = []
        for row in self.subject_rows():
            lines = row["lines"].filtered(lambda l: l.procedure in PROZORRO_TYPES)
            if not lines:
                continue
            first = lines.sorted(lambda l: (int(l.month), l.id))[0]
            start = "%04d-%02d-01" % (self.year, int(first.month))
            breakdown = defaultdict(float)
            for line in lines:
                breakdown[line.funding] += line.amount
            plans.append({
                "procuringEntity": {"name": company.name, "identifier": {
                    "scheme": "UA-EDR", "id": company.company_registry or None}},
                "classification": {"scheme": "ДК021", "id": row["dk021"].code,
                                   "description": row["dk021"].name},
                "budget": {
                    "description": row["name"], "amount": round(sum(lines.mapped("amount")), 2),
                    "currency": self.currency_id.name, "year": self.year,
                    "period": {"startDate": start, "endDate": "%04d-12-31" % self.year},
                    "breakdown": [{"title": key, "amount": round(value, 2)}
                                  for key, value in sorted(breakdown.items())],
                },
                "tender": {"procurementMethodType": PROZORRO_TYPES[first.procedure],
                           "tenderPeriod": {"startDate": start}},
                "items": [{"description": line.name, "classification": {
                    "scheme": "ДК021", "id": line.dk021_id.code,
                    "description": line.dk021_id.name}} for line in lines],
            })
        return plans

    def action_export_json(self):
        """Файл для майданчика: предмети плану в структурі планів API Prozorro."""
        self.ensure_one()
        content = json.dumps({"year": self.year, "revision": self.revision,
                              "plans": self.prozorro_plans()}, ensure_ascii=False, indent=2)
        attachment = self.env["ir.attachment"].create({
            "name": "plan-%s-r%s.json" % (self.year, self.revision), "raw": content.encode(),
            "mimetype": "application/json", "res_model": self._name, "res_id": self.id})
        return {"type": "ir.actions.act_url", "target": "self",
                "url": "/web/content/%s?download=true" % attachment.id}


class UaProcurementPlanLine(models.Model):
    _name = "ua.procurement.plan.line"
    _description = "Рядок річного плану закупівель"
    _order = "plan_id, sequence, id"

    plan_id = fields.Many2one("ua.procurement.plan", "План", required=True, index=True,
                              ondelete="cascade")
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related="plan_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="plan_id.currency_id")
    plan_state = fields.Selection(related="plan_id.state")
    dk021_id = fields.Many2one("ua.dk021", "Код ДК 021", required=True, index=True)
    kind = fields.Selection(KINDS, "Вид", compute="_compute_kind", store=True)
    name = fields.Char("Предмет закупівлі", required=True)
    amount = fields.Monetary("Очікувана вартість з ПДВ", required=True)
    procedure = fields.Selection(PROCEDURES, "Процедура", required=True, default="open")
    month = fields.Selection(MONTHS, "Орієнтовний початок", required=True, default="1")
    funding = fields.Selection(FUNDING, "Джерело фінансування", required=True, default="own")
    kekv = fields.Char("КЕКВ", help="Код економічної класифікації видатків - для бюджетних коштів.")
    exception_reason = fields.Char(
        "Підстава винятку", help="Пункт постанови № 1178 чи стаття закону, за якими договір "
                                 "укладають без торгів.")
    note = fields.Char("Примітка")
    check_level = fields.Selection([("ok", "Гаразд"), ("warn", "Увага"), ("error", "Помилка")],
                                   "Перевірка", compute="_compute_check")
    check_text = fields.Char("Що не так", compute="_compute_check")

    @api.depends("dk021_id.code", "dk021_id.is_service")
    def _compute_kind(self):
        for line in self:
            code = line.dk021_id.code or ""
            line.kind = "works" if code.startswith("45") else \
                "services" if line.dk021_id.is_service else "goods"

    @api.depends("plan_id.line_ids.amount", "plan_id.line_ids.procedure",
                 "plan_id.line_ids.dk021_id", "plan_id.line_ids.exception_reason",
                 "plan_id.open_goods", "plan_id.open_works", "plan_id.report_from")
    def _compute_check(self):
        checks = {}
        for plan in self.plan_id:
            checks.update(plan._line_checks())
        for line in self:
            line.check_level, line.check_text = checks.get(line.id, ("ok", ""))

    @api.constrains("amount")
    def _check_amount(self):
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Очікувана вартість рядка плану має бути більшою за нуль."))

    def _procedure_label(self):
        return dict(PROCEDURES).get(self.procedure, "")

    def _month_label(self):
        return dict(MONTHS).get(self.month, "")

    def _funding_label(self):
        return dict(FUNDING).get(self.funding, "")

    def _subject_key(self):
        self.ensure_one()
        if self.kind == "works":
            return "W%s" % (self.id or self.name)
        return subject_code(self.dk021_id.code)

    def _subject_dk021(self):
        """Код класу ДК 021, за яким визначено предмет; для робіт - код рядка."""
        self.ensure_one()
        if self.kind == "works":
            return self.dk021_id
        key = subject_code(self.dk021_id.code)
        return self.env["ua.dk021"].search([("code", "=like", key + "0000-%")], limit=1) \
            or self.dk021_id

    def write(self, vals):
        if any(line.plan_id.state != "draft" for line in self):
            raise UserError(_("Затверджений план не правиться: внесіть зміни новою редакцією."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        plans = self.env["ua.procurement.plan"].browse(
            [v["plan_id"] for v in vals_list if v.get("plan_id")])
        if any(plan.state != "draft" for plan in plans.exists()):
            raise UserError(_("Затверджений план не правиться: внесіть зміни новою редакцією."))
        return super().create(vals_list)

    def unlink(self):
        if any(line.plan_id.state != "draft" for line in self):
            raise UserError(_("Затверджений план не правиться: внесіть зміни новою редакцією."))
        return super().unlink()
