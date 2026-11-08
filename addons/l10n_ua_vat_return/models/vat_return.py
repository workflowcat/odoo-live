# -*- coding: utf-8 -*-
"""Податкова декларація з ПДВ за місяць (J0200126) з додатком Д2 (J0215226).

Числа не рахуються вдруге: декларація бере зведення ПДВ за той самий місяць (ua.vat.period з
l10n_ua_vat) і розкладає його по рядках форми в гривнях без копійок. Рядки можна поправити
вручну в чернетці; підсумки 9, 17-21 рахуються з рядків.

Рядки (наказ Мінфіну № 21 у редакції наказу № 400 від 2024 року; звіряйте чинну):
    1.1 / 1.2 / 1.3   постачання за ставкою 20 %, 7 %, 14 % (аванси першої події - у 1.1)
    2.1               вивезення товарів за межі митної території, 0 %
    4.1, 4.1.1        компенсуючі ПЗ за п. 198.5 і ст. 199 ПКУ, річний перерахунок частки
    5, 5.1            не є об'єктом, звільнені; у тому числі звільнені
    7.1               коригування ПЗ (розрахунки коригування на повернення)
    9                 усього ПЗ
    10.1 / 10.2 / 10.3  придбання на митній території за ставкою 20 %, 7 %, 14 %
    11.1              ввезення товарів (митний ПДВ), основна ставка
    14                коригування ПК
    16.1              від'ємне значення попереднього періоду (рядок 21 попередньої декларації)
    17                усього ПК
    18 / 19           до сплати / від'ємне значення
    19.1, 20, 20.x    понад суму, на яку можна зареєструвати ПН (Σнакл), і в її межах:
                      у погашення боргу (20.1), до бюджетного відшкодування (20.2)
    21                від'ємне значення до ПК наступного періоду (19.1 + 20.3)

Д2: від'ємне значення рядка 19 за періодами виникнення і постачальниками. Залишок минулого
місяця переходить рядками Д2 попередньої декларації; нова частина лягає на найпізніші
вхідні накладні місяця, кожна в межах свого ПДВ, решта (імпорт, зменшення ПЗ) - на власний
ІПН. Погашення боргу і відшкодування беруться з найстаріших рядків.

Не робимо: Д1 (незареєстровані ПН і РК), Д3-Д6, рядки 2.2, 2.3.x, 3, 6, 8, 12, 13, 15, 16.2,
16.3, уточнюючу декларацію. XML і схеми - для періодів з жовтня 2024 року.
"""
import base64
import calendar
import re
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

from odoo.addons.l10n_ua_finrep_dps.models import dps_xml

FORM_MAIN = "J0200126"
FORM_D2 = "J0215226"
# Перший звітний місяць цієї версії форми (наказ № 400 від 2024 року); звіряйте чинну.
FORM_FROM = date(2024, 10, 1)

STATES = [("draft", "Чернетка"), ("done", "Затверджено")]
DOC_KINDS = [("HZ", "Звітна"), ("HZN", "Звітна нова")]
MONTHS = [(str(m), name) for m, name in enumerate(
    ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень",
     "Вересень", "Жовтень", "Листопад", "Грудень"], start=1)]

# (код рядка, назва, вид, тег обсягу, тег ПДВ). Вид: pz - у рядок 9, pk - у рядок 17,
# info - лише обсяг.
ROWS = [
    ("1.1", "Постачання за основною ставкою (20 %)", "pz", "R11GA", "R11GB"),
    ("1.2", "Постачання за ставкою 7 %", "pz", "R12GA", "R12GB"),
    ("1.3", "Постачання за ставкою 14 %", "pz", "R13GA", "R13GB"),
    ("2.1", "Вивезення товарів за межі митної території (0 %)", "info", "R21GA", False),
    ("4.1", "Компенсуючі ПЗ (п. 198.5, ст. 199 ПКУ), основна ставка", "pz", "R41GA", "R41GB"),
    ("4.1.1", "Коригування компенсуючих ПЗ, річний перерахунок частки", "pz", "R411GA", "R411GB"),
    ("5", "Не є об'єктом оподаткування, звільнені", "info", "R50GA", False),
    ("5.1", "У тому числі звільнені від оподаткування", "info", "R51GA", False),
    ("7.1", "Коригування обсягів постачання і ПЗ", "pz", "R71GA", "R71GB"),
    ("10.1", "Придбання на митній території за основною ставкою (20 %)", "pk", "R101GA", "R101GB"),
    ("10.2", "Придбання за ставкою 7 %", "pk", "R102GA", "R102GB"),
    ("10.3", "Придбання за ставкою 14 %", "pk", "R103GA", "R103GB"),
    ("11.1", "Ввезення товарів, основна ставка (митний ПДВ)", "pk", "R111GA", "R111GB"),
    ("14", "Коригування податкового кредиту", "pk", "R140GA", "R140GB"),
]
ROW_INFO = {code: (kind, tag_a, tag_b) for code, _name, kind, tag_a, tag_b in ROWS}


def _uah(value):
    return float_round(value or 0.0, precision_digits=0)


def _digits(value):
    return re.sub(r"\D", "", value or "")


class UaVatReturn(models.Model):
    _name = "ua.vat.return"
    _description = "Декларація з ПДВ"
    _inherit = ["mail.thread"]
    _order = "date_to desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    year = fields.Integer("Рік", required=True, default=lambda s: s._default_period()[0])
    month = fields.Selection(MONTHS, "Місяць", required=True, default=lambda s: str(s._default_period()[1]))
    date_from = fields.Date("Початок", compute="_compute_dates", store=True)
    date_to = fields.Date("Кінець", compute="_compute_dates", store=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True, copy=False)
    doc_kind = fields.Selection(DOC_KINDS, "Вид декларації", default="HZ", required=True)
    new_number = fields.Integer("Номер звітної нової", default=1,
                                help="Для звітної нової: котра вона за цей місяць (C_DOC_TYPE у файлі).")
    summary_id = fields.Many2one("ua.vat.period", "Зведення ПДВ", readonly=True, copy=False)
    line_ids = fields.One2many("ua.vat.return.line", "return_id", "Рядки", copy=False)
    d2_line_ids = fields.One2many("ua.vat.return.d2", "return_id", "Д2: від'ємне значення", copy=False)
    problems = fields.Text("Зауваження", readonly=True, copy=False)

    r9 = fields.Monetary("9 Усього ПЗ", compute="_compute_totals", store=True)
    r16_1 = fields.Monetary(
        "16.1 Від'ємне значення попереднього періоду",
        help="Рядок 21 декларації за попередній місяць. Береться з неї під час розрахунку; "
             "якщо попередню декларацію подано не звідси - введіть вручну.")
    r17 = fields.Monetary("17 Усього ПК", compute="_compute_totals", store=True)
    r18 = fields.Monetary("18 До сплати", compute="_compute_totals", store=True)
    r19 = fields.Monetary("19 Від'ємне значення", compute="_compute_totals", store=True)
    limit_amount = fields.Monetary(
        "Σнакл (п. 200-1.3 ПКУ)",
        help="Сума, на яку можна зареєструвати ПН і РК в ЄРПН на дату подання, з електронного "
             "кабінету. Від'ємне значення понад неї йде в рядок 19.1, решта - у рядок 20.")
    r19_1 = fields.Monetary("19.1 Понад Σнакл", compute="_compute_totals", store=True)
    r20 = fields.Monetary("20 У межах Σнакл", compute="_compute_totals", store=True)
    r20_1 = fields.Monetary("20.1 У погашення податкового боргу з ПДВ")
    r20_2_1 = fields.Monetary("20.2.1 Бюджетне відшкодування на рахунок у банку")
    r20_2_2 = fields.Monetary("20.2.2 Бюджетне відшкодування в рахунок інших платежів")
    r20_2 = fields.Monetary("20.2 Бюджетне відшкодування", compute="_compute_totals", store=True)
    r20_3 = fields.Monetary("20.3 Залишок у межах Σнакл", compute="_compute_totals", store=True)
    r21 = fields.Monetary("21 До ПК наступного періоду", compute="_compute_totals", store=True)

    tin = fields.Char("Код ЄДРПОУ", default=lambda s: _digits(s.env.company.company_registry))
    ipn = fields.Char("ІПН платника ПДВ", default=lambda s: _digits(s.env.company.vat))
    sti_code = fields.Char("Код ДПІ", size=4,
                           default=lambda s: s._ua_company_value("ua_dps_sti", "ua_sti_code"),
                           help="Чотири цифри: перші дві - область (C_REG), дві наступні - район (C_RAJ).")
    sti_name = fields.Char("Назва ДПІ", default=lambda s: s._ua_company_value("ua_sti_name"))
    address = fields.Char("Адреса", default=lambda s: s._ua_company_address())
    phone = fields.Char("Телефон", default=lambda s: s.env.company.phone)
    email = fields.Char("Ел. пошта", default=lambda s: s.env.company.email)
    director = fields.Char("Керівник", default=lambda s: s._ua_company_value("ua_director_name"))
    director_rnokpp = fields.Char("РНОКПП керівника", size=10,
                                  default=lambda s: s._ua_company_value("ua_director_rnokpp"))
    accountant = fields.Char("Головний бухгалтер", default=lambda s: s._ua_company_value("ua_accountant_name"))
    accountant_rnokpp = fields.Char("РНОКПП бухгалтера", size=10,
                                    default=lambda s: s._ua_company_value("ua_accountant_rnokpp"))
    xml_file = fields.Binary("Декларація XML", attachment=True, readonly=True, copy=False)
    xml_name = fields.Char("Ім'я файлу декларації", readonly=True, copy=False)
    d2_xml_file = fields.Binary("Д2 XML", attachment=True, readonly=True, copy=False)
    d2_xml_name = fields.Char("Ім'я файлу Д2", readonly=True, copy=False)

    _period_uniq = models.Constraint(
        "unique(company_id, year, month, doc_kind, new_number)",
        "Декларація цього виду за цей місяць уже є.")

    @api.model
    def _default_period(self):
        today = fields.Date.context_today(self)
        return (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    @api.depends("year", "month", "doc_kind")
    def _compute_name(self):
        kinds = dict(DOC_KINDS)
        for doc in self:
            doc.name = _("Декларація з ПДВ %(month)02d.%(year)s (%(kind)s)") % {
                "month": int(doc.month or 0), "year": doc.year or "", "kind": kinds.get(doc.doc_kind, "").lower()}

    @api.depends("year", "month")
    def _compute_dates(self):
        for doc in self:
            if doc.year and doc.month:
                month = int(doc.month)
                doc.date_from = date(doc.year, month, 1)
                doc.date_to = date(doc.year, month, calendar.monthrange(doc.year, month)[1])
            else:
                doc.date_from = doc.date_to = False

    @api.depends("line_ids.vat", "r16_1", "limit_amount", "r20_1", "r20_2_1", "r20_2_2")
    def _compute_totals(self):
        for doc in self:
            r9 = sum(line.vat for line in doc.line_ids if ROW_INFO.get(line.code, ("",))[0] == "pz")
            r17 = sum(line.vat for line in doc.line_ids if ROW_INFO.get(line.code, ("",))[0] == "pk") + doc.r16_1
            diff = r9 - r17
            r19 = max(-diff, 0.0)
            r19_1 = max(r19 - max(doc.limit_amount, 0.0), 0.0)
            r20 = r19 - r19_1
            r20_2 = doc.r20_2_1 + doc.r20_2_2
            r20_3 = r20 - doc.r20_1 - r20_2
            doc.update({"r9": r9, "r17": r17, "r18": max(diff, 0.0), "r19": r19, "r19_1": r19_1, "r20": r20,
                        "r20_2": r20_2, "r20_3": r20_3, "r21": r19_1 + r20_3})

    @api.constrains("year")
    def _check_year(self):
        for doc in self:
            if not 2000 <= doc.year <= 2099:
                raise ValidationError(_("Рік декларації - чотири цифри, від 2000."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError(_("Видалити можна лише чернетку."))

    @api.model
    def _ua_company_value(self, *names):
        """Реквізит компанії з поля іншого модуля, якщо такий модуль стоїть (звітність з ЄСВ, ПДВ)."""
        company = self.env.company
        for name in names:
            if name in company._fields and company[name]:
                return company[name]
        return False

    @api.model
    def _ua_company_address(self):
        company = self.env.company
        return ", ".join(filter(None, [company.zip, company.state_id.name, company.city, company.street,
                                       company.street2])) or False

    # ------------------------------------------------------------------ розрахунок
    def _ua_previous(self):
        self.ensure_one()
        return self.search([("company_id", "=", self.company_id.id), ("date_to", "<", self.date_from),
                            ("state", "=", "done")], order="date_to desc, id desc", limit=1)

    def _ua_summary(self):
        """Зведення ПДВ рівно за цей місяць: наявне або нове; перераховується."""
        self.ensure_one()
        summary = self.summary_id or self.env["ua.vat.period"].search([
            ("company_id", "=", self.company_id.id), ("date_from", "=", self.date_from),
            ("date_to", "=", self.date_to)], order="id desc", limit=1)
        if not summary:
            summary = self.env["ua.vat.period"].create({
                "company_id": self.company_id.id, "date_from": self.date_from, "date_to": self.date_to})
        summary.action_compute()
        return summary

    def _ua_row_values(self, summary):
        """{код: (обсяг, ПДВ)} у гривнях без копійок зі зведення."""
        s = summary
        # Аванси першої події - за основною ставкою: обсяг = ПДВ × 100 / 20.
        return {
            "1.1": (s.ua_r1_base + s.ua_fe_vat * 5.0, s.ua_r1_vat + s.ua_fe_vat),
            "1.2": (s.ua_r3_base, s.ua_r3_vat),
            "1.3": (s.ua_r2_base, s.ua_r2_vat),
            "2.1": (s.ua_r_export_base, 0.0),
            "4.1": (s.ua_r41_base, s.ua_r41_vat),
            "4.1.1": (0.0, s.ua_r411_vat),
            "5": (s.ua_r_exempt_base, 0.0),
            "5.1": (s.ua_r_exempt_base, 0.0),
            "7.1": (s.ua_r7_base, s.ua_r7_vat),
            "10.1": (s.ua_pk1_base, s.ua_pk1_vat),
            "10.2": (s.ua_pk3_base, s.ua_pk3_vat),
            "10.3": (s.ua_pk2_base, s.ua_pk2_vat),
            # Митний ПДВ - за основною ставкою: обсяг = ПДВ × 100 / 20.
            "11.1": (s.ua_customs_vat * 5.0, s.ua_customs_vat),
            "14": (s.ua_r14_base, s.ua_r14_vat),
        }

    def action_compute(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Декларацію затверджено: поверніть її в чернетку, щоб перерахувати."))
            summary = doc._ua_summary()
            values = doc._ua_row_values(summary)
            doc.line_ids.unlink()
            lines = []
            for sequence, (code, name, _kind, _tag_a, _tag_b) in enumerate(ROWS, start=1):
                base, vat = values.get(code, (0.0, 0.0))
                lines.append((0, 0, {"sequence": sequence * 10, "code": code, "name": name,
                                     "base": _uah(base), "vat": _uah(vat)}))
            vals = {"summary_id": summary.id, "line_ids": lines}
            previous = doc._ua_previous()
            if previous:
                vals["r16_1"] = previous.r21
            doc.write(vals)
            doc._ua_fill_d2()
            doc.problems = "\n".join(filter(None, [
                summary.problems or "", "\n".join("- %s" % p for p in doc._ua_problems())])) or _("Зауважень немає.")
        return True

    # ------------------------------------------------------------------ Д2
    def _ua_d2_sources(self):
        """[(дата, ІПН, партнер, місяць, рік, ПДВ)] вхідного ПДВ місяця, найпізніші першими."""
        self.ensure_one()
        own = _digits(self.ipn)
        groups = {}
        moves = self.env["account.move"].search([
            ("move_type", "=", "in_invoice"), ("state", "=", "posted"), ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", self.date_from), ("invoice_date", "<=", self.date_to)])
        for move in moves:
            if move.amount_tax <= 0:
                continue
            ipn = _digits(move.partner_id.commercial_partner_id.vat)
            partner = move.partner_id.commercial_partner_id.id if ipn else False
            key = (ipn or own, partner, move.invoice_date.month, move.invoice_date.year)
            group = groups.setdefault(key, [move.invoice_date, 0.0])
            group[0] = max(group[0], move.invoice_date)
            group[1] += move.amount_tax
        return sorted(((group[0], *key, group[1]) for key, group in groups.items()),
                      key=lambda item: (item[0], item[1]), reverse=True)

    @staticmethod
    def _ua_consume(rows, amount):
        """Зменшити рядки на amount, починаючи з найстаріших."""
        rows.sort(key=lambda r: (r["origin_year"], r["origin_month"], r["doc_year"], r["doc_month"]))
        for row in rows:
            if amount <= 0:
                break
            used = min(row["amount"], amount)
            row["amount"] -= used
            amount -= used
        rows[:] = [row for row in rows if row["amount"] > 0]

    def _ua_fill_d2(self):
        """Розкласти рядок 19 у Д2: залишок минулого місяця, нова частина, погашення і відшкодування."""
        self.ensure_one()
        self.d2_line_ids.unlink()
        if self.r19 <= 0:
            return
        own = _digits(self.ipn)
        month, year = int(self.month), self.year
        previous = self._ua_previous()
        rows = [{"origin_month": line.origin_month, "origin_year": line.origin_year,
                 "partner_id": line.partner_id.id, "ipn": line.ipn, "doc_month": line.doc_month,
                 "doc_year": line.doc_year, "amount": line.carry_amount}
                for line in previous.d2_line_ids if line.carry_amount > 0]
        missing = self.r16_1 - sum(row["amount"] for row in rows)
        if missing > 0:
            # Попередню декларацію подано не звідси: залишок одним рядком на власний ІПН.
            before = self.date_from - timedelta(days=1)
            rows.append({"origin_month": before.month, "origin_year": before.year, "partner_id": False,
                         "ipn": own, "doc_month": before.month, "doc_year": before.year, "amount": missing})
        elif missing < 0:
            self._ua_consume(rows, -missing)
        new = self.r19 - self.r16_1
        if new > 0:
            for _when, ipn, partner, doc_month, doc_year, vat in self._ua_d2_sources():
                if new <= 0:
                    break
                part = min(_uah(vat), new)
                rows.append({"origin_month": month, "origin_year": year, "partner_id": partner, "ipn": ipn,
                             "doc_month": doc_month, "doc_year": doc_year, "amount": part})
                new -= part
            if new > 0:
                rows.append({"origin_month": month, "origin_year": year, "partner_id": False, "ipn": own,
                             "doc_month": month, "doc_year": year, "amount": new})
        elif new < 0:
            self._ua_consume(rows, -new)
        # Погашення боргу і відшкодування - з найстаріших сум.
        rows.sort(key=lambda r: (r["origin_year"], r["origin_month"], r["doc_year"], r["doc_month"]))
        debt, refund = self.r20_1, self.r20_2
        for row in rows:
            row["debt_amount"] = min(debt, row["amount"])
            debt -= row["debt_amount"]
            row["refund_amount"] = min(refund, row["amount"] - row["debt_amount"])
            refund -= row["refund_amount"]
        rows.reverse()  # таблиця 1 Д2 - у зворотному хронологічному порядку
        self.env["ua.vat.return.d2"].create([dict(row, return_id=self.id, sequence=index * 10)
                                             for index, row in enumerate(rows, start=1)])

    # ------------------------------------------------------------------ перевірки
    def _ua_problems(self):
        self.ensure_one()
        problems = []
        if self.r20_1 + self.r20_2 > self.r20 + 0.001:
            problems.append(_("Погашення боргу і відшкодування (%(asked).0f) більші за рядок 20 (%(r20).0f): "
                              "понад Σнакл відшкодувати не можна.") % {"asked": self.r20_1 + self.r20_2,
                                                                       "r20": self.r20})
        if self.r19 > 0:
            d2 = sum(self.d2_line_ids.mapped("amount"))
            if abs(d2 - self.r19) > 0.001:
                problems.append(_("Д2 графа 6 (%(d2).0f) не дорівнює рядку 19 (%(r19).0f).") % {
                    "d2": d2, "r19": self.r19})
            carry = sum(self.d2_line_ids.mapped("carry_amount"))
            if abs(carry - self.r21) > 0.001:
                problems.append(_("Д2 графа 10 (%(d2).0f) не дорівнює рядку 21 (%(r21).0f).") % {
                    "d2": carry, "r21": self.r21})
        return problems

    def _ua_head_problems(self):
        self.ensure_one()
        problems = []
        if not re.fullmatch(r"\d{8}", _digits(self.tin)):
            problems.append(_("код ЄДРПОУ - 8 цифр"))
        if not re.fullmatch(r"\d{9,12}", _digits(self.ipn)):
            problems.append(_("ІПН платника ПДВ"))
        if not re.fullmatch(r"\d{4}", _digits(self.sti_code)):
            problems.append(_("код ДПІ - 4 цифри"))
        if not (self.sti_name or "").strip():
            problems.append(_("назва ДПІ"))
        if not (self.address or "").strip():
            problems.append(_("адреса"))
        if not (self.director or "").strip():
            problems.append(_("керівник"))
        if not re.fullmatch(r"\d{10}", _digits(self.director_rnokpp)):
            problems.append(_("РНОКПП керівника - 10 цифр"))
        if not self.line_ids:
            problems.append(_("рядки (кнопка «Розрахувати»)"))
        return problems

    # ------------------------------------------------------------------ XML
    def _ua_xml(self):
        """[(ім'я файлу, байти)]: декларація і, якщо рядок 19 не нуль, Д2; перевірені схемами."""
        self.ensure_one()
        if self.date_from < FORM_FROM:
            raise UserError(_("Схема %(form)s - для періодів з %(start)s. Для %(name)s діяла інша версія форми.")
                            % {"form": FORM_MAIN, "start": FORM_FROM.isoformat(), "name": self.name})
        problems = self._ua_head_problems()
        if problems:
            raise UserError(_("Для XML заповніть: %s.") % "; ".join(problems))
        problems = self._ua_problems()
        if problems:
            raise UserError("\n".join(problems))
        sti, tin, month = _digits(self.sti_code), _digits(self.tin), int(self.month)
        state, doc_type = (2, max(self.new_number, 1)) if self.doc_kind == "HZN" else (1, 0)
        fill_date = fields.Date.context_today(self)
        with_d2 = self.r19 > 0
        name_main = dps_xml.file_name(FORM_MAIN, sti, tin, 1, month, self.year, state=state, doc_type=doc_type)
        name_d2 = dps_xml.file_name(FORM_D2, sti, tin, 1, month, self.year, state=state, doc_type=doc_type)
        phone = re.sub(r"[^0-9 ()\-+.,;]", "", self.phone or "")
        zip_code = (self.company_id.zip or "").strip()
        sign = {"HFILL": fill_date.strftime("%d%m%Y"), "HBOS": self.director.strip(),
                "HKBOS": _digits(self.director_rnokpp), "HBUH": (self.accountant or "").strip(),
                "HKBUH": _digits(self.accountant_rnokpp) if self.accountant else False}
        common = {self.doc_kind: True, "HZY": str(self.year), "HZM": str(month), "HNAME": self.company_id.name,
                  "HTIN": tin, "HNPDV": _digits(self.ipn)}
        main = dict(common, **sign, **{
            "HLOC": self.address.strip(),
            "HZIP": zip_code if re.fullmatch(r"\d{5}", zip_code) else False,
            "HTEL": phone if len(phone) >= 4 else False,
            "HEMAIL": self.email if re.fullmatch(r"[^@\s]+@[^@\s]+", self.email or "") else False,
            "HSTI": self.sti_name.strip(),
            "R90GB": self.r9, "R160GB": self.r16_1, "R161GB": self.r16_1, "R170GB": self.r17,
            "R180GB": self.r18, "R190GB": self.r19, "R191GB": self.r19_1, "R200GB": self.r20,
            "R201GB": self.r20_1, "R202GB": self.r20_2, "R2021GB": self.r20_2_1, "R2022GB": self.r20_2_2,
            "R203GB": self.r20_3, "R210GB": self.r21, "HD2": with_d2,
        })
        for line in self.line_ids:
            _kind, tag_a, tag_b = ROW_INFO.get(line.code, (False, False, False))
            if tag_a:
                main[tag_a] = line.base
            if tag_b:
                main[tag_b] = line.vat
        files = []
        try:
            files.append(dps_xml.build(
                dps_xml.schema_path(__file__, FORM_MAIN), FORM_MAIN, sti, tin, 1, month, self.year, fill_date,
                main, linked=[(FORM_D2, name_d2, 1)] if with_d2 else (), state=state, doc_type=doc_type))
            if with_d2:
                rows = list(enumerate(self.d2_line_ids, start=1))
                d2 = dict(common, **sign, **{
                    "T1RXXXXG2": [(n, line.origin_month) for n, line in rows],
                    "T1RXXXXG3": [(n, line.origin_year) for n, line in rows],
                    "T1RXXXXG4": [(n, _digits(line.ipn)) for n, line in rows],
                    "T1RXXXXG51": [(n, line.doc_month) for n, line in rows],
                    "T1RXXXXG52": [(n, line.doc_year) for n, line in rows],
                    "T1RXXXXG6": [(n, line.amount) for n, line in rows],
                    "T1RXXXXG7": [(n, line.from_reorg) for n, line in rows],
                    "T1RXXXXG8": [(n, line.debt_amount) for n, line in rows],
                    "T1RXXXXG9": [(n, line.refund_amount) for n, line in rows],
                    "T1RXXXXG10": [(n, line.carry_amount) for n, line in rows],
                    "R01G6": self.r19, "R01G8": self.r20_1, "R01G9": self.r20_2, "R01G10": self.r21,
                })
                files.append(dps_xml.build(
                    dps_xml.schema_path(__file__, FORM_D2), FORM_D2, sti, tin, 1, month, self.year, fill_date,
                    d2, linked=[(FORM_MAIN, name_main, 2)], state=state, doc_type=doc_type))
        except ValueError as error:
            raise UserError(_("XML не відповідає схемі ДПС:\n%s") % error) from error
        return files

    def action_xml(self):
        for doc in self:
            files = doc._ua_xml()
            (name, data), d2 = files[0], files[1] if len(files) > 1 else (False, False)
            doc.write({"xml_file": base64.b64encode(data), "xml_name": name,
                       "d2_xml_file": d2[1] and base64.b64encode(d2[1]), "d2_xml_name": d2[0]})
        return True

    def action_done(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError(_("Спершу розрахуйте декларацію."))
            problems = doc._ua_problems()
            if problems:
                raise UserError("\n".join(problems))
            doc.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True


class UaVatReturnLine(models.Model):
    _name = "ua.vat.return.line"
    _description = "Рядок декларації з ПДВ"
    _order = "sequence, id"

    return_id = fields.Many2one("ua.vat.return", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="return_id.company_id", store=True)
    currency_id = fields.Many2one(related="return_id.currency_id")
    sequence = fields.Integer(default=10)
    code = fields.Char("Рядок", required=True, readonly=True)
    name = fields.Char("Показник", required=True, readonly=True)
    base = fields.Monetary("Обсяг (графа А)")
    vat = fields.Monetary("ПДВ (графа Б)")


class UaVatReturnD2(models.Model):
    _name = "ua.vat.return.d2"
    _description = "Д2: рядок розшифровки від'ємного значення"
    _order = "sequence, id"

    return_id = fields.Many2one("ua.vat.return", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="return_id.company_id", store=True)
    currency_id = fields.Many2one(related="return_id.currency_id")
    sequence = fields.Integer(default=10)
    origin_month = fields.Integer("Місяць виникнення", required=True, help="Графа 2")
    origin_year = fields.Integer("Рік виникнення", required=True, help="Графа 3")
    partner_id = fields.Many2one("res.partner", "Постачальник")
    ipn = fields.Char("ІПН", help="Графа 4: ІПН постачальника або власний (імпорт, зменшення ПЗ).")
    doc_month = fields.Integer("Місяць документа", required=True, help="Графа 5: період складання ПН чи МД.")
    doc_year = fields.Integer("Рік документа", required=True)
    amount = fields.Monetary("Від'ємне значення", help="Графа 6")
    from_reorg = fields.Boolean("Від реорганізованого", help="Графа 7")
    debt_amount = fields.Monetary("У погашення боргу", help="Графа 8, разом - рядок 20.1")
    refund_amount = fields.Monetary("До відшкодування", help="Графа 9, разом - рядок 20.2")
    carry_amount = fields.Monetary("До ПК наступного періоду", compute="_compute_carry", store=True,
                                   help="Графа 10 = 6 - 8 - 9, разом - рядок 21")

    @api.depends("amount", "debt_amount", "refund_amount")
    def _compute_carry(self):
        for line in self:
            line.carry_amount = line.amount - line.debt_amount - line.refund_amount
