# -*- coding: utf-8 -*-
"""Довідник кодів професій і звірка з класифікатором ДК 003:2010.

Довідник тримає лише те, що компанія справді використовує, а не всі 9179 професій:
класифікатор живе в окремій службі (profkod), бо інакше його довелося б возити
в базі кожного клієнта і перезавантажувати після кожної зміни.

Дві назви на одну позицію - не примха. У класифікаторі немає голого «Юрисконсульт»,
там «Юрисконсульт (радник юридичний)»; немає «Менеджерки з персоналу», там
«Менеджер (управитель) з персоналу». Закон хоче офіційну назву в штатному розписі
і наказі, людина зветься так, як зветься. Тому код несе офіційну назву, а посада
лишає за собою власну.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, fields, models

SERVICE_URL = os.environ.get("UA_KP_URL", "https://profkod.botpartners.workers.dev")
SERVICE_TIMEOUT = 6
UNAVAILABLE = "Служба кодів професій недоступна"


class UaKpCode(models.Model):
    _name = "ua.kp.code"
    _description = "Код професії (ДК 003:2010)"
    _order = "code"
    _rec_name = "display_name"

    code = fields.Char("Код КП", required=True, index=True)
    group = fields.Char("Група", help="Назва класифікаційного угруповання, до якого належить код")
    names_count = fields.Integer("Професій у коді", default=0)
    source = fields.Char("Редакція класифікатора")
    checked = fields.Boolean("Звірено зі службою", default=False)
    active = fields.Boolean(default=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _code_uniq = models.Constraint("unique(code)", "Такий код уже є в довіднику.")

    # Офіційної назви професії тут навмисно немає. Під кодом 1210.1 стоїть дев'яносто
    # різних назв, під 2149.2 - сто три. Вибрати з них одну «головну» означало б
    # підставити випадкову назву замість тієї, яку має посада. Назва належить позиції
    # штатного розпису, код - цьому довіднику.
    @api.depends("code", "group")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s %s" % (rec.code or "", rec.group or "")

    # ------------------------------------------------------------------ служба
    @api.model
    def _service_get(self, path, params=None):
        """Запит до служби. Недоступна - повертаємо None, а не падаємо: прийняття
        на роботу не має спинятися через те, що зовнішня служба мовчить."""
        url = "%s%s" % (SERVICE_URL.rstrip("/"), path)
        if params:
            url = "%s?%s" % (url, urllib.parse.urlencode(params))
        request = urllib.request.Request(url, headers={"User-Agent": "odoo-l10n-ua-kp"})
        try:
            with urllib.request.urlopen(request, timeout=SERVICE_TIMEOUT) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None

    @api.model
    def suggest(self, query, limit=10):
        """Підказки за назвою посади. Розуміє англійські назви і фемінітиви."""
        data = self._service_get("/suggest", {"q": query or "", "limit": limit})
        if data is None:
            return {"available": False, "note": UNAVAILABLE, "items": []}
        return {
            "available": True,
            "via": data.get("via"),
            "total": data.get("total", 0),
            "items": data.get("items") or [],
            "codes": data.get("codes") or [],
        }

    @api.model
    def official(self, code):
        """Офіційна назва і група за кодом. Немає служби - None."""
        data = self._service_get("/code/%s" % urllib.parse.quote(str(code or "")))
        if not data or not data.get("items"):
            return None
        return {"code": data.get("code"), "group": data.get("group") or "",
                "names": [i["name"] for i in data["items"]], "source": data.get("source") or ""}

    # ------------------------------------------------------------------ довідник
    @api.model
    def ensure(self, code, group=None, source=None):
        """Запис довідника для коду; створює, якщо ще немає."""
        code = (code or "").strip()
        if not code:
            return self.browse()
        rec = self.with_context(active_test=False).search([("code", "=", code)], limit=1)
        values = {k: v for k, v in (("group", group), ("source", source)) if v}
        if rec:
            if values and not rec.checked:
                rec.write(values)
            return rec
        return self.create(dict(values, code=code))

    @api.model
    def sync_from_documents(self):
        """Наповнити довідник кодами, які вже стоять у штатних розписах."""
        lines = self.env["ua.staff.list.line"].sudo().search([("kp_code", "!=", False)])
        created = 0
        for code in sorted({(l.kp_code or "").strip() for l in lines if (l.kp_code or "").strip()}):
            before = self.with_context(active_test=False).search_count([("code", "=", code)])
            self.ensure(code)
            if not before:
                created += 1
        return created

    def verify(self):
        """Звірити офіційні назви зі службою. Недоступна - лишаємо як є."""
        for rec in self:
            data = rec.official(rec.code)
            if not data:
                continue
            rec.write({
                "group": data["group"],
                "source": data["source"],
                "names_count": len(data["names"]),
                "checked": True,
            })
        return True

    # ------------------------------------------------------------------ звірка версій
    @api.model
    def audit_versions(self):
        """Версії, де посада змінилася, а код професії лишився від попередньої.

        Саме так неправильний код потрапляє в штатний розпис: наказ про переведення
        підставляв код зі старої версії, і його ніхто не звіряв."""
        Version = self.env["hr.version"].sudo()
        rows = []
        versions = Version.search([("employee_id", "!=", False)], order="employee_id, date_version")
        previous = {}
        for version in versions:
            key = version.employee_id.id
            before = previous.get(key)
            previous[key] = version
            if not before:
                continue
            prof_now = (version.ua_prof_name or version.job_title or "").strip()
            prof_before = (before.ua_prof_name or before.job_title or "").strip()
            if not prof_now or prof_now == prof_before:
                continue
            if (version.ua_kp_code or "") != (before.ua_kp_code or ""):
                continue
            rows.append({
                "level": "crit",
                "employee": version.employee_id.name,
                "from": prof_before,
                "to": prof_now,
                "code": version.ua_kp_code or "",
                "date": str(version.date_version or ""),
                "text": "посада змінилася, код професії лишився від попередньої",
                "target": {"model": "hr.version", "res_id": version.id},
            })
        return rows

    # ------------------------------------------------------------------ звірка розпису
    @api.model
    def audit_staff_lists(self):
        """Що не так із кодами в штатних розписах: кожен рядок - факт і ціль.

        Три види проблем: коду немає зовсім; код є, але такої професії в класифікаторі
        немає; назва посади стоїть у класифікаторі під іншим кодом."""
        Line = self.env["ua.staff.list.line"].sudo()
        rows, seen = [], set()
        for line in Line.search([]):
            title = (line.job_title or "").strip()
            code = (line.kp_code or "").strip()
            key = (title.lower(), code)
            if not title or key in seen:
                continue
            seen.add(key)
            target = {"model": "ua.staff.list.line", "res_id": line.id}
            if not code:
                sug = self.suggest(title, limit=1)
                first = (sug.get("items") or [None])[0]
                rows.append({"level": "crit", "title": title, "code": "",
                             "text": "немає коду", "suggested": first, "target": target})
                continue
            official = self.official(code)
            if official is None:
                rows.append({"level": "warn", "title": title, "code": code,
                             "text": "код не звірено: служба недоступна", "suggested": None,
                             "target": target})
                continue
            if not official.get("names"):
                rows.append({"level": "crit", "title": title, "code": code,
                             "text": "такого коду в класифікаторі немає", "suggested": None,
                             "target": target})
                continue
            if title.lower() in [n.lower() for n in official["names"]]:
                continue
            # Назва не дослівна - це саме по собі не помилка («Юрисконсульт» проти
            # «Юрисконсульт (радник юридичний)»). Помилка - коли класифікатор знає цю
            # назву дослівно, але під іншим кодом.
            sug = self.suggest(title, limit=8)
            items = sug.get("items") or []
            exact = next((i for i in items if i["name"].lower() == title.lower()), None)
            if exact and exact["code"] != code:
                rows.append({"level": "crit", "title": title, "code": code,
                             "text": "класифікатор дає цій назві код %s" % exact["code"],
                             "suggested": exact, "target": target})
                continue
            # Назви немає дослівно, і серед підказок немає того коду, що стоїть.
            # Це не доведена помилка, але ніхто цього не звіряв: «Менеджер із збуту»
            # стояв під 3118 («Креслярі»), скопійованим із сусіднього рядка.
            if items and code not in {i["code"] for i in items}:
                rows.append({"level": "warn", "title": title, "code": code,
                             "text": "код не підтверджується назвою",
                             "suggested": items[0], "target": target})
        return rows
