#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показова база: заповнює списки ТОВ «Ясен Меблі», які після demo_business.py порожні.

Що додає (усе - кнопками і публічними методами самих модулів, без зовнішніх служб):
  1. Зарплата / Місяці: закриває пакет листків серпня 2026 і, якщо банк серпня звірено, сам місяць;
     вересень лишається в роботі.
  2. Заява-розрахунок ПФУ за серпень (повний цикл) і чернетка за вересень, якщо є що заявляти.
  3. Анкета компанії: заповнена і затверджена, підтверджені відповіді застосовано.
  4. Коди професій ДК 003:2010, які справді стоять у штатному розписі і картках.
  5. Перевірка документів на 2026-09-30.
  6. KYC: три справи постачальників на різних етапах, перевірки внесено вручну.
  7. Вхідні рахунки: три записи в різних станах, значення внесено вручну (без AI і ЄДР).
  8. Виробництво: чотири робочі центри, операції на трьох специфікаціях, одне замовлення в роботі.
  9. Аналітичний план «Підрозділи» з чотирма рахунками.
 10. Два списання матеріалів 2026-09-30 (Дт 947 / Кт 201).

Ідемпотентно: кожен запис шукається за стійким ключем (origin, код, пара «компанія - дата»).
Сервер не перезапускає і код модулів не чіпає - лише JSON-RPC.

Запуск: DEMO_DB=show ODOO_URL=http://127.0.0.1:8133 python3 scripts/demo_show.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8133").rstrip("/")
DB = os.environ.get("DEMO_DB", "show").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
CO_ID = 1          # ТОВ «Ясен Меблі»
CTX = {"allowed_company_ids": [CO_ID]}
SHOW_DAY = "2026-09-30"

_opener = urllib.request.build_opener()
_opener.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36")]
urllib.request.install_opener(_opener)


class RpcError(Exception):
    pass


def rpc(service, method, *args):
    req = urllib.request.Request(
        URL + "/jsonrpc",
        json.dumps({"jsonrpc": "2.0", "method": "call",
                    "params": {"service": service, "method": method, "args": args},
                    "id": 1}).encode(),
        {"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=600).read())
    if "error" in d:
        msg = d["error"].get("data", {}).get("message") or d["error"].get("message")
        raise RpcError(str(msg)[:3000])
    return d.get("result")


UID = rpc("common", "login", DB, "admin", PW)
if not UID:
    sys.exit("Не вдалося увійти в базу %s на %s" % (DB, URL))


def call(model, method, *a, **kw):
    """Виклик від імені компанії «Ясен Меблі»: контекст компанії додається завжди."""
    kw["context"] = dict(CTX, **(kw.get("context") or {}))
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(a), kw)


def say(msg):
    print(msg, flush=True)


def upsert(model, domain, vals):
    ids = call(model, "search", domain)
    if ids:
        call(model, "write", [ids[0]], vals)
        return ids[0]
    return call(model, "create", vals)


def first_id(value):
    """Метод, що повертає запис, по RPC віддає id або список id."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else False
    return value


def iban_ua(mfo, acc19):
    bban = f"{mfo}{acc19}"
    num = "".join(str(int(ch, 36)) for ch in bban + "UA00")
    return f"UA{98 - int(num) % 97:02d}{bban}"


def partner(ref):
    rows = call("res.partner", "search_read", [["ref", "=", ref]],
                fields=["name", "company_registry", "vat", "street", "city", "is_company", "bank_ids"])
    if not rows:
        raise RpcError("Немає контрагента %s - спершу scripts/demo_business.py" % ref)
    return rows[0]


def product(code):
    ids = call("product.product", "search", [["default_code", "=", code]])
    if not ids:
        raise RpcError("Немає товару %s - спершу scripts/demo_business.py" % code)
    return ids[0]


# =====================================================================================
# 1. Зарплата / Місяці: серпень закрито, вересень у роботі
# =====================================================================================
def payroll_months():
    """demo_company.py закриває лише липень: і пакет листків, і місяць. Серпневі листки
    він проводить, але пакет серпня лишає чернеткою, а закриття серпня не кличе зовсім.
    Тут доводимо серпень тим самим шляхом, яким будівник закрив липень."""
    out = []
    run = call("hr.payslip.run", "search_read",
               [["company_id", "=", CO_ID], ["date_start", "=", "2026-08-01"]], fields=["name", "state"])
    if run and run[0]["state"] != "close":
        not_done = call("hr.payslip", "search_count",
                        [["payslip_run_id", "=", run[0]["id"]], ["state", "not in", ["done", "cancel"]]])
        if not_done:
            out.append(f"пакет серпня не закрито: непроведених листків {not_done}")
        else:
            call("hr.payslip.run", "close_payslip_run", [run[0]["id"]])
            out.append("пакет листків серпня закрито")
    dom = [["company_id", "=", CO_ID], ["year", "=", 2026], ["month", "=", 8], ["kind", "=", "month"]]
    closed = call("ua.period.close", "search", dom + [["state", "=", "closed"]])
    lock = call("res.company", "read", [CO_ID], ["fiscalyear_lock_date"])[0]["fiscalyear_lock_date"]
    if closed and (not lock or lock < "2026-08-31"):
        # Запис «закрито» є, а дата блокування відстала: перезапуск demo_company.py відкриває
        # липень і скидає дату на попередній закритий період. Проходимо закриття ще раз.
        call("ua.period.close", "write", closed, {"reopen_reason": "Дата блокування відстала після перезбирання демо"})
        call("ua.period.close", "action_reopen", closed)
        closed = []
    if closed:
        out.append("серпень уже закрито")
    else:
        # Перевірка, якої blockers() не знає: нативний Odoo не дає поставити дату блокування,
        # поки в періоді є незвірені рядки банківської виписки. Дивимося її першою, щоб не
        # приймати журнал змін заради закриття, яке все одно не відбудеться.
        unreconciled = call("account.bank.statement.line", "search_read",
                            [["company_id", "=", CO_ID], ["is_reconciled", "=", False], ["date", "<=", "2026-08-31"],
                             ["date", ">", lock or "1900-01-01"]], fields=["date", "amount"], order="date")
        reasons = call("ua.period.close", "blockers", CO_ID, 2026, 8)
        if unreconciled:
            out.append("серпень НЕ закрито: незвірених рядків банківської виписки в періоді "
                       f"{len(unreconciled)} (" + ", ".join(f"{u['date']} {u['amount']:,.2f}" for u in unreconciled)
                       + ") - це нативна перевірка дати блокування"
                       + ("; ще перешкоди модуля: " + "; ".join(reasons) if reasons else ""))
        else:
            if any("непереглянутих змін" in r for r in reasons):
                n = call("ua.change.log", "accept_period", 2026, 8)
                out.append(f"прийнято змін журналу за серпень: {n}")
                reasons = call("ua.period.close", "blockers", CO_ID, 2026, 8)
            if reasons:
                out.append("серпень НЕ закрито, перешкоди: " + "; ".join(reasons))
            else:
                try:
                    call("ua.period.close", "close_period", 2026, 8, False)
                    out.append("серпень закрито, дата блокування 2026-08-31")
                except RpcError as e:
                    out.append("серпень НЕ закрито: " + str(e).splitlines()[0][:200])
    if not call("ua.period.close", "search", dom):
        call("ua.period.close", "ensure_for", CO_ID, 2026, 8)   # картка серпня у списку «Місяці»
    # Вересень: місяць у роботі, листки пораховані. Чернетку без рядків рахуємо, готові не чіпаємо.
    slips = call("hr.payslip", "search_read",
                 [["company_id", "=", CO_ID], ["date_from", ">=", "2026-09-01"], ["date_from", "<=", "2026-09-30"],
                  ["state", "!=", "cancel"]], fields=["state", "line_ids"])
    empty = [s["id"] for s in slips if not s["line_ids"] and s["state"] in ("draft", "verify")]
    for sid in empty:
        call("hr.payslip", "compute_sheet", [sid])
    sep = call("ua.period.close", "search_read",
               [["company_id", "=", CO_ID], ["year", "=", 2026], ["month", "=", 9], ["kind", "=", "month"]],
               fields=["state"])
    if not sep:
        call("ua.period.close", "ensure_for", CO_ID, 2026, 9)
        sep = [{"state": "open"}]
    out.append(f"вересень: {sep[0]['state']}, листків {len(slips)}, з них пораховано щойно {len(empty)}")
    say("1. Місяці: " + "; ".join(out) + ".")


# =====================================================================================
# 2. Заяви-розрахунки ПФУ
# =====================================================================================
# Дати циклу фінансування: дії модуля ставлять «сьогодні», а серпневу заяву подавали у вересні.
PFU_AUG = {"date": "2026-09-02", "submitted_date": "2026-09-02", "accepted_date": "2026-09-04",
           "funded_date": "2026-09-09", "paid_date": "2026-09-10", "notice_date": "2026-09-11"}


def pfu_claims():
    out = []
    run = call("hr.payslip.run", "search", [["company_id", "=", CO_ID], ["date_start", "=", "2026-08-01"]])
    if run:
        ids = call("ua.pfu.claim", "search", [["payslip_run_id", "=", run[0]]])
        if not ids:
            ids = [call("hr.payslip.run", "action_ua_pfu_claim", [run[0]])["res_id"]]
        claim = ids[0]
        steps = [("draft", "action_confirm"), ("confirmed", "action_submit"), ("submitted", "action_accept"),
                 ("accepted", "action_register_funding"), ("funded", "action_register_payment"),
                 ("paid", "action_notice_sent"), ("notified", "action_done")]
        for state, method in steps:
            if call("ua.pfu.claim", "read", [claim], ["state"])[0]["state"] == state:
                call("ua.pfu.claim", method, [claim])
        call("ua.pfu.claim", "write", [claim], PFU_AUG)
        r = call("ua.pfu.claim", "read", [claim], ["name", "state", "total", "line_ids", "unfunded", "to_pay"])[0]
        out.append(f"серпень - {r['state']}, рядків {len(r['line_ids'])}, разом {r['total']:,.2f}, "
                   f"не профінансовано {r['unfunded']:,.2f}")
    run = call("hr.payslip.run", "search", [["company_id", "=", CO_ID], ["date_start", "=", "2026-09-01"]])
    if run:
        ids = call("ua.pfu.claim", "search", [["payslip_run_id", "=", run[0]]])
        if not ids:
            ids = [call("hr.payslip.run", "action_ua_pfu_claim", [run[0]])["res_id"]]
        r = call("ua.pfu.claim", "read", ids[:1], ["state", "total", "line_ids"])[0]
        if not r["line_ids"] and r["state"] == "draft":
            # у вересневих листках немає сум за рахунок ПФУ - порожню чернетку не лишаємо
            call("ua.pfu.claim", "unlink", ids[:1])
            out.append("вересень - заявляти нічого, порожню чернетку прибрано")
        else:
            out.append(f"вересень - {r['state']}, рядків {len(r['line_ids'])}, разом {r['total']:,.2f}")
    say("2. Заяви-розрахунки ПФУ: " + "; ".join(out) + ".")


# =====================================================================================
# 3. Анкета компанії
# =====================================================================================
PROFILE_TEXT = ("Діюче українське ТОВ, виробництво меблів у Львові, є історія обліку. 23 працівники, "
                "більшість на окладі у штаті, є договори ЦПХ і один підрядник ФОП, двоє на неповній ставці. "
                "Індексацію ведемо. Зарплата через кілька банків. Розрахунки з покупцями в гривні, є експорт у Польщу.")
# код питання -> відповідь бухгалтера. Питання про ІТ-послуги і Дія.City лишаються без відповіді:
# до меблевого виробництва вони не стосуються.
ANSWERS = {
    "q003": "20.01.2015",
    "q005": "ТОВ",
    "q006": "2",
    "q007": "Повністю",
    "q008": "Немає",
    "q009": "Діюча, є історія обліку",
    "q010": "Загальна система, 18% на прибуток",
    "q011": "Так: ІПН 438120726558",
    "q012": "Понад ліміт 3 групи - тому загальна система",
    "q013": "І ті, і ті: переважно Україна, є покупець у Польщі",
    "q014": "Польща",
    "q015": "UAH, EUR",
    "q016": "Банк",
    "q018": "Акти, Видаткові накладні, Податкові накладні",
    "q019": "Так",
    "q020": "Бухгалтер",
    "q021": "Гривневі: 2 (поточний і еквайринг)",
    "q022": "Гаврилюк Богдан Тарасович, директор",
    "q023": "Є",
    "q024": "Є",
    "q025": "Система автоматично",
    "q026": "16-50",
    "q027": "Штат (трудовий договір), ЦПХ (цивільно-правовий), ФОП (аутстаф)",
    "q028": "Ні",
    "q030": "Так: 1",
    "q031": "Ні",
    "q034": "Є нижчі (неповна ставка)",
    "q035": "Так",
    "q036": "Так",
    "q037": "Вже бронюємо",
    "q039": "Мельник Ірина Володимирівна, менеджерка з персоналу",
    "q045": "Штатний бухгалтер",
    "q046": "Ні",
    "q049": "18% на прибуток",
    "q050": "Є, передамо",
    "q051": "Немає",
    "q052": "Є",
    "q053": "Цього року",
    "q056": "Мельник Ірина Володимирівна, менеджерка з персоналу",
    "q057": "Данилюк Олег Ігорович, юрисконсульт",
    "q058": "Запуск обліку",
    "q059": "Ні",
    "q060": "Ні",
    "q061": "Ні",
    "q062": "Через кілька банків залежно від того, де в працівників картки",
    "q063": "Кушнір Галина Романівна, бухгалтер",
}


def setup_profile():
    ids = call("ua.setup.profile", "search", [["company_id", "=", CO_ID]])
    if not ids:
        ids = [call("ua.setup.profile", "create", {"company_id": CO_ID, "description": PROFILE_TEXT})]
    pid = ids[0]
    state = call("ua.setup.profile", "read", [pid], ["state"])[0]["state"]
    if state != "active":
        call("ua.setup.profile", "action_fill", [pid])
        call("ua.setup.profile", "write", [pid], {"description": PROFILE_TEXT})
        call("ua.setup.profile", "action_propose", [pid])
        answers = call("ua.setup.answer", "search_read", [["profile_id", "=", pid]],
                       fields=["question_id", "value", "state"])
        codes = {q["id"]: q["code"] for q in call("ua.setup.question", "search_read", [], fields=["code"])}
        for a in answers:
            value = ANSWERS.get(codes.get(a["question_id"][0]))
            if value and a["state"] != "supplied":
                call("ua.setup.answer", "write", [a["id"]], {"value": value, "source": "accountant"})
                call("ua.setup.answer", "action_confirm", [a["id"]])
        call("ua.setup.profile", "action_ready", [pid])
        call("ua.setup.profile", "action_activate", [pid])
    applied = 0
    rows = call("ua.setup.profile", "preview_apply", [pid])
    if rows:
        call("ua.setup.profile", "action_apply", [pid])
        applied = len(rows)
    r = call("ua.setup.profile", "read", [pid],
             ["state", "total_count", "confirmed_count", "missing_count", "required_missing"])[0]
    say(f"3. Анкета компанії: {r['state']}, питань {r['total_count']}, підтверджено {r['confirmed_count']}, "
        f"без відповіді {r['missing_count']} (обов'язкових {r['required_missing']}), "
        f"застосовано налаштувань цього прогону {applied}.")


# =====================================================================================
# 4. Коди професій (ДК 003:2010)
# =====================================================================================
# Код -> назва класифікаційного угруповання. Записано вручну з класифікатора і НЕ звірено
# зі службою profkod (позначка «Звірено зі службою» лишається знятою): звірку робить
# кнопка довідника, вона ходить у мережу. Коди - ті, що вже стоять у розписі і картках.
KP_SOURCE = "ДК 003:2010"
KP_CODES = {
    "1210.1": "Керівники підприємств, установ та організацій",
    "1231": "Керівники фінансових, бухгалтерських, економічних, юридичних та адміністративних підрозділів та інші керівники",
    "1233": "Керівники підрозділів маркетингу",
    "1475.4": "Менеджери (управителі) з питань комерційної діяльності та управління",
    "1477.1": "Менеджери (управителі) з підбору, забезпечення та використання персоналу",
    "2149.2": "Інженери (інші галузі інженерної справи)",
    "2419.2": "Професіонали у сфері державної служби, маркетингу, ефективності господарської діяльності, "
              "раціоналізації виробництва та інтелектуальної власності",
    "2429": "Інші професіонали в галузі правознавства",
    "3118": "Креслярі",
    "3433": "Бухгалтери та касири-експерти",
    "3471": "Декоратори та комерційні дизайнери",
    "4131": "Службовці на складах",
    "7422": "Столяри-червонодеревники та робітники споріднених професій",
    "7423": "Наладчики деревообробних верстатів, верстатники та робітники споріднених професій",
    "8322": "Водії легкових автомобілів, таксі та автофургонів",
    "9132": "Прибиральники в установах, готелях та інших закладах",
    "9322": "Ручні пакувальники та інші некваліфіковані робітники промисловості",
}


def kp_codes():
    from_lists = call("ua.kp.code", "sync_from_documents")
    used = {v["ua_kp_code"] for v in call("hr.version", "search_read",
                                          [["company_id", "=", CO_ID], ["ua_kp_code", "!=", False]],
                                          fields=["ua_kp_code"])}
    used |= {l["kp_code"] for l in call("ua.staff.list.line", "search_read",
                                        [["list_id.company_id", "=", CO_ID], ["kp_code", "!=", False]],
                                        fields=["kp_code"])}
    unknown = sorted(used - set(KP_CODES))
    for code in sorted(used | set(KP_CODES)):
        call("ua.kp.code", "ensure", code, KP_CODES.get(code), KP_SOURCE)
    by_code = {r["code"]: r["id"] for r in call("ua.kp.code", "search_read", [], fields=["code"])}
    # Рядки розпису отримують посилання на довідник; сам код і назва в рядку не змінюються.
    linked, failed = 0, ""
    for line in call("ua.staff.list.line", "search_read",
                     [["list_id.company_id", "=", CO_ID], ["kp_code", "!=", False], ["kp_id", "=", False]],
                     fields=["kp_code"]):
        if line["kp_code"].strip() not in by_code:
            continue
        try:
            call("ua.staff.list.line", "write", [line["id"]], {"kp_id": by_code[line["kp_code"].strip()]})
            linked += 1
        except RpcError as e:
            failed = str(e)[:160]
            break
    say(f"4. Коди професій: у довіднику {len(by_code)}, з розписів узято {from_lists}, "
        f"рядків розпису прив'язано {linked}"
        + (f", прив'язка відмовила: {failed}" if failed else "")
        + (f", без назви угруповання: {', '.join(unknown)}" if unknown else "") + ".")


# =====================================================================================
# 5. Перевірка документів
# =====================================================================================
def doc_check():
    ids = call("ua.hr.doc.check", "search", [["company_id", "=", CO_ID], ["date", "=", SHOW_DAY]])
    if not ids:
        ids = [first_id(call("ua.hr.doc.check", "ua_compose", CO_ID, date=SHOW_DAY))]
    cid = ids[0]
    if call("ua.hr.doc.check", "read", [cid], ["state"])[0]["state"] == "draft":
        call("ua.hr.doc.check", "write", [cid], {"note": "Квартальна перевірка особових справ перед закриттям вересня."})
        call("ua.hr.doc.check", "action_confirm", [cid])
    r = call("ua.hr.doc.check", "read", [cid], ["name", "state", "employee_count", "missing_count", "line_ids"])[0]
    say(f"5. {r['name']}: {r['state']}, працівників {r['employee_count']}, рядків {len(r['line_ids'])}, "
        f"бракує документів {r['missing_count']}.")


# =====================================================================================
# 6. KYC: справи і перевірки
# =====================================================================================
# Скринінг ЄДР, судові рішення і рішення по справі ходять у міст інтеграцій (bp.bridge), тому
# тут лише те, що аналітик робить руками: картка, чеклист, ручні перевірки, «Наступний етап».
# (ref постачальника, етап, значення картки, ручні перевірки)
KYC_CASES = [
    ("DEMO-S02", "assess", {
        "kind": "company", "role": "Постачальник плитних матеріалів (ДСП, МДФ)",
        "introduced_by": "Крамар Володимир Зіновійович, комерційний директор", "risk": "low",
        "registry_status": "зареєстровано", "registry_kved": "46.73 Оптова торгівля деревиною, будівельними матеріалами",
        "check_registry": True, "check_ubo": True, "check_sanctions": True, "check_courts": True, "check_docs": True,
        "summary": "Працюємо з 2024 року, три поставки за квартал оплачено без затримок. Витяг з ЄДР і довідку "
                   "про відсутність боргу отримано. Маркерів немає, лишилося рішення.",
    }, [
        ("registry", "info", "Витяг з ЄДР від постачальника", "Стан: зареєстровано. Керівник і засновники збігаються з договором."),
        ("sanctions", "info", "Санкційні списки РНБО", "Збігів за назвою і кодом не знайдено, перевірено вручну 2026-09-22."),
        ("tax_debt", "info", "Довідка про відсутність податкового боргу", "Надана постачальником, дата довідки 2026-09-15."),
    ]),
    ("DEMO-S04", "screen", {
        "kind": "company", "role": "Постачальник оббивних тканин",
        "introduced_by": "Прокопів Наталія Богданівна, інженер-технолог", "risk": "medium",
        "registry_status": "зареєстровано", "registry_kved": "46.41 Оптова торгівля текстильними товарами",
        "check_registry": True, "check_sanctions": True,
        "summary": "Реквізити збігаються з договором. Чекаємо статутні документи і пояснення щодо зміни керівника.",
    }, [
        ("registry", "info", "Витяг з ЄДР від постачальника", "Стан: зареєстровано."),
        ("head_change", "warn", "Зміна керівника у 2026 році", "У договорі 2025 року підписант інший. Запитано наказ про призначення."),
    ]),
    ("DEMO-S09", "collect", {
        "kind": "fop", "role": "Підрядник: ремонт і налагодження верстатів",
        "introduced_by": "Мельничук Андрій Петрович, столяр",
        "summary": "Запитано виписку з ЄДР, КВЕДи і довідку про систему оподаткування.",
    }, []),
]
KYC_STAGES = ["new", "collect", "screen", "assess", "done"]


def kyc_cases():
    made, stages = 0, []
    for ref, stage, vals, screenings in KYC_CASES:
        p = partner(ref)
        ids = call("kyc.case", "search", [["partner_id", "=", p["id"]], ["active", "in", [True, False]]])
        if not ids:
            card = dict(vals, partner_id=p["id"], code=p["company_registry"] or "", company_id=CO_ID,
                        subject_group="counterparty", registry_name=p["name"],
                        registry_address=", ".join(x for x in (p["city"], p["street"]) if x))
            ids = [call("kyc.case", "create", card)]
            made += 1
            for key, severity, title, detail in screenings:
                call("kyc.screening", "create", {"case_id": ids[0], "source": "manual", "key": key,
                                                 "severity": severity, "title": title, "detail": detail})
        case = ids[0]
        # до потрібного етапу - кнопкою «Наступний етап», по одному кроку
        for _ in KYC_STAGES:
            now = call("kyc.case", "read", [case], ["stage"])[0]["stage"]
            if KYC_STAGES.index(now) >= KYC_STAGES.index(stage):
                break
            call("kyc.case", "action_stage", [case])
        r = call("kyc.case", "read", [case], ["name", "stage"])[0]
        stages.append(f"{r['name']} {p['name']} - {r['stage']}")
    say(f"6. KYC: справ {len(KYC_CASES)} (нових {made}), перевірок "
        f"{call('kyc.screening', 'search_count', [['case_id.company_id', '=', CO_ID]])}: " + "; ".join(stages) + ".")


# =====================================================================================
# 7. Вхідні рахунки постачальників
# =====================================================================================
# Розбір листа (bp.ai) і запит ЄДР (міст) тут не викликаються: поля і перевірки внесено вручну
# тими самими ключами і словами, якими їх пише сам модуль. Рахунок-чернетку складає кнопка модуля.
REGISTRY_NOTE = ("registry", "ЄДР", "warn", "не запитано: запис внесено вручну, міст інтеграцій не викликався")


def _intake(ref, number, vals, lines, checks):
    p = partner(ref)
    ids = call("bp.purchase.intake", "search", [["number", "=", number], ["supplier_code", "=", p["company_registry"]]])
    if ids:
        return ids[0], p, False
    untaxed = round(sum(q * price for _n, q, _u, price in lines), 2)
    tax = round(untaxed * 0.2, 2)
    iban = vals.pop("supplier_iban", None)
    if not iban and p["bank_ids"]:
        iban = call("res.partner.bank", "read", p["bank_ids"][:1], ["acc_number"])[0]["acc_number"].replace(" ", "")
    card = dict({
        "company_id": CO_ID, "partner_id": p["id"], "number": number, "currency_name": "UAH",
        "supplier_name": p["name"], "supplier_code": p["company_registry"], "supplier_ipn": p["vat"] or False,
        "supplier_iban": iban, "supplier_bank": "АТ КБ «ПриватБанк»",
        "supplier_address": ", ".join(x for x in (p["city"], p["street"]) if x),
        "buyer_name": "ТОВ «Ясен Меблі»", "buyer_code": "43812071",
        "prices_include_vat": False, "amount_untaxed": untaxed, "vat_rate": 20.0, "amount_tax": tax,
        "amount_total": round(untaxed + tax, 2),
        "line_ids": [(0, 0, {"sequence": i, "name": n, "quantity": q, "uom_name": u, "price_unit": price,
                             "amount": round(q * price, 2)}) for i, (n, q, u, price) in enumerate(lines, 1)],
        "check_ids": [(0, 0, {"key": k, "name": n, "level": lvl, "detail": d}) for k, n, lvl, d in [
            ("code", "Код постачальника", "ok", f"{p['company_registry']}: контрольна сума збігається"),
            ("lines", "Сума позицій", "ok", f"{untaxed:.2f} без ПДВ"),
            ("vat", "ПДВ", "ok", f"20%: {tax:.2f}"),
            ("total", "Всього", "ok", f"{untaxed + tax:.2f}"),
            ("buyer", "Покупець", "ok", "ТОВ «Ясен Меблі»"),
            ("partner", "Картка постачальника", "ok", f"знайдено: {p['name']}; статус: без статусу"),
        ] + checks + [REGISTRY_NOTE]],
    }, **vals)
    return call("bp.purchase.intake", "create", card), p, True


def purchase_intake():
    made = 0
    # 1) Усе збіглося: кнопка «Створити рахунок» складає чернетку рахунку постачальника.
    rid, p, new = _intake("DEMO-S03", "ФС-1047", {
        "state": "new", "doc_type": "invoice", "date": "2026-10-02", "due_date": "2026-10-16",
        "contract": "Договір поставки № 14/2025 від 2025-03-03",
        "email_from": "ТОВ «Фурнітура Сервіс» <demo-s03@example.ua>", "email_subject": "Рахунок ФС-1047 на фурнітуру",
        "received_at": "2026-10-02 08:41:00",
    }, [("Петля меблева накладна", 200, "шт", 28.0), ("Напрямні кулькові 450 мм", 40, "компл.", 165.0)],
        [("iban", "IBAN", "ok", "контрольна сума збігається"),
         ("iban_known", "IBAN у картці", "ok", "рахунок уже є в картці постачальника")])
    made += new
    if not call("bp.purchase.intake", "read", [rid], ["move_id"])[0]["move_id"]:
        call("bp.purchase.intake", "action_create_bill", [rid])
    # 2) Потребує перевірки: у документі інший IBAN, ніж у картці постачальника.
    other_iban = iban_ua("300335", "0000026004555000123")
    rid, p, new = _intake("DEMO-S05", "318", {
        "state": "review", "doc_type": "invoice", "date": "2026-10-05", "due_date": "2026-10-12",
        "supplier_iban": other_iban, "supplier_bank": "АТ «Райффайзен Банк»",
        "email_from": "ТОВ «Лаки і фарби Україна» <demo-s05@example.ua>", "email_subject": "Рахунок 318 від 05.10.2026",
        "received_at": "2026-10-05 14:07:00",
    }, [("Лак поліуретановий", 60, "л", 420.0), ("Морилка на водній основі", 40, "л", 260.0)],
        [("iban", "IBAN", "ok", f"{other_iban}: контрольна сума збігається"),
         ("iban_known", "IBAN у картці", "error",
          "у картці постачальника інший рахунок: підтвердьте новий IBAN дзвінком постачальнику")])
    made += new
    # 3) Дублікат: накладну, вже проведену рахунком у вересні, надіслали вдруге.
    bill = call("account.move", "search_read",
                [["company_id", "=", CO_ID], ["move_type", "=", "in_invoice"], ["state", "=", "posted"],
                 ["partner_id.ref", "=", "DEMO-S02"], ["invoice_date", ">=", "2026-09-01"]],
                fields=["name", "ref", "invoice_date", "invoice_line_ids"], order="invoice_date", limit=1)
    if bill:
        rows = call("account.move.line", "read", bill[0]["invoice_line_ids"], ["name", "quantity", "price_unit", "display_type"])
        lines = [(r["name"], r["quantity"], "шт", r["price_unit"]) for r in rows if r["display_type"] == "product"]
        rid, p, new = _intake("DEMO-S02", bill[0]["ref"], {
            "state": "duplicate", "doc_type": "waybill", "date": bill[0]["invoice_date"],
            "email_from": "ТОВ «Плита-Захід» <demo-s02@example.ua>", "email_subject": "Повторно: накладна і рахунок",
            "received_at": "2026-10-06 10:15:00",
        }, lines, [("iban", "IBAN", "ok", "контрольна сума збігається"),
                   ("iban_known", "IBAN у картці", "ok", "рахунок уже є в картці постачальника"),
                   ("duplicate", "Дублікат", "error",
                    f"документ № {bill[0]['ref']} уже зареєстровано: рахунок {bill[0]['name']}")])
        made += new
    states = call("bp.purchase.intake", "search_read", [["company_id", "=", CO_ID]],
                  fields=["name", "state", "amount_total", "move_id"], order="id")
    say(f"7. Вхідні рахунки: {len(states)} (нових {made}): "
        + "; ".join(f"{s['name']} - {s['state']}, {s['amount_total']:,.2f}"
                    + (f", чернетка рахунку id {s['move_id'][0]}" if s["move_id"] else "") for s in states) + ".")


# =====================================================================================
# 8. Виробництво: робочі центри, операції, наряди
# =====================================================================================
# (код, назва, вартість години)
WORKCENTERS = [("ЯМ-РОЗКР", "Розкрій", 220.0), ("ЯМ-КРАЙК", "Крайкування", 200.0),
               ("ЯМ-СКЛАД", "Складання", 190.0), ("ЯМ-ПАК", "Пакування", 140.0)]
# (операція, код центру, кроки, перевірка)
OPERATIONS = [
    ("Розкрій плит", "ЯМ-РОЗКР", "Звірити карту розкрою\nРозкроїти плити на форматно-розкрійному верстаті\nПромаркувати деталі",
     "Розміри деталей за картою розкрою\nВідсутність сколів ламінату"),
    ("Крайкування деталей", "ЯМ-КРАЙК", "Наклеїти кромку ПВХ 2 мм\nЗняти звиси і відполірувати торці",
     "Кромка без відшарувань\nКолір кромки відповідає плиті"),
    ("Складання виробу", "ЯМ-СКЛАД", "Присадка отворів\nЗібрати корпус на конфірмати\nВстановити фурнітуру",
     "Діагоналі корпусу\nХід шухляд і дверцят"),
    ("Пакування", "ЯМ-ПАК", "Захистити кути\nУпакувати в гофрокартон\nНаклеїти етикетку",
     "Комплектність фурнітури\nЕтикетка відповідає замовленню"),
]
# код виробу -> хвилини на одиницю по чотирьох операціях
BOM_TIMES = {"F02": (20, 15, 35, 8), "F06": (35, 30, 55, 12), "F07": (30, 25, 50, 10)}
SHOW_MO = ("ВЗ-2026-11", "F02", 6)


def manufacturing():
    WC = {}
    for code, name, cost in WORKCENTERS:
        WC[code] = upsert("mrp.workcenter", [["code", "=", code], ["company_id", "=", CO_ID]],
                          {"name": name, "code": code, "company_id": CO_ID, "time_efficiency": 100.0, "costs_hour": cost})
    boms = {}
    for code, minutes in BOM_TIMES.items():
        tmpl = call("product.product", "read", [product(code)], ["product_tmpl_id"])[0]["product_tmpl_id"][0]
        bom = call("mrp.bom", "search", [["product_tmpl_id", "=", tmpl], ["company_id", "=", CO_ID]])[0]
        boms[code] = bom
        for seq, ((op, wc, steps, checks), mins) in enumerate(zip(OPERATIONS, minutes), start=1):
            upsert("mrp.routing.workcenter", [["bom_id", "=", bom], ["name", "=", op]],
                   {"name": op, "workcenter_id": WC[wc], "bom_id": bom, "sequence": seq * 10, "time_mode": "manual",
                    "time_cycle_manual": mins, "company_id": CO_ID, "ua_steps": steps, "ua_checks": checks})
    origin, code, qty = SHOW_MO
    ids = call("mrp.production", "search", [["origin", "=", origin], ["company_id", "=", CO_ID]])
    if not ids:
        ids = [call("mrp.production", "create", {
            "product_id": product(code), "product_qty": qty, "bom_id": boms[code], "origin": origin,
            "company_id": CO_ID, "date_start": SHOW_DAY + " 08:00:00"})]
    mo = ids[0]
    if call("mrp.production", "read", [mo], ["state"])[0]["state"] == "draft":
        call("mrp.production", "action_confirm", [mo])
        call("mrp.production", "action_assign", [mo])
    wos = call("mrp.workorder", "search_read", [["production_id", "=", mo]],
               fields=["name", "state", "duration_expected"], order="sequence, id")
    note = ""
    if len(wos) >= 2 and all(w["state"] not in ("progress", "done") for w in wos):
        # Перший наряд виконано, другий розпочато і поставлено на паузу: таймер не біжить,
        # замовлення лишається «в роботі». Час нарядів - день замовлення, а не день збірки демо.
        first, second = wos[0], wos[1]
        call("mrp.workorder", "button_start", [first["id"]])
        call("mrp.workorder", "button_finish", [first["id"]])
        call("mrp.workorder", "button_start", [second["id"]])
        call("mrp.workorder", "button_pending", [second["id"]])
        for wo, start, end in ((first, " 08:00:00", " 10:00:00"), (second, " 10:15:00", " 11:00:00")):
            times = call("mrp.workcenter.productivity", "search", [["workorder_id", "=", wo["id"]]])
            if times:
                call("mrp.workcenter.productivity", "write", times[:1],
                     {"date_start": SHOW_DAY + start, "date_end": SHOW_DAY + end})
        # button_start ставить нарядам і замовленню «зараз». force_date - нативний ключ: без нього
        # запис дати початку пробує зняти планування і впирається у вже виконаний наряд.
        force = {"force_date": True}
        try:
            call("mrp.workorder", "write", [first["id"]],
                 {"date_start": SHOW_DAY + " 08:00:00", "date_finished": SHOW_DAY + " 10:00:00"}, context=force)
            call("mrp.workorder", "write", [second["id"]], {"date_start": SHOW_DAY + " 10:15:00"}, context=force)
            call("mrp.production", "write", [mo], {"date_start": SHOW_DAY + " 08:00:00"}, context=force)
        except RpcError as e:
            note = f"; дати нарядів лишилися днем збірки: {str(e)[:120]}"
    r = call("mrp.production", "read", [mo], ["name", "state", "workorder_ids"])[0]
    wos = call("mrp.workorder", "read", r["workorder_ids"], ["name", "state", "duration"])
    say(f"8. Виробництво: робочих центрів {len(WC)}, операцій "
        f"{call('mrp.routing.workcenter', 'search_count', [['company_id', '=', CO_ID]])} на {len(boms)} специфікаціях; "
        f"{r['name']} ({origin}) - {r['state']}, наряди: "
        + ", ".join(f"{w['name']} {w['state']} {w['duration']:.0f} хв" for w in wos) + note + ".")


# =====================================================================================
# 9. Аналітичні рахунки
# =====================================================================================
ANALYTIC = [("П-01", "Виробництво"), ("П-02", "Склад і логістика"), ("П-03", "Продажі"), ("П-04", "Адміністрація")]


def analytic_accounts():
    plan = upsert("account.analytic.plan", [["name", "=", "Підрозділи"]], {"name": "Підрозділи"})
    for code, name in ANALYTIC:
        upsert("account.analytic.account", [["code", "=", code], ["company_id", "=", CO_ID]],
               {"name": name, "code": code, "plan_id": plan, "company_id": CO_ID})
    say(f"9. Аналітика: план «Підрозділи», рахунків "
        f"{call('account.analytic.account', 'search_count', [['plan_id', '=', plan], ['company_id', '=', CO_ID]])}; "
        f"старі проводки не перепроводилися.")


# =====================================================================================
# 10. Списання
# =====================================================================================
# (ключ, код товару, кількість, причина). Дата - день інвентаризації: брак знайшла комісія.
SCRAPS = [("СПИС-2026-01", "M19", 1.5, "Бій скла під час зберігання"),
          ("СПИС-2026-02", "M01", 2.0, "Пошкоджено навантажувачем")]


def scraps():
    lines = []
    for key, code, qty, reason in SCRAPS:
        pid = product(code)
        ids = call("stock.scrap", "search", [["origin", "=", key], ["company_id", "=", CO_ID]])
        if not ids:
            quant = call("stock.quant", "search_read",
                         [["product_id", "=", pid], ["company_id", "=", CO_ID], ["location_id.usage", "=", "internal"],
                          ["quantity", ">=", qty]], fields=["location_id"], order="quantity desc", limit=1)
            if not quant:
                lines.append(f"{key}: залишку {code} немає - пропущено")
                continue
            tag = upsert("stock.scrap.reason.tag", [["name", "=", reason]], {"name": reason})
            ids = [call("stock.scrap", "create", {
                "product_id": pid, "scrap_qty": qty, "location_id": quant[0]["location_id"][0],
                "origin": key, "company_id": CO_ID, "scrap_reason_tag_ids": [(6, 0, [tag])]})]
        sid = ids[0]
        if call("stock.scrap", "read", [sid], ["state"])[0]["state"] != "done":
            # force_period_date - дата проводки оцінки запасів (як у _validate_picking демо-бізнесу)
            res = call("stock.scrap", "action_validate", [sid], context={"force_period_date": SHOW_DAY})
            if isinstance(res, dict) and res.get("res_model"):
                lines.append(f"{key}: майстер {res['res_model']} - не проведено")
                continue
            when = SHOW_DAY + " 15:00:00"
            call("stock.scrap", "write", [sid], {"date_done": when})
            moves = call("stock.scrap", "read", [sid], ["move_ids"])[0]["move_ids"]
            call("stock.move", "write", moves, {"date": when})
            mls = call("stock.move.line", "search", [["move_id", "in", moves]])
            call("stock.move.line", "write", mls, {"date": when})
        r = call("stock.scrap", "read", [sid], ["name", "state", "move_ids", "date_done"])[0]
        entries = call("account.move.line", "search_read",
                       [["move_id.stock_move_ids", "in", r["move_ids"]]] if _has("account.move", "stock_move_ids")
                       else [["move_id.stock_move_id", "in", r["move_ids"]]],
                       fields=["date", "account_id", "debit", "credit", "parent_state"])
        text = ", ".join(f"{'Дт' if e['debit'] else 'Кт'} {e['account_id'][1].split(' ')[0]} "
                         f"{e['debit'] or e['credit']:,.2f} ({e['date']}, {e['parent_state']})" for e in entries)
        lines.append(f"{r['name']} ({key}) {code} x {qty:g} - {r['state']}, {str(r['date_done'])[:10]}: "
                     + (text or "проводок оцінки немає"))
    say("10. Списання: " + "; ".join(lines) + ".")


_FIELDS = {}


def _has(model, field):
    if model not in _FIELDS:
        _FIELDS[model] = set(call(model, "fields_get", [], attributes=["type"]))
    return field in _FIELDS[model]


# =====================================================================================
# Контроль
# =====================================================================================
COUNTS = [
    ("ua.period.close", [["company_id", "=", CO_ID]]),
    ("ua.pfu.claim", [["company_id", "=", CO_ID]]),
    ("ua.setup.profile", [["company_id", "=", CO_ID]]),
    ("ua.kp.code", []),
    ("ua.hr.doc.check", [["company_id", "=", CO_ID]]),
    ("kyc.case", [["company_id", "=", CO_ID]]),
    ("kyc.screening", [["case_id.company_id", "=", CO_ID]]),
    ("bp.purchase.intake", [["company_id", "=", CO_ID]]),
    ("mrp.workcenter", [["company_id", "=", CO_ID]]),
    ("mrp.routing.workcenter", [["company_id", "=", CO_ID]]),
    ("mrp.workorder", [["production_id.company_id", "=", CO_ID]]),
    ("account.analytic.account", [["company_id", "=", CO_ID]]),
    ("stock.scrap", [["company_id", "=", CO_ID]]),
    ("ua.vat.relief", []),
    ("ua.vat.compensation", [["company_id", "=", CO_ID]]),
]


def control():
    say("\nКонтроль (компанія «Ясен Меблі»):")
    for model, domain in COUNTS:
        say(f"  {model:28s} {call(model, 'search_count', domain)}")
    months = call("ua.period.close", "search_read", [["company_id", "=", CO_ID], ["kind", "=", "month"]],
                  fields=["name", "state"], order="year, month")
    say("  місяці: " + ", ".join(f"{m['name']} - {m['state']}" for m in months))
    tot = call("account.move.line", "read_group", [["company_id", "=", CO_ID], ["parent_state", "=", "posted"]],
               ["debit:sum", "credit:sum"], [])[0]
    diff = round(tot["debit"] - tot["credit"], 2)
    say(f"  проведені проводки: Дт {tot['debit']:,.2f}  Кт {tot['credit']:,.2f}  різниця {diff:,.2f}")
    return abs(diff) < 0.005


def main():
    say("== показова база %s на %s ==" % (DB, URL))
    errors = []
    # ПФУ - до закриття серпня: заява читає серпневі листки і відпустки.
    for step in (pfu_claims, payroll_months, setup_profile, kp_codes, doc_check, kyc_cases,
                 purchase_intake, manufacturing, analytic_accounts, scraps):
        try:
            step()
        except RpcError as e:
            errors.append(f"{step.__name__}: {str(e)[:600]}")
            say(f"ПОМИЛКА {step.__name__}: {str(e)[:600]}")
    balanced = control()
    if not balanced:
        errors.append("дебет не дорівнює кредиту")
    if errors:
        say("\nНе все пройшло: " + " | ".join(errors))
        sys.exit(1)
    say("\nГотово: показову базу доповнено.")


if __name__ == "__main__":
    main()
