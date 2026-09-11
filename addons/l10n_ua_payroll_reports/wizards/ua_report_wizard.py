"""Об'єднана звітність (J0500111) з Д1 (J0510111) і 4ДФ (J0510411) за місяць, з проведених листків."""
import base64
import calendar
import io
import zipfile
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

VER = "11"
ESV_CAT = {"employment": "1", "disabled": "2", "gph": "26", "sick": "29", "mat": "42"}
INCOME_SIGN = {"employment": "101", "gph": "102", "fop": "157"}   # ознака доходу 4ДФ
PSP_CODE = {"none": None, "base": "01", "child": "04", "child150": "04", "s150": "02", "s200": "03"}
GENDER = {"male": "1", "female": "0"}   # схема допускає лише 0 або 1; трактування підтвердити (припущення: 1 = чоловік, 0 = жінка)


D1_COLS = ["G5", "G6", "G7S", "G8", "G9", "G101", "G102", "G111S", "G112S", "G113S", "G12", "G13", "G14",
           "G15", "G16", "G17", "G18", "G19", "G20", "G21", "G22", "G23", "G24", "G25", "G26"]
DF_COLS = ["G02", "G03A", "G03", "G04A", "G04", "G5A", "G5", "G05", "G06D", "G07D", "G08", "G09"]
D1_FLAG, DF_FLAG = "G26", "G09"          # графа «Ознака (0, 1)»: 0 - рядок на введення, 1 - на вилучення
D1_KEY = ("G7S", "G8", "G101", "G102")   # РНОКПП, категорія ЗО, місяць, рік
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
    fill_date = fields.Date("Дата заповнення", default=fields.Date.context_today, required=True)
    base_attachment_ids = fields.Many2many(
        "ir.attachment", "ua_report_wizard_base_att_rel", "wizard_id", "attachment_id",
        string="Файли поданого розрахунку",
        help="XML раніше поданого розрахунку за цей місяць. Для звітного нового і уточнюючого "
             "з них беруться рядки, які треба вилучити.")
    result_ids = fields.Many2many("ir.attachment", string="Файли")
    log = fields.Text("Перевірка за схемою", readonly=True)

    # ---- data collection ------------------------------------------------
    def _period(self):
        d1 = date(self.year, self.month, 1)
        return d1, date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    def _payslips(self):
        d1, d2 = self._period()
        return self.env["hr.payslip"].search([("company_id", "=", self.company_id.id), ("state", "=", "done"),
                                              ("date_from", ">=", d1), ("date_to", "<=", d2)], order="employee_id")

    def _line(self, slip, code):
        return sum(slip.line_ids.filtered(lambda l: l.code == code).mapped("total"))

    def _person_rows(self, slip, params):
        """Рядки Д1 для одного листка: основний рядок за категорією ЗО і окремий рядок 29 за лікарняні."""
        emp = slip.employee_id.sudo()
        d1, d2 = self._period()
        hire, dism = self._employment_dates(emp, d1, d2)
        start = max(d1, hire) if hire else d1
        end = min(d2, dism) if dism else d2
        days_in = max((end - start).days + 1, 0)
        kind = emp.ua_contract_kind or "employment"
        cat = ESV_CAT["gph"] if kind == "gph" else (ESV_CAT["disabled"] if emp.ua_esv_category == "disabled" else ESV_CAT["employment"])
        rate = params["esv_rate_disabled"] if emp.ua_esv_category == "disabled" else params["esv_rate"]
        sick_emp, sick_pfu = self._line(slip, "SICK_EMP"), self._line(slip, "SICK_PFU")
        gross = self._line(slip, "GROSS")
        salary = r2(gross - sick_emp - sick_pfu)
        esv_total = r2(self._line(slip, "ESV"))
        max_base = params["min_wage"] * params["esv_max_multiplier"]
        remaining = max_base
        rows = []
        # мінімальна доплата ЄСВ: різниця між МЗП і фактичним нарахуванням (лише основне місце, повний місяць)
        min_diff = 0.0
        leaves_all = slip._ua_leave_calendar_days() if hasattr(slip, "_ua_leave_calendar_days") else {}
        if kind == "employment" and emp.ua_main_job and gross < params["min_wage"] and days_in >= (d2 - d1).days + 1 and not leaves_all.get("mat_cover_days"):
            min_diff = r2(params["min_wage"] - gross)
        base_main = r2(min(salary, remaining)); remaining = r2(remaining - base_main)
        esv_main = r2(base_main * rate / 100.0)
        esv_diff = r2(min_diff * 22.0 / 100.0)
        leaves = slip._ua_leave_calendar_days() if hasattr(slip, "_ua_leave_calendar_days") else {}
        sick_days = (leaves.get("sick_emp_days", 0) + leaves.get("sick_pfu_days", 0))
        unpaid_days = leaves.get("unpaid_days", 0)
        part_time = (not emp.ua_full_time) or float(emp.ua_fte or "1") < 1.0
        common = {"G5": "1", "G6": GENDER.get(getattr(emp, "sex", None) or "", None), "G7S": emp.ua_rnokpp or "", "G101": self.month, "G102": self.year,
                  "names": emp._ua_name_parts(), "G21": "1" if (emp.ua_main_job and kind == "employment") else "0",
                  "G22": "1" if part_time else "0", "G23": "0", "G24": "0", "G26": "0", "G14": days_in, "G13": unpaid_days or None}
        rows.append({**common, "G8": cat, "G12": None, "G16": salary, "G17": base_main, "G18": min_diff or None, "G19": 0.0,
                     "G20": r2(esv_main + esv_diff), "rate": rate})
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
                    rows.append({**common, "G101": cur.month, "G102": cur.year, "G8": ESV_CAT["mat"], "G12": seg_days, "G16": share, "G17": base_mat, "G18": None,
                                 "G19": 0.0, "G20": r2(base_mat * rate / 100.0), "rate": rate, "G14": None, "G13": None})
                    cur = seg_end + timedelta(days=1)
        sick = r2(sick_emp + sick_pfu)
        if sick:
            base_sick = r2(min(sick, remaining)); remaining = r2(remaining - base_sick)
            esv_sick = r2(base_sick * rate / 100.0)
            rows.append({**common, "G8": ESV_CAT["sick"], "G12": sick_days or None, "G16": sick, "G17": base_sick, "G18": None,
                         "G19": 0.0, "G20": esv_sick, "rate": rate, "G14": None})
        # копійки округлення - на основний рядок, щоб Σ рядків = ЄСВ листка
        delta = r2(esv_total - sum(r["G20"] for r in rows))
        if abs(delta) <= 0.05:
            rows[0]["G20"] = r2(rows[0]["G20"] + delta)
        if kind == "fop":
            rows = []   # ФОП-підрядник: без ЄСВ, у Д1 не потрапляє; лише 4ДФ з ознакою 157
        return rows, {"gross": gross, "salary": salary, "gph": salary if kind == "gph" else 0.0, "sick_emp": sick_emp, "sick_pfu": sick_pfu, "mat": mat,
                      "pdfo": r2(-self._line(slip, "PDFO")), "vz": r2(-self._line(slip, "VZ")), "kind": kind, "cat": cat, "min_diff": min_diff,
                      "emp": emp, "hire": hire, "dism": dism}

    def _employment_dates(self, emp, d1, d2):
        """Період трудових відносин у місяці з версій контракту (hr.version): одна картка, кілька періодів роботи.
        Повторне прийняття = нова версія з новою датою початку; історія не втрачається."""
        versions = emp.version_ids.filtered(lambda v: v.contract_date_start and v.contract_date_start <= d2
                                            and (not v.contract_date_end or v.contract_date_end >= d1)).sorted("contract_date_start")
        if versions:
            v = versions[-1]
            return v.contract_date_start, v.contract_date_end
        return emp.ua_hire_date, emp.ua_dismissal_date

    # ---- builders --------------------------------------------------------
    def _company_head(self):
        c = self.company_id
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
            if col in ("G111S", "G112S", "G113S") and "names" in row:
                value = row["names"][("G111S", "G112S", "G113S").index(col)]
            else:
                value = row.get(col)
            out[col] = "" if value is None or value == "" or value is False else X._fmt(value)
        out[D1_FLAG if cols is D1_COLS else DF_FLAG] = flag
        return out

    @staticmethod
    def _rows_from_xml(data, cols):
        """Рядки додатка з поданого XML: елементи T1RXXXX<колонка> з атрибутом ROWNUM."""
        from lxml import etree

        root = etree.fromstring(data)
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
        """Рядки 4ДФ: основний дохід кожної особи плюс окремий рядок допомоги по вагітності та пологах."""
        d1, d2 = self._period()
        rows = []
        for p in persons:
            rows.append({"G02": p["emp"].ua_rnokpp or "", "G03A": p["gross"], "G03": p["gross"], "G04A": p["pdfo"], "G04": p["pdfo"],
                         "G5A": p["vz"], "G5": p["vz"], "G05": INCOME_SIGN.get(p["kind"], "101"),
                         "G06D": p["hire"] if (p["hire"] and d1 <= p["hire"] <= d2) else None,
                         "G07D": p["dism"] if (p["dism"] and d1 <= p["dism"] <= d2) else None,
                         "G08": PSP_CODE.get(p["emp"].ua_psp or "none"), "G09": None})
        for p in persons:
            if p.get("mat"):
                rows.append({"G02": p["emp"].ua_rnokpp or "", "G03A": p["mat"], "G03": p["mat"], "G04A": 0.0, "G04": 0.0, "G5A": 0.0, "G5": 0.0, "G05": "128",
                             "G06D": None, "G07D": None, "G08": None, "G09": None})
        return rows

    def _build_4df(self, persons, text_rows=None):
        c = self.company_id
        rows = text_rows if text_rows is not None else [self._text_row(r, DF_COLS) for r in self._4df_rows(persons)]
        f = self._company_head() + [("HNUM", self.number), ("HNAME", c.name), ("HTIN", c.company_registry), ("HKATOTTG", c.ua_katottg or "")]
        f += [("R00G01I", sum(1 for p in persons if p["kind"] == "employment")), ("R00G02I", sum(1 for p in persons if p["kind"] == "gph"))]
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
            rows.append({"G5": "1", "G6": "1" if kind == "gph" else "0", "G7": "3" if kind == "gph" else "1",
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

    def _build_main(self, persons, all_rows, params, n_d1, n_4df, n_d5=0):
        c = self.company_id
        rate22 = [r for r in all_rows if r["rate"] == params["esv_rate"]]
        rate841 = [r for r in all_rows if r["rate"] == params["esv_rate_disabled"] and r["rate"] != params["esv_rate"]]
        s = lambda rows, k: r2(sum(r[k] or 0 for r in rows))
        r1_1 = r2(sum(p["salary"] for p in persons if p["kind"] != "gph"))
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
             ("R065G3", bool(n_d5)), ("R065G4", n_d5 or None),
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

    def _correction_rows(self, all_rows, persons):
        """Рядки коригування для Д1 і 4ДФ: вилучення поданих рядків і введення виправлених."""
        if not self.base_attachment_ids:
            raise UserError("Для звітного нового і уточнюючого розрахунку додайте файли раніше поданого розрахунку: "
                            "з них беруться рядки на вилучення.")
        old_d1 = self._base_rows("101", D1_COLS)
        old_df = self._base_rows("104", DF_COLS)
        if old_d1 is None and old_df is None:
            raise UserError("Серед доданих файлів немає ні Д1 (J0510111), ні 4ДФ (J0510411).")
        new_d1 = [self._text_row(r, D1_COLS) for r in all_rows]
        new_df = [self._text_row(r, DF_COLS) for r in self._4df_rows(persons)]
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
        slips = self._payslips()
        if not slips:
            raise UserError("Немає підтверджених листків за цей місяць.")
        params = self.env["ua.payroll.param"].get_all(self._period()[1], c)
        persons, all_rows = [], []
        for slip in slips:
            rows, p = self._person_rows(slip, params)
            all_rows += rows; persons.append(p)
        X = self.env["ua.dps.xml"]
        stan = {"HZ": 1, "HZN": 1, "HZU": 3}[self.doc_type]  # STAN: 1 звітний/новий звітний, 3 уточнюючий (як у прикладах)
        d1_text = df_text = None
        if self.doc_type in ("HZN", "HZU"):
            d1_text, df_text = self._correction_rows(all_rows, persons)
        files, log = [], []
        main_name = X.file_name(c.company_registry, c.ua_sti_code, "J05", "001", VER, stan, 0, self.number, 1, self.month, self.year, c.ua_sti_code)
        appendices = []
        if self.with_d1:
            appendices.append(("101", "J0510111", self._build_d1(all_rows, text_rows=d1_text)))
        if self.with_4df:
            appendices.append(("104", "J0510411", self._build_4df(persons, text_rows=df_text)))
        d5_rows = self._d5_rows() if self.with_d5 else []
        if d5_rows:
            appendices.append(("105", "J0510511", self._build_d5(d5_rows)))
        linked_for_main, app_files = [], []
        for i, (sub, code, body) in enumerate(appendices, 1):
            linked = [{"num": 1, "type": 2, "C_DOC": "J05", "C_DOC_SUB": "001", "C_DOC_VER": VER, "C_DOC_TYPE": 0, "C_DOC_CNT": self.number, "C_DOC_STAN": stan, "FILENAME": main_name}]
            fname, data = X.build(c, "J05", sub, VER, 1, self.month, self.year, body, linked=linked, c_doc_cnt=self.number, c_doc_stan=stan, fill_date=self.fill_date)
            app_files.append((fname, data, code))
            linked_for_main.append({"num": i, "type": 1, "C_DOC": "J05", "C_DOC_SUB": sub, "C_DOC_VER": VER, "C_DOC_TYPE": 0, "C_DOC_CNT": self.number, "C_DOC_STAN": stan, "FILENAME": fname})
        body_main = self._build_main(persons, all_rows, params, 1 if self.with_d1 else 0, 1 if self.with_4df else 0, 1 if d5_rows else 0)
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
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}
