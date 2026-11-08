# -*- coding: utf-8 -*-
"""Фінансова звітність до ДПС: Ф1, Ф2 і фінзвітність малого підприємства в XML.

Числа - з тих самих шаблонів mis_builder, що й друковані форми (l10n_ua_finrep): тимчасовий звіт
з одним фіксованим періодом на кожну графу.
- Баланс (Ф1, Ф1-м): графа 3 - на початок звітного року (кінець минулого), графа 4 - на кінець
  періоду.
- Фінрезультати (Ф2, Ф2-м): графа 3 - з 1 січня до кінця періоду, графа 4 - той самий період
  минулого року.
Суми в тисячах гривень: Ф1 і Ф2 без десяткового знака, мала форма - з одним. Після округлення
підсумкові рядки перевіряються формулами самих шаблонів; розбіжність бухгалтер виправляє рядком у
чернетці. Рядки «в дужках» (1425, 1430) у файлі додатні, прибуток і збиток Ф2 - окремими рядками
(2090/2095, 2190/2195, 2290/2295, 2350/2355).

XML будується за схемою ДПС із теки schemas (порядок тегів і формат чисел - зі схеми) і нею ж
перевіряється. Коди форм, версії схем і правила - перевіряйте чинні.
"""
import base64
import os
import re
from datetime import date

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas")
XS = "{http://www.w3.org/2001/XMLSchema}"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

STATES = [("draft", "Чернетка"), ("done", "Затверджено")]
FORMS = [
    ("J0900108", "Ф1. Баланс (J0900108)"),
    ("J0900207", "Ф2. Звіт про фінансові результати (J0900207)"),
    ("J0901107", "Фінзвітність малого підприємства, Ф1-м і Ф2-м (J0901107)"),
]
# Частини форми: шаблон l10n_ua_finrep і вид (баланс чи фінрезультати).
FORM_PARTS = {
    "J0900108": [("f1", "balance")],
    "J0900207": [("f2", "pnl")],
    "J0901107": [("f1m", "balance"), ("f2m", "pnl")],
}
FORM_DIGITS = {"J0900108": 0, "J0900207": 0, "J0901107": 1}
PERIODS = [("3", "I квартал"), ("6", "Півріччя"), ("9", "9 місяців"), ("12", "Рік")]
PERIOD_TYPE = {3: 2, 6: 3, 9: 4, 12: 5}
STANDARDS = [("nsbo", "НП(С)БО"), ("ifrs", "МСФЗ")]
# Текст періоду в шапці: «Баланс на 30 вересня ... р.», «Звіт ... за 9 місяців ... р.».
MONTHS_GENITIVE = {3: "31 березня", 6: "30 червня", 9: "30 вересня", 12: "31 грудня"}
PERIOD_TEXT = {3: "I квартал", 6: "I півріччя", 9: "9 місяців", 12: "рік"}
# Форми, де схема вимагає код КОАТУУ.
KOATUU_FORMS = {"J0900108", "J0901107"}
PARTS = [("f1", "Ф1"), ("f2", "Ф2"), ("f1m", "Ф1-м"), ("f2m", "Ф2-м")]

# Рядки, що у формі стоять у дужках, а в шаблоні мають знак мінус.
BRACKETS = {"1425", "1430"}
# Ф2 (повна): результат зі знаком у шаблоні -> рядок прибутку і рядок збитку.
SPLIT = {"2090": "2095", "2190": "2195", "2290": "2295", "2350": "2355"}
SPLIT_FORMS = {"J0900207"}

ROW_RE = re.compile(r"^[a-z](\d{4})$")
FORMULA_RE = re.compile(r"^\s*[+-]?\s*[a-z]\d{4}(\s*[+-]\s*[a-z]\d{4})*\s*$")
TERM_RE = re.compile(r"([+-]?)\s*[a-z](\d{4})")

_SCHEMAS = {}


def _schema(form):
    """(XMLSchema, [(тег, тип)] тіла) форми; схема читається один раз."""
    if form not in _SCHEMAS:
        tree = etree.parse(os.path.join(SCHEMAS_DIR, "%s.xsd" % form))
        body = tree.find(".//%scomplexType[@name='DBody']/%ssequence" % (XS, XS))
        elements = [(el.get("name"), el.get("type")) for el in body.iter(XS + "element")]
        _SCHEMAS[form] = (etree.XMLSchema(tree), elements)
    return _SCHEMAS[form]


def _digits(value):
    return re.sub(r"\D", "", value or "")


def _default_period(today):
    """Останній завершений звітний період: (рік, кінцевий місяць)."""
    quarter_end = 3 * ((today.month - 1) // 3)
    if quarter_end == 0:
        return today.year - 1, 12
    return today.year, quarter_end


class UaFinrepFiling(models.Model):
    _name = "ua.finrep.filing"
    _description = "Фінансова звітність до ДПС"
    _inherit = ["mail.thread"]
    _order = "date_to desc, form, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    form = fields.Selection(FORMS, "Форма", required=True, default="J0900108", tracking=True)
    year = fields.Integer("Рік", required=True, default=lambda s: _default_period(fields.Date.context_today(s))[0])
    period = fields.Selection(PERIODS, "Період", required=True,
                              default=lambda s: str(_default_period(fields.Date.context_today(s))[1]))
    date_from = fields.Date("Початок", compute="_compute_dates", store=True)
    date_to = fields.Date("Кінець", compute="_compute_dates", store=True)
    standard = fields.Selection(STANDARDS, "Основа складання", default="nsbo", required=True,
                                help="Для балансу (J0900108): позначка H01 (НП(С)БО) чи H02 (МСФЗ).")
    tin = fields.Char("Код ЄДРПОУ", default=lambda s: _digits(s.env.company.company_registry))
    sti_code = fields.Char("Код ДПІ", size=4, default=lambda s: s._ua_company_value("ua_dps_sti", "ua_sti_code"),
                           help="Чотири цифри: перші дві - область (C_REG), дві наступні - район (C_RAJ).")
    kved = fields.Char("Основний КВЕД", default=lambda s: s._ua_company_value("ua_kved"))
    koatuu = fields.Char("Код КОАТУУ", size=10, default=lambda s: s._ua_company_value("ua_koatuu"),
                         help="Схеми балансу і малої форми досі вимагають код КОАТУУ (9-10 цифр) місця "
                              "реєстрації, хоча класифікатор замінив КАТОТТГ. Перевіряйте чинну схему.")
    legal_form = fields.Char("Код КОПФГ", help="Організаційно-правова форма, наприклад 240 для ТОВ. Необов'язково.")
    address = fields.Char("Адреса", default=lambda s: s._ua_company_address())
    phone = fields.Char("Телефон", default=lambda s: s.env.company.phone)
    director = fields.Char("Керівник", default=lambda s: s._ua_company_value("ua_director_name"))
    accountant = fields.Char("Головний бухгалтер", default=lambda s: s._ua_company_value("ua_accountant_name"))
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    line_ids = fields.One2many("ua.finrep.filing.line", "filing_id", "Рядки")
    check_text = fields.Text("Зауваження", readonly=True)
    computed_at = fields.Datetime("Розраховано", readonly=True)
    xml_file = fields.Binary("Файл XML", attachment=True, readonly=True, copy=False)
    xml_name = fields.Char("Ім'я файлу", readonly=True, copy=False)

    @api.depends("form", "period", "year")
    def _compute_name(self):
        forms, periods = dict(FORMS), dict(PERIODS)
        for doc in self:
            doc.name = "%s, %s %s" % (forms.get(doc.form, ""), (periods.get(doc.period) or "").lower(), doc.year or "")

    @api.depends("period", "year")
    def _compute_dates(self):
        for doc in self:
            if doc.year and doc.period:
                month = int(doc.period)
                doc.date_from = date(doc.year, 1, 1)
                doc.date_to = date(doc.year, month, 31 if month in (3, 12) else 30)
            else:
                doc.date_from = doc.date_to = False

    @api.constrains("year")
    def _check_year(self):
        for doc in self:
            if not 2000 <= doc.year <= 2099:
                raise ValidationError(_("Рік звітності - чотири цифри, від 2000."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(doc.state != "draft" for doc in self):
            raise UserError(_("Видалити можна лише чернетку."))

    @api.model
    def _ua_company_value(self, *names):
        """Реквізит компанії з поля іншого модуля, якщо такий модуль стоїть (ПДВ, звітність з ЄСВ)."""
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
    def _ua_values(self, part, date_from, date_to):
        """{код рядка: сума в гривнях} шаблону part за період - тим самим розрахунком, що друк форми."""
        instance = self.env["mis.report.instance"].create({
            "name": "%s для подання до ДПС" % part,
            "report_id": self.env.ref("l10n_ua_finrep.report_%s" % part).id,
            "target_move": "posted",
            "company_id": self.company_id.id,
            "temporary": True,
            "period_ids": [(0, 0, {"name": "Графа", "mode": "fix", "manual_date_from": date_from,
                                   "manual_date_to": date_to, "sequence": 1})],
        })
        values = instance.with_company(self.company_id)._ua_finrep_values()
        instance.unlink()
        return values

    def _ua_columns(self, kind):
        """((початок, кінець) графи 3, (початок, кінець) графи 4)."""
        self.ensure_one()
        start, end = self.date_from, self.date_to
        last_year_start, last_year_end = date(self.year - 1, 1, 1), date(self.year - 1, 12, 31)
        if kind == "balance":
            return (last_year_start, last_year_end), (start, end)
        return (start, end), (last_year_start, date(self.year - 1, end.month, end.day))

    def action_compute(self):
        for doc in self:
            if doc.state != "draft":
                raise UserError(_("Затверджену звітність не перераховують: поверніть її в чернетку."))
            doc.line_ids.unlink()
            digits = FORM_DIGITS[doc.form]
            values = []
            for part, kind in FORM_PARTS[doc.form]:
                (f3, t3), (f4, t4) = doc._ua_columns(kind)
                col3, col4 = doc._ua_values(part, f3, t3), doc._ua_values(part, f4, t4)
                report = self.env.ref("l10n_ua_finrep.report_%s" % part)
                sub_style = self.env.ref("l10n_ua_finrep.style_sub", raise_if_not_found=False)
                for kpi in report.kpi_ids.sorted("sequence"):
                    match = ROW_RE.match(kpi.name or "")
                    if not match:
                        continue
                    code = match.group(1)
                    expression = (kpi.expression or "").strip()
                    base = {
                        "filing_id": doc.id, "part": part, "sequence": kpi.sequence, "code": code,
                        "name": re.sub(r"^\d{4}\s*", "", kpi.description or ""),
                        "sub": bool(sub_style and kpi.style_id == sub_style),
                        "formula": expression if FORMULA_RE.match(expression) else False,
                    }
                    for row in doc._ua_present(code, col3.get(code, 0.0), col4.get(code, 0.0)):
                        values.append(dict(base, **row, g3=float_round(row["uah_g3"] / 1000.0, digits),
                                           g4=float_round(row["uah_g4"] / 1000.0, digits)))
            self.env["ua.finrep.filing.line"].create(values)
            doc.write({"computed_at": fields.Datetime.now(), "xml_file": False, "xml_name": False})
            doc._ua_check()
        return True

    def _ua_present(self, code, v3, v4):
        """Рядки форми з одного рядка шаблону: дужки - додатні, результат Ф2 - на прибуток і збиток."""
        if code in BRACKETS:
            return [{"code": code, "uah_g3": -v3, "uah_g4": -v4}]
        if code in SPLIT and self.form in SPLIT_FORMS:
            return [{"code": code, "uah_g3": max(v3, 0.0), "uah_g4": max(v4, 0.0)},
                    {"code": SPLIT[code], "uah_g3": max(-v3, 0.0), "uah_g4": max(-v4, 0.0),
                     "formula": False, "sequence_shift": 1}]
        return [{"code": code, "uah_g3": v3, "uah_g4": v4}]

    # ------------------------------------------------------------------ перевірки
    def _ua_signed(self, lines, code, column):
        """Сума рядка зі знаком шаблону (назад від вигляду у формі)."""
        value = lines.get(code, {}).get(column, 0.0)
        if code in BRACKETS:
            return -value
        if code in SPLIT and self.form in SPLIT_FORMS:
            return value - lines.get(SPLIT[code], {}).get(column, 0.0)
        return value

    def _ua_problems(self):
        """Розбіжності підсумків після округлення і порожні реквізити."""
        self.ensure_one()
        digits = FORM_DIGITS[self.form]
        tolerance = 0.5 * 10 ** -digits
        problems = []
        by_part = {}
        for line in self.line_ids:
            by_part.setdefault(line.part, {})[line.code] = {"g3": line.g3, "g4": line.g4, "formula": line.formula}
        for part, lines in by_part.items():
            for code, row in lines.items():
                if not row["formula"]:
                    continue
                for column in ("g3", "g4"):
                    total = sum((-1 if sign == "-" else 1) * self._ua_signed(lines, ref, column)
                                for sign, ref in TERM_RE.findall(row["formula"]))
                    value = self._ua_signed(lines, code, column)
                    if abs(total - value) > tolerance:
                        problems.append(_("Графа %(col)s, рядок %(code)s: %(value)s, а сума рядків %(total)s "
                                          "(округлення) - поправте один з рядків.") % {
                            "col": column[1], "code": code, "value": round(value, digits),
                            "total": round(total, digits)})
            if "1300" in lines and "1900" in lines:
                for column in ("g3", "g4"):
                    diff = lines["1300"][column] - lines["1900"][column]
                    if abs(diff) > tolerance:
                        problems.append(_("Графа %(col)s: актив 1300 і пасив 1900 різняться на %(diff)s.") % {
                            "col": column[1], "diff": round(diff, digits)})
        return problems

    def _ua_check(self):
        for doc in self:
            doc.check_text = "\n".join(doc._ua_problems()) or False
        return True

    def action_check(self):
        return self._ua_check()

    # ------------------------------------------------------------------ XML
    def _ua_head_problems(self):
        self.ensure_one()
        problems = []
        if not re.fullmatch(r"\d{8}", _digits(self.tin)):
            problems.append(_("код ЄДРПОУ - 8 цифр"))
        if not re.fullmatch(r"\d{4}", _digits(self.sti_code)):
            problems.append(_("код ДПІ - 4 цифри"))
        if self.form in KOATUU_FORMS and not re.fullmatch(r"\d{9,10}", _digits(self.koatuu)):
            problems.append(_("код КОАТУУ - 9 або 10 цифр"))
        if self.kved and not re.fullmatch(r"\d{2}\.\d{1,2}(\.\d)?", self.kved.strip()):
            problems.append(_("КВЕД у вигляді 00.00"))
        if not (self.director or "").strip():
            problems.append(_("керівник"))
        if not self.line_ids:
            problems.append(_("рядки (кнопка «Розрахувати»)"))
        return problems

    def _ua_header_values(self):
        today = fields.Date.context_today(self)
        values = {
            "HFILL": today.strftime("%d%m%Y"),
            "HNAME": self.company_id.name,
            "HTIN": _digits(self.tin),
            "HKOATUU": _digits(self.koatuu),
            "HKOPFG": (self.legal_form or "").strip(),
            "HKVED": (self.kved or "").strip(),
            "HLOC": (self.address or "").strip(),
            "HTEL": re.sub(r"[^0-9 ()\-+.,;]", "", self.phone or ""),
            "HPERIOD": PERIOD_TEXT[int(self.period)] if self.form == "J0900207" else MONTHS_GENITIVE[int(self.period)],
            "HZY": str(self.year),
            "HPERIOD1": PERIOD_TEXT[int(self.period)],
            "HZY1": str(self.year),
            "HBOS": (self.director or "").strip(),
            "HBUH": (self.accountant or "").strip(),
        }
        if self.form == "J0900108":
            values["H01" if self.standard == "nsbo" else "H02"] = "1"
        if len(values["HTEL"]) < 4:
            values["HTEL"] = ""
        return values

    @staticmethod
    def _ua_number(value, type_name):
        if type_name == "DGdecimal0":
            return "%d" % float_round(value, 0)
        if type_name == "DGdecimal1":
            return "%.1f" % float_round(value, 1)
        return "%.2f" % float_round(value, 2)

    def _ua_xml(self):
        """(ім'я файлу, байти) XML форми, перевірений схемою."""
        self.ensure_one()
        problems = self._ua_head_problems()
        if problems:
            raise UserError(_("Для XML заповніть: %s.") % "; ".join(problems))
        form = self.form
        schema, elements = _schema(form)
        sti = _digits(self.sti_code)
        tin = _digits(self.tin)
        month = int(self.period)
        root = etree.Element("DECLAR", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
        root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", "%s.xsd" % form)
        head = etree.SubElement(root, "DECLARHEAD")
        for tag, value in [
            ("TIN", tin), ("C_DOC", form[:3]), ("C_DOC_SUB", form[3:6]), ("C_DOC_VER", str(int(form[6:8]))),
            ("C_DOC_TYPE", "0"), ("C_DOC_CNT", "1"), ("C_REG", str(int(sti[:2]))), ("C_RAJ", str(int(sti[2:]))),
            ("PERIOD_MONTH", str(month)), ("PERIOD_TYPE", str(PERIOD_TYPE[month])), ("PERIOD_YEAR", str(self.year)),
            ("C_STI_ORIG", sti), ("C_DOC_STAN", "1"),
        ]:
            etree.SubElement(head, tag).text = value
        etree.SubElement(head, "LINKED_DOCS").set(XSI_NIL, "true")
        etree.SubElement(head, "D_FILL").text = fields.Date.context_today(self).strftime("%d%m%Y")
        etree.SubElement(head, "SOFTWARE").text = "odoo-live"

        header = self._ua_header_values()
        rows = {}
        for line in self.line_ids:
            # У малій формі коди Ф1-м і Ф2-м не перетинаються, тож одна таблиця на файл.
            rows["R%sG3" % line.code] = line.g3
            rows["R%sG4" % line.code] = line.g4
        known = {name for name, _type in elements}
        body = etree.SubElement(root, "DECLARBODY")
        for name, type_name in elements:
            if name in header:
                if header[name]:
                    etree.SubElement(body, name).text = header[name]
            elif name in rows and float_round(rows[name], 2):
                etree.SubElement(body, name).text = self._ua_number(rows[name], type_name)
        missing = sorted({line.code for line in self.line_ids if "R%sG3" % line.code not in known
                          and (line.g3 or line.g4)})
        if missing:
            raise UserError(_("Рядків %s немає у схемі %s: перевірте шаблон форми.") % (", ".join(missing), form))
        data = etree.tostring(root, xml_declaration=True, encoding="windows-1251", pretty_print=True)
        document = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
        if not schema.validate(document):
            errors = "\n".join("- %s" % error.message for error in list(schema.error_log)[:5])
            raise UserError(_("XML %(form)s не відповідає схемі ДПС:\n%(errors)s") % {"form": form, "errors": errors})
        name = "%s%s%s%s%s%s%s%s%s%s%s%s.XML" % (
            sti, tin.rjust(10, "0"), form[:3], form[3:6], form[6:8], "1", "00", "1".rjust(7, "0"),
            PERIOD_TYPE[month], str(month).rjust(2, "0"), self.year, sti)
        return name, data

    def action_xml(self):
        self.ensure_one()
        self._ua_check()
        name, data = self._ua_xml()
        self.write({"xml_file": base64.b64encode(data), "xml_name": name})
        return True

    def action_done(self):
        for doc in self:
            if not doc.line_ids:
                raise UserError(_("Спершу розрахуйте звітність."))
            doc._ua_check()
            if doc.check_text:
                raise UserError(_("Підсумки не сходяться:\n%s") % doc.check_text)
            doc.state = "done"
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True


class UaFinrepFilingLine(models.Model):
    _name = "ua.finrep.filing.line"
    _description = "Рядок фінансової звітності до ДПС"
    _order = "part, sequence, code, id"

    filing_id = fields.Many2one("ua.finrep.filing", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="filing_id.company_id", store=True)
    part = fields.Selection(PARTS, "Форма", required=True)
    sequence = fields.Integer()
    code = fields.Char("Код рядка", size=4, required=True)
    name = fields.Char("Стаття")
    sub = fields.Boolean("У тому числі", help="Рядок-розшифровка: у підсумок розділу не входить.")
    formula = fields.Char("Формула", help="Підсумок з інших рядків, як у шаблоні форми; перевіряється після "
                                          "округлення.")
    uah_g3 = fields.Float("Графа 3, грн", digits=(16, 2), readonly=True)
    uah_g4 = fields.Float("Графа 4, грн", digits=(16, 2), readonly=True)
    g3 = fields.Float("Графа 3, тис. грн", digits=(16, 1),
                      help="Баланс - на початок року; фінрезультати - за звітний період.")
    g4 = fields.Float("Графа 4, тис. грн", digits=(16, 1),
                      help="Баланс - на кінець періоду; фінрезультати - за той самий період минулого року.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            shift = vals.pop("sequence_shift", 0)
            if shift:
                vals["sequence"] = (vals.get("sequence") or 0) + shift
        return super().create(vals_list)
