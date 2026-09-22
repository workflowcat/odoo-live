#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка поділу на логіку і інтерфейс. Стенд не потрібен - читаємо самі файли.

Від 2026-09-22 продукт іде голим Odoo: власних екранів немає, уся робота йде через
стандартні списки, форми, кнопки і чарівники. Відкладені екрани лежать поза addons/,
у shelved/addons-owl/, і Odoo їх не бачить.

Правила:
  1. жоден НЕ-UI модуль не залежить від UI-модуля - ні прямо, ні через ланцюг;
  2. жоден НЕ-UI модуль не посилається в XML на ідентифікатор UI-модуля
     (пункт меню під чужим розділом падає на порожній базі);
  3. у addons/ немає жодного власного static/src - екранів ми більше не пишемо;
     тема прийде окремим модулем, тоді це правило перепишемо разом із нею;
  4. жоден модуль у addons/ не згадує відкладений екран (shelved/addons-owl);
  5. єдиний UI-модуль - l10n_ua_navigation - справді везе меню;
  6. кожна нова модель наших модулів знає свою компанію.

Правило 6 детальніше. Odoo ділить дані між компаніями полем company_id і правилами
запису; модель без company_id видно всім, хто має доступ до моделі. Тому кожна НОВА
модель (l10n_ua_*, bp_*) має пройти одним із чотирьох шляхів:
  OWN     - сама тримає поле company_id;
  BASE    - успадковує прототипом (_name + _inherit) модель, яка компанію вже має;
  PARENT  - висить на обов'язковому Many2one до моделі, яка компанію має: рядок
            документа живе і вмирає разом із документом, і правило запису на
            документі закриває рядок разом із ним;
  SHARED  - стоїть у переліку SHARED нижче з однорядковою причиною: це довідник
            або налаштування, спільні для всієї бази навмисно.
Нова модель, яка не проходить жодним шляхом, провалює перевірку. Не додавайте її в
SHARED «щоб стало зелено»: SHARED - це класифікатори (КП, індекс цін, пільги ПДВ),
а не документи.

Припущення статичного розбору (стенд не піднімаємо, читаємо AST):
  - «наша нова модель» - клас із _name, якого немає серед його ж _inherit; клас, де
    _name дорівнює чужій моделі, - це розширення, його не перевіряємо;
  - AbstractModel і TransientModel таблиці не мають, їх пропускаємо (чарівник живе
    у сесії користувача і компанію бере з контексту);
  - company_id шукаємо в усіх наших класах цієї моделі, хоч у якому модулі;
  - вендоровані модулі (OCA, payroll) розбираємо так само, як свої, - лише не
    перевіряємо; для моделей ядра Odoo коду тут немає, тому тримаємо перелік
    COMPANY_BOUND: у ньому лише ті, де company_id завжди заповнене. res.partner,
    product.* і res.currency туди не входять навмисно - вони спільні, і «батько -
    партнер» компанії не доводить.

Запуск: python3 scripts/layers_check.py"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, "addons")
SHELVED = os.path.join(ROOT, "shelved", "addons-owl")

# Модуль інтерфейсу рівно один: власник меню. Йому можна залежати від будь-чого.
UI_MODULES = {"l10n_ua_navigation"}
OURS = re.compile(r"^(l10n_ua_|bp_)")

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def manifests():
    out = {}
    for name in sorted(os.listdir(ADDONS)):
        path = os.path.join(ADDONS, name, "__manifest__.py")
        if not os.path.isfile(path):
            continue
        try:
            out[name] = ast.literal_eval(open(path, encoding="utf-8").read())
        except Exception as error:
            check(f"{name}: маніфест читається", False, str(error))
            out[name] = {}
    return out


MANIFESTS = manifests()
DEPENDS = {name: list(data.get("depends") or []) for name, data in MANIFESTS.items()}
# Відкладені екрани переїхали в репозиторій odoo-ui (reference/owl-2026-09-22); тут лишається
# лише перелік їхніх назв, щоб жоден модуль ядра на них не посилався.
SHELVED_MODULES = sorted([
    "l10n_ua_bank_ui", "l10n_ua_card_ui", "l10n_ua_dashboard", "l10n_ua_hire_ui", "l10n_ua_home",
    "l10n_ua_papers", "l10n_ua_payroll_ui", "l10n_ua_people", "l10n_ua_period",
    "l10n_ua_reporting_ui", "l10n_ua_setup_ui", "l10n_ua_shell",
] + [name for name in (os.listdir(SHELVED) if os.path.isdir(SHELVED) else [])
     if os.path.isdir(os.path.join(SHELVED, name))])


def chain_to_ui(module, seen=None, path=None):
    """Найкоротший ланцюг залежностей від module до UI-модуля, або None."""
    seen = seen if seen is not None else set()
    path = path or [module]
    for dep in DEPENDS.get(module, []):
        if dep in UI_MODULES:
            return path + [dep]
        if dep in seen or dep not in DEPENDS:
            continue
        seen.add(dep)
        found = chain_to_ui(dep, seen, path + [dep])
        if found:
            return found
    return None


def files_of(name, suffixes):
    for base, _dirs, file_names in os.walk(os.path.join(ADDONS, name)):
        if "__pycache__" in base:
            continue
        for file_name in file_names:
            if file_name.endswith(suffixes):
                yield os.path.join(base, file_name)


def read_no_comments(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".xml"):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


# 1. залежності
for name in sorted(DEPENDS):
    if name in UI_MODULES:
        continue
    chain = chain_to_ui(name)
    check(f"{name} не залежить від інтерфейсу", chain is None, " -> ".join(chain or []))

# 2. посилання в XML на ідентифікатори UI-модулів
XMLID = re.compile(r"\b(%s)\.[a-zA-Z0-9_]+" % "|".join(sorted(UI_MODULES)))
for name in sorted(MANIFESTS):
    if name in UI_MODULES or not OURS.match(name):
        continue
    hits = []
    for path in files_of(name, (".xml",)):
        for match in XMLID.finditer(read_no_comments(path)):
            hits.append("%s: %s" % (os.path.relpath(path, ADDONS), match.group(0)))
    check(f"{name}: XML не посилається на інтерфейс", not hits, "; ".join(hits[:4]))

# 3. static/src у addons/ більше немає взагалі - вендорований OCA не рахуємо
for name in sorted(MANIFESTS):
    if not OURS.match(name):
        continue
    has_assets = os.path.isdir(os.path.join(ADDONS, name, "static", "src"))
    check(f"{name}: без static/src", not has_assets, "є static/src" if has_assets else "")

# 4. жодного ЖИВОГО посилання на відкладений екран у addons/
#    Живе посилання - це depends у маніфесті, ідентифікатор у XML, env.ref або import
#    у Python. Згадка в коментарі чи в тексті міграції, яка саме прибирає старий модуль,
#    посиланням не є: теки migrations/ пропускаємо, у Python дивимось лише на ref/import.
if SHELVED_MODULES:
    names = "|".join(SHELVED_MODULES)
    XML_REF = re.compile(r"\b(%s)\.[a-zA-Z0-9_]+" % names)
    PY_REF = re.compile(r"""(?:env\.ref\(\s*["']|odoo\.addons\.)(%s)\b""" % names)
    for name in sorted(MANIFESTS):
        if not OURS.match(name):
            continue
        hits = [dep for dep in DEPENDS.get(name, []) if dep in SHELVED_MODULES]
        for path in files_of(name, (".xml", ".py")):
            if os.sep + "migrations" + os.sep in path:
                continue
            text = read_no_comments(path)
            finder = XML_REF if path.endswith(".xml") else PY_REF
            for match in finder.finditer(text):
                hits.append("%s: %s" % (os.path.relpath(path, ADDONS), match.group(0)))
        check(f"{name}: не посилається на відкладені екрани", not hits, "; ".join(hits[:4]))
else:
    check("тека відкладених екранів на місці", False, SHELVED)

# 5. модуль інтерфейсу справді везе меню
for name in sorted(UI_MODULES):
    if name not in MANIFESTS:
        check(f"{name}: модуль є в addons/", False)
        continue
    data = MANIFESTS[name].get("data") or []
    check(f"{name}: модуль інтерфейсу везе меню",
          any("menu" in f for f in data), str(data))

# 6. поділ даних між компаніями --------------------------------------------------

# Моделі ядра Odoo, де company_id є і завжди заповнене. Сюди йде лише те, на чому
# справді висять наші моделі; перелік розширюємо разом із кодом, а не про запас.
COMPANY_BOUND = {
    "account.move", "account.move.line", "account.journal", "account.account",
    "account.payment", "account.bank.statement", "account.bank.statement.line",
    "sale.order", "purchase.order", "stock.picking", "stock.warehouse", "stock.location",
    "mrp.production", "hr.employee", "hr.department", "hr.job", "hr.contract",
    "hr.payslip", "hr.payslip.run", "hr.leave", "hr.leave.allocation", "res.users",
}

# Моделі, спільні для всієї бази навмисно. Причина - в один рядок, і вона має
# відповідати на питання «чому в «Ясен Меблі» і в «АероСіч» тут однакові дані».
SHARED = {
    "ua.kp.code": "класифікатор професій ДК 003:2010 - державний, один на країну",
    "ua.cpi.index": "індекс споживчих цін Держстату - однаковий для всіх компаній",
    "ua.vat.relief": "довідник пільг ПДВ за УКТ ЗЕД - із закону, не з обліку компанії",
    "ua.hr.doc.requirement": "перелік обов'язкових кадрових документів - вимога КЗпП",
    "ua.setup.question": "питання анкети запуску - текст анкети, а не відповіді",
    "ua.change.field": "налаштування журналу змін: висить на auditlog.rule, яке саме "
                       "компанії не має",
}


def field_call(node):
    """{'type': 'Many2one', 'comodel': ..., 'required': ...} з виклику fields.X(...)."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    kind = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if not kind or kind[0].islower():
        return None
    comodel = None
    if node.args:
        try:
            comodel = ast.literal_eval(node.args[0])
        except Exception:
            comodel = None
    keywords = {}
    for keyword in node.keywords:
        try:
            keywords[keyword.arg] = ast.literal_eval(keyword.value)
        except Exception:
            keywords[keyword.arg] = None
    if not isinstance(comodel, str):
        comodel = keywords.get("comodel_name")
    return {"type": kind, "comodel": comodel if isinstance(comodel, str) else None,
            "required": bool(keywords.get("required"))}


def scan_models():
    """Усі моделі з addons/: поля збираємо з усіх класів, де модель згадана."""
    found = {}
    for module in sorted(os.listdir(ADDONS)):
        if not os.path.isdir(os.path.join(ADDONS, module)):
            continue
        ours = bool(OURS.match(module))
        for path in files_of(module, (".py",)):
            if os.sep + "migrations" + os.sep in path:
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
            except SyntaxError as error:
                check(f"{os.path.relpath(path, ADDONS)}: файл читається", False, str(error))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                name = inherit = None
                fields = {}
                for statement in node.body:
                    if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                            and isinstance(statement.targets[0], ast.Name)):
                        continue
                    target = statement.targets[0].id
                    if target in ("_name", "_inherit"):
                        try:
                            value = ast.literal_eval(statement.value)
                        except Exception:
                            value = None
                        if target == "_name":
                            name = value
                        else:
                            inherit = value
                    else:
                        info = field_call(statement.value)
                        if info:
                            fields[target] = info
                bases = [ast.unparse(base) for base in node.bases]
                kind = "Model"
                if any("TransientModel" in base for base in bases):
                    kind = "Transient"
                if any("AbstractModel" in base for base in bases):
                    kind = "Abstract"
                parents = [inherit] if isinstance(inherit, str) else list(inherit or [])
                # Клас без _name тільки доповнює перелічені в _inherit моделі.
                for key in ([name] if isinstance(name, str) else parents):
                    if not isinstance(key, str):
                        continue
                    entry = found.setdefault(key, {"fields": {}, "inherit": set(), "modules": set(),
                                                   "kind": "Model", "own": False, "ours": False})
                    entry["fields"].update(fields)
                    entry["modules"].add(module)
                    if name == key:
                        entry["own"] = True
                        entry["ours"] = entry["ours"] or ours
                        entry["kind"] = kind
                        entry["inherit"].update(p for p in parents if p != key)
    return found


MODELS = scan_models()


def company_path(name, seen=None):
    """Яким шляхом модель дістає компанію: own / base / parent, або None."""
    seen = seen if seen is not None else set()
    if name in seen:
        return None
    seen.add(name)
    if name in COMPANY_BOUND:
        return "base"
    entry = MODELS.get(name)
    if not entry:
        return None
    if "company_id" in entry["fields"]:
        return "own"
    for parent in sorted(entry["inherit"]):
        if company_path(parent, seen):
            return "base"
    for field, info in sorted(entry["fields"].items()):
        if info["type"] == "Many2one" and info["required"] and info["comodel"]:
            if company_path(info["comodel"], seen):
                return "parent"
    return None


counts = {"own": 0, "base": 0, "parent": 0, "shared": 0, "exempt": 0}
checked = []
for name in sorted(MODELS):
    entry = MODELS[name]
    if not (entry["own"] and entry["ours"]):
        continue          # розширення чужої моделі або чужий модуль
    if name in entry["inherit"]:
        continue
    if entry["kind"] != "Model":
        counts["exempt"] += 1
        continue
    checked.append(name)
    if name in SHARED:
        counts["shared"] += 1
        # Довідник, який раптом завів компанію, - це вже не довідник: або поле зайве,
        # або запис треба прибрати зі SHARED. Мовчки такого не лишаємо.
        check(f"{name}: спільний довідник без company_id",
              "company_id" not in entry["fields"], SHARED[name])
        continue
    path = company_path(name)
    if path:
        counts[path] += 1
        continue
    check(f"{name}: знає свою компанію", False,
          f'{sorted(entry["modules"])[0]}: немає company_id, немає обов\'язкового батька '
          f"з компанією і немає рядка в SHARED")

stale = sorted(set(SHARED) - set(checked))
check("перелік SHARED без застарілих записів", not stale, ", ".join(stale))
print(f"[..] моделей перевірено: {len(checked)} - власне company_id {counts['own']}, "
      f"через предка {counts['base']}, через батька {counts['parent']}, "
      f"спільних {counts['shared']}; абстрактних і тимчасових пропущено {counts['exempt']}")

if errors:
    print(f"\nПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    for label in errors:
        print(f"  - {label}")
    sys.exit(1)
print(f"\nУсі перевірки пройдено ({total} з {total}).")
