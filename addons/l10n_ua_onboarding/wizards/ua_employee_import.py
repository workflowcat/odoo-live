# -*- coding: utf-8 -*-
"""Перенесення працівників у систему одним файлом.

Перший місяць буде правильним лише тоді, коли разом із картками перенести три залишки:
залишок відпустки на дату впровадження, заробіток за 12 місяців (для середньої) і базовий
місяць індексації. Тому все це є в одному файлі.

Аркуш «Працівники» - одна людина в рядку. Аркуш «Заробіток» - РНОКПП, місяць, сума
(для середньої за Постановами 100 і 1266). Файл CSV читається як один аркуш «Працівники».

Працівник шукається за РНОКПП: наявного оновлюємо, нового створюємо. Рядки з помилками
пропускаємо і показуємо списком, решта імпортується.
"""
import base64
import csv
import io
from datetime import date, datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

SHEET_EMPLOYEES = "Працівники"
SHEET_EARNINGS = "Заробіток"

COLUMNS = [
    ("last_name", "Прізвище", True),
    ("first_name", "Ім'я", True),
    ("middle_name", "По батькові", False),
    ("rnokpp", "РНОКПП", True),
    ("sex", "Стать (ч/ж)", False),
    ("birthday", "Дата народження", False),
    ("job", "Посада", False),
    ("department", "Підрозділ", False),
    ("hire_date", "Дата прийняття", True),
    ("wage", "Оклад", True),
    ("fte", "Ставка", False),
    ("contract_kind", "Вид договору", False),
    ("main_job", "Основне місце (так/ні)", False),
    ("esv_category", "Категорія ЄСВ", False),
    ("psp", "ПСП", False),
    ("psp_children", "Дітей для ПСП", False),
    ("kp_code", "Код КП", False),
    ("order_ref", "Наказ про прийняття", False),
    ("iban", "IBAN", False),
    ("phone", "Телефон", False),
    ("email", "Email", False),
    ("insurance_years", "Страховий стаж, років", False),
    ("vacation_balance", "Залишок відпустки на дату", False),
    ("vacation_date", "Дата залишку відпустки", False),
    ("index_base", "Базовий місяць індексації", False),
]

EXAMPLE_ROWS = [
    ["Шевченко", "Тарас", "Григорович", "1234567890", "ч", "1990-03-09", "Столяр", "Виробництво",
     "2024-02-01", "28000", "1", "трудовий", "так", "загальна", "немає", "", "7422",
     "Наказ № 12-к від 31.01.2024", "UA213052990000026007233566001", "+380 67 123 45 67",
     "shevchenko@example.com", "8", "12,5", "2026-01-01", "2026-06-01"],
    ["Українка", "Леся", "Петрівна", "2345678901", "ж", "1991-02-25", "Бухгалтер", "Бухгалтерія",
     "2023-09-11", "25000", "0,5", "трудовий", "так", "загальна", "на дітей", "2", "3433",
     "Наказ № 44-к від 08.09.2023", "UA733052990000026005011122334", "+380 63 222 33 44",
     "", "5", "4", "2026-01-01", ""],
]

CONTRACT_KIND = {
    "трудовий": "employment", "трудовий договір": "employment", "основний": "employment",
    "сумісництво": "employment", "цпх": "gph", "договір цпх": "gph", "гпх": "gph",
    "фоп": "fop", "підрядник": "fop",
}
PSP = {"немає": "none", "ні": "none", "": "none", "базова": "base", "на дітей": "child",
       "на дітей 150": "child150", "150": "s150", "200": "s200"}
ESV_CATEGORY = {"загальна": "standard", "звичайна": "standard", "": "standard",
                "інвалідність": "disabled", "інвалід": "disabled"}
FTE = {"1": "1", "1.0": "1", "0.75": "0.75", "0,75": "0.75", "0.5": "0.5", "0,5": "0.5",
       "0.25": "0.25", "0,25": "0.25", "": "1"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _number(value):
    text = _text(value).replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise ValueError(_("«%s» не схоже на число") % value)


def _day(value):
    text = _text(value)
    if not text:
        return False
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(_("«%s» не схоже на дату") % value)


class UaEmployeeImport(models.TransientModel):
    _name = "ua.employee.import"
    _description = "Імпорт працівників і залишків"

    file = fields.Binary("Файл", required=True)
    filename = fields.Char("Ім'я файлу")
    dry_run = fields.Boolean("Тільки перевірити", default=True,
                             help="Перевіряє файл і показує, що буде зроблено, нічого не записуючи.")
    log = fields.Text("Результат", readonly=True)
    state = fields.Selection([("draft", "Файл"), ("done", "Результат")], default="draft")

    # ------------------------------------------------------------------ шаблон
    def action_template(self):
        """Порожній файл із заголовками, двома прикладами і аркушем заробітку."""
        import openpyxl

        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = SHEET_EMPLOYEES
        sheet.append([title for _key, title, _req in COLUMNS])
        for row in EXAMPLE_ROWS:
            sheet.append(row)
        for index, (_key, title, required) in enumerate(COLUMNS, start=1):
            sheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = max(14, len(title) + 2)
            if required:
                sheet.cell(row=1, column=index).font = openpyxl.styles.Font(bold=True)
        earnings = book.create_sheet(SHEET_EARNINGS)
        earnings.append(["РНОКПП", "Місяць (РРРР-ММ)", "Нараховано"])
        earnings.append(["1234567890", "2026-07", "28000"])
        earnings.append(["1234567890", "2026-06", "28000"])
        stream = io.BytesIO()
        book.save(stream)
        attachment = self.env["ir.attachment"].create({
            "name": "Шаблон імпорту працівників.xlsx",
            "type": "binary",
            "datas": base64.b64encode(stream.getvalue()),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {"type": "ir.actions.act_url", "url": "/web/content/%s?download=1" % attachment.id, "target": "self"}

    # ------------------------------------------------------------------ читання
    def _rows(self):
        """(рядки працівників, рядки заробітку) як словники за ключами COLUMNS."""
        content = base64.b64decode(self.file)
        name = (self.filename or "").lower()
        titles = {title: key for key, title, _req in COLUMNS}
        if name.endswith(".csv") or (not name.endswith((".xlsx", ".xlsm")) and content[:2] != b"PK"):
            text = content.decode("utf-8-sig", "replace")
            dialect = csv.Sniffer().sniff(text.splitlines()[0]) if text.splitlines() else csv.excel
            reader = csv.reader(io.StringIO(text), dialect)
            table = list(reader)
            return self._table_rows(table, titles), []
        import openpyxl

        book = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        sheet = book[SHEET_EMPLOYEES] if SHEET_EMPLOYEES in book.sheetnames else book.worksheets[0]
        table = [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
        earnings = []
        if SHEET_EARNINGS in book.sheetnames:
            for row in book[SHEET_EARNINGS].iter_rows(min_row=2, values_only=True):
                if row and _text(row[0]):
                    earnings.append({"rnokpp": _text(row[0]), "month": _text(row[1]), "amount": row[2]})
        return self._table_rows(table, titles), earnings

    @staticmethod
    def _table_rows(table, titles):
        if not table:
            raise UserError(_("Файл порожній."))
        header = [_text(cell) for cell in table[0]]
        mapping = {}
        for index, cell in enumerate(header):
            key = titles.get(cell)
            if key:
                mapping[key] = index
        missing = [title for key, title, required in COLUMNS if required and key not in mapping]
        if missing:
            raise UserError(_("У файлі бракує колонок: %s.\nВізьміть шаблон кнопкою «Шаблон файлу».") % ", ".join(missing))
        rows = []
        for number, raw in enumerate(table[1:], start=2):
            values = {key: (raw[index] if index < len(raw) else None) for key, index in mapping.items()}
            if not any(_text(value) for value in values.values()):
                continue
            values["_row"] = number
            rows.append(values)
        return rows

    # ------------------------------------------------------------------ довідники
    def _job(self, name):
        name = _text(name)
        if not name:
            return False
        Job = self.env["hr.job"]
        job = Job.search([("name", "=", name), ("company_id", "in", (False, self.env.company.id))], limit=1)
        return job.id if job else Job.create({"name": name, "company_id": self.env.company.id}).id

    def _department(self, name):
        name = _text(name)
        if not name:
            return False
        Department = self.env["hr.department"]
        department = Department.search([("name", "=", name), ("company_id", "=", self.env.company.id)], limit=1)
        return department.id if department else Department.create({"name": name, "company_id": self.env.company.id}).id

    def _structure(self):
        structure = self.env.ref("l10n_ua_payroll_rules.struct_ua_salary", raise_if_not_found=False)
        return structure.id if structure else False

    # ------------------------------------------------------------------ імпорт
    def action_import(self):
        self.ensure_one()
        rows, earnings = self._rows()
        created = updated = 0
        problems = []
        Employee = self.env["hr.employee"]
        calendar_id = self.env.company.resource_calendar_id.id
        structure_id = self._structure()
        by_rnokpp = {}

        for row in rows:
            number = row["_row"]
            try:
                rnokpp = _text(row["rnokpp"])
                if len(rnokpp) != 10 or not rnokpp.isdigit():
                    raise ValueError(_("РНОКПП має бути десять цифр"))
                wage = _number(row["wage"])
                if wage <= 0:
                    raise ValueError(_("оклад має бути більший за нуль"))
                hire = _day(row["hire_date"])
                if not hire:
                    raise ValueError(_("немає дати прийняття"))
                last, first, middle = _text(row["last_name"]), _text(row["first_name"]), _text(row["middle_name"])
                if not last or not first:
                    raise ValueError(_("немає прізвища або імені"))
                values = {
                    "name": " ".join(part for part in (last, first, middle) if part),
                    "ua_last_name": last, "ua_first_name": first, "ua_middle_name": middle,
                    "ua_rnokpp": rnokpp,
                    "company_id": self.env.company.id,
                    "job_title": _text(row["job"]) or False,
                    "job_id": self._job(row["job"]),
                    "department_id": self._department(row["department"]),
                    "ua_contract_kind": CONTRACT_KIND.get(_text(row["contract_kind"]).lower(), "employment"),
                    "ua_main_job": _text(row["main_job"]).lower() not in ("ні", "no", "0", "false"),
                    "ua_esv_category": ESV_CATEGORY.get(_text(row["esv_category"]).lower(), "standard"),
                    "ua_psp": PSP.get(_text(row["psp"]).lower(), "none"),
                    "ua_fte": FTE.get(_text(row["fte"]).lower(), "1"),
                }
                if _text(row["sex"]):
                    values["sex"] = "female" if _text(row["sex"]).lower().startswith(("ж", "f")) else "male"
                if _day(row["birthday"]):
                    values["birthday"] = _day(row["birthday"])
                if _text(row["psp_children"]):
                    values["ua_psp_children"] = int(_number(row["psp_children"]))
                if _text(row["insurance_years"]):
                    values["ua_insurance_years"] = int(_number(row["insurance_years"]))
                if _text(row["phone"]):
                    values["mobile_phone"] = _text(row["phone"])
                if _text(row["email"]):
                    values["work_email"] = _text(row["email"])
                if _text(row["vacation_balance"]):
                    values["ua_vacation_opening_balance"] = _number(row["vacation_balance"])
                if _day(row["vacation_date"]):
                    values["ua_vacation_opening_date"] = _day(row["vacation_date"])
                if _day(row["index_base"]):
                    values["ua_index_base"] = _day(row["index_base"]).replace(day=1)

                employee = Employee.search([("ua_rnokpp", "=", rnokpp), ("company_id", "=", self.env.company.id)], limit=1)
                if self.dry_run:
                    updated += 1 if employee else 0
                    created += 0 if employee else 1
                    by_rnokpp[rnokpp] = employee
                    continue
                if employee:
                    employee.write(values)
                    updated += 1
                else:
                    employee = Employee.create(values)
                    created += 1
                by_rnokpp[rnokpp] = employee

                version = employee.version_id
                version_values = {
                    "wage": wage, "date_version": hire, "contract_date_start": hire,
                    "resource_calendar_id": calendar_id,
                    "ua_kp_code": _text(row["kp_code"]) or False,
                    "ua_order_ref": _text(row["order_ref"]) or False,
                }
                if structure_id:
                    version_values["struct_id"] = structure_id
                version.with_context(sync_contract_dates=True).write(version_values)

                iban = _text(row["iban"]).replace(" ", "")
                if iban:
                    partner = employee.work_contact_id or employee.address_home_id if hasattr(employee, "address_home_id") else employee.work_contact_id
                    if partner:
                        Bank = self.env["res.partner.bank"]
                        if not Bank.search([("acc_number", "=", iban), ("partner_id", "=", partner.id)], limit=1):
                            Bank.create({"acc_number": iban, "partner_id": partner.id})
            except (ValueError, UserError) as error:
                problems.append("рядок %s: %s" % (number, error.args[0] if error.args else error))

        months = 0
        History = self.env["ua.earnings.history"]
        for item in earnings:
            employee = by_rnokpp.get(item["rnokpp"])
            if not employee:
                problems.append(_("заробіток: РНОКПП %s немає серед працівників файлу") % item["rnokpp"])
                continue
            try:
                month = _day(item["month"] + "-01" if len(item["month"]) == 7 else item["month"])
                amount = _number(item["amount"])
            except ValueError as error:
                problems.append(_("заробіток %s: %s") % (item["rnokpp"], error.args[0]))
                continue
            months += 1
            if self.dry_run:
                continue
            existing = History.search([("employee_id", "=", employee.id), ("month", "=", month)], limit=1)
            if existing:
                existing.gross = amount
            else:
                History.create({"employee_id": employee.id, "month": month, "gross": amount})

        head = _("Перевірка файлу") if self.dry_run else _("Імпорт виконано")
        lines = [
            "%s." % head,
            _("Нових працівників: %s") % created,
            _("Оновлених карток: %s") % updated,
            _("Рядків заробітку: %s") % months,
        ]
        if problems:
            lines.append("")
            lines.append(_("Не перенесено (%s):") % len(problems))
            lines.extend("  %s" % problem for problem in problems[:50])
            if len(problems) > 50:
                lines.append(_("  ... ще %s рядків") % (len(problems) - 50))
        elif self.dry_run:
            lines.append("")
            lines.append(_("Помилок немає. Зніміть «Тільки перевірити» і натисніть «Імпортувати»."))
        self.write({"log": "\n".join(lines), "state": "done"})
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new",
        }
