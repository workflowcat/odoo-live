#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сценарії лабораторії S1-S5 над демо «АероСіч»: однаковий стартовий стан для
порівняння облич складського клієнта (запит UI 2026-09-23-001).

    python3 scripts/demo_scenarios.py seed S1 S3      # підготувати названі
    python3 scripts/demo_scenarios.py seed all        # усі пʼять
    python3 scripts/demo_scenarios.py reset [S2 ...]  # прибрати сліди (без назв - усі)

Змінні: ODOO_URL (типово http://127.0.0.1:8131), DEMO_DB (типово demo). Потрібна
демо-база з `scripts/demo_aerosich.py`. Друкує JSON з id документів кожного сценарію.

Сценарії:
  S1  приймання від ТОВ «Карбон-Технології» на 8 позицій, мотор 2207 (D02)
      очікується 12; стан «Готово» (assigned), нічого не прийнято
  S2  відкритий опис на 12 рядків у стані «Підрахунок», факт = облік; дві
      розбіжності вносить сама лабораторія. Локація - зона «Комплектуючі»: на
      полиці К-2 у демо лише 4 товари, 12 рядків дає тільки зона
  S3  3 пакунки на «Підлозі» полиці К-2: мотори D02 × 4 і пропелери D09 × 8
      (їхня полиця К-2, влазять) і рами D01 × 2 (полиця К-1 переповнена - не влазять)
  S4  5 камер D06 у зоні «Приймання» - перемістити на К-3
  S5  виробниче замовлення «Шершень» 7" на 1 шт., підтверджене і зарезервоване,
      6 нарядів у стані до старту, відповідей на перевірки немає

Ідемпотентність - через `ua_client_ref` (мітки `lab-S1` .. `lab-S5`). Повторний seed:
якщо документ сценарію ще в стартовому стані, його віддають як є (ті самі id); якщо
лабораторія вже щось зробила - сценарій спершу скидається і складається заново
(id нові, стан той самий). Проведений документ не видаляється: його мітка стає
`lab-Sn-<id>`, щоб звільнити `lab-Sn` для нового. Переміщення S3/S4 при скиданні
повертають товар з «Підлоги» і «Приймання» на полиці окремим проведеним
переміщенням - історія рухів лишається чесною.
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = dict(l.split("=", 1) for l in open(os.path.join(ROOT, ".env")).read().splitlines()
           if "=" in l and not l.startswith("#"))
URL = os.environ.get("ODOO_URL", "http://127.0.0.1:8131").rstrip("/")
DB = os.environ.get("DEMO_DB", "demo").strip()
PW = ENV["ODOO_ADMIN_USER_PASSWORD"].strip()
COMPANY = "ТОВ «АероСіч»"

SUPPLIER = "ТОВ «Карбон-Технології»"
S1_LINES = [("D01", 2), ("D02", 12), ("D03", 3), ("D04", 3), ("D05", 3), ("D06", 3),
            ("D07", 3), ("D08", 3)]
S2_LINES = 12
FLOOR = "Підлога"
FLOOR_SHELF = "К-2"
S3_PACKAGES = [("D02", 4, "К-2"), ("D09", 8, "К-2"), ("D01", 2, "К-1")]
S4_ZONE, S4_HOME, S4_ITEM = "Приймання", "К-3", ("D06", 5)
S5_PRODUCT = "FPV7"
ALL = ["S1", "S2", "S3", "S4", "S5"]
SKIP = {"skip_backorder": True, "skip_sms": True, "skip_immediate": True}


class RpcError(Exception):
    pass


def rpc(service, method, *args):
    req = urllib.request.Request(
        URL + "/jsonrpc",
        json.dumps({"jsonrpc": "2.0", "method": "call",
                    "params": {"service": service, "method": method, "args": args},
                    "id": 1}).encode(),
        {"Content-Type": "application/json",
         "User-Agent": "Mozilla/5.0 (Macintosh) demo_scenarios"})
    data = json.loads(urllib.request.urlopen(req, timeout=600).read())
    if "error" in data:
        err = data["error"].get("data", {}).get("message") or data["error"].get("message")
        raise RpcError(str(err)[:2000])
    return data.get("result")


UID = CO = None
CTX = {"lang": "uk_UA"}


def call(model, method, *args, **kw):
    ctx = dict(CTX, **(kw.pop("context", None) or {}))
    return rpc("object", "execute_kw", DB, UID, PW, model, method, list(args),
               dict(kw, context=ctx))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ довідники демо
def connect():
    global UID, CO
    UID = rpc("common", "login", DB, "admin", PW)
    if not UID:
        sys.exit("Не вдалося увійти в базу %s на %s" % (DB, URL))
    ids = rpc("object", "execute_kw", DB, UID, PW, "res.company", "search",
              [[["name", "=", COMPANY]]], {})
    if not ids:
        sys.exit("Компанії %s у базі немає - спершу scripts/demo_aerosich.py." % COMPANY)
    CO = ids[0]
    CTX["allowed_company_ids"] = [CO]


def product(code):
    ids = call("product.product", "search", [["default_code", "=", code]])
    if not ids:
        sys.exit("Товару %s немає - демо «АероСіч» не завантажене." % code)
    return ids[0]


def location(name):
    ids = call("stock.location", "search",
               [["name", "=", name], ["company_id", "=", CO], ["usage", "=", "internal"]])
    if not ids:
        sys.exit("Локації «%s» немає - демо «АероСіч» старше за зони (2026-09-23-002)." % name)
    return ids[0]


def warehouse():
    return call("stock.warehouse", "search_read", [["company_id", "=", CO]],
                fields=["lot_stock_id", "in_type_id", "int_type_id"], limit=1)[0]


def floor_location():
    """«Підлога» під полицею К-2: створюємо, якщо її ще немає."""
    shelf = location(FLOOR_SHELF)
    ids = call("stock.location", "search",
               [["name", "=", FLOOR], ["location_id", "=", shelf]],
               context={"active_test": False})
    if ids:
        call("stock.location", "write", ids[:1], {"active": True})
        return ids[0]
    return call("stock.location", "create", {
        "name": FLOOR, "location_id": shelf, "usage": "internal", "company_id": CO})


def by_ref(model, ref):
    ids = call(model, "search", [["ua_client_ref", "=", ref], ["company_id", "=", CO]])
    return ids[0] if ids else None


def free_ref(model, ref, rid):
    """Проведений документ лишається в історії, а мітка звільняється."""
    call(model, "write", [rid], {"ua_client_ref": "%s-%d" % (ref, rid)})


def quants_on(loc):
    return call("stock.quant", "search_read",
                [["location_id", "=", loc], ["quantity", ">", 0]],
                fields=["product_id", "quantity"])


def transfer(ref, origin, lines):
    """Внутрішнє переміщення рядків (product_id, qty, from, to) і проведення.

    Повертає id переміщення або None, коли переносити нічого."""
    lines = [line for line in lines if line[1] > 0]
    if not lines:
        return None
    wh = warehouse()
    int_type = wh["int_type_id"][0]
    call("stock.picking.type", "write", [int_type], {"active": True})
    vals = {"picking_type_id": int_type, "company_id": CO, "origin": origin,
            "location_id": lines[0][2], "location_dest_id": lines[0][3],
            "move_ids": [(0, 0, {"product_id": pid, "product_uom_qty": qty,
                                 "location_id": src, "location_dest_id": dst,
                                 "company_id": CO})
                         for pid, qty, src, dst in lines]}
    pid = call("stock.picking", "ua_get_or_create", ref, vals) if ref else \
        call("stock.picking", "create", vals)
    pid = pid[0] if isinstance(pid, list) else pid
    call("stock.picking", "action_confirm", [pid])
    call("stock.picking", "action_assign", [pid])
    moves = call("stock.move", "search_read", [["picking_id", "=", pid]],
                 fields=["product_uom_qty"])
    for move in moves:
        call("stock.move", "write", [move["id"]],
             {"quantity": move["product_uom_qty"], "picked": True})
    call("stock.picking", "button_validate", [pid],
         context=dict(SKIP, picking_ids_not_to_backorder=[pid]))
    state = call("stock.picking", "read", [pid], ["state"])[0]["state"]
    if state != "done":
        raise RpcError("Переміщення %s не провелось (стан %s)." % (pid, state))
    return pid


# ------------------------------------------------------------------ S1 приймання
def s1_pristine(pid):
    head = call("stock.picking", "read", [pid], ["state", "move_ids"])[0]
    if head["state"] != "assigned" or len(head["move_ids"]) != len(S1_LINES):
        return False
    moves = call("stock.move", "read", head["move_ids"], ["picked"])
    return not any(move["picked"] for move in moves)


def s1_reset():
    pid = by_ref("stock.picking", "lab-S1")
    if not pid:
        return
    state = call("stock.picking", "read", [pid], ["state"])[0]["state"]
    if state == "done":
        free_ref("stock.picking", "lab-S1", pid)
        return
    if state != "cancel":
        call("stock.picking", "action_cancel", [pid])
    call("stock.picking", "unlink", [pid])


def s1_seed():
    pid = by_ref("stock.picking", "lab-S1")
    if pid and not s1_pristine(pid):
        s1_reset()
        pid = None
    if not pid:
        partner = call("res.partner", "search", [["name", "=", SUPPLIER]])
        partner = partner[0] if partner else call("res.partner", "create", {
            "name": SUPPLIER, "is_company": True, "supplier_rank": 1,
            "company_id": False, "city": "Дніпро"})
        wh = warehouse()
        supplier = call("stock.location", "search", [["usage", "=", "supplier"]], limit=1)[0]
        dest = wh["lot_stock_id"][0]
        pid = call("stock.picking", "ua_get_or_create", "lab-S1", {
            "picking_type_id": wh["in_type_id"][0], "partner_id": partner,
            "company_id": CO, "origin": "Лабораторія S1",
            "location_id": supplier, "location_dest_id": dest,
            "move_ids": [(0, 0, {"product_id": product(code), "product_uom_qty": qty,
                                 "location_id": supplier, "location_dest_id": dest,
                                 "company_id": CO})
                         for code, qty in S1_LINES]})
        pid = pid[0] if isinstance(pid, list) else pid
        call("stock.picking", "action_confirm", [pid])
    head = call("stock.picking", "read", [pid], ["name", "state", "partner_id", "move_ids"])[0]
    moves = call("stock.move", "read", head["move_ids"], ["product_id", "product_uom_qty"])
    return {"picking_id": pid, "name": head["name"], "state": head["state"],
            "partner_id": head["partner_id"][0],
            "moves": [{"move_id": move["id"], "product_id": move["product_id"][0],
                       "expected": move["product_uom_qty"]} for move in moves]}


# ------------------------------------------------------------------ S2 опис
def s2_pristine(iid):
    head = call("ua.stock.inventory", "read", [iid], ["state", "line_ids"])[0]
    if head["state"] != "counting" or len(head["line_ids"]) != S2_LINES:
        return False
    lines = call("ua.stock.inventory.line", "read", head["line_ids"], ["qty_diff"])
    return not any(abs(line["qty_diff"]) > 1e-9 for line in lines)


def s2_reset():
    iid = by_ref("ua.stock.inventory", "lab-S2")
    if not iid:
        return
    if call("ua.stock.inventory", "read", [iid], ["state"])[0]["state"] == "done":
        free_ref("ua.stock.inventory", "lab-S2", iid)
    else:
        call("ua.stock.inventory", "unlink", [iid])


def s2_seed():
    iid = by_ref("ua.stock.inventory", "lab-S2")
    if iid and not s2_pristine(iid):
        s2_reset()
        iid = None
    if not iid:
        zone = location("Комплектуючі")
        iid = call("ua.stock.inventory", "ua_get_or_create", "lab-S2", {
            "location_id": zone, "company_id": CO,
            "basis": "Лабораторія S2", "keeper": "Павлів Ю. Р."})
        iid = iid[0] if isinstance(iid, list) else iid
        call("ua.stock.inventory", "action_fill", [iid])
        lines = call("ua.stock.inventory.line", "search_read", [["inventory_id", "=", iid]],
                     fields=["product_id"])
        codes = {row["id"]: row["default_code"] or "" for row in call(
            "product.product", "read", [line["product_id"][0] for line in lines],
            ["default_code"])}
        lines.sort(key=lambda line: (codes.get(line["product_id"][0], ""), line["id"]))
        extra = [line["id"] for line in lines[S2_LINES:]]
        if len(lines) < S2_LINES:
            raise RpcError("У зоні лише %d товарів, треба %d." % (len(lines), S2_LINES))
        if extra:
            call("ua.stock.inventory.line", "unlink", extra)
    head = call("ua.stock.inventory", "read", [iid], ["name", "state", "line_ids"])[0]
    return {"inventory_id": iid, "name": head["name"], "state": head["state"],
            "lines": head["line_ids"]}


# ------------------------------------------------------------------ S3 підлога
def s3_home():
    return {product(code): location(shelf) for code, _qty, shelf in S3_PACKAGES}


def s3_pristine(floor):
    have = {q["product_id"][0]: q["quantity"] for q in quants_on(floor)}
    want = {product(code): float(qty) for code, qty, _shelf in S3_PACKAGES}
    return have == want


def s3_reset():
    floor = floor_location()
    home, zone = s3_home(), location("Комплектуючі")
    pid = by_ref("stock.picking", "lab-S3")
    if pid:
        free_ref("stock.picking", "lab-S3", pid)
    transfer(None, "Лабораторія: скидання S3",
             [(q["product_id"][0], q["quantity"], floor, home.get(q["product_id"][0], zone))
              for q in quants_on(floor)])


def s3_seed():
    floor = floor_location()
    if not s3_pristine(floor):
        s3_reset()
        transfer("lab-S3", "Лабораторія S3",
                 [(product(code), qty, location(shelf), floor)
                  for code, qty, shelf in S3_PACKAGES])
    return {"floor_location_id": floor, "picking_id": by_ref("stock.picking", "lab-S3"),
            "packages": [{"product_id": product(code), "quantity": qty,
                          "target_location_id": location(shelf),
                          "fits": shelf != "К-1"} for code, qty, shelf in S3_PACKAGES]}


# ------------------------------------------------------------------ S4 переміщення
def s4_pristine(zone):
    have = {q["product_id"][0]: q["quantity"] for q in quants_on(zone)}
    return have == {product(S4_ITEM[0]): float(S4_ITEM[1])}


def s4_reset():
    zone, home = location(S4_ZONE), location(S4_HOME)
    pid = by_ref("stock.picking", "lab-S4")
    if pid:
        free_ref("stock.picking", "lab-S4", pid)
    transfer(None, "Лабораторія: скидання S4",
             [(q["product_id"][0], q["quantity"], zone, home) for q in quants_on(zone)])


def s4_seed():
    zone, home = location(S4_ZONE), location(S4_HOME)
    if not s4_pristine(zone):
        s4_reset()
        transfer("lab-S4", "Лабораторія S4",
                 [(product(S4_ITEM[0]), S4_ITEM[1], home, zone)])
    return {"from_location_id": zone, "to_location_id": home,
            "product_id": product(S4_ITEM[0]), "quantity": S4_ITEM[1],
            "picking_id": by_ref("stock.picking", "lab-S4")}


# ------------------------------------------------------------------ S5 виробництво
def s5_pristine(mid):
    head = call("mrp.production", "read", [mid], ["state", "workorder_ids"])[0]
    if head["state"] != "confirmed":
        return False
    orders = call("mrp.workorder", "read", head["workorder_ids"], ["state", "ua_check_ids"])
    return all(wo["state"] in ("ready", "waiting", "pending", "blocked")
               and not wo["ua_check_ids"] for wo in orders)


def s5_reset():
    mid = by_ref("mrp.production", "lab-S5")
    if not mid:
        return
    state = call("mrp.production", "read", [mid], ["state"])[0]["state"]
    if state == "done":
        free_ref("mrp.production", "lab-S5", mid)
        return
    if state != "cancel":
        call("mrp.production", "action_cancel", [mid])
    free_ref("mrp.production", "lab-S5", mid)
    try:
        call("mrp.production", "unlink", [mid])
    except RpcError as error:
        log("S5: скасоване замовлення %s лишилось в історії (%s)" % (mid, str(error)[:120]))


def s5_seed():
    mid = by_ref("mrp.production", "lab-S5")
    if mid and not s5_pristine(mid):
        s5_reset()
        mid = None
    if not mid:
        pid = product(S5_PRODUCT)
        tmpl = call("product.product", "read", [pid], ["product_tmpl_id"])[0]["product_tmpl_id"][0]
        bom = call("mrp.bom", "search", [["product_tmpl_id", "=", tmpl], ["company_id", "=", CO]],
                   limit=1)[0]
        mid = call("mrp.production", "ua_get_or_create", "lab-S5", {
            "product_id": pid, "product_qty": 1, "bom_id": bom, "company_id": CO,
            "origin": "Лабораторія S5"})
        mid = mid[0] if isinstance(mid, list) else mid
        call("mrp.production", "action_confirm", [mid])
        call("mrp.production", "action_assign", [mid])
    head = call("mrp.production", "read", [mid],
                ["name", "state", "reservation_state", "workorder_ids"])[0]
    orders = call("mrp.workorder", "read", head["workorder_ids"], ["name", "state"])
    return {"production_id": mid, "name": head["name"], "state": head["state"],
            "reservation_state": head["reservation_state"],
            "workorders": [{"id": wo["id"], "name": wo["name"], "state": wo["state"]}
                           for wo in orders]}


SEED = {"S1": s1_seed, "S2": s2_seed, "S3": s3_seed, "S4": s4_seed, "S5": s5_seed}
RESET = {"S1": s1_reset, "S2": s2_reset, "S3": s3_reset, "S4": s4_reset, "S5": s5_reset}


def main(argv):
    if not argv or argv[0] not in ("seed", "reset"):
        sys.exit(__doc__)
    names = [name.upper() for name in argv[1:]]
    if not names or names == ["ALL"]:
        names = ALL
    unknown = [name for name in names if name not in SEED]
    if unknown:
        sys.exit("Невідомі сценарії: %s (є %s)." % (", ".join(unknown), ", ".join(ALL)))
    connect()
    out = {}
    for name in names:
        if argv[0] == "seed":
            out[name] = SEED[name]()
        else:
            RESET[name]()
            out[name] = "reset"
        log("%s: %s" % (name, argv[0]))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
