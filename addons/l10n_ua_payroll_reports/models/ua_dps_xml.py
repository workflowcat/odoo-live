"""Побудова XML за форматом ДПС (наказ Мінфіну 729): DECLAR / DECLARHEAD / DECLARBODY, ім'я файлу, перевірка за XSD.
Тіло кожної форми будує окремий метод; тут лише каркас, спільний для всіх форм."""
import os
from datetime import date

from lxml import etree

from odoo import models
from odoo.exceptions import UserError

SCHEMAS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas")


class UaDpsXml(models.AbstractModel):
    _name = "ua.dps.xml"
    _description = "XML за форматом ДПС"

    @staticmethod
    def file_name(tin, sti, c_doc, c_doc_sub, c_doc_ver, c_doc_stan, c_doc_type, c_doc_cnt, period_type, month, year, sti_orig):
        """Ім'я файлу за форматом ДПС, звірено з прикладом M.E.Doc 26550008012019J0500111100000000110720262655.XML:
        C_STI(4) + TIN(10, з нулями зліва) + C_DOC(3) + SUB(3) + VER(2) + STAN(1) + TYPE(2) + CNT(7) + PTYPE(1) + MM(2) + YYYY(4) + C_STI_ORIG(4) + .XML"""
        return (f"{str(sti).rjust(4, '0')}{str(tin).rjust(10, '0')}{c_doc}{c_doc_sub}{c_doc_ver}{c_doc_stan}"
                f"{str(c_doc_type).rjust(2, '0')}{str(c_doc_cnt).rjust(7, '0')}{period_type}{str(month).rjust(2, '0')}{year}{str(sti_orig).rjust(4, '0')}.XML")

    def build(self, company, c_doc, c_doc_sub, c_doc_ver, period_type, month, year, body_fields, linked=None, c_doc_cnt=1, c_doc_type=0, c_doc_stan=1, fill_date=None):
        """body_fields: список (тег, значення) у порядку схеми; порожні значення пропускаються. Повертає (ім'я файлу, bytes)."""
        tin = (company.company_registry or "").strip()
        if not tin or not company.ua_sti_code:
            raise UserError("Заповніть у компанії ЄДРПОУ і код ДПІ (Налаштування → Компанії → вкладка «Україна»).")
        fname = self.file_name(tin, company.ua_sti_code, c_doc, c_doc_sub, c_doc_ver, c_doc_stan, c_doc_type, c_doc_cnt, period_type, month, year, company.ua_sti_code)
        root = etree.Element("DECLAR", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
        root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", f"{c_doc}{c_doc_sub}{c_doc_ver}.xsd")
        head = etree.SubElement(root, "DECLARHEAD")
        for tag, val in [("TIN", tin), ("C_DOC", c_doc), ("C_DOC_SUB", c_doc_sub), ("C_DOC_VER", c_doc_ver), ("C_DOC_TYPE", c_doc_type),
                         ("C_DOC_CNT", c_doc_cnt), ("C_REG", company.ua_reg or "00"), ("C_RAJ", company.ua_raj or "00"),
                         ("PERIOD_MONTH", month), ("PERIOD_TYPE", period_type), ("PERIOD_YEAR", year),
                         ("C_STI_ORIG", company.ua_sti_code), ("C_DOC_STAN", c_doc_stan)]:
            etree.SubElement(head, tag).text = str(val)
        if linked:
            ld = etree.SubElement(head, "LINKED_DOCS")
            for doc in linked:
                d = etree.SubElement(ld, "DOC", NUM=str(doc.get("num", 1)), TYPE=str(doc.get("type", 1)))
                for tag in ("C_DOC", "C_DOC_SUB", "C_DOC_VER", "C_DOC_TYPE", "C_DOC_CNT", "C_DOC_STAN", "FILENAME"):
                    etree.SubElement(d, tag).text = str(doc[tag])
        etree.SubElement(head, "D_FILL").text = (fill_date or date.today()).strftime("%d%m%Y")
        etree.SubElement(head, "SOFTWARE").text = "Odoo 19 / odoo-live"
        body = etree.SubElement(root, "DECLARBODY")
        NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
        for item in body_fields:
            tag, val = item[0], item[1]
            attrs = item[2] if len(item) > 2 else {}
            empty = val is None or val == "" or val is False
            if empty and not attrs:
                continue                      # скалярне поле без значення - пропускаємо (minOccurs=0)
            el = etree.SubElement(body, tag, **{k: str(v) for k, v in attrs.items()})
            if empty:
                el.set(NIL, "true")           # порожня клітинка рядка таблиці - xsi:nil, як у прикладах ДПС/M.E.Doc
            else:
                el.text = self._fmt(val)
        data = etree.tostring(root, xml_declaration=True, encoding="windows-1251", pretty_print=True)
        return fname, data

    @staticmethod
    def _fmt(val):
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, float):
            return f"{val:.2f}"
        if isinstance(val, date):
            return val.strftime("%d%m%Y")
        return str(val)

    @staticmethod
    def validate(data, schema_code):
        """Перевірка за XSD зі schemas/ (файли збережені в UTF-8). Повертає список помилок; порожній = валідний."""
        path = os.path.join(SCHEMAS_DIR, f"{schema_code}.xsd")
        if not os.path.exists(path):
            return [f"Схеми {schema_code}.xsd немає в модулі; перевірку пропущено"]
        try:
            schema = etree.XMLSchema(etree.parse(path))
            doc = etree.fromstring(data)
            schema.validate(doc)
            return [f"рядок {e.line}: {e.message}" for e in schema.error_log]
        except Exception as e:  # noqa: BLE001 - помилка схеми не має зупиняти формування файлу
            return [f"не вдалося перевірити за схемою: {e}"]
