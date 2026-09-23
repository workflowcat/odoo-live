# -*- coding: utf-8 -*-
"""Список персонального військового обліку на дату: документ з рядками по кожному, хто підлягає обліку.

Ведеться за офіційним витягом (постанова КМУ № 1487) окремо по кожному ТЦК та СП: один документ = один
ТЦК. Рядки групуються за розділами форми - призовники / військовозобов'язані офіцери / військовозобов'язані
рядового і сержантського складу / резервісти / жінки-військовозобов'язані (окремим списком)."""
from datetime import date as date_type, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .hr_employee import CATEGORY, DOC_TYPE, FITNESS, GROUP, LIABLE_STATUSES

STATES = [("draft", "Чернетка"), ("confirmed", "Затверджено")]


def _month_end(year, month):
    """Останній день місяця."""
    return date_type(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
VARIANT = [
    ("all", "Усі розділи"),
    ("women", "Жінки, військовозобов'язані"),
    ("officers", "Офіцерський склад"),
    ("ranks", "Рядовий, сержантський і старшинський склад"),
    ("conscripts", "Призовники"),
    ("reservists", "Резервісти"),
]
SECTION_LABELS = {
    "women": "Жінки, військовозобов'язані",
    "conscripts": "Призовники",
    "reservists": "Резервісти",
    "officers": "Військовозобов'язані - офіцерський склад",
    "ranks": "Військовозобов'язані - рядовий, сержантський і старшинський склад",
    "other": "Інші",
}


def _section_key(emp):
    """Розділ форми для працівника: жінки - окремо від категорії; далі за станом обліку і категорією."""
    if emp.sex == "female" and emp.ua_mil_status in LIABLE_STATUSES:
        return "women"
    if emp.ua_mil_status == "conscript":
        return "conscripts"
    if emp.ua_mil_status == "reserve":
        return "reservists"
    if emp.ua_mil_category == "officers":
        return "officers"
    if emp.ua_mil_category == "ranks":
        return "ranks"
    return "other"


class UaMilitaryList(models.Model):
    _name = "ua.military.list"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Список персонального військового обліку"
    _order = "date desc, tcc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    tcc = fields.Char("ТЦК та СП", required=True, tracking=True,
                       help="Список ведеться окремо по кожному ТЦК та СП, де перебувають на обліку працівники.")
    variant = fields.Selection(VARIANT, "Розділ", default="all", required=True, tracking=True,
                                help="«Усі розділи» - повний список по ТЦК; інші значення - лише один розділ офіційної форми.")
    date = fields.Date("На дату", default=lambda s: fields.Date.context_today(s), required=True, tracking=True)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    note = fields.Text("Примітка")
    line_ids = fields.One2many("ua.military.list.line", "list_id", "Рядки")

    @api.depends("date", "tcc", "variant")
    def _compute_name(self):
        for doc in self:
            base = "Список персонального обліку на %s" % (doc.date.strftime("%d.%m.%Y") if doc.date else "")
            if doc.tcc:
                base += " · %s" % doc.tcc
            if doc.variant and doc.variant != "all":
                base += " · %s" % dict(VARIANT).get(doc.variant, doc.variant)
            doc.name = base

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError("Видалити можна лише чернетку списку персонального обліку.")

    @api.model
    def ua_compose(self, company, year=None, month=None, date=None, tcc=None, variant="all", **params):
        """Новий список персонального обліку, одразу заповнений.

        ТЦК - явний, якщо його передали. Без ТЦК складаємо по одному списку на кожен
        ТЦК, де є хоча б один військовозобов'язаний, і повертаємо перший: список ведеться
        окремо по кожному ТЦК, і вибір одного з них - питання до даних, не до екрана."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        if not date:
            date = (_month_end(int(year), int(month)) if year and month
                    else fields.Date.context_today(self))
        if tcc:
            doc = self.create({"company_id": company.id, "date": date, "tcc": tcc, "variant": variant})
            doc.action_refill()
            return doc
        ids = self.action_create_all_tcc(company.id, date, variant)
        if not ids:
            raise UserError("Немає жодного військовозобов'язаного працівника з указаним ТЦК та СП.")
        return self.browse(ids)

    def action_compose_all(self):
        """Кнопка списку «Створити за всіма ТЦК»: по одному документу на кожен ТЦК."""
        docs = self.ua_compose(self.env.company)
        return {"type": "ir.actions.act_window", "name": "Списки персонального обліку",
                "res_model": "ua.military.list", "view_mode": "list,form",
                "domain": [("id", "in", docs.ids)], "target": "current"}

    def _domain(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id), ("ua_mil_status", "in", list(LIABLE_STATUSES)),
                   ("ua_mil_tcc", "=", self.tcc), ("ua_contract_kind", "not in", ["gph", "fop"])]
        if self.variant == "women":
            domain += [("sex", "=", "female")]
        elif self.variant == "officers":
            domain += [("ua_mil_category", "=", "officers"), ("sex", "!=", "female")]
        elif self.variant == "ranks":
            domain += [("ua_mil_category", "=", "ranks"), ("sex", "!=", "female")]
        elif self.variant == "conscripts":
            domain += [("ua_mil_status", "=", "conscript"), ("sex", "!=", "female")]
        elif self.variant == "reservists":
            domain += [("ua_mil_status", "=", "reserve"), ("sex", "!=", "female")]
        return domain

    def action_refill(self):
        """Видалити рядки і заповнити знову з hr.employee: працівники цього ТЦК, що підлягають обліку
        (за розділом форми, якщо документ не на «усі розділи»)."""
        for doc in self:
            if doc.state != "draft":
                raise UserError("Перерахувати можна лише чернетку.")
            if not doc.tcc:
                raise UserError("Вкажіть ТЦК та СП.")
            doc.line_ids.unlink()
            employees = self.env["hr.employee"].sudo().search(doc._domain(), order="name")
            cat_labels = dict(CATEGORY)
            grp_labels = dict(GROUP)
            fit_labels = dict(FITNESS)
            doc_labels = dict(DOC_TYPE)
            vals_list = []
            for emp in employees:
                ln, fn, mn = emp._ua_name_parts()
                reg_address = ", ".join(p for p in [emp.private_street, emp.private_city, emp.private_zip] if p)
                doc_bits = " ".join(p for p in [doc_labels.get(emp.ua_mil_doc_type, ""), emp.ua_mil_doc_series, emp.ua_mil_doc_number] if p)
                if emp.ua_mil_doc_date:
                    doc_bits = ("%s від %s" % (doc_bits, emp.ua_mil_doc_date.strftime("%d.%m.%Y"))).strip()
                section = _section_key(emp)
                vals_list.append({
                    "employee_id": emp.id,
                    "full_name": " ".join(p for p in [ln, fn, mn] if p),
                    "birthday": emp.birthday,
                    "rnokpp": emp.ua_rnokpp or "",
                    "reg_address": reg_address,
                    "actual_address": getattr(emp, "ua_actual_address", "") or "",
                    "job_title": emp.job_title or "",
                    "rank": emp.ua_mil_rank or "",
                    "vos": emp.ua_mil_vos or "",
                    "category": cat_labels.get(emp.ua_mil_category, ""),
                    "grp": grp_labels.get(emp.ua_mil_group, ""),
                    "tcc": emp.ua_mil_tcc or "",
                    "doc_info": doc_bits,
                    "fitness": fit_labels.get(emp.ua_mil_fitness, ""),
                    "reserved_until": emp.ua_mil_reserve_until if emp.ua_mil_reserved else False,
                    "last_check": emp.ua_mil_last_check,
                    "note": emp.ua_mil_note or "",
                    "is_women": emp.ua_mil_women_list,
                    "section": section,
                    "section_label": SECTION_LABELS.get(section, section),
                })
            doc.line_ids = [(0, 0, v) for v in vals_list]
        return True

    def action_confirm(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            doc.state = "confirmed"

    def action_draft(self):
        self.state = "draft"

    def action_reconcile(self):
        """Звірка з ТЦК: записує дату звірки всім працівникам у списку і подію в їхню хроніку."""
        for doc in self:
            if not doc.line_ids:
                raise UserError("Немає рядків. Натисніть «Перерахувати».")
            employees = doc.line_ids.mapped("employee_id")
            employees.sudo().write({"ua_mil_last_check": doc.date})
            events = [{"employee_id": emp.id, "date": doc.date, "kind": "check",
                       "note": "Звірка з ТЦК %s (%s)" % (doc.tcc, doc.name)} for emp in employees]
            if events:
                self.env["ua.military.event"].sudo().create(events)
            doc.message_post(body="Звірку записано для %s працівників." % len(employees))
        return True

    @api.model
    def action_create_all_tcc(self, company_id=None, doc_date=None, variant="all"):
        """Створити по одному чернетковому списку на кожен ТЦК, де є хоча б один військовозобов'язаний."""
        company_id = company_id or self.env.company.id
        doc_date = doc_date or fields.Date.today()
        employees = self.env["hr.employee"].sudo().search([
            ("company_id", "=", company_id), ("ua_mil_status", "in", list(LIABLE_STATUSES)), ("ua_mil_tcc", "!=", False),
            ("ua_contract_kind", "not in", ["gph", "fop"]),
        ])
        tccs = sorted({emp.ua_mil_tcc for emp in employees if emp.ua_mil_tcc})
        docs = self.browse()
        for tcc in tccs:
            existing = self.search([("company_id", "=", company_id), ("date", "=", doc_date),
                                    ("tcc", "=", tcc), ("variant", "=", variant), ("state", "=", "draft")], limit=1)
            doc = existing or self.create({"company_id": company_id, "date": doc_date, "tcc": tcc, "variant": variant})
            doc.action_refill()
            docs |= doc
        return docs.ids

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        out = []
        if not self.tcc:
            out.append(self._check_error("ТЦК та СП не вказано", target=self._target_record(self)))
        expected = self.env["hr.employee"].sudo().search(self._domain())
        have = self.line_ids.mapped("employee_id")
        missing = expected - have
        if missing:
            out.append(self._check_error(
                "Військовозобов'язаний працівник відсутній у списку", fact=len(missing),
                target=self._target_records(missing, "hr.employee")))
        else:
            out.append(self._check_ok("Усі військовозобов'язані працівники у списку", fact=len(have)))

        other_tcc = have.filtered(lambda e: e.ua_mil_tcc != self.tcc)
        if other_tcc:
            out.append(self._check_error(
                "Рядки належать іншому ТЦК", fact=len(other_tcc), target=self._target_records(other_tcc, "hr.employee")))

        no_rnokpp = self.line_ids.filtered(lambda l: not l.rnokpp)
        if no_rnokpp:
            out.append(self._check_error(
                "Рядки без РНОКПП", fact=len(no_rnokpp), target=self._target_records(no_rnokpp, "ua.military.list.line")))
        no_doc = self.line_ids.filtered(lambda l: not l.doc_info)
        if no_doc:
            out.append(self._check_warn(
                "Рядки без даних військового документа", fact=len(no_doc),
                target=self._target_records(no_doc, "ua.military.list.line")))
        stale = have.filtered(lambda e: e.ua_mil_needs_check)
        if stale:
            out.append(self._check_warn(
                "Дата звірки даних відсутня або старша за рік", fact=len(stale),
                target=self._target_records(stale, "hr.employee")))
        out.append(self._check_ok("Стан документа", fact=dict(STATES).get(self.state, self.state)))
        return out


class UaMilitaryListLine(models.Model):
    _name = "ua.military.list.line"
    _description = "Рядок списку персонального обліку"
    _order = "section, full_name"

    list_id = fields.Many2one("ua.military.list", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    full_name = fields.Char("ПІБ")
    birthday = fields.Date("Дата народження")
    rnokpp = fields.Char("РНОКПП")
    reg_address = fields.Char("Адреса реєстрації")
    actual_address = fields.Char("Фактична адреса")
    job_title = fields.Char("Посада")
    rank = fields.Char("Звання")
    vos = fields.Char("ВОС")
    category = fields.Char("Категорія обліку")
    grp = fields.Char("Група обліку")
    tcc = fields.Char("ТЦК")
    doc_info = fields.Char("Документ")
    fitness = fields.Char("Придатність")
    reserved_until = fields.Date("Бронювання до")
    last_check = fields.Date("Дата звірки")
    note = fields.Char("Примітка")
    is_women = fields.Boolean("Жінка, військовозобов'язана")
    section = fields.Char("Розділ (ключ)")
    section_label = fields.Char("Розділ форми")
