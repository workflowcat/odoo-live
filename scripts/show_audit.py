#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Огляд показової бази очима людини: усі пункти меню, а не лише три наші розділи.

Для кожного пункту меню, який бачить адміністратор з мовою uk_UA:
  - чи є дія і якого вона типу; діалог з меню (target = new) - це провал;
  - чи будуються список, форма і пошук (get_views);
  - скільки записів у моделі під доменом дії: порожній список на показі - спостереження;
  - які видимі рядки лишились англійською: назва пункту, назва дії, мітки полів у
    поданнях, заголовки кнопок, сторінок і груп.

Нічого не пише. Працює через `odoo shell` у контейнері стенду.
Результат: demo-out/audit.json і короткий підсумок на екран.

Англійський прохід (AUDIT_LANG=en_US): та сама прогулянка очима адміністратора з
мовою en_US, але провалом є кирилиця - у назвах пунктів і дій, мітках полів, значеннях
вибору і рядках подань. Плюс підсумок по всій базі: скільки пунктів меню і міток полів
мають кирилицю в en_US. Результат: demo-out/audit_en.json.

Запуск: DEMO_DB=show python3 scripts/show_audit.py
        AUDIT_LANG=en_US DEMO_DB=show python3 scripts/show_audit.py
        AUDIT_COMPOSE=~/dev/odoo-dev ... - запуск у вже піднятому контейнері odoo того стенду
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("DEMO_DB", "demo").strip()
LANG = os.environ.get("AUDIT_LANG", "uk_UA").strip()
COMPOSE = os.path.expanduser(os.environ.get("AUDIT_COMPOSE", "").strip())
OUT = os.path.join(ROOT, "demo-out", "audit.json" if LANG == "uk_UA" else "audit_en.json")

SCRIPT = r"""
import json, re
from lxml import etree

LAT = re.compile(r"[A-Za-z]{3,}")
CYR = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
# Слова, які українською так і пишуть латинкою.
OK = {"iban", "xml", "pdf", "crm", "url", "sms", "email", "e-mail", "id", "api", "csv", "xlsx",
      "excel", "html", "json", "swift", "bic", "gps", "utm", "http", "https", "odoo", "oca",
      "kyc", "vat", "privatbank", "monobank", "privat24", "linkedin", "whatsapp", "google",
      "microsoft", "outlook", "ldap", "oauth", "smtp", "imap", "pop", "ssl", "tls", "qr",
      "sepa", "isr", "ean", "upc", "sku", "hs", "kpi", "mrp", "erp", "bom", "plm", "pos",
      "uah", "usd", "eur", "telegram", "viber", "wms", "cpi", "mis", "ok", "wip", "eta",
      "gmail", "png", "jpg", "zip", "txt", "doc", "docx", "xls", "ods", "ics", "ical", "geo",
      # назви продуктів і протоколів, які не перекладають
      "bas", "stun", "turn", "unicode", "utf", "barcodelookup", "com", "gelato", "recaptcha",
      "cloudflare", "turnstile", "oee", "qweb"}


EN = LANG == "en_US"
WORD = "українською" if EN else "англійською"


# Рядок не тією мовою: кирилиця для en_US, англійські слова для uk_UA.
def english(text):
    if not text:
        return False
    text = str(text)
    if EN:
        return bool(CYR.search(text))
    if CYR.search(text):
        return False
    words = [w.lower() for w in LAT.findall(text)]
    return any(w not in OK for w in words)


env = env(context=dict(env.context, lang=LANG))
Menu = env["ir.ui.menu"]
rows = []
seen_models = {}

# Дивимось очима адміністратора без режиму розробника: службові пункти не рахуємо.
admin = env.ref("base.user_admin")
visible = Menu.with_user(admin)._visible_menu_ids(debug=False)
for menu in Menu.search([("id", "in", list(visible))], order="parent_path"):
    path = menu.complete_name
    root = path.split("/")[0]
    row = {"id": menu.id, "path": path, "root": root, "xmlid": menu.get_external_id().get(menu.id) or "",
           "problems": [], "notes": []}
    if english(menu.name):
        row["problems"].append("назва пункту %s: %s" % (WORD, menu.name))
    act = menu.action
    if not act:
        if not (set(menu.child_id.ids) & set(visible)):
            row["problems"].append("пункт без дії і без підпунктів")
        rows.append(row)
        continue
    row["action_type"] = act._name
    row["action_name"] = act.name
    if english(act.name):
        row["problems"].append("назва дії %s: %s" % (WORD, act.name))
    if act._name == "ir.actions.act_window":
        row["model"] = act.res_model
        row["target"] = act.target
        if act.target == "new":
            row["problems"].append("з меню відкривається діалог, а не сторінка")
        if act.res_model not in env:
            row["problems"].append("моделі немає: %s" % act.res_model)
            rows.append(row)
            continue
        Model = env[act.res_model]
        modes = [m for m in (act.view_mode or "list,form").split(",") if m in ("list", "form", "kanban")]
        if "form" not in modes:
            modes.append("form")
        try:
            views = Model.get_views([(False, m) for m in modes] + [(False, "search")])
        except Exception as exc:
            env.cr.rollback()
            row["problems"].append("подання не будується: %s" % str(exc)[:300])
            rows.append(row)
            continue
        if not Model._transient and not Model._abstract:
            try:
                dom = act.domain and eval(act.domain, {"uid": env.uid, "active_id": False, "context": {},
                                                       "time": __import__("time"), "datetime": __import__("datetime"),
                                                       "context_today": __import__("datetime").date.today}) or []
                row["count"] = Model.search_count(dom)
                row["count_all"] = Model.search_count([])
            except Exception as exc:
                env.cr.rollback()
                row["notes"].append("домен дії не обчислюється поза браузером: %s" % str(exc)[:120])
                try:
                    row["count_all"] = Model.search_count([])
                except Exception:
                    env.cr.rollback()
        if act.res_model not in seen_models:
            eng = []
            fields = Model.fields_get()
            for mode, data in views["views"].items():
                arch = etree.fromstring(data["arch"])
                for node in arch.iter():
                    if node.tag == "field":
                        name = node.get("name")
                        if node.get("invisible") in ("1", "True") or node.get("column_invisible") in ("1", "True"):
                            continue
                        label = node.get("string") or (fields.get(name) or {}).get("string")
                        if english(label):
                            eng.append("%s: поле %s = %s" % (mode, name, label))
                        # назви мов Odoo пише рідною мовою («Ukrainian / українська») навмисно
                        if EN and name != "lang":
                            for key, val in (fields.get(name) or {}).get("selection") or []:
                                if english(val):
                                    eng.append("%s: вибір %s.%s = %s" % (mode, name, key, val))
                    elif node.tag in ("button", "page", "group", "separator", "filter", "label", "span", "div", "h1", "h2", "h3", "p", "a", "strong", "b"):
                        for attr in ("string", "title", "placeholder", "help", "confirm"):
                            val = node.get(attr)
                            if english(val):
                                eng.append("%s: <%s %s> %s" % (mode, node.tag, attr, val[:80]))
                        if node.tag not in ("button", "page", "group", "separator", "filter") and node.text and english(node.text.strip()):
                            eng.append("%s: текст <%s> %s" % (mode, node.tag, node.text.strip()[:80]))
            seen_models[act.res_model] = sorted(set(eng))
        row["english"] = len(seen_models[act.res_model])
    elif act._name == "ir.actions.client":
        row["tag"] = act.tag
    rows.append(row)

# Сирі англійські рядки для словника data/terms_uk.json.
raw = set()
for items in seen_models.values():
    for item in items:
        raw.add(re.sub(r"^\w+: (поле \S+ = |вибір \S+ = |<\w+ \w+> |текст <\w+> )", "", item))
for row in rows:
    for key in ("action_name",):
        if english(row.get(key)):
            raw.add(row[key])
    if english(row["path"].split("/")[-1]):
        raw.add(row["path"].split("/")[-1])
# По всій базі, не лише видиме адміністраторові: джерело en_US з кирилицею.
whole = {}
if EN:
    env.cr.execute("SELECT count(*) FROM ir_ui_menu WHERE active AND name->>'en_US' ~ '[А-Яа-яІіЇїЄєҐґ]'")
    whole["menus"] = env.cr.fetchone()[0]
    env.cr.execute("SELECT count(*) FROM ir_model_fields WHERE field_description->>'en_US' ~ '[А-Яа-яІіЇїЄєҐґ]'")
    whole["fields"] = env.cr.fetchone()[0]
    env.cr.execute("SELECT count(*) FROM ir_model_fields_selection WHERE name->>'en_US' ~ '[А-Яа-яІіЇїЄєҐґ]'")
    whole["selection"] = env.cr.fetchone()[0]
    env.cr.execute("SELECT count(*) FROM ir_act_window WHERE name->>'en_US' ~ '[А-Яа-яІіЇїЄєҐґ]'")
    whole["actions"] = env.cr.fetchone()[0]
out = {"db": env.cr.dbname, "lang": LANG, "whole": whole, "menus": rows, "raw_english": sorted(raw), "english_by_model": seen_models,
       "modules": env["ir.module.module"].search([("state", "=", "installed")]).mapped("name")}
print("@@JSON@@" + json.dumps(out, ensure_ascii=False))
"""


def main():
    cmd = ["docker", "compose", "run", "--rm", "--no-deps", "-T", "odoo", "sh", "-c",
           "exec odoo shell --addons-path=/mnt/extra-addons --db_host=db --db_user=odoo "
           "--db_password=odoo --max-cron-threads=0 -d '%s' --db-filter='.*' --log-level=error" % DB]
    if COMPOSE:
        # стенд у ~/dev/odoo-dev: пароль бази в оточенні контейнера, http не потрібен
        cmd = ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
               "exec odoo shell --addons-path=/mnt/extra-addons,/mnt/ui-addons --db_host=db --db_user=odoo "
               "--db_password=\"$PG_PASSWORD\" --max-cron-threads=0 --no-http -d '%s' --db-filter='.*' "
               "--log-level=error" % DB]
    res = subprocess.run(cmd, input="LANG = %r\n" % LANG + SCRIPT, capture_output=True, text=True,
                         cwd=COMPOSE or ROOT, timeout=1800)
    marker = "@@JSON@@"
    line = next((l for l in res.stdout.splitlines() if marker in l), None)
    if not line:
        sys.stderr.write(res.stdout[-3000:] + "\n" + res.stderr[-3000:] + "\n")
        sys.exit(1)
    payload = line.split(marker, 1)[1]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(payload)
    import json
    data = json.loads(payload)
    menus = data["menus"]
    bad = [m for m in menus if m["problems"]]
    empty = [m for m in menus if m.get("count") == 0]
    eng = sum(len(v) for v in data["english_by_model"].values())
    word = "українських" if LANG == "en_US" else "англійських"
    print("База %s (%s): пунктів меню %d, з проблемами %d, порожніх списків %d, %s рядків у поданнях %d"
          % (data["db"], LANG, len(menus), len(bad), len(empty), word, eng))
    if data.get("whole"):
        print("Уся база, кирилиця в en_US: меню %(menus)d, дії %(actions)d, мітки полів %(fields)d, "
              "значення вибору %(selection)d" % data["whole"])
    for m in bad:
        print("  ! %s - %s" % (m["path"], "; ".join(m["problems"])))
    sys.exit(0)


if __name__ == "__main__":
    main()
