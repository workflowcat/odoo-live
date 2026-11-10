"""Об'єднана звітність (J0500111) з Д1 (J0510111) і 4ДФ (J0510411) за місяць, з проведених листків."""
import base64
import calendar
import io
import zipfile
from datetime import date, timedelta

from odoo import fields, models
from odoo.exceptions import UserError

VER = "11"
ESV_CAT = {"employment": "1", "disabled": "2", "gph": "26", "sick": "29", "mat": "42",
           "gig": "83", "gig_disabled": "82"}   # 83/82 - гіг-спеціаліст резидента Дія Сіті (з інвалідністю - 82)
INCOME_SIGN = {"employment": "101", "gph": "102", "gig": "102", "fop": "157"}   # ознака доходу 4ДФ
CIVIL_KINDS = ("gph", "gig")   # винагорода за цивільно-правовим договором: окремий рядок у розрахунку
# Виплати поза зарплатою: ознака 4ДФ -> (правила з сумою доходу, правила з оподатковуваною частиною).
# У Д1 вони не потрапляють: ЄСВ на них не нараховується.
OTHER_INCOME = {
    "169": (("AID_FREE", "AID_TAX"), ("AID_TAX",)),        # нецільова благодійна допомога, пп. 170.7.3 ПКУ
    "160": (("GIFT_FREE", "GIFT_TAX"), ("GIFT_TAX",)),     # вартість дарунків, пп. 165.1.39 ПКУ
    "127": (("SEVERANCE", "COMP_TOOL"), ("SEVERANCE", "COMP_TOOL")),   # інші доходи
}
PSP_CODE = {"none": None, "base": "01", "child": "04", "child150": "04", "s150": "02", "s200": "03"}
GENDER = {"male": "1", "female": "0"}   # схема допускає лише 0 або 1; трактування підтвердити (припущення: 1 = чоловік, 0 = жінка)


D1_COLS = ["G5", "G6", "G7S", "G8", "G9", "G101", "G102", "G111S", "G112S", "G113S", "G12", "G13", "G14",
           "G15", "G16", "G17", "G18", "G19", "G20", "G21", "G22", "G23", "G24", "G25", "G26"]
# Д6 (J0510611), спецстаж: 05 громадянин, 06 РНОКПП, 07 код підстави, 08 ПІБ, 09-10 перший і останній день
# періоду, 11 дні, 12 години і хвилини, 13 норма (дні, години, хвилини), 14-15 наказ про атестацію,
# 16 сезон, 17 ознака рядка (0 - ввести, 1 - вилучити).
D6_COLS = ["G5", "G6S", "G7S", "G81S", "G82S", "G83S", "G9", "G10", "G11", "G121", "G122", "G131", "G132", "G133",
           "G14S", "G15D", "G16", "G17"]
D6_FLAG = "G17"
D6_KEY = ("G6S", "G7S", "G9")
NAME_COLS = (("G111S", "G112S", "G113S"), ("G81S", "G82S", "G83S"))
DF_COLS = ["G02", "G03A", "G03", "G04A", "G04", "G5A", "G5", "G05", "G06D", "G07D", "G08", "G09"]
# Графи Д1 за бланком: 12 - дні непрацездатності, 13 - дні без збереження зарплати, 14 - дні трудових
# відносин, 15 - дні відпустки у зв'язку з вагітністю та пологами, 21 - основне місце роботи (трудова книжка),
# 22 - неповний час, 23 - спецстаж, 24 - нове робоче місце, 25 - ознака рядка, 26 - нефіксований робочий час.
D1_FLAG, DF_FLAG = "G25", "G09"          # графа «Ознака (0, 1)»: 0 - рядок на введення, 1 - на вилучення
D1_KEY = ("G7S", "G8", "G9", "G101", "G102")   # РНОКПП, категорія ЗО, код типу нарахувань, місяць, рік
D1_ADD = ("G12", "G13", "G15", "G16", "G17", "G18", "G19", "G20")   # графи, що складаються при злитті рядків
KTN_PRIOR_BENEFIT = "13"   # код типу нарахувань: допомога по непрацездатності чи вагітності та пологах за минулі місяці
KTN_VACATION = "10"        # код типу нарахувань: відпускні, окремим рядком за кожен місяць, на який припадають дні
VACATION_CODES = ("VAC", "CHILD_VAC_PAY", "STUDY_PAY")   # правила листка з відпускними
MIL_CODE = "MIL"           # вид відсутності «військова служба»: трудові відносини тривають, зарплати немає
DF_KEY = ("G02", "G05")                  # РНОКПП, ознака доходу
D1_SUMS = [("R01G16", "G16"), ("R01G17", "G17"), ("R01G18", "G18"), ("R01G19", None), ("R01G20", "G20")]
DF_SUMS = [("R01G03A", "G03A"), ("R01G03", "G03"), ("R01G04A", "G04A"), ("R01G04", "G04"),
           ("R01G5A", "G5A"), ("R01G5", "G5")]


def r2(x):
    return round(float(x or 0.0) + 1e-9, 2)


class UaPayrollReportWizard(models.TransientModel):
    _name = "ua.payroll.report.wizard"
    _description = "Об'єднана звітність ПДФО/ВЗ/ЄСВ (XML для ДПС)"

    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    year = fields.Integer("Рік", default=lambda s: date.today().year, required=True)
    month = fields.Integer("Місяць", default=lambda s: date.today().month, required=True)
    doc_type = fields.Selection([("HZ", "Звітний"), ("HZN", "Звітний новий"), ("HZU", "Уточнюючий")], "Тип", default="HZ", required=True)
    number = fields.Integer("Номер розрахунку за період", default=1, required=True)
    with_d1 = fields.Boolean("Додаток 1 (Д1)", default=True)
    with_4df = fields.Boolean("Додаток 4ДФ", default=True)
    with_d5 = fields.Boolean("Додаток 5 (Д5, трудові відносини)", default=True)
    with_d6 = fields.Boolean("Додаток 6 (Д6, спецстаж)", default=True,
                             help="Періоди роботи, що дають право на пенсію на пільгових умовах або за вислугу років: "
                                  "люди з позначкою «Спецстаж» у версії договору.")
    fill_date = fields.Date("Дата заповнення", default=fields.Date.context_today, required=True)
    base_attachment_ids = fields.Many2many(
        "ir.attachment", "ua_report_wizard_base_att_rel", "wizard_id", "attachment_id",
        string="Файли поданого розрахунку",
        help="XML раніше поданого розрахунку за цей місяць. Для звітного нового і уточнюючого "
             "з них беруться рядки, які треба вилучити.")
    result_ids = fields.Many2many("ir.attachment", string="Файли")
    lines_edited = fields.Boolean("Рядки зібрано для правок", readonly=True)
    d1_line_ids = fields.One2many("ua.payroll.report.d1.line", "wizard_id", "Рядки Д1")
    df_line_ids = fields.One2many("ua.payroll.report.df.line", "wizard_id", "Рядки 4ДФ")
    log = fields.Text("Перевірка за схемою", readonly=True)

    # ---- data collection ------------------------------------------------
    def _period(self):
        d1 = date(self.year, self.month, 1)
        return d1, date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    def _payslips(self):
        """Проведені листки, що звітуються в цьому місяці: свої і коригування за минулі місяці."""
        d1, _d2 = self._period()
        return self.env["hr.payslip"].search([("company_id", "=", self.company_id.id), ("state", "=", "done"),
                                              ("ua_report_month", "=", d1)], order="employee_id, date_from")

    def _line(self, slip, code):
        return sum(slip.line_ids.filtered(lambda l: l.code == code).mapped("total"))

    def _person_rows(self, slip, params):
        """Рядки Д1 для одного листка: основний рядок за категорією ЗО і окремий рядок 29 за лікарняні."""
        emp = slip.employee_id.sudo()
        d1, d2 = self._period()
        days_in, hire, dism = self._days_in(emp, d1, d2)
        kind = emp.ua_contract_kind or "employment"
        period = slip.date_from.replace(day=1)
        late = period < d1      # листок-коригування за минулий місяць, проведений у цьому
        disabled = emp.ua_esv_category == "disabled"
        if kind == "gig":
            cat = ESV_CAT["gig_disabled"] if disabled else ESV_CAT["gig"]
        elif kind == "gph":
            cat = ESV_CAT["gph"]
        else:
            cat = ESV_CAT["disabled"] if disabled else ESV_CAT["employment"]
        rate = params["esv_rate_disabled"] if emp.ua_esv_category == "disabled" else params["esv_rate"]
        sick_emp, sick_pfu = self._line(slip, "SICK_EMP"), self._line(slip, "SICK_PFU")
        sick_care = self._line(slip, "SICK_CARE_PAY")        # догляд за хворим: ПФУ з першого дня, у Д1 та сама категорія 29
        gross = self._line(slip, "GROSS")
        # відпускні наперед (дні наступних місяців): рядки КТН 10 з місяцем відпустки, база - кожного свого місяця
        ahead = slip._ua_vac_ahead_rows() if hasattr(slip, "_ua_vac_ahead_rows") else []
        ahead_total = r2(sum(amount for _month, _days, amount in ahead))
        vacation = r2(sum(self._line(slip, code) for code in VACATION_CODES) - ahead_total)
        salary = r2(gross - sick_emp - sick_pfu - sick_care - vacation - ahead_total)
        esv_total = r2(self._line(slip, "ESV"))
        max_base = params["min_wage"] * params["esv_max_multiplier"]
        remaining = max_base
        rows = []
        # мінімальна доплата ЄСВ: різниця між МЗП і фактичним нарахуванням (лише основне місце, повний місяць)
        min_diff = 0.0
        leaves_all = slip._ua_leave_calendar_days() if hasattr(slip, "_ua_leave_calendar_days") else {}
        # без нарахувань (військова служба весь місяць) мінімальної доплати немає - як у правилі ЄСВ листка
        gross_month = r2(gross - ahead_total)
        if kind == "employment" and emp.ua_main_job and 0 < gross_month < params["min_wage"] and days_in >= (d2 - d1).days + 1 and not leaves_all.get("mat_cover_days"):
            min_diff = r2(params["min_wage"] - gross_month)
        base_main = r2(min(salary, remaining)); remaining = r2(remaining - base_main)
        esv_main = r2(base_main * rate / 100.0)
        esv_diff = r2(min_diff * 22.0 / 100.0)
        leaves = slip._ua_leave_calendar_days() if hasattr(slip, "_ua_leave_calendar_days") else {}
        sick_days = (leaves.get("sick_emp_days", 0) + leaves.get("sick_pfu_days", 0) + leaves.get("sick_care_days", 0))
        unpaid_days = leaves.get("unpaid_days", 0)
        common = {**self._row_head(emp, kind, days_in), "G13": (unpaid_days or None) if not late else None}
        rows.append({**common, "G8": cat, "G12": None, "G16": salary, "G17": base_main, "G18": min_diff or None, "G19": 0.0,
                     "G20": r2(esv_main + esv_diff), "rate": rate})
        extra = {"G8": cat, "G9": KTN_VACATION, "G12": None, "G13": None, "G14": None, "G15": None, "G18": None,
                 "G19": 0.0, "rate": rate}
        if vacation:
            base_vac = r2(min(vacation, remaining)); remaining = r2(remaining - base_vac)
            rows.append({**common, **extra, "G16": vacation, "G17": base_vac, "G20": r2(base_vac * rate / 100.0)})
        for month, _days, amount in ahead:
            base_ahead = r2(min(amount, max_base))
            rows.append({**common, **extra, "G101": month.month, "G102": month.year, "G16": r2(amount),
                         "G17": base_ahead, "G20": r2(base_ahead * rate / 100.0)})
        mat = r2(self._line(slip, "MAT"))
        if mat:
            # допомога по вагітності та пологах: категорія 42, у кожному місяці періоду відпустки своя частка (пропорційно календарним дням)
            leaves = self.env["hr.leave"].sudo().search([("employee_id", "=", emp.id), ("state", "=", "validate"), ("holiday_status_id.work_entry_type_id.code", "=", "MAT"),
                                                         ("request_date_from", ">=", d1), ("request_date_from", "<=", d2)])
            for lv in leaves:
                total_days = (lv.request_date_to - lv.request_date_from).days + 1
                cur = lv.request_date_from
                while cur <= lv.request_date_to:
                    m_end = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
                    seg_end = min(m_end, lv.request_date_to)
                    seg_days = (seg_end - cur).days + 1
                    share = r2(mat * seg_days / total_days)
                    base_mat = r2(min(share, params["min_wage"] * params["esv_max_multiplier"]))
                    prior = date(cur.year, cur.month, 1) < d1
                    rows.append({**common, "G101": cur.month, "G102": cur.year, "G9": KTN_PRIOR_BENEFIT if prior else None,
                                 "G8": ESV_CAT["mat"], "G15": seg_days, "G16": share, "G17": base_mat, "G18": None,
                                 "G19": 0.0, "G20": r2(base_mat * rate / 100.0), "rate": rate, "G14": None, "G13": None})
                    cur = seg_end + timedelta(days=1)
        sick = r2(sick_emp + sick_pfu + sick_care)
        if sick:
            base_sick = r2(min(sick, remaining)); remaining = r2(remaining - base_sick)
            esv_sick = r2(base_sick * rate / 100.0)
            sick_row = {**common, "G8": ESV_CAT["sick"], "G12": sick_days or None, "G16": sick, "G17": base_sick, "G18": None,
                        "G19": 0.0, "G20": esv_sick, "rate": rate, "G14": None}
            if late:
                # лікарняні за минулий місяць: рядок за той місяць з кодом типу нарахувань 13
                sick_row.update({"G101": period.month, "G102": period.year, "G9": KTN_PRIOR_BENEFIT, "G13": None})
            rows.append(sick_row)
        # копійки округлення - на основний рядок, щоб Σ рядків = ЄСВ листка
        delta = r2(esv_total - sum(r["G20"] for r in rows))
        if abs(delta) <= 0.05:
            rows[0]["G20"] = r2(rows[0]["G20"] + delta)
        if getattr(slip, "ua_diia_city", False) and rows:
            # Дія Сіті: ЄСВ - мінімальний внесок за місяць, тож один рядок за основною категорією:
            # нараховано все (і лікарняні), база - мінімальна зарплата, внесок - як у листку.
            # Окремі рядки 29 і 42 для резидента підтверджує бухгалтер.
            main = rows[0]
            main.update({"G16": r2(gross + mat), "G17": r2(params["min_wage"]) if esv_total else 0.0,
                         "G18": None, "G19": 0.0, "G20": esv_total})
            rows = [main]
            min_diff = 0.0
        if kind == "fop":
            rows = []   # ФОП-підрядник: без ЄСВ, у Д1 не потрапляє; лише 4ДФ з ознакою 157
        other = {}
        for sign, (income_codes, tax_codes) in OTHER_INCOME.items():
            income = r2(sum(self._line(slip, code) for code in income_codes))
            taxable = r2(sum(self._line(slip, code) for code in tax_codes))
            if income:
                other[sign] = (income, taxable)
        pay = r2(salary + vacation + ahead_total)   # головна форма, рядок 1.1: уся зарплата з відпускними
        return rows, {"gross": gross, "salary": pay, "gph": pay if kind in CIVIL_KINDS else 0.0, "sick_emp": sick_emp, "sick_pfu": r2(sick_pfu + sick_care), "mat": mat,
                      "pdfo": r2(-self._line(slip, "PDFO")), "vz": r2(-self._line(slip, "VZ")), "kind": kind, "cat": cat, "min_diff": min_diff,
                      "other": other, "other_income": r2(sum(v[0] for v in other.values())),
                      "emp": emp, "hire": hire, "dism": dism}

    def _row_head(self, emp, kind, days_in):
        """Спільна частина рядків Д1 людини: особа, місяць, дні трудових відносин, ознаки."""
        d1, d2 = self._period()
        return {"G5": "1", "G6": GENDER.get(getattr(emp, "sex", None) or "", None), "G7S": emp.ua_rnokpp or "",
                "G9": None, "G101": self.month, "G102": self.year, "names": emp._ua_name_parts(), "G14": days_in,
                "employee_id": emp.id, **self._flags(emp, kind, d1, d2)}

    def _flags(self, emp, kind, d1, d2):
        """Ознаки рядка Д1 (графи 21-24, 26): стабільні на весь місяць, з картки і версії договору."""
        version = self._version_in_month(emp, d1, d2).sudo()
        part_time = (not emp.ua_full_time) or float(emp.ua_fte or "1") < 1.0
        new_place = bool(version.ua_new_workplace) and (
            not version.ua_new_workplace_until or version.ua_new_workplace_until >= d1)
        return {"G21": "1" if (emp.ua_main_job and kind == "employment") else "0",
                "G22": "1" if part_time else "0",
                "G23": "1" if version.ua_special_seniority else "0",
                "G24": "1" if new_place else "0",
                "G26": "1" if version.ua_unfixed_hours else "0"}

    @staticmethod
    def _version_in_month(emp, d1, d2):
        """Версія договору, що діє в місяці (остання з тих, що його перетинають), або порожній запис."""
        versions = emp.version_ids.filtered(lambda v: v.contract_date_start and v.contract_date_start <= d2
                                            and (not v.contract_date_end or v.contract_date_end >= d1)).sorted("contract_date_start")
        return versions[-1:]

    def _employment_dates(self, emp, d1, d2):
        """Період трудових відносин у місяці з версій контракту (hr.version): одна картка, кілька періодів роботи.
        Повторне прийняття = нова версія з новою датою початку; історія не втрачається."""
        version = self._version_in_month(emp, d1, d2)
        if version:
            return version.contract_date_start, version.contract_date_end
        return emp.ua_hire_date, emp.ua_dismissal_date

    def _days_in(self, emp, d1, d2):
        """Календарні дні трудових відносин у місяці і межі цих відносин."""
        hire, dism = self._employment_dates(emp, d1, d2)
        start = max(d1, hire) if hire else d1
        end = min(d2, dism) if dism else d2
        return max((end - start).days + 1, 0), hire, dism

    # ---- військова служба без листка ----------------------------------------------
    def _idle_employees(self, slips):
        """Працівники на військовій службі (місце роботи зберігається), за яких у місяці немає листка.

        Трудові відносини тривають, тож людина є в Д1: категорія 1 (2 - з інвалідністю), дні трудових
        відносин у графі 14, суми нульові. У 4ДФ її немає: доходу не було."""
        d1, d2 = self._period()
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id.company_id", "=", self.company_id.id), ("state", "=", "validate"),
            ("holiday_status_id.work_entry_type_id.code", "=", MIL_CODE),
            ("request_date_from", "<=", d2), ("request_date_to", ">=", d1)])
        people = leaves.mapped("employee_id") - slips.mapped("employee_id")
        return people.filtered(lambda e: (e.ua_contract_kind or "employment") == "employment"
                               and self._days_in(e, d1, d2)[0] > 0).sorted("name")

    def _idle_rows(self, emp, params):
        d1, d2 = self._period()
        days_in, hire, dism = self._days_in(emp, d1, d2)
        disabled = emp.ua_esv_category == "disabled"
        cat = ESV_CAT["disabled"] if disabled else ESV_CAT["employment"]
        row = {**self._row_head(emp, "employment", days_in), "G8": cat, "G12": None, "G13": None, "G15": None,
               "G16": 0.0, "G17": 0.0, "G18": None, "G19": 0.0, "G20": 0.0,
               "rate": params["esv_rate_disabled"] if disabled else params["esv_rate"]}
        person = {"gross": 0.0, "salary": 0.0, "gph": 0.0, "sick_emp": 0.0, "sick_pfu": 0.0, "mat": 0.0, "pdfo": 0.0,
                  "vz": 0.0, "kind": "employment", "cat": cat, "min_diff": 0.0, "other": {}, "other_income": 0.0,
                  "emp": emp, "hire": hire, "dism": dism, "idle": True}
        return [row], person

    @staticmethod
    def _merge_rows(rows):
        """Рядки з тим самим ключем (особа, категорія, код типу, місяць) - один рядок із сумами.

        Так буває, коли в місяці два листки людини: основний і коригування за минулий місяць."""
        merged, order = {}, []
        for row in rows:
            key = tuple(row.get(col) for col in D1_KEY)
            if key not in merged:
                merged[key] = dict(row)
                order.append(key)
                continue
            into = merged[key]
            for col in D1_ADD:
                if row.get(col) is not None or into.get(col) is not None:
                    total = (into.get(col) or 0) + (row.get(col) or 0)
                    into[col] = total if col in ("G12", "G13", "G15") else r2(total)
            if row.get("G14") is not None:
                into["G14"] = max(into.get("G14") or 0, row["G14"])
        return [merged[key] for key in order]

    # ---- builders --------------------------------------------------------
    def _company_head(self):
        return [("HZ", self.doc_type == "HZ"), ("HZN", self.doc_type == "HZN"), ("HZU", self.doc_type == "HZU"),
                ("HZY", self.year), ("HZM", self.month)]

    def _signers(self):
        c = self.company_id
        return [("HFILL", self.fill_date), ("HKBOS", c.ua_director_rnokpp or ""), ("HBOS", c.ua_director_name or ""),
                ("HKBUH", c.ua_accountant_rnokpp or None), ("HBUH", c.ua_accountant_name or None)]

    # ---- рядки як текст: один формат і для нових даних, і для розібраного XML ----------
    def _text_row(self, row, cols, flag="0"):
        """Рядок у тому вигляді, у якому він лягає в XML: усі колонки - рядки тексту."""
        X = self.env["ua.dps.xml"]
        out = {}
        for col in cols:
            names = next((group for group in NAME_COLS if col in group), None)
            if names and "names" in row:
                value = row["names"][names.index(col)]
            else:
                value = row.get(col)
            out[col] = "" if value is None or value == "" or value is False else X._fmt(value)
        out[D1_FLAG if cols is D1_COLS else D6_FLAG if cols is D6_COLS else DF_FLAG] = flag
        return out

    @staticmethod
    def _rows_from_xml(data, cols):
        """Рядки додатка з поданого XML: елементи T1RXXXX<колонка> з атрибутом ROWNUM."""
        from lxml import etree

        from ..models.ua_dps_xml import safe_fromstring

        root = safe_fromstring(data)
        rows = {}
        for element in root.iter():
            tag = etree.QName(element).localname
            if not tag.startswith("T1RXXXX"):
                continue
            col = tag[len("T1RXXXX"):]
            if col not in cols:
                continue
            number = int(element.get("ROWNUM") or 0)
            rows.setdefault(number, {c: "" for c in cols})[col] = (element.text or "").strip()
        return [rows[key] for key in sorted(rows)]

    @staticmethod
    def _diff_rows(old_rows, new_rows, key_cols, flag_col):
        """Рядки коригування: спершу вилучення старих (ознака 1), потім введення нових (ознака 0).
        Незмінені рядки в коригування не потрапляють."""
        def key(row):
            return tuple(row.get(col, "") for col in key_cols)

        def payload(row):
            return tuple((col, value) for col, value in sorted(row.items()) if col != flag_col)

        old_by_key, new_by_key = {}, {}
        for row in old_rows:
            old_by_key.setdefault(key(row), []).append(row)
        for row in new_rows:
            new_by_key.setdefault(key(row), []).append(row)
        remove, add = [], []
        for row_key in sorted(set(old_by_key) | set(new_by_key)):
            olds, news = old_by_key.get(row_key, []), new_by_key.get(row_key, [])
            old_payloads = [payload(row) for row in olds]
            new_payloads = [payload(row) for row in news]
            if old_payloads == new_payloads:
                continue
            remove += [dict(row, **{flag_col: "1"}) for row in olds]
            add += [dict(row, **{flag_col: "0"}) for row in news]
        return remove + add

    @staticmethod
    def _signed_sum(rows, col, flag_col):
        total = 0.0
        for row in rows:
            value = row.get(col) or ""
            if not value:
                continue
            total += -float(value) if row.get(flag_col) == "1" else float(value)
        return r2(total)

    def _build_d1(self, all_rows, text_rows=None):
        c = self.company_id
        rows = text_rows if text_rows is not None else [self._text_row(r, D1_COLS) for r in all_rows]
        f = self._company_head() + [("HNAME", c.name), ("HTIN", c.company_registry)]
        for col in D1_COLS:                                  # формат ДПС: усі значення однієї колонки підряд, з ROWNUM
            for i, r in enumerate(rows, 1):
                f.append((f"T1RXXXX{col}", r.get(col) or None, {"ROWNUM": i}))
        for tag, col in D1_SUMS:                             # порядок елементів як у схемі: G16, G17, G18, G19, G20
            if col is None:
                f.append((tag, 0.0))
                continue
            value = self._signed_sum(rows, col, D1_FLAG)
            f.append((tag, value if (value or tag != "R01G18") else None))
        return f + self._signers()

    def _4df_rows(self, persons):
        """Рядки 4ДФ: зарплата, виплати поза зарплатою за своїми ознаками і допомога по вагітності та пологах.

        Податок ділиться між рядками пропорційно оподатковуваній частині кожного доходу;
        копійки округлення лишаються на рядку зарплати."""
        d1, d2 = self._period()
        rows = []
        persons = [p for p in persons if self._in_4df(p)]
        for p in persons:
            other = p.get("other") or {}
            base = r2(p["gross"] + sum(taxable for _income, taxable in other.values()))
            extra_rows, used_pdfo, used_vz = [], 0.0, 0.0
            for sign in sorted(other):
                income, taxable = other[sign]
                share = (taxable / base) if base else 0.0
                pdfo_sign, vz_sign = r2(p["pdfo"] * share), r2(p["vz"] * share)
                used_pdfo, used_vz = r2(used_pdfo + pdfo_sign), r2(used_vz + vz_sign)
                extra_rows.append({"employee_id": p["emp"].id, "G02": p["emp"].ua_rnokpp or "", "G03A": income, "G03": income,
                                   "G04A": pdfo_sign, "G04": pdfo_sign, "G5A": vz_sign, "G5": vz_sign, "G05": sign,
                                   "G06D": None, "G07D": None, "G08": None, "G09": None})
            main_pdfo, main_vz = r2(p["pdfo"] - used_pdfo), r2(p["vz"] - used_vz)
            rows.append({"employee_id": p["emp"].id, "G02": p["emp"].ua_rnokpp or "", "G03A": p["gross"], "G03": p["gross"], "G04A": main_pdfo, "G04": main_pdfo,
                         "G5A": main_vz, "G5": main_vz, "G05": INCOME_SIGN.get(p["kind"], "101"),
                         "G06D": p["hire"] if (p["hire"] and d1 <= p["hire"] <= d2) else None,
                         "G07D": p["dism"] if (p["dism"] and d1 <= p["dism"] <= d2) else None,
                         "G08": PSP_CODE.get(p["emp"].ua_psp or "none"), "G09": None})
            rows += extra_rows
        for p in persons:
            if p.get("mat"):
                rows.append({"employee_id": p["emp"].id, "G02": p["emp"].ua_rnokpp or "", "G03A": p["mat"], "G03": p["mat"], "G04A": 0.0, "G04": 0.0, "G5A": 0.0, "G5": 0.0, "G05": "128",
                             "G06D": None, "G07D": None, "G08": None, "G09": None})
        return rows

    @staticmethod
    def _in_4df(person):
        """У 4ДФ - лише ті, кому щось нараховано: людина на військовій службі без зарплати туди не йде."""
        return not person.get("idle") and bool(person["gross"] or person.get("other") or person.get("mat"))

    def _build_4df(self, persons, text_rows=None):
        c = self.company_id
        rows = text_rows if text_rows is not None else [self._text_row(r, DF_COLS) for r in self._4df_rows(persons)]
        f = self._company_head() + [("HNUM", self.number), ("HNAME", c.name), ("HTIN", c.company_registry), ("HKATOTTG", c.ua_katottg or "")]
        income = [p for p in persons if self._in_4df(p)]
        f += [("R00G01I", sum(1 for p in income if p["kind"] == "employment")), ("R00G02I", sum(1 for p in income if p["kind"] in CIVIL_KINDS))]
        for col in DF_COLS:
            for i, r in enumerate(rows, 1):
                f.append((f"T1RXXXX{col}", r.get(col) or None, {"ROWNUM": i}))
        f += [(tag, self._signed_sum(rows, col, DF_FLAG)) for tag, col in DF_SUMS]
        return f + self._signers()

    def _d5_rows(self):
        """Рядки Д5: кожна версія контракту, що почалася або закінчилася в місяці (прийняття, звільнення)."""
        d1, d2 = self._period()
        rows = []
        versions = self.env["hr.version"].sudo().search([("employee_id.company_id", "=", self.company_id.id), ("contract_date_start", "!=", False),
                                                          "|", "&", ("contract_date_start", ">=", d1), ("contract_date_start", "<=", d2),
                                                          "&", ("contract_date_end", ">=", d1), ("contract_date_end", "<=", d2)])
        for v in versions.sorted(lambda v: (v.employee_id.name or "", v.contract_date_start)):
            emp = v.employee_id.sudo()
            started = d1 <= v.contract_date_start <= d2
            ended = bool(v.contract_date_end) and d1 <= v.contract_date_end <= d2
            kind = emp.ua_contract_kind or "employment"
            civil = kind in CIVIL_KINDS
            rows.append({"G5": "1", "G6": "1" if civil else "0", "G7": "3" if civil else "1",
                         "G8S": emp.ua_rnokpp or "", "names": emp._ua_name_parts(),
                         "G101D": v.contract_date_start if started else None, "G102D": v.contract_date_end if ended else None,
                         "G11": "1" if v.ua_internal_parttime else "0", "G12": "0",
                         "G13S": v.ua_prof_name or v.job_id.name or emp.job_title or "", "G14S": v.ua_kp_code or "",
                         "G15S": v.job_title or v.job_id.name or emp.job_title or "",
                         "G16S": (v.ua_order_ref if started else v.ua_end_order_ref) or "",
                         "G17S": (v.ua_dismissal_basis or "") if ended else None, "G18D": None, "G19S": None, "G20": None})
        return rows

    def _build_d5(self, rows):
        c = self.company_id
        f = self._company_head() + [("HNAME", c.name), ("HTIN", c.company_registry)]
        for col in ["G5", "G6", "G7", "G8S", "G91S", "G92S", "G93S", "G101D", "G102D", "G11", "G12", "G13S", "G14S", "G15S", "G16S", "G17S", "G18D", "G19S", "G20"]:
            for i, r in enumerate(rows, 1):
                val = r["names"][("G91S", "G92S", "G93S").index(col)] if col in ("G91S", "G92S", "G93S") else r.get(col)
                f.append((f"T1RXXXX{col}", val, {"ROWNUM": i}))
        return f + self._signers()

    def _d6_rows(self):
        """Рядки Д6: людина в місяці працювала на роботі зі спецстажем (позначка і код у версії договору).

        Період - дні трудових відносин цієї версії в місяці, облік у календарних днях: графа 11 -
        дні періоду без днів відпустки без збереження зарплати, графа 13 - календарні дні місяця.
        Відпустки по вагітності та догляду за дитиною стаж не переривають (п. 6 розд. IV Порядку № 4)."""
        d1, d2 = self._period()
        versions = self.env["hr.version"].sudo().search([
            ("employee_id.company_id", "=", self.company_id.id), ("ua_special_seniority", "=", True),
            ("contract_date_start", "!=", False), ("contract_date_start", "<=", d2),
            "|", ("contract_date_end", "=", False), ("contract_date_end", ">=", d1)])
        rows = []
        for version in versions.sorted(lambda v: (v.employee_id.name or "", v.contract_date_start)):
            emp = version.employee_id.sudo()
            if (emp.ua_contract_kind or "employment") != "employment" or not version.ua_special_seniority_code:
                continue
            start = max(d1, version.contract_date_start)
            end = min(d2, version.contract_date_end) if version.contract_date_end else d2
            if end < start:
                continue
            unpaid = self.env["hr.leave"].sudo().search([
                ("employee_id", "=", emp.id), ("state", "=", "validate"),
                ("holiday_status_id.work_entry_type_id.code", "=", "UNPAID"),
                ("request_date_from", "<=", end), ("request_date_to", ">=", start)])
            off = sum((min(lv.request_date_to, end) - max(lv.request_date_from, start)).days + 1 for lv in unpaid)
            days = (end - start).days + 1 - off
            if days <= 0:
                continue
            rows.append({"G5": "1", "G6S": emp.ua_rnokpp or "", "G7S": version.ua_special_seniority_code,
                         "names": emp._ua_name_parts(), "G9": start.day, "G10": end.day, "G11": days,
                         "G121": None, "G122": None, "G131": (d2 - d1).days + 1, "G132": None, "G133": None,
                         "G14S": version.ua_special_attest_number or None, "G15D": version.ua_special_attest_date or None,
                         "G16": None, "employee_id": emp.id})
        return rows

    def _build_d6(self, rows, text_rows=None):
        c = self.company_id
        rows = text_rows if text_rows is not None else [self._text_row(r, D6_COLS) for r in rows]
        f = self._company_head() + [("HNAME", c.name), ("HTIN", c.company_registry)]
        for col in D6_COLS:
            for i, r in enumerate(rows, 1):
                f.append((f"T1RXXXX{col}", r.get(col) or None, {"ROWNUM": i}))
        return f + self._signers()

    def _build_main(self, persons, all_rows, params, n_d1, n_4df, n_d5=0, n_d6=0):
        c = self.company_id
        rate22 = [r for r in all_rows if r["rate"] == params["esv_rate"]]
        rate841 = [r for r in all_rows if r["rate"] == params["esv_rate_disabled"] and r["rate"] != params["esv_rate"]]
        s = lambda rows, k: r2(sum(r[k] or 0 for r in rows))
        r1_1 = r2(sum(p["salary"] for p in persons if p["kind"] not in CIVIL_KINDS))
        r1_2 = r2(sum(p["gph"] for p in persons))
        r1_3 = r2(sum(p["sick_emp"] for p in persons)); r1_4 = r2(sum(p["sick_pfu"] for p in persons))
        r2_1, r2_2 = s(rate22, "G17"), s(rate841, "G17")
        r2_5 = r2(sum(p["min_diff"] for p in persons))
        r3_5 = r2(r2_5 * 22 / 100.0)
        r3_1 = r2(s(rate22, "G20") - r3_5); r3_2 = s(rate841, "G20")
        employment = [p for p in persons if p["kind"] == "employment"]
        f = self._company_head() + [("HNUM", self.number), ("HNAME", c.name), ("HTIN", c.company_registry), ("HKATOTTG", c.ua_katottg or ""),
             ("HLOC", c.street or ""), ("HZIP", c.zip or ""), ("HTEL", c.phone or None), ("HEMAIL", c.email or None), ("HSTI", c.ua_sti_name or ""),
             ("R061G3", bool(n_d1)), ("R061G4", n_d1 or None), ("R064G3", bool(n_4df)), ("R064G4", n_4df or None),
             ("R065G3", bool(n_d5)), ("R065G4", n_d5 or None), ("R066G3", bool(n_d6)), ("R066G4", n_d6 or None),
             ("HKVED", c.ua_kved or None), ("R081G3", True),
             ("R091G3", len(employment)), ("R0911G3", sum(1 for p in employment if p["emp"].ua_esv_category == "disabled")),
             ("R092G3", len(employment)), ("R101G3", 0),
             ("R0101G3", r2(r1_1 + r1_2 + r1_3 + r1_4)), ("R01011G3", r1_1), ("R01012G3", r1_2), ("R01013G3", r1_3), ("R01014G3", r1_4), ("R01015G3", 0.0),
             ("R0102G3", r2(r2_1 + r2_2 + r2_5)), ("R01021G3", r2_1), ("R01022G3", r2_2), ("R01025G3", r2_5),
             ("R0103G3", r2(r3_1 + r3_2 + r3_5)), ("R01031G3", r3_1), ("R01032G3", r3_2), ("R010321G3", r2(r2_2 * 22 / 100.0) if r2_2 else 0.0), ("R01035G3", r3_5),
             ("R0104G3", 0.0), ("R0106G3", 0.0), ("R0107G3", r2(r3_1 + r3_2 + r3_5))]
        return f + self._signers()

    # ---- action ------------------------------------------------------------
    def _base_rows(self, sub, cols):
        """Рядки додатка з поданого XML: файл упізнаємо за кодом додатка в імені (J0510111, J0510411)."""
        code = "J05%s%s" % (sub, VER)
        for attachment in self.base_attachment_ids:
            if code in (attachment.name or ""):
                return self._rows_from_xml(base64.b64decode(attachment.datas), cols)
        return None

    def _correction_rows(self, all_rows, df_rows):
        """Рядки коригування для Д1 і 4ДФ: вилучення поданих рядків і введення виправлених."""
        if not self.base_attachment_ids:
            raise UserError("Для звітного нового і уточнюючого розрахунку додайте файли раніше поданого розрахунку: "
                            "з них беруться рядки на вилучення.")
        old_d1 = self._base_rows("101", D1_COLS)
        old_df = self._base_rows("104", DF_COLS)
        if old_d1 is None and old_df is None:
            raise UserError("Серед доданих файлів немає ні Д1 (J0510111), ні 4ДФ (J0510411).")
        new_d1 = [self._text_row(r, D1_COLS) for r in all_rows]
        new_df = [self._text_row(r, DF_COLS) for r in df_rows]
        d1_text = self._diff_rows(old_d1 or [], new_d1, D1_KEY, D1_FLAG) if old_d1 is not None else None
        df_text = self._diff_rows(old_df or [], new_df, DF_KEY, DF_FLAG) if old_df is not None else None
        if not (d1_text or df_text):
            raise UserError("Розбіжностей з поданим розрахунком немає: коригувати нічого.")
        return d1_text, df_text

    def action_generate(self):
        self.ensure_one()
        c = self.company_id
        if not c.company_registry or not c.ua_sti_code:
            raise UserError("Заповніть у компанії ЄДРПОУ і код ДПІ (Налаштування → Компанії → «Україна»).")
        persons, all_rows, params = self._collect()
        df_rows = self._4df_rows(persons)
        log = []
        if self.lines_edited:
            # бухгалтер зібрав рядки і поправив їх: файли - з рядків як є
            computed_g16 = r2(sum(r["G16"] or 0.0 for r in all_rows))
            all_rows = [line._as_row() for line in self.d1_line_ids]
            df_rows = [line._as_row() for line in self.df_line_ids]
            edited_g16 = r2(sum(r["G16"] or 0.0 for r in all_rows))
            log.append("Д1 і 4ДФ сформовано з рядків, поправлених вручну.")
            if abs(edited_g16 - computed_g16) >= 0.01:
                log.append("Увага: графа 16 Д1 після правок %.2f, за листками %.2f. Суми нарахувань головної форми "
                           "(рядок 1.1-1.4) взято з листків - звірте їх перед поданням." % (edited_g16, computed_g16))
        X = self.env["ua.dps.xml"]
        stan = {"HZ": 1, "HZN": 1, "HZU": 3}[self.doc_type]  # STAN: 1 звітний/новий звітний, 3 уточнюючий (як у прикладах)
        d1_text = df_text = None
        if self.doc_type in ("HZN", "HZU"):
            d1_text, df_text = self._correction_rows(all_rows, df_rows)
        elif self.lines_edited:
            df_text = [self._text_row(r, DF_COLS) for r in df_rows]
        files = []
        main_name = X.file_name(c.company_registry, c.ua_sti_code, "J05", "001", VER, stan, 0, self.number, 1, self.month, self.year, c.ua_sti_code)
        appendices = []
        if self.with_d1:
            appendices.append(("101", "J0510111", self._build_d1(all_rows, text_rows=d1_text)))
        if self.with_4df:
            appendices.append(("104", "J0510411", self._build_4df(persons, text_rows=df_text)))
        d5_rows = self._d5_rows() if self.with_d5 else []
        if d5_rows:
            appendices.append(("105", "J0510511", self._build_d5(d5_rows)))
        d6_rows = self._d6_rows() if self.with_d6 else []
        d6_text = None
        if d6_rows and self.doc_type in ("HZN", "HZU"):
            # коригування: вилучити подані рядки Д6 і ввести виправлені; без поданого Д6 - усі рядки на введення
            old_d6 = self._base_rows("106", D6_COLS)
            new_d6 = [self._text_row(r, D6_COLS) for r in d6_rows]
            d6_text = self._diff_rows(old_d6, new_d6, D6_KEY, D6_FLAG) if old_d6 is not None else new_d6
        if d6_rows and (d6_text is None or d6_text):
            appendices.append(("106", "J0510611", self._build_d6(d6_rows, text_rows=d6_text)))
        linked_for_main, app_files = [], []
        for i, (sub, code, body) in enumerate(appendices, 1):
            linked = [{"num": 1, "type": 2, "C_DOC": "J05", "C_DOC_SUB": "001", "C_DOC_VER": VER, "C_DOC_TYPE": 0, "C_DOC_CNT": self.number, "C_DOC_STAN": stan, "FILENAME": main_name}]
            fname, data = X.build(c, "J05", sub, VER, 1, self.month, self.year, body, linked=linked, c_doc_cnt=self.number, c_doc_stan=stan, fill_date=self.fill_date)
            app_files.append((fname, data, code))
            linked_for_main.append({"num": i, "type": 1, "C_DOC": "J05", "C_DOC_SUB": sub, "C_DOC_VER": VER, "C_DOC_TYPE": 0, "C_DOC_CNT": self.number, "C_DOC_STAN": stan, "FILENAME": fname})
        has_d6 = any(sub == "106" for sub, _code, _body in appendices)
        body_main = self._build_main(persons, all_rows, params, 1 if self.with_d1 else 0, 1 if self.with_4df else 0,
                                     1 if d5_rows else 0, 1 if has_d6 else 0)
        fname, data = X.build(c, "J05", "001", VER, 1, self.month, self.year, body_main, linked=linked_for_main, c_doc_cnt=self.number, c_doc_stan=stan, fill_date=self.fill_date)
        files.append((fname, data, "J0500111")); files += app_files
        Att = self.env["ir.attachment"]; atts = Att
        for fname, data, code in files:
            errs = X.validate(data, code)
            log.append(f"{fname}: {'валідний за ' + code + '.xsd' if not errs else 'ПОМИЛКИ: ' + '; '.join(errs[:8])}")
            atts |= Att.create({"name": fname, "datas": base64.b64encode(data), "mimetype": "application/xml", "res_model": self._name, "res_id": self.id})
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fname, data, _ in files:
                z.writestr(fname, data)
        atts |= Att.create({"name": f"J05_{self.year}-{self.month:02d}.zip", "datas": base64.b64encode(buf.getvalue()), "mimetype": "application/zip", "res_model": self._name, "res_id": self.id})
        self.write({"result_ids": [(6, 0, atts.ids)], "log": "\n".join(log)})
        return self._reopen()

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}

    def _collect(self):
        """Рядки Д1 і дані людей з проведених листків місяця плюс люди на військовій службі без листка."""
        c = self.company_id
        slips = self._payslips()
        idle = self._idle_employees(slips)
        if not slips and not idle:
            raise UserError("Немає підтверджених листків за цей місяць.")
        params = self.env["ua.payroll.param"].get_all(self._period()[1], c)
        persons, all_rows = [], []
        for slip in slips:
            rows, person = self._person_rows(slip, params)
            all_rows += rows
            persons.append(person)
        for emp in idle:
            rows, person = self._idle_rows(emp, params)
            all_rows += rows
            persons.append(person)
        return persons, self._merge_rows(all_rows), params

    # ---- рядки для правок перед формуванням ---------------------------------------
    def action_collect(self):
        """Зібрати рядки Д1 і 4ДФ у таблиці: бухгалтер править їх, потім «Сформувати» бере рядки як є."""
        self.ensure_one()
        persons, all_rows, _params = self._collect()
        D1Line, DfLine = self.env["ua.payroll.report.d1.line"], self.env["ua.payroll.report.df.line"]
        self.d1_line_ids.unlink()
        self.df_line_ids.unlink()
        for index, row in enumerate(all_rows, 1):
            D1Line.create(D1Line._vals_from_row(self, row, index))
        for index, row in enumerate(self._4df_rows(persons), 1):
            DfLine.create(DfLine._vals_from_row(self, row, index))
        self.write({"lines_edited": True, "result_ids": [(5, 0, 0)], "log": False})
        return self._reopen()

    def action_drop_lines(self):
        """Прибрати зібрані рядки: файли знову рахуються прямо з листків."""
        self.d1_line_ids.unlink()
        self.df_line_ids.unlink()
        self.write({"lines_edited": False})
        return self._reopen()
