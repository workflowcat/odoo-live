# -*- coding: utf-8 -*-
"""XML податкової накладної для ЄРПН, форма J1201016.

Формат звірявся у пісочниці з описом структури DECLAR (Comarch EDI, опис від
01.10.2024) і описами M.E.Doc. Чинна версія електронної ПН - J1201016, форма в
редакції наказу Мінфіну від 09.08.2024 №400.

Коди ставок графи 8 (вузол RXXXXG008): 20, 14, 7 - оподатковувані;
901 - 0 % експорт; 902 - 0 % на митній території; 903 - звільнені.

Ім'я файла (43 символи плюс «.xml»): код ДПІ (4) + ЄДРПОУ (10) + код форми
(3+3+2) + стан (1) + тип (2) + лічильник (7) + тип періоду (1) + місяць (2) +
рік (4) + ДПІ оригіналу (4).

Умовні ІПН покупця за Порядком №1307: 100000000000 - неплатник або кінцевий
споживач; 600000000000 - зведена ПН за п.198.5 або ст.199 (покупець є самим
продавцем).

Спрощення, які перенесено з пісочниці свідомо:
* код одиниці виміру за КСПОВО завжди 2009 («штука») - у каталозі демо-бази
  штучні позиції;
* у зведених ПН графи УКТ ЗЕД і одиниці виміру не заповнюються;
* вузол ПДВ 14 % (R03G141 / R01G141) - реконструкція за аналогією: форма
  старша за ставку 14 % і в описі цих вузлів немає.
"""
import re
import xml.etree.ElementTree as ET

from odoo import fields, models
from odoo.exceptions import UserError

# КСПОВО-код одиниці виміру «штука».
UA_KSPOVO_SHT = "2009"
# Умовні ІПН за Порядком №1307.
UA_IPN_NONPAYER = "100000000000"
UA_IPN_SELF = "600000000000"


def _digits(value):
    """Лише цифри з рядка - ІПН і ЄДРПОУ без префіксів на кшталт «UA»."""
    return re.sub(r"\D", "", value or "")


def _first_line(*candidates):
    """Перший непорожній рядок з кандидатів, інакше слово «рядок».

    Потрібно, бо рядок рахунку може не мати ні назви, ні товару, а
    "".splitlines()[0] на такому падає.
    """
    for cand in candidates:
        lines = (cand or "").splitlines()
        if lines and lines[0].strip():
            return lines[0]
    return "рядок"


class UaVatDocumentPnXml(models.Model):
    _inherit = "ua.vat.document"

    # --- Перевірка повноти перед експортом --------------------------------

    def _ua_pn_missing(self):
        """Чого бракує для експорту ПН і де це заповнити.

        Порожній список означає, що документ готовий.
        """
        self.ensure_one()
        move = self.move_id
        company = (move.company_id if move else False) or self.company_id
        missing = []
        if not _digits(company.vat):
            missing.append(
                "ІПН продавця: Налаштування - Компанії - «%s» - Податковий номер"
                % (company.name or "?"))
        if self.ua_pn_consolidated:
            # Зведена: покупцем є сам платник, УКТ ЗЕД і одиниці не заповнюються.
            if not (self.ua_pn_reason_type or "").strip():
                missing.append(
                    "Тип причини зведеної ПН (напр. 09): ПДВ - Накладні і РК - "
                    "«%s» - Тип причини" % (self.name or "?"))
            return missing
        if not move:
            missing.append("ПН не пов'язана з рахунком - немає даних")
            return missing
        partner = move.partner_id
        if partner.ua_vat_payer_status == "payer" and not _digits(partner.vat):
            missing.append(
                "ІПН покупця-платника: Контакти - «%s» - Податковий номер"
                % (partner.name or "?"))
        for line in move.invoice_line_ids:
            if line.display_type not in (False, "product"):
                continue
            product = line.product_id
            pname = (product.display_name if product
                     else _first_line(line.name))
            # УКТ ЗЕД обов'язковий для товарних рядків; для послуг у накладній
            # зазначається код ДКПП, і його тут не вимагаємо.
            if product and product.type != "service" and not (
                    product.ua_uktzed or "").strip():
                missing.append(
                    "УКТ ЗЕД: товар «%s» - Товари - Код УКТ ЗЕД" % pname)
            if product and product.ua_vat_treatment == "exempt":
                relief = product.ua_vat_relief_effective_id
                if not relief:
                    missing.append(
                        "Підстава пільги: товар «%s» - довідник ПДВ - Пільги"
                        % pname)
                elif not (relief.dps_benefit_code or "").strip():
                    missing.append(
                        "Код пільги ДПС: підстава «%s» - ПДВ - Пільги - Код "
                        "пільги" % (relief.name or "?"))
        return missing

    # --- Класифікація рядка ------------------------------------------------

    def _ua_line_rate_code(self, line):
        """(код ставки графи 8, ставка у відсотках, підстава пільги)."""
        rate = 0.0
        for tax in line.tax_ids:
            if tax.amount_type == "percent":
                rate = tax.amount
                break
        if rate:
            return "%g" % rate, rate, None
        if line._ua_vat_zero_class() == "exempt":
            product = line.product_id
            relief = (product.ua_vat_relief_effective_id if product else None) or None
            return "903", 0.0, relief
        return "901", 0.0, None

    # --- Складання XML -----------------------------------------------------

    def _ua_head(self, root, c_doc, c_doc_sub, c_doc_ver, month, year, doc_cnt):
        """DECLARHEAD - спільна шапка документів DECLAR."""
        company = (self.move_id.company_id if self.move_id else False) \
            or self.company_id
        head = ET.SubElement(root, "DECLARHEAD")
        tin = _digits(company.company_registry) or _digits(company.vat)[:8]
        c_reg = (company.ua_dps_reg or "26").zfill(2)
        c_raj = (company.ua_dps_raj or "59").zfill(2)
        c_sti = (company.ua_dps_sti or "2659").zfill(4)
        ET.SubElement(head, "TIN").text = tin
        ET.SubElement(head, "C_DOC").text = c_doc
        ET.SubElement(head, "C_DOC_SUB").text = c_doc_sub
        ET.SubElement(head, "C_DOC_VER").text = c_doc_ver
        ET.SubElement(head, "C_DOC_TYPE").text = "0"
        ET.SubElement(head, "C_DOC_CNT").text = str(doc_cnt)
        ET.SubElement(head, "C_REG").text = c_reg
        ET.SubElement(head, "C_RAJ").text = c_raj
        ET.SubElement(head, "PERIOD_MONTH").text = str(month)
        ET.SubElement(head, "PERIOD_TYPE").text = "1"
        ET.SubElement(head, "PERIOD_YEAR").text = str(year)
        ET.SubElement(head, "C_STI_ORIG").text = c_sti
        ET.SubElement(head, "C_DOC_STAN").text = "1"
        ET.SubElement(head, "D_FILL").text = fields.Date.context_today(
            self).strftime("%d%m%Y")
        ET.SubElement(head, "SOFTWARE").text = "Odoo 19 CE, l10n_ua_vat"
        return head, tin, (c_reg, c_raj, c_sti)

    @staticmethod
    def _ua_filename(tin, dps, c_doc, c_doc_sub, c_doc_ver, month, year, doc_cnt):
        """Ім'я файла за конвенцією ДПС: 43 символи плюс розширення."""
        c_reg, c_raj, c_sti = dps
        return "".join([
            c_reg, c_raj,                    # 1-4: код ДПІ
            tin.zfill(10),                   # 5-14: ЄДРПОУ
            c_doc, c_doc_sub, c_doc_ver,     # 15-22: код форми
            "1",                             # 23: стан документа
            "00",                            # 24-25: тип документа
            str(doc_cnt).zfill(7)[-7:],      # 26-32: лічильник
            "1",                             # 33: тип періоду
            "%02d" % int(month),             # 34-35: місяць
            "%04d" % int(year),              # 36-39: рік
            c_sti,                           # 40-43: ДПІ оригіналу
            ".xml",
        ])

    def _ua_build_pn_xml(self):
        """Зібрати XML J1201016 для цієї ПН. Повертає (bytes, ім'я файла)."""
        self.ensure_one()
        move = self.move_id
        company = move.company_id or self.company_id
        partner = move.partner_id
        consolidated = bool(self.ua_pn_consolidated)
        pn_date = self.date or fields.Date.context_today(self)
        hnum = self._ua_pn_number()

        root = ET.Element(
            "DECLAR",
            {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"})
        _head, tin, dps = self._ua_head(
            root, "J12", "010", "16", pn_date.month, pn_date.year, hnum)

        body = ET.SubElement(root, "DECLARBODY")
        if consolidated:
            ET.SubElement(body, "H03").text = "1"       # ознака зведеної
            ET.SubElement(body, "HORIG1").text = "1"    # покупцю не видається
            ET.SubElement(body, "HTYPR").text = self.ua_pn_reason_type or "09"
        ET.SubElement(body, "HFILL").text = pn_date.strftime("%d%m%Y")
        ET.SubElement(body, "HNUM").text = hnum
        ET.SubElement(body, "HNAMESEL").text = company.name or ""
        ET.SubElement(body, "HKSEL").text = _digits(company.vat)
        ET.SubElement(body, "HKS").text = "1"
        if consolidated:
            ET.SubElement(body, "HNAMEBUY").text = company.name or ""
            ET.SubElement(body, "HKBUY").text = UA_IPN_SELF
        elif partner.ua_vat_payer_status == "payer":
            ET.SubElement(body, "HNAMEBUY").text = partner.name or ""
            ET.SubElement(body, "HKBUY").text = _digits(partner.vat)
            ET.SubElement(body, "HKB").text = "1"
        else:
            ET.SubElement(body, "HNAMEBUY").text = partner.name or "Неплатник"
            ET.SubElement(body, "HKBUY").text = UA_IPN_NONPAYER

        vol = {"20": 0.0, "14": 0.0, "7": 0.0,
               "901": 0.0, "902": 0.0, "903": 0.0}
        vat = {"20": 0.0, "14": 0.0, "7": 0.0}
        exempt_bases = []

        def row_el(tag, num, text):
            el = ET.SubElement(body, tag, ROWNUM=str(num))
            el.text = text
            return el

        if consolidated:
            comp = self.env["ua.vat.compensation"].search(
                [("doc_id", "=", self.id)], limit=1)
            lines = comp.line_ids if comp else []
            if not lines:
                raise UserError(
                    "Зведена ПН «%s» не має рядків компенсації - спершу "
                    "розрахуйте і проведіть компенсуючі ПЗ періоду."
                    % (self.name or "?"))
            for num, cline in enumerate(lines, start=1):
                row_el("RXXXXG3S", num, cline.name or "компенсація п.198.5")
                row_el("RXXXXG008", num, "20")
                row_el("RXXXXG010", num, "%.2f" % cline.comp_base)
                vol["20"] += cline.comp_base
                vat["20"] += cline.comp_vat
        else:
            inv_lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type in (False, "product"))
            for num, line in enumerate(inv_lines, start=1):
                code, rate, relief = self._ua_line_rate_code(line)
                # Невідома ставка мовчки випадала б з підсумків, і в ЄРПН пішов
                # би занижений ПДВ. Краще явна відмова з підказкою.
                if code not in vol:
                    raise UserError(
                        "Рядок «%s»: ставка ПДВ %s %% не підтримується "
                        "експортом ПН (очікуються 20, 14, 7 %% або 0 %% "
                        "експорт чи звільнення). Виправте податок рядка."
                        % (_first_line(line.name,
                                       line.product_id.display_name),
                           "%g" % rate))
                name = _first_line(line.name, line.product_id.display_name)
                row_el("RXXXXG3S", num, name)
                product = line.product_id
                if product and product.type != "service":
                    row_el("RXXXXG4", num,
                           (product.ua_uktzed or "").replace(" ", ""))
                    row_el("RXXXXG4S", num, line.product_uom_id.name or "шт.")
                    row_el("RXXXXG105_2S", num, UA_KSPOVO_SHT)
                row_el("RXXXXG5", num, "%g" % line.quantity)
                row_el("RXXXXG6", num, "%.6g" % line.price_unit)
                row_el("RXXXXG008", num, code)
                if code == "903" and relief:
                    row_el("RXXXXG009", num, relief.dps_benefit_code or "")
                    if relief.basis:
                        exempt_bases.append(relief.basis)
                row_el("RXXXXG010", num, "%.2f" % line.price_subtotal)
                vol[code] += line.price_subtotal
                if code in vat:
                    vat[code] += line.price_total - line.price_subtotal

        total_vat = round(sum(vat.values()), 2)
        total_all = round(sum(vol.values()) + total_vat, 2)
        ET.SubElement(body, "R04G11").text = "%.2f" % total_all
        ET.SubElement(body, "R03G11").text = "%.2f" % total_vat
        ET.SubElement(body, "R03G7").text = "%.2f" % round(vat["20"], 2)
        ET.SubElement(body, "R03G109").text = "%.2f" % round(vat["7"], 2)
        if vat["14"]:
            ET.SubElement(body, "R03G141").text = "%.2f" % round(vat["14"], 2)
        ET.SubElement(body, "R01G7").text = "%.2f" % round(vol["20"], 2)
        ET.SubElement(body, "R01G109").text = "%.2f" % round(vol["7"], 2)
        if vol["14"]:
            ET.SubElement(body, "R01G141").text = "%.2f" % round(vol["14"], 2)
        ET.SubElement(body, "R01G9").text = "%.2f" % round(vol["901"], 2)
        ET.SubElement(body, "R01G8").text = "%.2f" % round(vol["902"], 2)
        ET.SubElement(body, "R01G10").text = "%.2f" % round(vol["903"], 2)
        if vol["903"]:
            ET.SubElement(body, "R03G10S").text = "Без ПДВ"
            if exempt_bases:
                ET.SubElement(body, "R003G10S").text = "; ".join(
                    dict.fromkeys(exempt_bases))
        ET.SubElement(body, "HBOS").text = self.env.user.name or ""

        fname = self._ua_filename(tin, dps, "J12", "010", "16",
                                  pn_date.month, pn_date.year, hnum)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True), fname

    # --- Дії ---------------------------------------------------------------

    def _ua_attach_xml(self, xml_bytes, fname):
        """Ідемпотентне вкладення: повторний експорт оновлює той самий файл."""
        self.ensure_one()
        Attachment = self.env["ir.attachment"]
        attachment = Attachment.search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("name", "=", fname)], limit=1)
        vals = {"raw": xml_bytes, "mimetype": "application/xml"}
        if attachment:
            attachment.write(vals)
        else:
            attachment = Attachment.create(dict(
                vals, name=fname, type="binary",
                res_model=self._name, res_id=self.id))
        return attachment

    def _ua_export_pn_attach(self):
        """Перевірка повноти, XML J1201016, вкладення на документі."""
        self.ensure_one()
        self._ua_check_kind("tax_invoice", "податкових накладних")
        missing = self._ua_pn_missing()
        if missing:
            raise UserError(
                "ПН не готова до ЄРПН - заповніть:\n- " + "\n- ".join(missing))
        xml_bytes, fname = self._ua_build_pn_xml()
        return self._ua_attach_xml(xml_bytes, fname)

    def action_export_xml(self):
        """«XML для ЄРПН»: перевірка, складання, вкладення, завантаження."""
        self.ensure_one()
        attachment = self._ua_export_pn_attach()
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%d?download=true" % attachment.id,
            "target": "self",
        }
