#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наскрізний прохід показової бази тими самими запитами, що їх робить браузер.

Для кожного логіна (адміністратор і демо-користувачі) скрипт входить через
/web/session/authenticate, бере меню через /web/webclient/load_menus і для кожного
пункту з дією робить те, що робить вебклієнт, коли людина клацає пункт:
  1. /web/action/load - дія завантажується;
  2. get_views - список, форма, пошук (і канбан, якщо він у дії) будуються;
  3. web_search_read першої сторінки списку з полями зі списку;
  4. web_read першого запису з полями форми - форма відкривається з даними;
  5. для сторінок-майстрів (тимчасова модель) - onchange нового запису.
Окремо для адміністратора: кожен друкований звіт, прив'язаний до побаченої моделі,
рендериться для першого запису (/report/pdf або /report/html).

Нічого не створює і не змінює (onchange нового запису в базу не пише).
Результат: demo-out/e2e.json і підсумок на екран; код виходу 1, якщо є помилки.

Запуск: DEMO_DB=show ODOO_URL=http://127.0.0.1:8133 python3 scripts/show_e2e.py
        E2E_USERS=admin,zakupivli python3 scripts/show_e2e.py
"""
import ast
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = os.environ.get("DEMO_DB", "demo")
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
USERS = [u for u in os.environ.get("E2E_USERS", "admin,zakupivli,petrenko,tkach,koval").split(",") if u]
REPORT_LIMIT = int(os.environ.get("E2E_REPORTS", "200"))
CTX = {"lang": "uk_UA", "tz": "Europe/Kyiv"}
SKIP_REPORTS = {"hr_holidays.report_holidayssummary", "account.report_original_vendor_bill"}
SKIP_MODELS = {"board.board"}


class Session:
    def __init__(self, login):
        self.login = login
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.info = self.json("/web/session/authenticate", {"db": DB, "login": login, "password": PW})
        self.ctx = dict(CTX, allowed_company_ids=[self.info["user_companies"]["current_company"]])

    def json(self, path, params):
        body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1, "params": params}).encode()
        req = urllib.request.Request(URL + path, data=body, headers={"Content-Type": "application/json"})
        with self.opener.open(req, timeout=180) as resp:
            out = json.loads(resp.read())
        if out.get("error"):
            data = out["error"].get("data") or {}
            raise RuntimeError("%s: %s" % (data.get("name", "помилка"), (data.get("message") or "")[:300]))
        return out.get("result")

    def call(self, model, method, args=None, kwargs=None):
        kwargs = dict(kwargs or {})
        kwargs.setdefault("context", self.ctx)
        return self.json("/web/dataset/call_kw/%s/%s" % (model, method),
                         {"model": model, "method": method, "args": args or [], "kwargs": kwargs})

    def get(self, path):
        with self.opener.open(URL + path, timeout=300) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def field_spec(arch, fields):
    """Поля подання у вигляді специфікації web_read: {поле: {}}."""
    spec = {}
    try:
        root = ET.fromstring(arch)
    except ET.ParseError:
        return spec
    for node in root.iter("field"):
        name = node.get("name")
        if name and name in fields and name not in spec:
            ftype = fields[name].get("type")
            spec[name] = {"fields": {"display_name": {}}} if ftype in ("many2one",) else {}
    return spec


def walk_menus(tree):
    """Список (стежка, action) з відповіді load_menus."""
    out = []

    def visit(menu_id, path):
        menu = tree.get(str(menu_id)) or tree.get(menu_id)
        if not menu:
            return
        here = path + [menu["name"]]
        if menu.get("actionID"):
            out.append(("/".join(here), menu["actionID"], menu.get("actionModel")))
        for child in menu.get("children", []):
            visit(child, here)

    for child in tree["root"]["children"]:
        visit(child, [])
    return out


def check_user(login, do_reports):
    result = {"login": login, "ok": 0, "errors": [], "reports_ok": 0, "report_errors": []}
    try:
        session = Session(login)
    except Exception as exc:  # користувача може не бути в цій базі
        result["errors"].append({"path": "(вхід)", "step": "authenticate", "error": str(exc)[:300]})
        return result
    status, _ctype, raw = session.get("/web/webclient/load_menus")
    menus = walk_menus(json.loads(raw))
    result["menus"] = len(menus)
    seen_models = {}
    for path, action_id, action_model in menus:
        step = "action/load"
        try:
            action = session.json("/web/action/load", {"action_id": action_id, "context": session.ctx})
            if not action or action.get("type") != "ir.actions.act_window":
                result["ok"] += 1
                continue
            model = action["res_model"]
            if model in SKIP_MODELS:
                result["ok"] += 1
                continue
            modes = [m for m in (action.get("view_mode") or "list,form").split(",") if m in ("list", "form", "kanban")]
            if "form" not in modes:
                modes.append("form")
            step = "get_views"
            views = session.call(model, "get_views", [], {
                "views": [[False, m] for m in modes] + [[False, "search"]],
                "options": {"action_id": action_id, "load_filters": True, "toolbar": True}})
            fields = views["models"][model]["fields"]
            form_spec = field_spec(views["views"]["form"]["arch"], fields)
            # Сторінка-майстер: у дії лише форма. Зведені звіти (graph, pivot, calendar)
            # форми не відкривають - їх перевіряє сам get_views.
            own_modes = [m for m in (action.get("view_mode") or "").split(",") if m]
            transient = own_modes == ["form"]
            if "list" in views["views"] or "kanban" in views["views"]:
                step = "web_search_read"
                first = "list" if "list" in views["views"] else "kanban"
                spec = field_spec(views["views"][first]["arch"], fields)
                # Домен дії приходить рядком Python; простий - читаємо, складний (з uid,
                # датами) - пропускаємо і беремо весь список.
                domain = action.get("domain") or []
                if isinstance(domain, str):
                    try:
                        domain = ast.literal_eval(domain)
                    except Exception:
                        domain = []
                page = session.call(model, "web_search_read", [], {
                    "domain": domain if isinstance(domain, list) else [], "specification": spec,
                    "limit": 20, "offset": 0})
                records = page.get("records") or []
                if records:
                    step = "web_read"
                    session.call(model, "web_read", [[records[0]["id"]]], {"specification": form_spec})
                    ids = seen_models.setdefault(model, [])
                    if records[0]["id"] not in ids:
                        ids.append(records[0]["id"])
            if transient:
                step = "onchange"
                session.call(model, "onchange", [[], {}, [], form_spec])
            result["ok"] += 1
        except Exception as exc:
            result["errors"].append({"path": path, "step": step, "error": str(exc)[:400]})
    if do_reports:
        reports = session.call("ir.actions.report", "search_read", [[["model", "in", list(seen_models)]]],
                               {"fields": ["report_name", "report_type", "model", "name"]})
        for report in reports[:REPORT_LIMIT]:
            if report["report_type"] not in ("qweb-pdf", "qweb-html"):
                continue
            # етикетки і зведення відпусток друкуються лише з майстра з параметрами
            if "label" in report["report_name"] or report["report_name"] in SKIP_REPORTS:
                continue
            kind = "pdf" if report["report_type"] == "qweb-pdf" else "html"
            # Звіт годиться не для кожного запису моделі (рахунок - не будь-яка проводка),
            # тому пробуємо записи з різних пунктів меню; провал - лише коли не вийшло з жодним.
            last = ""
            for rec_id in seen_models[report["model"]][:20]:
                try:
                    status, ctype, body = session.get("/report/%s/%s/%s" % (kind, report["report_name"], rec_id))
                    if status == 200 and len(body) >= 500:
                        last = ""
                        break
                    last = "відповідь %s, %s байт" % (status, len(body))
                except urllib.error.HTTPError as exc:
                    text = exc.read().decode("utf-8", "replace")
                    mark = text.find("o_error_detail")
                    last = "HTTP %s %s" % (exc.code, " ".join(text[mark:mark + 900].split())[-500:] if mark > 0 else text[-200:])
                except Exception as exc:
                    last = str(exc)[:300]
            if last:
                result["report_errors"].append({"report": report["report_name"], "model": report["model"], "error": last})
            else:
                result["reports_ok"] += 1
    return result


def main():
    started = time.time()
    results = [check_user(login, do_reports=(login == "admin")) for login in USERS]
    os.makedirs(os.path.join(ROOT, "demo-out"), exist_ok=True)
    with open(os.path.join(ROOT, "demo-out", "e2e.json"), "w") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    failed = 0
    for res in results:
        failed += len(res["errors"]) + len(res["report_errors"])
        print("%-10s пунктів меню %s, відкрились %s, помилок %s; звітів надруковано %s, помилок друку %s" % (
            res["login"], res.get("menus", 0), res["ok"], len(res["errors"]),
            res["reports_ok"], len(res["report_errors"])))
        for err in res["errors"]:
            print("   ! %s [%s] %s" % (err["path"], err["step"], err["error"][:220]))
        for err in res["report_errors"]:
            print("   ! друк %s (%s): %s" % (err["report"], err["model"], err["error"][:220]))
    print("Час: %.0f с" % (time.time() - started))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
