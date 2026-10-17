#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наповненість полів показової бази: які поля форми порожні в усіх записах.

Для кожної моделі, яку адміністратор бачить у меню і в якій є записи, беремо поля з
форми (те, що людина бачить, відкривши запис) і рахуємо, у скількох записах поле
заповнене. Рахуються лише збережені поля: текст, дата, вибір, зв'язок, число, файл.
Прапорці не рахуються (порожній прапорець - теж відповідь), нуль у числі - порожньо.

Підсумок - поля, порожні в усіх записах моделі, і поля, заповнені менш ніж у чверті.
Нічого не пише. Результат: demo-out/fill.json.

Запуск: DEMO_DB=show ODOO_URL=http://127.0.0.1:8133 python3 scripts/show_fill.py
        FILL_MODELS=hr.employee,account.asset python3 scripts/show_fill.py   (докладно по названих)
"""
import json
import os
import sys
import urllib.request
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(ROOT, ".env")) if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = os.environ.get("DEMO_DB", "demo")
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
ONLY = [m for m in os.environ.get("FILL_MODELS", "").split(",") if m]
CTX = {"lang": "uk_UA", "active_test": False}
SKIP_PREFIX = ("ir.", "base.", "mail.", "discuss.", "res.config", "res.users", "res.groups", "bus.",
               "iap.", "sms.", "payment.", "auditlog.", "utm.", "digest.", "onboarding.", "spreadsheet.",
               "res.lang", "res.country", "res.currency", "report.", "fetchmail", "snailmail", "privacy",
               "phone.", "web_tour", "link.", "res.device", "res.role", "calendar.", "date.range",
               "uom.", "decimal.", "resource.", "barcode", "account.account.tag", "account.tax",
               "account.fiscal", "account.incoterms", "account.payment.term", "account.journal",
               "account.account", "account.group", "account.reconcile", "product.attribute",
               "product.category", "product.tag", "product.pricelist", "stock.route", "stock.rule",
               "stock.picking.type", "stock.location", "stock.warehouse", "stock.putaway",
               "hr.leave.type", "hr.work.entry.type", "hr.salary.rule", "hr.payroll.structure",
               "hr.contribution", "crm.stage", "crm.team", "crm.tag", "crm.lost", "mis.", "account.analytic.plan")
TYPES = ("char", "text", "html", "date", "datetime", "selection", "many2one", "many2many", "one2many",
         "integer", "float", "monetary", "binary")


def rpc(service, method, *args):
    body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": 1,
                       "params": {"service": service, "method": method, "args": list(args)}}).encode()
    req = urllib.request.Request(URL + "/jsonrpc", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read())
    if out.get("error"):
        raise RuntimeError((out["error"].get("data") or {}).get("message") or str(out["error"]))
    return out["result"]


UID = rpc("common", "login", DB, "admin", PW)


def call(model, method, *args, **kwargs):
    kwargs.setdefault("context", CTX)
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(args), kwargs)


def form_fields(model):
    views = call(model, "get_views", [[False, "form"]])
    fields = views["models"][model]["fields"]
    names = []
    try:
        root = ET.fromstring(views["views"]["form"]["arch"])
    except ET.ParseError:
        return fields, names
    # поля вкладених списків (рядки документа) не належать самій моделі
    nested = set()
    for parent in root.iter("field"):
        for child in parent.iter("field"):
            if child is not parent:
                nested.add(id(child))
    for node in root.iter("field"):
        name = node.get("name")
        if id(node) in nested or not name or name not in fields or name in names:
            continue
        if node.get("invisible") in ("1", "True") or node.get("column_invisible") in ("1", "True"):
            continue
        names.append(name)
    return fields, names


def main():
    if ONLY:
        models = ONLY
    else:
        actions = call("ir.ui.menu", "search_read", [["action", "like", "ir.actions.act_window,"]], fields=["action"])
        ids = sorted({int(a["action"].split(",")[1]) for a in actions})
        models = sorted({a["res_model"] for a in call("ir.actions.act_window", "read", ids, ["res_model"])})
        models = [m for m in models if not m.startswith(SKIP_PREFIX)]
    report = {}
    for model in models:
        try:
            total = call(model, "search_count", [])
            if not total:
                continue
            info = call("ir.model", "search_read", [["model", "=", model]], fields=["transient", "name"])
            if not info or info[0]["transient"]:
                continue
            fields, names = form_fields(model)
        except Exception as exc:
            report[model] = {"error": str(exc)[:200]}
            continue
        rows = []
        for name in names:
            meta = fields[name]
            if meta["type"] not in TYPES or not meta.get("store") or name in ("id", "display_name"):
                continue
            try:
                if meta["type"] in ("integer", "float", "monetary"):
                    filled = call(model, "search_count", [[name, "!=", 0]])
                else:
                    filled = call(model, "search_count", [[name, "!=", False]])
            except Exception:
                continue
            rows.append({"field": name, "label": meta.get("string"), "type": meta["type"], "filled": filled})
        report[model] = {"name": info[0]["name"], "total": total, "fields": rows}
    os.makedirs(os.path.join(ROOT, "demo-out"), exist_ok=True)
    with open(os.path.join(ROOT, "demo-out", "fill.json"), "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    empty_total = 0
    for model, data in sorted(report.items()):
        if "error" in data:
            print("%s: %s" % (model, data["error"]))
            continue
        empty = [r for r in data["fields"] if r["filled"] == 0]
        thin = [r for r in data["fields"] if 0 < r["filled"] < data["total"] / 4]
        empty_total += len(empty)
        if not empty and not (ONLY and thin):
            continue
        print("%s - %s: записів %s, полів на формі %s, порожніх скрізь %s" % (
            model, data["name"], data["total"], len(data["fields"]), len(empty)))
        print("    порожні: " + "; ".join("%s (%s)" % (r["label"], r["field"]) for r in empty))
        if ONLY and thin:
            print("    рідко: " + "; ".join("%s %s/%s" % (r["label"], r["filled"], data["total"]) for r in thin))
    print("Моделей %s, полів, порожніх у всіх записах: %s" % (len(report), empty_total))


if __name__ == "__main__":
    main()
