"""Завантаження прайсу постачальника: розбір, зіставлення, ціни постачальників.

1. «Розібрати» - таблиця читається за профілем; кожен рядок зіставляється з товаром:
   - за кодом постачальника (уже записаним у ціні постачальника);
   - за відбитком комплектуючого: назва розбирається класифікатором, і «Болт DIN 933
     М10х40 кл.8.8 цинк» знаходить товар «Болт М10×40 DIN 933 8.8 цинк»;
   - за точною назвою.
   Ціна приводиться до ціни без ПДВ за одиницю постачальника і за одиницю обліку товару
   (для порівняння з іншими постачальниками і з попереднім прайсом).
2. Людина переглядає рядки, знімає позначку «Застосувати» з сумнівних.
3. «Застосувати» - ціни постачальника створюються чи оновлюються; нові позиції за
   бажанням стають товарами з видом і характеристиками.

Болти за кілограм: якщо в товару є маса 1000 шт, для нього створюється одиниця
«кг (артикул)» і ціна за кілограм лягає саме в неї - Odoo сам перерахує її в штуки
в замовленні постачальнику.
"""
import base64
import json

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from odoo.addons.l10n_ua_component.models import component_core as core
from odoo.addons.l10n_ua_component.models import table_io

# Ціна за штуку дрібного кріплення - частки копійки: 250 грн за 500 шайб = 0,4167.
PRICE_DIGITS = (16, 4)

STATES = [("draft", "Чернетка"), ("parsed", "Розібрано"), ("applied", "Застосовано")]
STATUSES = [("matched", "Знайдено"), ("new", "Новий товар"), ("unknown", "Не розібрано"),
            ("error", "Помилка в рядку")]
MATCHES = [("code", "За кодом постачальника"), ("key", "За характеристиками"),
           ("name", "За назвою")]
UNIT_MODES = [("same", "Одиниця товару"), ("uom", "Інша одиниця товару"),
              ("kg_pieces", "Кілограм штучного товару"), ("pack", "Упаковка")]


class UaSupplierPriceImport(models.Model):
    _name = "ua.supplier.price.import"
    _description = "Прайс постачальника"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Назва", required=True, default="Прайс")
    profile_id = fields.Many2one("ua.supplier.price.profile", "Профіль прайсу", required=True,
                                 ondelete="cascade", index=True)
    partner_id = fields.Many2one(related="profile_id.partner_id", store=True, string="Постачальник")
    company_id = fields.Many2one(related="profile_id.company_id", store=True, index=True,
                                 string="Компанія")
    date = fields.Date("Ціни діють з", required=True, default=fields.Date.context_today,
                       tracking=True)
    file = fields.Binary("Файл прайсу", attachment=False)
    file_name = fields.Char("Назва файла")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    create_missing = fields.Boolean(
        "Створювати нові товари",
        help="Рядок, який розібрано класифікатором, але товару ще немає, стане товаром з "
             "видом і характеристиками.")
    line_ids = fields.One2many("ua.supplier.price.import.line", "import_id", "Рядки")
    count_total = fields.Integer("Рядків", compute="_compute_counts")
    count_matched = fields.Integer("Знайдено", compute="_compute_counts")
    count_new = fields.Integer("Нових", compute="_compute_counts")
    count_unknown = fields.Integer("Не розібрано", compute="_compute_counts")
    count_changed = fields.Integer("Зміна ціни понад 5 %", compute="_compute_counts")
    summary = fields.Text("Підсумок", readonly=True)

    def _compute_counts(self):
        for rec in self:
            statuses = rec.line_ids.mapped("status")
            rec.count_total = len(statuses)
            rec.count_matched = statuses.count("matched")
            rec.count_new = statuses.count("new")
            rec.count_unknown = statuses.count("unknown") + statuses.count("error")
            rec.count_changed = len(rec.line_ids.filtered(lambda x: abs(x.change_pct) > 5.0))

    # ---------------------------------------------------------------- читання
    def _ua_rows(self):
        """[(код, назва, одиниця, ціна, фасовка, залишок)] з файла за профілем."""
        self.ensure_one()
        if not self.file:
            raise UserError("Додайте файл прайсу: CSV чи Excel.")
        rows, header = table_io.read_table(base64.b64decode(self.file), self.file_name)
        if header is None:
            raise UserError("Не знайшов рядок заголовка з колонкою «Найменування».")
        head = rows[header]
        profile = self.profile_id
        cols, used = {}, set()
        for f in ("name", "code", "price", "unit", "pack", "stock"):
            cols[f] = table_io.guess_column(head, profile._ua_words("col_" + f), used)
            if cols[f] is not None:
                used.add(cols[f])
        if cols["name"] is None or cols["price"] is None:
            raise UserError("Не знайшов колонки назви чи ціни. Заголовок: %s. Допишіть слова "
                            "в профілі прайсу." % " | ".join(c for c in head if c))

        def cell(row, key):
            i = cols[key]
            return row[i].strip() if i is not None and i < len(row) and row[i] else ""

        out = []
        for row in rows[header + 1:]:
            name = cell(row, "name")
            if not name:
                continue
            out.append((cell(row, "code"), name, cell(row, "unit"), cell(row, "price"),
                        cell(row, "pack"), cell(row, "stock")))
        return out

    def _ua_unit(self, text):
        word = (text or "").strip().lower().rstrip(".")
        Uom = self.env["uom.uom"]
        if not word:
            return Uom
        return (Uom.search([("ua_kspovo_short", "=ilike", word)], limit=1)
                or Uom.search([("name", "=ilike", word)], limit=1))

    def _ua_match(self, code, name, cls, key):
        """(товар, як знайдено) або (порожньо, False)."""
        Tmpl = self.env["product.template"]
        company = [self.company_id.id, False]
        if code:
            info = self.env["product.supplierinfo"].search(
                [("partner_id", "=", self.partner_id.id), ("product_code", "=", code),
                 ("company_id", "in", company)], limit=1)
            if info:
                return info.product_tmpl_id, "code"
        if cls and key:
            tmpl = Tmpl.search([("ua_component_key", "=", key), ("company_id", "in", company)],
                               order="id", limit=1)
            if tmpl:
                return tmpl, "key"
        tmpl = Tmpl.search([("name", "=ilike", name), ("company_id", "in", company)], limit=1)
        if tmpl:
            return tmpl, "name"
        return Tmpl, False

    def _ua_price_lines(self, tmpl, cls, raw_unit, net, pack):
        """Одиниця постачальника і ціни для рядка."""
        profile = self.profile_id
        price_unit, min_qty = profile._ua_per_unit(net, pack)
        base_uom = tmpl.uom_id if tmpl else (cls._ua_inherited("uom_id") if cls else False)
        if price_unit != net or min_qty:
            # ціна за упаковку, сотню чи тисячу - перераховано в одиницю обліку
            return {"unit_mode": "pack", "uom_id": base_uom.id if base_uom else False,
                    "price_unit": price_unit, "min_qty": min_qty, "price_base": price_unit}
        vals = {"unit_mode": "same", "uom_id": base_uom.id if base_uom else False,
                "price_unit": price_unit, "min_qty": 0.0, "price_base": price_unit}
        word = (raw_unit or "").strip().lower().rstrip(".")
        if tmpl and word:
            # одиниця саме цього товару: «м (MPR-ST3-40x20x2)», «лист 1500×6000 (...)»
            own = tmpl.uom_ids.filtered(lambda u: u.name.lower().split(" (")[0] == word
                                        or u.name.lower().startswith(word + " "))[:1]
            if own:
                per = own._compute_quantity(1.0, base_uom, round=False, raise_if_failure=False)
                vals.update(unit_mode="uom", uom_id=own.id,
                            price_base=price_unit / per if per else 0.0)
                return vals
        uom = self._ua_unit(raw_unit)
        if not uom or not base_uom or uom == base_uom:
            return vals
        if tmpl and uom in tmpl.uom_ids:
            per = uom._compute_quantity(1.0, base_uom, round=False, raise_if_failure=False)
            vals.update(unit_mode="uom", uom_id=uom.id, price_base=price_unit / per if per else 0.0)
            return vals
        kg = self.env.ref("uom.product_uom_kgm")
        mass_1000 = (tmpl._ua_values().get("mass_1000") if tmpl else None)
        if uom == kg and mass_1000:
            vals.update(unit_mode="kg_pieces", uom_id=False,
                        price_base=price_unit * mass_1000 / 1000.0)
            return vals
        vals.update(note="одиниця «%s» не збігається з одиницею товару «%s»"
                    % (raw_unit, base_uom.name))
        return vals

    # ---------------------------------------------------------------- розбір
    def action_parse(self):
        for rec in self:
            rec._ua_parse()
        return True

    def _ua_parse(self):
        self.ensure_one()
        spec = self.env["ua.component.class"]._ua_spec()
        classes = {c.code: c for c in self.env["ua.component.class"].search([])}
        Info = self.env["product.supplierinfo"]
        self.line_ids.unlink()
        vals_list = []
        for seq, (code, name, unit, price, pack, stock) in enumerate(self._ua_rows(), start=1):
            vals = {"import_id": self.id, "sequence": seq, "raw_code": code or False,
                    "raw_name": name[:250], "raw_unit": unit or False,
                    "raw_price": table_io.to_float(price) or 0.0,
                    "raw_pack": table_io.to_float(pack) or 0.0,
                    "raw_stock": table_io.to_float(stock) or 0.0}
            if not vals["raw_price"]:
                vals.update(status="error", note="немає ціни", apply=False)
                vals_list.append(vals)
                continue
            result = core.parse(spec, name)
            cls = classes.get(result["class"])
            key = False
            if cls:
                keys = [line.attribute_id.code for line in cls.line_ids if line.key]
                key = core.component_key(cls.code, result["values"], keys)
                vals.update(class_id=cls.id, key=key, values_json=json.dumps(
                    result["values"], ensure_ascii=False, sort_keys=True))
            tmpl, how = self._ua_match(code, name, cls, key)
            if tmpl:
                vals.update(status="matched", match=how, product_tmpl_id=tmpl.id, apply=True)
            elif cls and result["confidence"] >= 1.0:
                vals.update(status="new", apply=self.create_missing)
            else:
                vals.update(status="unknown", apply=False)
            net = self.profile_id._ua_net(vals["raw_price"])
            pack = vals["raw_pack"] or self.profile_id.default_pack
            vals.update(self._ua_price_lines(tmpl, cls, unit, net, pack))
            if tmpl:
                old = Info.search([("partner_id", "=", self.partner_id.id),
                                   ("product_tmpl_id", "=", tmpl.id),
                                   ("company_id", "in", [self.company_id.id, False])],
                                  order="date_start desc, id desc", limit=1)
                if old and old.ua_price_base:
                    vals["price_old"] = old.ua_price_base
                    vals["change_pct"] = (vals["price_base"] - old.ua_price_base) \
                        / old.ua_price_base * 100.0
            vals_list.append(vals)
        self.env["ua.supplier.price.import.line"].create(vals_list)
        self.state = "parsed"
        self.summary = self._ua_summary()
        return True

    def _ua_summary(self):
        lines = self.line_ids
        by = {m: len(lines.filtered(lambda x, m=m: x.match == m)) for m, _l in MATCHES}
        return ("Рядків %d: знайдено %d (за кодом %d, за характеристиками %d, за назвою %d), "
                "нових %d, не розібрано %d, ціна змінилась понад 5 %% у %d."
                % (self.count_total, self.count_matched, by["code"], by["key"], by["name"],
                   self.count_new, self.count_unknown, self.count_changed))

    # ---------------------------------------------------------------- застосування
    def action_apply(self):
        for rec in self:
            if rec.state != "parsed":
                raise UserError("Спершу розберіть прайс.")
            rec._ua_apply()
            rec.state = "applied"
        return True

    def _ua_create_product(self, line):
        cls = line.class_id
        spec = self.env["ua.component.class"]._ua_spec()
        values = line._ua_values()
        name = core.render(spec, cls.name_template, values) or line.raw_name
        uom = cls._ua_inherited("uom_id") or self.env.ref("uom.product_uom_unit")
        vals = {"name": name, "type": "consu", "uom_id": uom.id, "company_id": self.company_id.id,
                "purchase_ok": True}
        if "is_storable" in self.env["product.template"]._fields:
            vals["is_storable"] = True
        tmpl = self.env["product.template"].create(vals)
        tmpl._ua_set_values(cls.code, values)
        tmpl._ua_class_defaults()
        return tmpl

    def _ua_apply(self):
        Info = self.env["product.supplierinfo"]
        prec = self.env["decimal.precision"].precision_get("Product Price")
        created = updated = made = 0
        for line in self.line_ids.filtered("apply").sorted("sequence"):
            tmpl = line.product_tmpl_id
            if not tmpl and line.status == "new":
                tmpl = self._ua_create_product(line)
                line.product_tmpl_id = tmpl
                made += 1
            if not tmpl:
                continue
            uom = line.uom_id
            if line.unit_mode == "kg_pieces":
                tmpl._ua_make_units()
                uom = tmpl.uom_ids.filtered(lambda u: u.name.startswith("кг ("))[:1]
            uom = uom or tmpl.uom_id
            price, min_qty = line.price_unit, line.min_qty
            if line.unit_mode == "pack" and min_qty > 1 and float_compare(
                    price, float_round(price, precision_digits=prec), precision_digits=6):
                # Шайба 0,4167 за штуку не вміщається в ціну Odoo з двома знаками: ціну
                # кладемо за упаковку («уп. 500 шт» - 208,33), щоб не губити копійки.
                uom = tmpl._ua_pack_unit(min_qty)
                price, min_qty = float_round(price * min_qty, precision_digits=prec), 1.0
            vals = {"partner_id": self.partner_id.id, "product_tmpl_id": tmpl.id,
                    "product_code": line.raw_code or False, "product_name": line.raw_name,
                    "price": price, "product_uom_id": uom.id, "min_qty": min_qty,
                    "delay": self.profile_id.delay, "currency_id": self.profile_id.currency_id.id,
                    "date_start": self.date, "company_id": self.company_id.id,
                    "ua_import_id": self.id, "ua_stock": line.raw_stock}
            domain = [("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id),
                      ("company_id", "in", [self.company_id.id, False])]
            if line.raw_code:
                domain.append(("product_code", "in", [line.raw_code, False]))
            info = Info.search(domain, order="date_start desc, id desc", limit=1)
            if info:
                info.write(vals)
                updated += 1
                line.result = "ціну оновлено"
            else:
                Info.create(vals)
                created += 1
                line.result = "ціну додано"
        self.summary = (self._ua_summary() + "\nЦін додано %d, оновлено %d, нових товарів %d."
                        % (created, updated, made))

    def action_lines(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.name,
                "res_model": "ua.supplier.price.import.line", "view_mode": "list",
                "domain": [("import_id", "=", self.id)]}


class UaSupplierPriceImportLine(models.Model):
    _name = "ua.supplier.price.import.line"
    _description = "Рядок прайсу постачальника"
    _order = "import_id, sequence, id"

    import_id = fields.Many2one("ua.supplier.price.import", required=True, ondelete="cascade",
                                index=True)
    sequence = fields.Integer("№")
    raw_code = fields.Char("Код постачальника")
    raw_name = fields.Char("Назва в прайсі", required=True)
    raw_unit = fields.Char("Од. в прайсі")
    raw_price = fields.Float("Ціна в прайсі", digits="Product Price")
    raw_pack = fields.Float("Фасовка")
    raw_stock = fields.Float("Залишок")
    product_tmpl_id = fields.Many2one("product.template", "Товар")
    match = fields.Selection(MATCHES, "Як знайдено")
    class_id = fields.Many2one("ua.component.class", "Вид")
    key = fields.Char("Відбиток")
    values_json = fields.Text("Характеристики (JSON)")
    status = fields.Selection(STATUSES, "Результат")
    apply = fields.Boolean("Застосувати")
    unit_mode = fields.Selection(UNIT_MODES, "Одиниця ціни")
    uom_id = fields.Many2one("uom.uom", "Одиниця постачальника")
    price_unit = fields.Float("Ціна без ПДВ", digits=PRICE_DIGITS,
                              help="За одиницю постачальника.")
    min_qty = fields.Float("Мін. кількість")
    price_base = fields.Float("За одиницю обліку", digits=PRICE_DIGITS)
    price_old = fields.Float("Була", digits=PRICE_DIGITS)
    change_pct = fields.Float("Зміна, %", digits=(6, 1))
    note = fields.Char("Примітка")
    result = fields.Char("Що зроблено", readonly=True)

    def _ua_values(self):
        self.ensure_one()
        try:
            return json.loads(self.values_json or "{}")
        except ValueError:
            return {}
