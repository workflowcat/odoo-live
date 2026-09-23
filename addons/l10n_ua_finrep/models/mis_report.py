"""Тонкий шар над mis_builder: позначка форми і чернетка XML.

Уся арифметика форм живе у даних (data/mis_report_*.xml) як вирази KPI.
Тут лише два додатки:

1) `ua_finrep_form` на шаблоні mis.report - яка це офіційна форма. Поле
   потрібне, щоб кнопка експорту і меню знали, з чим мають справу, і щоб
   не чіпати чужі звіти mis_builder у тій самій базі.
2) Читання порахованих значень і складання XML. Другого розрахунку немає:
   `_ua_finrep_values` бере матрицю самого mis_builder (`_compute_matrix`)
   і повертає {код рядка: сума}.
"""

import re
import xml.etree.ElementTree as ET

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.mis_builder.models.accounting_none import AccountingNone

# Ім'я KPI = літера форми + код рядка: r1300 (Ф1/Ф2), m1300 (Ф1-м), n2350 (Ф2-м).
# Контрольні рядки звуться ctl_* і в XML не потрапляють.
ROW_NAME_RE = re.compile(r"^[a-z](\d{4})$")

FORM_SELECTION = [
    ("f1", "Ф1. Баланс (НП(С)БО 1)"),
    ("f2", "Ф2. Звіт про фінансові результати (НП(С)БО 1)"),
    ("f1m", "Ф1-м. Баланс (НП(С)БО 25)"),
    ("f2m", "Ф2-м. Звіт про фінансові результати (НП(С)БО 25)"),
]

# Заголовок чернетки. Реальний формат ДПС ми не звіряли з чинною схемою -
# див. docs/base/spec-finrep.md, розділ «XML».
XML_DRAFT_C_DOC = "S01"
XML_DRAFT_C_DOC_SUB = "100"
XML_DRAFT_CHARCODE = "S0110013"


class MisReport(models.Model):
    _inherit = "mis.report"

    ua_finrep_form = fields.Selection(
        FORM_SELECTION,
        string="Українська форма",
        help="Позначка офіційної форми. Заповнена лише на наших шаблонах; "
             "звичайні звіти mis_builder її не мають.",
    )


class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"

    ua_finrep_form = fields.Selection(
        related="report_id.ua_finrep_form",
        string="Українська форма",
        store=True,
        readonly=True,
    )

    # --- відкриття звіту -----------------------------------------------------

    def preview(self):
        """Перегляд звіту з id у контексті.

        Віджет mis_builder 19.0 бере id звіту з `props.value`, якого в полях
        Odoo 19 вже немає, тож лишається запасний шлях - `active_id` у
        контексті. Кнопка на записі кладе його сама, а пункт меню і дія, що
        повертає preview() з коду, - ні, і віджет падає з «Invalid ids list».
        Тому кладемо `active_id` тут, для будь-якого виклику preview()."""
        action = super().preview()
        context = dict(action.get("context") or {})
        context.update(active_model=self._name, active_id=self.id, active_ids=self.ids)
        action["context"] = context
        action.setdefault("name", self.name)
        return action

    @api.model
    def _ua_finrep_open(self, form):
        """Пункт меню форми: звіт поточної компанії, відкритий на перегляд.

        Звіт шукаємо серед звітів однієї компанії (консолідації групи - багато
        компаній - не беремо). Якщо в компанії його ще немає, копіюємо готовий
        звіт модуля (`instance_<форма>`): той самий шаблон, колонка «поточний
        рік», лише інша компанія. Період відносний, тож окремого звіту на рік
        не треба."""
        company = self.env.company
        instance = self.search([
            ("ua_finrep_form", "=", form),
            ("multi_company", "=", False),
            ("company_id", "=", company.id),
        ], order="sequence, id", limit=1)
        if not instance:
            template = self.env.ref("l10n_ua_finrep.instance_%s" % form,
                                    raise_if_not_found=False)
            if template:
                copied = template.sudo().copy({"company_id": company.id})
                # copy() mis_builder дописує до назви «(copy)» - повертаємо назву шаблону.
                copied.name = template.sudo().name
            else:
                report = self.env["mis.report"].sudo().search(
                    [("ua_finrep_form", "=", form)], limit=1)
                if not report:
                    raise UserError("Немає шаблону форми %s." % form)
                copied = self.sudo().create({
                    "name": report.name,
                    "report_id": report.id,
                    "company_id": company.id,
                    "target_move": "posted",
                    "widget_show_pivot_date": True,
                    "widget_show_settings_button": True,
                    "period_ids": [(0, 0, {
                        "name": "Поточний рік", "mode": "relative", "type": "y",
                        "offset": 0, "duration": 1, "sequence": 1,
                    })],
                })
            instance = self.browse(copied.id)
        return instance.preview()

    # --- читання порахованого ------------------------------------------------

    def _ua_finrep_values(self):
        """{код рядка: сума} з матриці mis_builder для першої колонки.

        Другого розрахунку немає: беремо ту саму матрицю, що її малює віджет.
        Порожня клітинка (AccountingNone) стає 0.0 - у звітній формі порожній
        рядок подається нулем.
        """
        self.ensure_one()
        matrix = self._compute_matrix()
        subcols = list(matrix.iter_subcols())
        if not subcols:
            return {}
        first = subcols[0]
        values = {}
        for row in matrix.iter_rows():
            if row.account_id:
                continue  # рядки «деталі за рахунками» - не рядки форми
            match = ROW_NAME_RE.match(row.kpi.name or "")
            if not match:
                continue
            cell = first.get_cell_for_row(row)
            value = cell and cell.val
            if value is AccountingNone or value is None or isinstance(value, str):
                value = 0.0
            values[match.group(1)] = float(value)
        return values

    def _ua_finrep_control(self):
        """{ім'я контрольного KPI: сума} - для тестів і для повідомлень."""
        self.ensure_one()
        matrix = self._compute_matrix()
        subcols = list(matrix.iter_subcols())
        if not subcols:
            return {}
        first = subcols[0]
        out = {}
        for row in matrix.iter_rows():
            if row.account_id or not (row.kpi.name or "").startswith("ctl_"):
                continue
            cell = first.get_cell_for_row(row)
            value = cell and cell.val
            out[row.kpi.name] = 0.0 if value is AccountingNone or value is None else float(value)
        return out

    # --- чернетка XML --------------------------------------------------------

    def _ua_finrep_xml(self):
        """Байти XML: DECLARHEAD з періодом і платником, DECLARBODY з R<рядок>G3."""
        self.ensure_one()
        company = self.company_id or self.env.company
        values = self._ua_finrep_values()
        period = self.period_ids[:1]
        date_to = period.date_to or self.date_to or fields.Date.context_today(self)
        date_to = fields.Date.to_date(date_to)

        root = ET.Element("DECLAR")
        root.append(ET.Comment(
            "Чернетка формату. Структуру не звірено з чинною схемою ДПС; "
            "подавати через Вчасно або M.E.Doc не можна."
        ))
        head = ET.SubElement(root, "DECLARHEAD")
        ET.SubElement(head, "C_DOC").text = XML_DRAFT_C_DOC
        ET.SubElement(head, "C_DOC_SUB").text = XML_DRAFT_C_DOC_SUB
        ET.SubElement(head, "CHARCODE").text = XML_DRAFT_CHARCODE
        ET.SubElement(head, "PERIOD_MONTH").text = str(date_to.month)
        ET.SubElement(head, "PERIOD_YEAR").text = str(date_to.year)
        ET.SubElement(head, "HNAME").text = company.name or ""
        ET.SubElement(head, "TIN").text = company.vat or ""

        body = ET.SubElement(root, "DECLARBODY")
        for code in sorted(values):
            ET.SubElement(body, "R%sG3" % code).text = "%.2f" % values[code]
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def action_ua_finrep_xml_draft(self):
        """Кнопка «XML (чернетка формату)»: вкладення і посилання на завантаження."""
        self.ensure_one()
        attachment = self.env["ir.attachment"].create({
            "name": "%s (чернетка).xml" % (self.ua_finrep_form or "finrep"),
            "type": "binary",
            "raw": self._ua_finrep_xml(),
            "mimetype": "application/xml",
            "res_model": self._name,
            "res_id": self.id,
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%d?download=true" % attachment.id,
            "target": "self",
        }
