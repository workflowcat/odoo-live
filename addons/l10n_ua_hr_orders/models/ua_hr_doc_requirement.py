# -*- coding: utf-8 -*-
"""Обов'язковий пакет документів на працівника: настроювані вимоги і перевірка покриття
наявними ua.employee.document (за кодом типу) або наказами (наказ про прийняття).

Джерело (docs/payroll/spec-intake.md): документ або приходить ВІД ПРАЦІВНИКА (ми лише
приймаємо і зберігаємо - паспорт, РНОКПП, диплом, військово-обліковий документ), або ВІД
КОМПАНІЇ (система склала сама і має підписати - заява, наказ, трудовий договір, згода,
лист ознайомлення, опис справи). Один рядок пакета належить рівно одному боку.

package_for() - єдине місце, де рахується пакет: ним користуються і справа прийняття
(ua.hire.case._case_payload, ключ "package_split"), і картка працівника
(hr.employee.get_ua_doc_package, l10n_ua_hr_card) - щоб перелік не розійшовся на дві
реалізації."""
from odoo import api, fields, models

APPLIES_TO = [
    ("employment", "трудовий договір"),
    ("gph", "договір ЦПХ"),
    ("fop", "ФОП"),
    ("all", "усі"),
]
MIL_LIABLE = ("conscript", "liable", "reserve")

SOURCE = [("employee", "від працівника"), ("company", "від компанії")]

# Родовий відмінок місяця для "when" - «1 серпня», без року, коли рік поточний.
MONTHS_OF = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}

# Пакет першого дня (константа PACKAGE у l10n_ua_hire.ua_hire_case) друкує сім документів;
# чотири з них уже є записами довідника (source "company" - hire_order/contract/consent/statement).
# l10n_ua_hr_orders не залежить від l10n_ua_hire (залежність лише у зворотний бік, як і з
# order_id у ua_employee_document.py), тож PACKAGE звідти імпортувати не можна - трьом кодам,
# яких у довіднику нема (nda, ack, inventory), назва і мітка продубльовані тут навмисно;
# лишити їх точно тими самими, що в PACKAGE, коли той міняється.
EXTRA_COMPANY_ROWS = [
    ("nda", "Договір про нерозголошення"),
    ("ack", "Лист ознайомлення"),
    ("inventory", "Опис документів особової справи"),
]
# "order" - код PACKAGE, що означає той самий документ, що й довідниковий код "hire_order" -
# один рядок, не два.
PACKAGE_CODE_ALIAS = {"order": "hire_order"}
# Коди, для яких стан підпису не має сенсу (наказ - "проведено", опис справи - службовий
# документ без окремого підписання в цьому переліку): sign завжди null, коротке пояснення
# йде в note. Фронтенд показує note саме тоді, коли sign порожній.
NO_SIGN_CODES = ("hire_order", "inventory")
# Підписаний скан, повернутий під час оформлення. Типи файлів справи так і звуться:
# «Трудовий договір, підписаний», «Лист ознайомлення, підписаний». Отже завантажений файл
# закриває рядок компанії ще до прийняття, і в «Інші файли» він не падає.
COMPANY_CASE_FILE_TYPES = {
    "statement": "statement", "contract": "contract", "nda": "nda",
    "ack": "acknowledgement", "consent": "consent",
}


class UaHrDocRequirement(models.Model):
    _name = "ua.hr.doc.requirement"
    _description = "Обов'язковий документ у пакеті працівника"
    _order = "sequence, id"

    name = fields.Char("Назва", required=True)
    code = fields.Char("Код", required=True)
    applies_to = fields.Selection(APPLIES_TO, string="Кого стосується", default="all", required=True)
    source = fields.Selection(SOURCE, string="Джерело", default="employee", required=True)
    active = fields.Boolean("Чинний", default=True)
    sequence = fields.Integer("Порядок", default=10)

    def _applies(self, kind):
        """kind: ua_contract_kind працівника (employment/gph/fop)."""
        self.ensure_one()
        return self.applies_to == "all" or self.applies_to == kind or (self.code == "gph_contract" and kind == "fop")

    def _is_covered(self, employee):
        """True/False - покрито чи ні; None - вимога не застосовна до цього працівника (н/п)."""
        self.ensure_one()
        emp = employee.sudo()
        if self.code == "military_id" and emp.ua_mil_status not in MIL_LIABLE:
            return None
        if self.code == "hire_order":
            return bool(self.env["ua.hr.order"].sudo().search_count([
                ("employee_id", "=", emp.id), ("order_type", "=", "hire"), ("state", "in", ("posted", "acknowledged")),
            ]))
        if self.code == "passport_rnokpp":
            types = emp.ua_document_ids.mapped("type")
            return "passport" in types and "rnokpp" in types
        return self.code in emp.ua_document_ids.mapped("type")

    # ------------------------------------------------------------------ пакет (спека)
    def _human_date(self, day):
        """«1 серпня» - родовий відмінок місяця, без року, коли рік поточний."""
        if not day:
            return ""
        text = "%s %s" % (day.day, MONTHS_OF[day.month])
        if day.year != fields.Date.context_today(self).year:
            text += " %s" % day.year
        return text

    @api.model
    def package_for(self, employee=None, case=None):
        """Пакет документів за формою зі спеки: employee-блок (що приносить людина) і
        company-блок (що складає сама система), одним переліком для картки працівника
        (employee) і для справи прийняття (case) - рівно один з двох.

        Якщо case вже прийнято (case.employee_id заповнено), документи вже реальні -
        рахуємо так само, як для картки, інакше employee- і company-блок для того самого
        працівника розійшлися б (docs/payroll/spec-intake.md, розділ «Перевірка»)."""
        if case and case.employee_id:
            employee, case = case.employee_id, None
        if bool(employee) == bool(case):
            raise ValueError("package_for: потрібен рівно один з employee, case")
        kind = (employee.ua_contract_kind if employee else case.contract_kind) or "employment"
        reqs = self.sudo().search([], order="sequence")
        employee_block = self._package_employee_block(reqs.filtered(lambda r: r.source == "employee"), kind, employee, case)
        company_block = self._package_company_block(reqs.filtered(lambda r: r.source == "company"), kind, employee, case)
        return {
            "employee": employee_block,
            "company": company_block,
            "settings": {"xmlid": "l10n_ua_hr_orders.menu_ua_hr_doc_requirement"},
        }

    # -- employee: те, що приносить людина ------------------------------------------------
    # Файли справи прийняття (ua.hire.file) і документи працівника (ua.employee.document)
    # не поділяють словник кодів 1:1 - тут узгодження між кодом вимоги і типом файла справи.
    CASE_FILE_TYPES = {"passport_rnokpp": ("passport", "rnokpp"), "military_id": ("military_id",), "medical": ("medical",)}

    def _package_employee_block(self, reqs, kind, employee, case):
        rows = [self._employee_row(req, kind, employee, case) for req in reqs]
        need = sum(1 for r in rows if r["state"] != "not_needed")
        have = sum(1 for r in rows if r["state"] == "have")
        return {"rows": rows, "have": have, "need": need}

    def _employee_row(self, req, kind, employee, case):
        row = {"code": req.code, "name": req.name, "state": "missing", "sign": None,
               "when": "", "note": "немає", "target": None}
        if not req._applies(kind):
            row["state"], row["note"] = "not_needed", ""
            return row
        if employee:
            covered = req._is_covered(employee)
            if covered is None:
                row["state"], row["note"] = "not_needed", ""
                return row
            types = ("passport", "rnokpp") if req.code == "passport_rnokpp" else (req.code,)
            doc = self.env["ua.employee.document"].sudo().search(
                [("employee_id", "=", employee.id), ("type", "in", list(types))], limit=1, order="id desc")
            if not doc:
                return row
            row["state"] = "expired" if doc.ua_doc_state == "expired" else "have"
            row["note"] = "прострочений" if row["state"] == "expired" else ""
            row["when"] = self._human_date(doc.date)
            row["target"] = {"model": "ua.employee.document", "res_id": doc.id}
            return row
        # case: документа ще нема - покриття рахуємо з file_ids і їх doc_type.
        if req.code == "military_id" and not case._military_required():
            row["state"], row["note"] = "not_needed", ""
            return row
        matches = self._case_file_matches(req, case)
        # passport_rnokpp - як і _is_covered для картки, потрібні обидва файли, не один із двох.
        types = self.CASE_FILE_TYPES.get(req.code, (req.code,))
        if req.code == "passport_rnokpp" and set(matches.mapped("doc_type")) < set(types):
            return row
        f = matches[:1]
        if not f:
            return row
        row["state"], row["note"] = "have", ""
        row["when"] = self._human_date(f.create_date.date()) if f.create_date else ""
        row["target"] = {"model": "ua.hire.file", "res_id": f.id}
        return row

    def _case_file_matches(self, req, case):
        types = self.CASE_FILE_TYPES.get(req.code, (req.code,))
        return case.file_ids.filtered(lambda x, t=types: x.doc_type in t)

    def package_used_file_ids(self, case):
        """Файли справи, що підпадають під якусь employee-вимогу пакета (docs/payroll/
        spec-intake.md, «Інші файли») - навіть коли вимога ще не покрита повністю (паспорт
        є, РНОКПП ще нема): файл, що вже підписаний під вимогу, не "інший", доки вимога сама
        не стане not_needed. Той самий CASE_FILE_TYPES, що й для рядків пакета - не копія."""
        case.ensure_one()
        kind = case.contract_kind or "employment"
        used = self.env["ua.hire.file"]
        reqs = self.sudo().search([("source", "=", "employee")])
        for req in reqs:
            if not req._applies(kind):
                continue
            used |= self._case_file_matches(req, case)
        # Підписані скани документів компанії теж не "інші": вони стоять у своєму рядку.
        company_types = set(COMPANY_CASE_FILE_TYPES.values())
        used |= case.file_ids.filtered(lambda f: f.doc_type in company_types)
        return set(used.ids)

    # -- company: те, що складає сама система -----------------------------------------------
    def _package_company_block(self, reqs, kind, employee, case):
        rows, seen = [], set()
        for req in reqs:
            rows.append(self._company_row(req.code, req.name, req, kind, employee, case))
            seen.add(req.code)
        for code, label in EXTRA_COMPANY_ROWS:
            if code in seen:
                continue
            rows.append(self._company_row(code, label, None, kind, employee, case))
            seen.add(code)
        need = sum(1 for r in rows if r["state"] != "not_needed")
        done = sum(1 for r in rows if r["state"] == "have")
        signed = sum(1 for r in rows if r["sign"] == "signed")
        return {"rows": rows, "done": done, "need": need, "signed": signed}

    def _company_row(self, code, name, req, kind, employee, case):
        row = {"code": code, "name": name, "state": "missing", "sign": None, "when": "", "note": "", "target": None}
        if req and not req._applies(kind):
            row["state"] = "not_needed"
            return row
        if employee:
            self._company_row_for_employee(row, code, employee)
            return row
        # case, ще не прийнято: документів нема; package_skip (екран «Пакет») знімає рядок
        # так само, як action_hire знімає його при прийнятті (Doc.state "not_needed").
        skip = {k for k in (case.package_skip or "").split(",") if k}
        package_key = next((k for k, v in PACKAGE_CODE_ALIAS.items() if v == code), code)
        if package_key in skip:
            row["state"], row["note"] = "not_needed", ""
            return row
        file_type = COMPANY_CASE_FILE_TYPES.get(code)
        if file_type:
            scan = case.file_ids.filtered(lambda f: f.doc_type == file_type)[:1]
            if scan:
                row["state"] = "have"
                row["sign"] = "signed"
                row["note"] = "підписаний скан"
                row["target"] = {"model": "ua.hire.file", "res_id": scan.id}
                return row
        if code in NO_SIGN_CODES:
            row["note"] = "не проведено" if code == "hire_order" else "не створено"
        else:
            # Рядок без стану підпису і без пояснення показувався самою лише позначкою:
            # видно колір, не видно, чого бракує.
            row["note"] = "немає"
        return row

    def _company_row_for_employee(self, row, code, employee):
        Doc = self.env["ua.employee.document"].sudo()
        if code == "hire_order":
            order = self.env["ua.hr.order"].sudo().search([
                ("employee_id", "=", employee.id), ("order_type", "=", "hire"), ("state", "in", ("posted", "acknowledged")),
            ], limit=1)
            if not order:
                row["note"] = "не проведено"
                return
            row["state"] = "have"
            row["when"] = self._human_date(order.date)
            row["note"] = "проведено %s" % row["when"] if row["when"] else "проведено"
            row["target"] = {"model": "ua.hr.order", "res_id": order.id}
            return
        doc = Doc.search([("employee_id", "=", employee.id), ("type", "=", code)], limit=1, order="id desc")
        if not doc:
            row["note"] = "не створено" if code == "inventory" else "немає"
            return
        row["target"] = {"model": "ua.employee.document", "res_id": doc.id}
        if doc.state == "not_needed":
            row["state"] = "not_needed"
            return
        row["state"] = "have"
        if code in NO_SIGN_CODES:
            row["when"] = self._human_date(doc.signed_date or doc.date)
            row["note"] = "створено %s" % row["when"] if row["when"] else "створено"
        else:
            row["sign"] = doc.state
            row["when"] = self._human_date(doc.signed_date) if doc.signed_date else ""
