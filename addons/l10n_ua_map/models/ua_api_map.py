# -*- coding: utf-8 -*-
"""Карта системи: що є на підприємстві, скільки там живого і що чекає на людину.

Навіщо. Odoo показує меню модулів, а людині треба бачити підприємство: замовники,
конструкція, постачання, склад, виробництво, якість, доставка, люди, гроші. Карта
лежить у `data/system_map.json` - ті самі дванадцять ділянок і ті самі стани
(є / частково / бракує), що в `docs/parity/capability-map.md`. Цей метод додає до
неї живе: чи встановлено модуль, чи може користувач це читати, скільки записів,
скільки відкритих, скільки потребує уваги і куди натиснути.

Правила ті самі, що для всієї ua.api: лише читання, без sudo, прості типи.
Чого користувач не має права читати, того він не бачить у числах: count = False,
access = False, а не AccessError на весь екран - карту дивляться всі.

Опис пункту в JSON:
  key, title, status (done/part/gap), note
  modules     модулі, без яких пункту немає (усі мають бути встановлені)
  model       модель, на якій рахуємо; без неї пункт лише описовий
  action      xmlid дії Odoo, яка відкриває перелік; без неї - перелік моделі за доменом
  domain      що взагалі належить пункту (Оборонні контракти - ua_defense = True)
  open        звуження до живого («підтверджених», «в дорозі») і його підпис open_label
  attention   {domain, label, model?, modules?} - що чекає на людину; model, якщо
              рахуємо на іншій моделі (Працівники - документи, що спливають)

У доменах «$today», «$today+30», «$today-7» - дата відносно сьогодні, «$company» - id
компанії карти (для моделей без company_id: документи працівника - через employee_id).
"""
import json
import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import file_open

MAP_FILE = "l10n_ua_map/data/system_map.json"
STATUSES = {"done": "Є", "part": "Частково", "gap": "Бракує"}
TODAY = re.compile(r"^\$today(?:([+-])(\d+))?$")


class UaApi(models.AbstractModel):
    _inherit = "ua.api"

    # ------------------------------------------------------------------ службове
    @api.model
    def _ua_map_spec(self):
        """Карта з файла як є: {version, areas: [{key, title, icon, items: [...]}]}."""
        with file_open(MAP_FILE) as handle:
            return json.load(handle)

    @api.model
    def _ua_map_installed(self):
        """Назви встановлених модулів."""
        Module = self.env["ir.module.module"]
        if hasattr(Module, "_installed"):
            return set(Module._installed())
        return set(getattr(self.env.registry, "_init_modules", ()) or ())

    @api.model
    def _ua_map_domain(self, domain, today, company):
        """Домен з файла: дати замість «$today±N», id замість «$company»."""
        out = []
        for term in domain or []:
            if isinstance(term, list) and len(term) == 3 and isinstance(term[2], str):
                match = TODAY.match(term[2])
                if term[2] == "$company":
                    term = [term[0], term[1], company.id]
                elif match:
                    days = int(match.group(2) or 0) * (-1 if match.group(1) == "-" else 1)
                    term = [term[0], term[1], fields.Date.to_string(today + timedelta(days=days))]
            out.append(list(term) if isinstance(term, (list, tuple)) else term)
        return out

    @api.model
    def _ua_map_count(self, model, domain, company):
        """Скільки записів бачить користувач; False, якщо модель йому закрита."""
        Model = self.env[model]
        if not Model.has_access("read"):
            return False
        if "company_id" in Model._fields:
            domain = [["company_id", "in", [company.id, False]]] + list(domain)
        try:
            return Model.search_count(domain)
        except AccessError:
            # поле з групою, якої в користувача немає (військовий облік - лише кадровикам)
            return False

    @api.model
    def _ua_map_target(self, action, model, domain, name):
        """Ціль у форматі ua.screen.open_target: дія Odoo або перелік моделі."""
        if action and self.env["ir.model.data"]._xmlid_to_res_id(action, raise_if_not_found=False):
            return {"xmlid": action, "domain": domain} if domain else {"xmlid": action}
        return {"model": model, "domain": domain or [], "name": name}

    # ------------------------------------------------------------------ карта
    @api.model
    def system_map(self, company_id=None):
        """Карта системи з живими лічильниками.

        Вхід: company_id (int) або нічого - поточна компанія.

        Вихід:
          company   {id, name}
          today     дата, відносно якої пораховано строки
          statuses  {done: "Є", part: "Частково", gap: "Бракує"}
          summary   {items, done, part, gap, installed, attention}
          areas     [{key, title, icon, summary, items: [ITEM]}] у сталому порядку
          attention [{area, area_title, item, title, label, count, target}] - смуга
                    «Потребує уваги»: лише ненульові, найбільші перші

        ITEM:
          key, title, status, status_label, note
          modules    які модулі потрібні; missing - яких бракує; installed - чи всі є
          model      модель або False
          access     чи може користувач читати модель
          count      скільки записів у пункті (False - не рахується або закрито)
          open       скільки живих, open_label - підпис («в дорозі»); False, якщо звуження немає
          attention  {count, label, target} або False
          target     куди веде пункт; open_target - лише живі; False, якщо нікуди
        """
        company = self._as_company(company_id)
        today = fields.Date.context_today(self)
        installed = self._ua_map_installed()
        spec = self._ua_map_spec()

        total = {"items": 0, "done": 0, "part": 0, "gap": 0, "installed": 0, "attention": 0}
        areas, strip = [], []
        for area in spec["areas"]:
            part = {"items": 0, "done": 0, "part": 0, "gap": 0, "attention": 0}
            items = []
            for item in area["items"]:
                row = self._ua_map_item(item, company, today, installed)
                items.append(row)
                part["items"] += 1
                part[row["status"]] += 1
                total["installed"] += 1 if row["installed"] and row["modules"] else 0
                if row["attention"] and row["attention"]["count"]:
                    part["attention"] += row["attention"]["count"]
                    strip.append({"area": area["key"], "area_title": area["title"],
                                  "item": row["key"], "title": row["title"],
                                  "label": row["attention"]["label"],
                                  "count": row["attention"]["count"],
                                  "target": row["attention"]["target"]})
            for key in ("items", "done", "part", "gap", "attention"):
                total[key] += part[key]
            areas.append({"key": area["key"], "title": area["title"], "icon": area.get("icon") or "",
                          "summary": part, "items": items})

        strip.sort(key=lambda row: -row["count"])
        return self._plain({
            "company": {"id": company.id, "name": company.name},
            "today": today,
            "statuses": dict(STATUSES),
            "summary": total,
            "areas": areas,
            "attention": strip,
        })

    @api.model
    def _ua_map_item(self, item, company, today, installed):
        modules = list(item.get("modules") or [])
        missing = [name for name in modules if name not in installed]
        model = item.get("model") or False
        live = bool(model) and not missing and model in self.env
        row = {
            "key": item["key"], "title": item["title"], "status": item["status"],
            "status_label": STATUSES[item["status"]], "note": item.get("note") or "",
            "modules": modules, "missing": missing, "installed": not missing,
            "model": model, "access": False, "count": False, "open": False,
            "open_label": item.get("open_label") or "", "attention": False,
            "target": False, "open_target": False,
        }
        if not live:
            return row

        base = self._ua_map_domain(item.get("domain"), today, company)
        row["access"] = self.env[model].has_access("read")
        row["count"] = self._ua_map_count(model, base, company)
        row["target"] = self._ua_map_target(item.get("action"), model, base, item["title"])
        if item.get("open"):
            narrow = base + self._ua_map_domain(item["open"], today, company)
            row["open"] = self._ua_map_count(model, narrow, company)
            row["open_target"] = self._ua_map_target(
                item.get("action"), model, narrow,
                "%s: %s" % (item["title"], item.get("open_label") or ""))

        watch = item.get("attention")
        if watch and not any(name not in installed for name in watch.get("modules") or []):
            other = watch.get("model")
            where = other or model
            if where in self.env:
                domain = self._ua_map_domain(watch["domain"], today, company)
                if not other:
                    domain = base + domain
                count = self._ua_map_count(where, domain, company)
                if count is not False:
                    row["attention"] = {
                        "count": count, "label": watch["label"],
                        "target": self._ua_map_target(
                            False if other else item.get("action"), where, domain,
                            "%s: %s" % (item["title"], watch["label"])),
                    }
        return row
