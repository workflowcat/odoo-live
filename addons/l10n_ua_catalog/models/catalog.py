"""Галузеві пакети: знайти, прочитати, завантажити в компанію.

Пакет - файл catalog/<id>.json у будь-якому встановленому модулі. Формат (schema 1):

    pack, name, summary, industry, requires[], sources[], notes[]
    groups[]       xmlid груп, які вмикають потрібні функції (серійні номери, маршрути)
    uoms[]         key, name, short, kspovo, relative_factor, relative_uom
    categories[]   key, name, parent
    workcenters[]  key, name, code, costs_hour, fields{}
    products[]     key, name, code, category, type, storable, uom, tracking, cost, price,
                   barcode, uktzed, dk021, sale_ok, purchase_ok, description, fields{}
    boms[]         key, product, qty, code, type, lines[], operations[], byproducts[]
    records[]      key, model, values{}, match[]

Посилання всередині пакета - "@key"; на запис Odoo - "ref:module.xmlid"; одиниця -
позначення КСПОВО ("кг", "год"), xmlid або ключ з uoms[]. Поля з fields{} ставляться,
лише якщо модель їх має: пакет оборонки підхоплює статті калькуляції, коли стоїть
l10n_ua_defense, і не ламається без нього.

Що вже завантажено, пам'ятає ir.model.data (модуль ua_catalog): повторний запуск
нічого не дублює. Наявні записи з тим самим артикулом чи назвою підхоплюються, а не
створюються вдруге. Режим update оновлює значення раніше завантаженого, але
не перебудовує склад специфікацій: на них уже можуть стояти замовлення.
"""
import glob
import json
import os
import re

from odoo import Command, api, models
from odoo.exceptions import UserError
from odoo.modules.module import get_module_path

XMLID_MODULE = "ua_catalog"
PACK_ID = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
SECTIONS = ("groups", "uoms", "categories", "workcenters", "products", "boms", "records")


def discover(module_names):
    """{id пакета: (модуль, шлях)} для пакетів у теках catalog/ цих модулів."""
    found = {}
    for module in sorted(module_names):
        path = get_module_path(module, display_warning=False)
        if not path:
            continue
        for file in sorted(glob.glob(os.path.join(path, "catalog", "*.json"))):
            pack_id = os.path.splitext(os.path.basename(file))[0]
            if PACK_ID.match(pack_id):
                found[pack_id] = (module, file)
    return found


def read_pack(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema") != 1:
        raise UserError("Пакет %s: невідома версія формату %r" % (path, data.get("schema")))
    return data


class UaCatalog(models.AbstractModel):
    _name = "ua.catalog"
    _description = "Галузеві каталоги"

    # ------------------------------------------------------------- пошук пакетів
    @api.model
    def _ua_installed(self):
        return set(self.env["ir.module.module"].sudo().search(
            [("state", "=", "installed")]).mapped("name"))

    @api.model
    def _ua_packs(self):
        """{id: опис} усіх пакетів у встановлених модулях."""
        packs = {}
        installed = self._ua_installed()
        for pack_id, (module, path) in discover(installed).items():
            try:
                data = read_pack(path)
            except (ValueError, OSError, UserError):
                continue
            requires = data.get("requires") or []
            packs[pack_id] = {
                "id": pack_id,
                "module": module,
                "path": path,
                "name": data.get("name") or pack_id,
                "summary": data.get("summary") or "",
                "industry": data.get("industry") or "",
                "requires": requires,
                "missing": [m for m in requires if m not in installed],
                "sources": data.get("sources") or [],
                "notes": data.get("notes") or [],
                "counts": {s: len(data.get(s) or []) for s in SECTIONS},
            }
        return packs

    # ------------------------------------------------------------- завантаження
    @api.model
    def _ua_load_pack(self, pack_id, company=None, mode="missing"):
        """Завантажує пакет у компанію. Повертає підсумок {розділ: {дія: кількість}}."""
        packs = self._ua_packs()
        if pack_id not in packs:
            raise UserError("Пакет «%s» не знайдено у встановлених модулях." % pack_id)
        info = packs[pack_id]
        if info["missing"]:
            raise UserError("Для пакета «%s» спершу встановіть модулі: %s."
                            % (info["name"], ", ".join(info["missing"])))
        company = company or self.env.company
        loader = _Loader(self.env, read_pack(info["path"]), company, mode)
        return loader.run()


class _Loader:
    """Один прохід завантаження пакета в одну компанію."""

    def __init__(self, env, data, company, mode):
        self.env = env(context=dict(env.context, active_test=False,
                                    tracking_disable=True, mail_create_nolog=True))
        self.data = data
        self.pack = data["pack"]
        self.company = company
        self.mode = mode
        self.keys = {}
        self.stats = {}
        self.skipped_fields = set()

    # ---- облік
    def _count(self, section, action):
        bucket = self.stats.setdefault(section, {})
        bucket[action] = bucket.get(action, 0) + 1

    def _xmlid_name(self, key, company_bound):
        if company_bound:
            return "%s__c%d__%s" % (self.pack, self.company.id, key)
        return "%s__%s" % (self.pack, key)

    def _linked(self, model, key, company_bound):
        imd = self.env["ir.model.data"].sudo().search([
            ("module", "=", XMLID_MODULE),
            ("name", "=", self._xmlid_name(key, company_bound)),
            ("model", "=", model)], limit=1)
        Model = self.env[model].sudo().with_company(self.company)
        return Model.browse(imd.res_id).exists() if imd else Model

    def _register(self, record, key, company_bound):
        name = self._xmlid_name(key, company_bound)
        IMD = self.env["ir.model.data"].sudo()
        IMD.search([("module", "=", XMLID_MODULE), ("name", "=", name)]).unlink()
        IMD.create({"module": XMLID_MODULE, "name": name, "model": record._name,
                    "res_id": record.id, "noupdate": True})

    def _ensure(self, section, model, key, vals, match=None, company_bound=True,
                update_vals=None):
        """Знайти раніше завантажене, підхопити наявне або створити."""
        # with_company: значення за замовчуванням (календар, податки) беруться
        # з цільової компанії, а не з поточної.
        Model = self.env[model].sudo().with_company(self.company)
        record = self._linked(model, key, company_bound)
        if record:
            if self.mode == "update":
                record.write(update_vals if update_vals is not None else vals)
                self._count(section, "updated")
            else:
                self._count(section, "kept")
        else:
            record = Model.search(match, limit=1) if match else Model
            if record:
                self._count(section, "matched")
            else:
                record = Model.create(vals)
                self._count(section, "created")
            self._register(record, key, company_bound)
        self.keys[key] = record
        return record

    # ---- значення
    def _ref(self, value):
        """"@key" -> запис пакета, "ref:m.x" -> запис Odoo, решта - як є."""
        if isinstance(value, str) and value.startswith("@"):
            key = value[1:]
            if key not in self.keys:
                raise UserError("Пакет %s: посилання на невідомий ключ «%s»." % (self.pack, key))
            return self.keys[key]
        if isinstance(value, str) and value.startswith("ref:"):
            return self.env.ref(value[4:])
        return value

    def _value(self, field, value):
        """Значення для write: записи - в id, списки записів - у Command.set."""
        if isinstance(value, list) and field.type in ("many2many", "one2many"):
            ids = []
            for item in value:
                rec = self._ref(item)
                ids.append(rec.id if isinstance(rec, models.BaseModel) else rec)
            return [Command.set(ids)]
        rec = self._ref(value)
        if isinstance(rec, models.BaseModel):
            if field.type == "many2one" and field.comodel_name == "product.product" \
                    and rec._name == "product.template":
                return rec.product_variant_id.id
            return rec.id
        return rec

    def _soft(self, model, vals, extra):
        """Додає до vals поля з extra, які модель має; решту відкладає в звіт."""
        fields_ = self.env[model]._fields
        for name, value in (extra or {}).items():
            if name in fields_:
                vals[name] = self._value(fields_[name], value)
            else:
                self.skipped_fields.add("%s.%s" % (model, name))
        return vals

    def _uom(self, alias):
        if not alias:
            return self.env.ref("uom.product_uom_unit")
        if alias.startswith("@"):
            return self._ref(alias)
        if "." in alias:
            uom = self.env.ref(alias, raise_if_not_found=False)
            if uom:
                return uom
        Uom = self.env["uom.uom"].sudo()
        uom = Uom.search([("ua_kspovo_short", "=", alias)], limit=1) \
            or Uom.search([("name", "=ilike", alias)], limit=1)
        if not uom:
            raise UserError("Пакет %s: невідома одиниця «%s»." % (self.pack, alias))
        return uom

    # ---- розділи
    def run(self):
        for section in SECTIONS:
            items = self.data.get(section) or []
            if items:
                getattr(self, "_load_" + section)(items)
        if self.skipped_fields:
            self.stats["skipped_fields"] = sorted(self.skipped_fields)
        return self.stats

    def _load_groups(self, xmlids):
        user_group = self.env.ref("base.group_user").sudo()
        for xmlid in xmlids:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                self._count("groups", "absent")
            elif group in user_group.implied_ids:
                self._count("groups", "kept")
            else:
                user_group.write({"implied_ids": [Command.link(group.id)]})
                self._count("groups", "enabled")

    def _load_uoms(self, items):
        for item in items:
            vals = {"name": item["name"],
                    "relative_factor": item.get("relative_factor", 1.0)}
            if item.get("relative_uom"):
                vals["relative_uom_id"] = self._uom(item["relative_uom"]).id
            if item.get("kspovo"):
                vals["ua_kspovo_code"] = item["kspovo"]
            if item.get("short"):
                vals["ua_kspovo_short"] = item["short"]
            match = [("name", "=ilike", item["name"])]
            if item.get("short"):
                match = ["|", ("ua_kspovo_short", "=", item["short"])] + match
            self._ensure("uoms", "uom.uom", item["key"], vals, match, company_bound=False)

    def _load_categories(self, items):
        for item in items:
            parent = self._ref(item["parent"]) if item.get("parent") else \
                self.env["product.category"]
            vals = {"name": item["name"], "parent_id": parent.id or False}
            match = [("name", "=", item["name"]), ("parent_id", "=", parent.id or False)]
            self._ensure("categories", "product.category", item["key"], vals, match,
                         company_bound=False)

    def _load_workcenters(self, items):
        for item in items:
            vals = {"name": item["name"], "company_id": self.company.id}
            if item.get("code"):
                vals["code"] = item["code"]
            if "costs_hour" in item:
                vals["costs_hour"] = item["costs_hour"]
            self._soft("mrp.workcenter", vals, item.get("fields"))
            match = [("name", "=", item["name"]), ("company_id", "=", self.company.id)]
            self._ensure("workcenters", "mrp.workcenter", item["key"], vals, match)

    def _load_products(self, items):
        Template = self.env["product.template"]
        fields_ = Template._fields
        for item in items:
            ptype = item.get("type", "consu")
            vals = {
                "name": item["name"],
                "type": ptype,
                "company_id": self.company.id,
                "uom_id": self._uom(item.get("uom")).id,
                "sale_ok": item.get("sale_ok", True),
                "purchase_ok": item.get("purchase_ok", True),
            }
            if "price" in item:
                vals["list_price"] = item["price"]
            if item.get("code"):
                vals["default_code"] = item["code"]
            if item.get("category"):
                vals["categ_id"] = self._ref(item["category"]).id
            if item.get("description"):
                vals["description_sale"] = item["description"]
            if "is_storable" in fields_ and ptype == "consu":
                vals["is_storable"] = item.get("storable", True)
            if item.get("tracking") and "tracking" in fields_:
                vals["tracking"] = item["tracking"]
            if item.get("uktzed") and "ua_uktzed" in fields_:
                vals["ua_uktzed"] = item["uktzed"]
            if item.get("dk021"):
                if "ua_dk021_id" in fields_:
                    dk = self.env["ua.dk021"].search([("code", "=", item["dk021"])], limit=1)
                    if dk:
                        vals["ua_dk021_id"] = dk.id
                else:
                    self.skipped_fields.add("product.template.ua_dk021_id")
            self._soft("product.template", vals, item.get("fields"))
            barcode = item.get("barcode")
            if barcode and not self.env["product.product"].sudo().search_count(
                    [("barcode", "=", barcode)]):
                vals["barcode"] = barcode
            if item.get("code"):
                match = [("default_code", "=", item["code"]),
                         ("company_id", "in", [self.company.id, False])]
            else:
                match = [("name", "=", item["name"]),
                         ("company_id", "in", [self.company.id, False])]
            update_vals = {k: v for k, v in vals.items() if k != "barcode"}
            tmpl = self._ensure("products", "product.template", item["key"], vals, match,
                                update_vals=update_vals)
            if "cost" in item and (self.mode == "update" or not tmpl.with_company(
                    self.company).standard_price):
                tmpl.with_company(self.company).sudo().standard_price = item["cost"]

    def _bom_line(self, line, field_qty="product_qty"):
        tmpl = self._ref(line["product"])
        return {
            "product_id": tmpl.product_variant_id.id,
            field_qty: line.get("qty", 1.0),
            "product_uom_id": self._uom(line["uom"]).id if line.get("uom") else tmpl.uom_id.id,
        }

    def _load_boms(self, items):
        for item in items:
            tmpl = self._ref(item["product"])
            code = item.get("code") or ""
            match = [("product_tmpl_id", "=", tmpl.id), ("company_id", "=", self.company.id),
                     ("code", "=", code or False)]
            header = {
                "product_tmpl_id": tmpl.id,
                "product_qty": item.get("qty", 1.0),
                "product_uom_id": tmpl.uom_id.id,
                "type": item.get("type", "normal"),
                "company_id": self.company.id,
            }
            if code:
                header["code"] = code
            vals = dict(header)
            vals["bom_line_ids"] = [Command.create(self._bom_line(line))
                                    for line in item.get("lines") or []]
            ops = []
            for seq, op in enumerate(item.get("operations") or [], start=1):
                op_vals = {
                    "name": op["name"],
                    "workcenter_id": self._ref(op["workcenter"]).id,
                    "time_mode": "manual",
                    "time_cycle_manual": op.get("minutes", 0.0),
                    "sequence": seq * 10,
                }
                extra = {k: op[k] for k in ("ua_steps", "ua_checks") if k in op}
                self._soft("mrp.routing.workcenter", op_vals, extra)
                ops.append(Command.create(op_vals))
            vals["operation_ids"] = ops
            vals["byproduct_ids"] = [Command.create(self._bom_line(bp))
                                     for bp in item.get("byproducts") or []]
            self._ensure("boms", "mrp.bom", item["key"], vals, match, update_vals=header)

    def _load_records(self, items):
        for item in items:
            model = item["model"]
            if model not in self.env:
                # модуль з цією моделлю не встановлено: запис пропускаємо, як і невідоме поле
                self.skipped_fields.add(model)
                self._count("records", "skipped")
                continue
            Model = self.env[model]
            vals = self._soft(model, {}, item.get("values"))
            company_bound = "company_id" in Model._fields and item.get("company_bound", True)
            if company_bound and "company_id" not in vals:
                vals["company_id"] = self.company.id
            match = []
            for fname, op, value in item.get("match") or []:
                field = Model._fields[fname]
                match.append((fname, op, self._value(field, value)))
            if match and company_bound:
                match.append(("company_id", "in", [self.company.id, False]))
            self._ensure("records", model, item["key"], vals, match or None,
                         company_bound=company_bound)
