"""Стандартні подання: кожен пункт меню відкривається, кожна кнопка існує, кожен звіт друкується.

Продукт іде голим Odoo, тому перевірка одна і проста: пройти всі пункти під трьома
нашими розділами («Зарплата», «Кадри», «Звітність») і довести, що
  - у пункта є дія, і це НЕ клієнтська дія (власних екранів більше немає);
  - список, форма і пошук цієї дії будуються без помилки (get_views);
  - кожна кнопка type="object" у побудованій арці має метод на моделі;
  - кожен звіт, прив'язаний до побаченої моделі, рендериться хоча б для одного запису;
  - жоден ідентифікатор відкладених екранів не лишився в ir.model.data.

Працює через `odoo shell` у контейнері стенду, а не через JSON-RPC: get_views і
рендер звіту зручніше кликати прямо, а короткочасний процес завжди читає .py з диска.

Запуск: PAYROLL_DB=payroll python3 scripts/views_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import sys
from lxml import etree

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(("[OK] " if ok else "[FAIL] ") + label + ((" - " + str(detail)) if detail else ""))
    if not ok:
        errors.append(label)


ROOTS = ["l10n_ua_navigation.menu_ua_payroll_root",
         "l10n_ua_navigation.menu_ua_hr_root",
         "l10n_ua_navigation.menu_ua_reporting_root"]

menus = env["ir.ui.menu"]
for xmlid in ROOTS:
    root = env.ref(xmlid, raise_if_not_found=False)
    check("розділ %s на місці" % xmlid, bool(root))
    if not root:
        continue
    stack = [root]
    while stack:
        node = stack.pop()
        menus |= node
        stack.extend(node.child_id)

check("під розділами є пункти", len(menus) > 20, "%s пунктів" % len(menus))

models_seen = set()
for menu in menus.sorted("complete_name"):
    name = menu.complete_name
    action = menu.action
    if not action:
        check("%s: розділ має дітей" % name, bool(menu.child_id), "порожній розділ")
        continue
    check("%s: дія не клієнтська" % name, action._name != "ir.actions.client",
          getattr(action, "tag", ""))
    if action._name != "ir.actions.act_window":
        continue
    model = action.res_model
    models_seen.add(model)
    modes = [m.strip() for m in (action.view_mode or "list,form").split(",") if m.strip()]
    pairs = [(v.view_id.id, v.view_mode) for v in action.view_ids if v.view_mode in modes]
    covered = {m for _i, m in pairs}
    pairs += [(False, m) for m in modes if m not in covered]
    pairs.append((False, "search"))
    context = dict(env.context)
    try:
        context.update(action._get_eval_context() if hasattr(action, "_get_eval_context") else {})
    except Exception:
        pass
    try:
        ctx = eval(action.context or "{}", {"uid": env.uid, "active_id": None, "allowed_company_ids": env.companies.ids, "context_today": lambda: None})
    except Exception:
        ctx = {}
    try:
        views = env[model].with_context(**ctx).get_views(pairs)
    except Exception as error:
        check("%s: подання будуються (%s)" % (name, model), False, str(error)[:300])
        continue
    check("%s: подання будуються (%s)" % (name, model), True,
          ", ".join(sorted(views["views"])))

    for mode, view in views["views"].items():
        arch = view.get("arch")
        if not arch:
            continue
        try:
            tree = etree.fromstring(arch)
        except Exception as error:
            check("%s/%s: арка читається" % (name, mode), False, str(error)[:200])
            continue
        missing = []
        root_model = view.get("model") or model
        for button in tree.xpath("//button[@type='object']"):
            method = button.get("name")
            if not method:
                continue
            # кнопка всередині вкладеного списку one2many належить моделі того поля,
            # а не моделі форми: шукаємо найближче поле-предка і беремо його comodel
            owner = root_model
            node = button.getparent()
            while node is not None:
                if node.tag == "field" and node.get("name"):
                    parent_field = env[root_model]._fields.get(node.get("name"))
                    if parent_field is not None and parent_field.comodel_name:
                        owner = parent_field.comodel_name
                    break
                node = node.getparent()
            target = env[owner]
            if not hasattr(target, method):
                missing.append("%s.%s" % (target._name, method))
        check("%s/%s: кнопки мають методи" % (name, mode), not missing, "; ".join(sorted(set(missing))))

# ------------------------------------------------------------------ звіти
Report = env["ir.actions.report"]
for report in Report.search([("model", "in", sorted(models_seen)),
                             ("report_type", "in", ("qweb-html", "qweb-pdf"))], order="report_name"):
    record = env[report.model].search([], limit=1)
    if not record:
        print("[--] %s: немає жодного запису %s, друк не перевірено" % (report.report_name, report.model))
        continue
    try:
        html, _kind = report._render_qweb_html(report.report_name, record.ids)
        ok = bool(html) and len(html) > 100
        detail = "%s байт" % len(html)
    except Exception as error:
        ok, detail = False, str(error)[:300]
    check("звіт %s рендериться" % report.report_name, ok, detail)

# ------------------------------------------------------------------ сліди відкладених екранів
SHELVED = ["l10n_ua_home", "l10n_ua_period", "l10n_ua_papers", "l10n_ua_people",
           "l10n_ua_dashboard", "l10n_ua_card_ui", "l10n_ua_shell", "l10n_ua_hire_ui",
           "l10n_ua_reporting_ui", "l10n_ua_setup_ui", "l10n_ua_bank_ui", "l10n_ua_payroll_ui"]
left = env["ir.model.data"].search_count([("module", "in", SHELVED)])
check("у ir.model.data немає записів відкладених модулів", left == 0, "%s записів" % left)
installed = env["ir.module.module"].search_count([("name", "in", SHELVED),
                                                  ("state", "!=", "uninstalled")])
check("жоден відкладений модуль не встановлений", installed == 0, "%s модулів" % installed)
own = env["ir.model.data"].search([("model", "=", "ir.actions.client"),
                                   "|", ("module", "=like", "l10n\\_ua\\_%"),
                                        ("module", "=like", "bp\\_%")])
check("власних клієнтських дій не лишилось", not own, ", ".join(own.mapped("complete_name")))

env.cr.rollback()
print()
if errors:
    print("ПЕРЕВІРКУ НЕ ПРОЙДЕНО: %s з %s пунктів провалено" % (len(errors), total))
    sys.exit(1)
print("Усі перевірки пройдено (%s з %s)." % (total, total))
quit()
"""

proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     "odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo "
     f"-d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
out = proc.stdout
print(out.strip())
if "Усі перевірки пройдено" not in out and "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" not in out:
    print("--- stderr (odoo shell) ---")
    print(proc.stderr[-4000:])
    sys.exit(proc.returncode or 1)
sys.exit(1 if "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in out else 0)
