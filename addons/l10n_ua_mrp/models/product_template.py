# -*- coding: utf-8 -*-
"""Складальне креслення виробу і складальна карта для екрана збирача.

Креслення - звичайний SVG у вкладенні (`attachment=True`, у базі лежить лише
посилання). Домовленість про вміст файла одна: елемент позиції має id
`bom-<номер>`, де номер - порядковий номер рядка специфікації (`sequence`, далі
`id`), починаючи з одиниці. Окремого поля «номер позиції» на рядку немає
свідомо: номер - це порядок, і два джерела правди про нього розійшлися б після
першого ж перетягування рядка.

`ua_assembly()` збирає те, що показує екран збирання: креслення плюс операції
маршруту, під кожною - позиції специфікації, прив'язані до неї нативним
`operation_id`. Рядки без операції йдуть окремою останньою групою «Без
операції»: специфікація без маршруту не зникає з екрана, вона просто вся в одній
групі.

Кількість у позиції - на ОДНУ одиницю виробу, в одиниці виміру самого
компонента: специфікація на партію 10 із 50 гвинтами дасть 5 гвинтів на виріб.
Збирач тримає в руках один виріб, а не партію.

Полиця позиції (`bin_location`) береться за двома джерелами в такому порядку:
правило розкладання (`_get_putaway_strategy` - куди товар кладуть за
налаштуванням), а якщо правила немає - локація найбільшого залишку в складі
компанії. Немає ні того, ні того - `None`: на складі товару просто нема.
"""
import base64
import re

from lxml import etree

from odoo import fields, models

# Креслення показує чужий екран, і він може вставити його як розмітку. Тому з SVG
# прибираємо все, що виконується: скрипти, вбудований HTML, обробники подій і
# посилання не на свої елементи. Чисте креслення повертається тим самим текстом.
_SVG_DROP = {"script", "foreignobject", "iframe", "embed", "object", "handler", "listener"}
_SVG_HREF = {"href", "{http://www.w3.org/1999/xlink}href"}
_SAFE_HREF = re.compile(r"^(#|data:image/(png|jpeg|gif|webp);)", re.I)


def ua_clean_svg(text):
    """SVG без активного вмісту. Нерозбірний текст - None: показувати нічого не треба."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(text.encode("utf-8"), parser)
    except (etree.XMLSyntaxError, ValueError):
        return None
    changed = bool(root.getroottree().docinfo.doctype)   # DOCTYPE з сутностями не потрібен
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue
        local = etree.QName(element).localname.lower()
        target = (element.get("attributeName") or "").lower()
        if local in _SVG_DROP or (local in ("set", "animate") and (target.startswith("on") or "href" in target)):
            if element is root:
                return None
            element.getparent().remove(element)
            changed = True
            continue
        for name in list(element.attrib):
            local_attr = etree.QName(name).localname.lower()
            value = re.sub(r"[\s\x00-\x1f]", "", element.attrib[name])
            if local_attr.startswith("on") or (name in _SVG_HREF and not _SAFE_HREF.match(value)):
                del element.attrib[name]
                changed = True
    if not changed:
        return text
    return etree.tostring(root, encoding="unicode")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_drawing_svg = fields.Binary(
        string="Складальне креслення",
        attachment=True,
        help="SVG складального креслення. Елемент позиції має id «bom-N», де N - "
             "порядковий номер рядка специфікації.",
    )
    ua_drawing_name = fields.Char(
        string="Файл креслення",
        help="Назва файла креслення - її показує кнопка завантаження.",
    )

    # ------------------------------------------------------------------
    # Службове
    # ------------------------------------------------------------------
    def _ua_bom(self):
        """Специфікація виробу: спершу нативний пошук, далі перша за порядком."""
        self.ensure_one()
        variant = self.product_variant_ids[:1]
        if variant:
            found = self.env["mrp.bom"]._bom_find(variant).get(variant)
            if found:
                return found
        return self.env["mrp.bom"].search(
            [("product_tmpl_id", "=", self.id)], order="sequence, id", limit=1)

    def _ua_bin_location(self, product, company):
        """Полиця компонента: правило розкладання, далі найбільший залишок."""
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)], order="sequence, id", limit=1)
        stock_location = warehouse.lot_stock_id
        if not stock_location:
            return None
        putaway = stock_location._get_putaway_strategy(product)
        if putaway and putaway != stock_location:
            return putaway.display_name
        quant = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "child_of", stock_location.id),
            ("quantity", ">", 0),
        ], order="quantity desc", limit=1)
        if quant:
            return quant.location_id.display_name
        return None

    @staticmethod
    def _ua_text_items(text):
        """Текст по пункту в рядок - у список. Порожні рядки не рахуються."""
        return [line.strip() for line in (text or "").splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Складальна карта
    # ------------------------------------------------------------------
    def ua_assembly(self):
        """Креслення і операції з позиціями - усе, що треба екрану збирання.

        Повертає {"drawing_svg": str|None, "drawing_name": str|None,
        "operations": [{"name", "workcenter", "time_minutes", "parts":
        [{"pos", "product", "qty", "bin_location"}], "steps": [...],
        "checks": [...]}]}. Лише читання, нічого не пише і не проводить.
        """
        self.ensure_one()
        company = self.env.company
        drawing = None
        if self.ua_drawing_svg:
            raw = self.ua_drawing_svg
            if isinstance(raw, str):
                raw = raw.encode()
            drawing = ua_clean_svg(base64.b64decode(raw).decode("utf-8", "replace"))

        bom = self._ua_bom()
        if not bom:
            return {"drawing_svg": drawing,
                    "drawing_name": self.ua_drawing_name or None,
                    "operations": []}

        batch = bom.product_qty or 1.0
        groups = []
        for operation in bom.operation_ids.sorted(lambda op: (op.sequence, op.id)):
            groups.append({
                "operation": operation,
                "name": operation.name,
                "workcenter": operation.workcenter_id.display_name or "",
                "time_minutes": round(operation.time_cycle, 2),
                "steps": self._ua_text_items(operation.ua_steps),
                "checks": self._ua_text_items(operation.ua_checks),
                "parts": [],
            })
        loose = {
            "operation": self.env["mrp.routing.workcenter"],
            "name": "Без операції",
            "workcenter": "",
            "time_minutes": 0.0,
            "steps": [],
            "checks": [],
            "parts": [],
        }
        by_operation = {group["operation"]: group for group in groups}

        for position, line in enumerate(
                bom.bom_line_ids.sorted(lambda l: (l.sequence, l.id)), start=1):
            quantity = line.product_uom_id._compute_quantity(
                line.product_qty, line.product_id.uom_id, round=False) / batch
            group = by_operation.get(line.operation_id, loose)
            group["parts"].append({
                "pos": position,
                "product": line.product_id.display_name,
                "qty": round(quantity, 4),
                "bin_location": self._ua_bin_location(line.product_id, company),
            })
        if loose["parts"]:
            groups.append(loose)

        return {
            "drawing_svg": drawing,
            "drawing_name": self.ua_drawing_name or None,
            "operations": [
                {key: group[key] for key in
                 ("name", "workcenter", "time_minutes", "parts", "steps", "checks")}
                for group in groups
            ],
        }
