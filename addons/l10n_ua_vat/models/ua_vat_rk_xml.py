# -*- coding: utf-8 -*-
"""XML розрахунку коригування для ЄРПН, форма J1201216.

Пара до ПН J1201016: та сама шапка DECLARHEAD, а DECLARBODY додає HNUM1 і
HFILL1 - номер і дату первинної податкової накладної, яку коригуємо.

Хто реєструє (п.192.1 ПКУ): зменшуючий РК реєструє покупець (продавець
надсилає йому РК, воєнний строк - 18 календарних днів з дня отримання),
збільшуючий - продавець, строки як у ПН. РК можна скласти лише протягом
1095 днів з дати складання ПН.

Механіка рядків з 01.12.2018: рядок «сторно» повторює показники первинного
рядка ПН зі знаком мінус, а за ним, якщо щось лишається, іде новий рядок із
новими значеннями. Обидва мають один номер групи коригування (графа 2.2) і
один код причини (графа 2.1).

Теги рядків розділу Б - RXXXXG1 (номер рядка ПН, що коригується), RXXXXG2
(номер групи), RXXXXG2S (код причини) - реконструйовані за схемою тегів ПН:
повного офіційного опису J1201216 у відкритому доступі немає. Решта тегів
(номенклатура, УКТ ЗЕД, кількість, ціна, код ставки, обсяг) - ті самі, що в
J1201016.
"""
import xml.etree.ElementTree as ET

from odoo import fields, models
from odoo.exceptions import UserError

from .ua_vat_pn_xml import UA_IPN_NONPAYER, UA_KSPOVO_SHT, _digits, _first_line


class UaVatDocumentRkXml(models.Model):
    _inherit = "ua.vat.document"

    # --- Перевірка повноти -------------------------------------------------

    def _ua_rk_missing(self):
        """Чого бракує для експорту РК і де це заповнити."""
        self.ensure_one()
        move = self.move_id
        company = (move.company_id if move else False) or self.company_id
        missing = []
        if not move:
            missing.append(
                "РК не пов'язаний з поверненням - немає даних для експорту")
            return missing
        if not _digits(company.vat):
            missing.append(
                "ІПН продавця: Налаштування - Компанії - «%s» - Податковий номер"
                % (company.name or "?"))
        pn = self.ua_adj_pn_document_id
        if not pn or not pn.move_id:
            missing.append(
                "Первинна ПН: ПДВ - Накладні і РК - «%s» - поле «Первинна ПН» "
                "(РК складається до вже складеної ПН)" % (self.name or "?"))
        if not self.ua_adj_reason_code:
            missing.append(
                "Причина коригування: ПДВ - Накладні і РК - «%s» - «Причина "
                "коригування» (довідник ДПС, графа 2.1)" % (self.name or "?"))
        partner = move.partner_id
        if partner.ua_vat_payer_status == "payer" and not _digits(partner.vat):
            missing.append(
                "ІПН покупця-платника: Контакти - «%s» - Податковий номер"
                % (partner.name or "?"))
        for line in move.invoice_line_ids:
            if line.display_type not in (False, "product"):
                continue
            product = line.product_id
            if product and product.type != "service" and not (
                    product.ua_uktzed or "").strip():
                missing.append(
                    "УКТ ЗЕД: товар «%s» - Товари - Код УКТ ЗЕД"
                    % (product.display_name or "?"))
        return missing

    # --- Рядки розділу Б ---------------------------------------------------

    def _ua_rk_rows(self):
        """Рядки РК за механікою груп коригування.

        Для кожного рядка повернення - «сторно» первинного рядка ПН зі знаком
        мінус і, якщо після коригування щось лишається, новий рядок із новими
        значеннями. Нові значення за причиною: 101 (зміна ціни) - кількість та
        сама, ціна нова; решта (102, 103) - ціна та сама, кількість нова.
        Якщо первинного рядка за товаром не знайдено, сторнуємо сам рядок
        повернення: дельта від цього не міняється.
        """
        self.ensure_one()
        move = self.move_id
        origin = (self.ua_adj_pn_document_id.move_id or move.reversed_entry_id)
        origin_lines = origin.invoice_line_ids.filtered(
            lambda l: l.display_type in (False, "product")) if origin else []
        by_product = {}
        for num, oline in enumerate(origin_lines, start=1):
            by_product.setdefault(oline.product_id.id, (num, oline))
        rows = []
        reason = self.ua_adj_reason_code or "103"
        ref_lines = move.invoice_line_ids.filtered(
            lambda l: l.display_type in (False, "product"))
        for group, rline in enumerate(ref_lines, start=1):
            pn_num, oline = by_product.get(rline.product_id.id, (group, None))
            base = oline if oline is not None else rline
            qty_old = base.quantity
            price_old = base.price_unit
            sub_old = base.price_subtotal
            common = {
                "pn_row": pn_num,
                "group": group,
                "reason": reason,
                "name": _first_line(base.name, base.product_id.display_name),
                "product": base.product_id,
                "uom": base.product_uom_id.name or "шт.",
                "line": base,
            }
            rows.append(dict(common, qty=-qty_old, price=price_old,
                             subtotal=-sub_old))
            if oline is None:
                continue
            if reason == "101":
                qty_new = qty_old
                sub_new = sub_old - rline.price_subtotal
                price_new = (sub_new / qty_new) if qty_new else 0.0
            else:
                qty_new = qty_old - rline.quantity
                price_new = price_old
                sub_new = sub_old - rline.price_subtotal
            if qty_new > 0.0005 and sub_new > 0.005:
                rows.append(dict(common, qty=qty_new, price=price_new,
                                 subtotal=sub_new))
        return rows

    def _ua_build_rk_xml(self):
        """Зібрати XML J1201216 для цього РК. Повертає (bytes, ім'я файла)."""
        self.ensure_one()
        move = self.move_id
        origin = (self.ua_adj_pn_document_id.move_id or move.reversed_entry_id)
        company = move.company_id or self.company_id
        partner = move.partner_id
        rk_date = move.invoice_date or move.date or fields.Date.context_today(self)
        hnum = self._ua_pn_number()

        root = ET.Element(
            "DECLAR",
            {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"})
        _head, tin, dps = self._ua_head(
            root, "J12", "012", "16", rk_date.month, rk_date.year, hnum)

        body = ET.SubElement(root, "DECLARBODY")
        ET.SubElement(body, "HFILL").text = rk_date.strftime("%d%m%Y")
        ET.SubElement(body, "HNUM").text = hnum
        pn_doc = self.ua_adj_pn_document_id
        ET.SubElement(body, "HNUM1").text = (
            pn_doc._ua_pn_number() if pn_doc else self._ua_pn_number())
        if origin and origin.invoice_date:
            ET.SubElement(body, "HFILL1").text = \
                origin.invoice_date.strftime("%d%m%Y")
        ET.SubElement(body, "HNAMESEL").text = company.name or ""
        ET.SubElement(body, "HKSEL").text = _digits(company.vat)
        ET.SubElement(body, "HKS").text = "1"
        if partner.ua_vat_payer_status == "payer":
            ET.SubElement(body, "HNAMEBUY").text = partner.name or ""
            ET.SubElement(body, "HKBUY").text = _digits(partner.vat)
            ET.SubElement(body, "HKB").text = "1"
        else:
            ET.SubElement(body, "HNAMEBUY").text = partner.name or "Неплатник"
            ET.SubElement(body, "HKBUY").text = UA_IPN_NONPAYER

        vol = {"20": 0.0, "14": 0.0, "7": 0.0,
               "901": 0.0, "902": 0.0, "903": 0.0}
        vat = {"20": 0.0, "14": 0.0, "7": 0.0}

        def row_el(tag, num, text):
            el = ET.SubElement(body, tag, ROWNUM=str(num))
            el.text = text
            return el

        for num, row in enumerate(self._ua_rk_rows(), start=1):
            code, rate, _relief = self._ua_line_rate_code(row["line"])
            if code not in vol:
                raise UserError(
                    "Рядок «%s»: ставка ПДВ %s %% не підтримується експортом РК."
                    % (row["name"], "%g" % rate))
            row_el("RXXXXG1", num, str(row["pn_row"]))
            row_el("RXXXXG2", num, str(row["group"]))
            row_el("RXXXXG2S", num, row["reason"])
            row_el("RXXXXG3S", num, row["name"])
            product = row["product"]
            if product and product.type != "service":
                row_el("RXXXXG4", num,
                       (product.ua_uktzed or "").replace(" ", ""))
                row_el("RXXXXG4S", num, row["uom"])
                row_el("RXXXXG105_2S", num, UA_KSPOVO_SHT)
            row_el("RXXXXG5", num, "%g" % row["qty"])
            row_el("RXXXXG6", num, "%.6g" % row["price"])
            row_el("RXXXXG008", num, code)
            row_el("RXXXXG010", num, "%.2f" % row["subtotal"])
            vol[code] += row["subtotal"]
            if code in vat:
                vat[code] += row["subtotal"] * rate / 100.0

        total_vat = round(sum(vat.values()), 2)
        total_all = round(sum(vol.values()) + total_vat, 2)
        ET.SubElement(body, "R04G11").text = "%.2f" % total_all
        ET.SubElement(body, "R03G11").text = "%.2f" % total_vat
        ET.SubElement(body, "R03G7").text = "%.2f" % round(vat["20"], 2)
        ET.SubElement(body, "R03G109").text = "%.2f" % round(vat["7"], 2)
        ET.SubElement(body, "R01G7").text = "%.2f" % round(vol["20"], 2)
        ET.SubElement(body, "R01G109").text = "%.2f" % round(vol["7"], 2)
        ET.SubElement(body, "R01G9").text = "%.2f" % round(vol["901"], 2)
        ET.SubElement(body, "R01G8").text = "%.2f" % round(vol["902"], 2)
        ET.SubElement(body, "R01G10").text = "%.2f" % round(vol["903"], 2)
        ET.SubElement(body, "HBOS").text = self.env.user.name or ""

        fname = self._ua_filename(tin, dps, "J12", "012", "16",
                                  rk_date.month, rk_date.year, hnum)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True), fname

    # --- Дії ---------------------------------------------------------------

    def _ua_export_rk_attach(self):
        self.ensure_one()
        self._ua_check_kind("adjustment", "розрахунків коригування")
        missing = self._ua_rk_missing()
        if missing:
            raise UserError(
                "РК не готовий до ЄРПН - заповніть:\n- " + "\n- ".join(missing))
        xml_bytes, fname = self._ua_build_rk_xml()
        return self._ua_attach_xml(xml_bytes, fname)

    def action_export_xml(self):
        """Диспетчер: РК будуємо за J1201216, решту віддаємо конвеєру ПН."""
        self.ensure_one()
        if self.doc_kind != "adjustment":
            return super().action_export_xml()
        attachment = self._ua_export_rk_attach()
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%d?download=true" % attachment.id,
            "target": "self",
        }
