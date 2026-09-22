# -*- coding: utf-8 -*-
"""End-to-end check on the running stand: three emails -> intakes -> suppliers -> ЄДР -> bills.
Real Workers AI and real bridge (OpenDataBot). Usage: python3 scripts/purchase/intake_check.py"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailgate import Odoo, deliver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # корінь репозиторію
FIX = os.path.join(ROOT, "scripts/purchase/fixtures")
EXP = json.load(open(os.path.join(FIX, "expected.json"), encoding="utf-8"))["invoices"]
o = Odoo()
fails = []


def check(label, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}{(': ' + str(detail)) if detail != '' else ''}")
    if not cond:
        fails.append(label)


# reset what earlier runs left behind (supplier cards first: deleting an intake clears their link)
codes = sorted({v["supplier_code"] for v in EXP.values()})
old = o.call("bp.purchase.intake", "search", [("supplier_code", "in", codes)])
partners = o.call("res.partner", "search", [("company_registry", "in", codes), "|", ("bp_intake_id", "!=", False), ("bp_supplier_status", "!=", False)])
moves = o.call("account.move", "search", ["|", ("bp_intake_id", "in", old), ("partner_id", "in", partners)]) if (old or partners) else []
if moves:
    posted = o.call("account.move", "search", [("id", "in", moves), ("state", "=", "posted")])
    if posted:
        o.call("account.move", "button_draft", posted)
    o.call("account.move", "unlink", moves)
if old:
    o.call("bp.purchase.intake", "unlink", old)
if partners:
    o.call("res.partner", "unlink", partners)
if not o.call("bp.purchase.intake", "search_count", []):
    seq = o.call("ir.sequence", "search", [("code", "=", "bp.purchase.intake")])
    o.call("ir.sequence", "write", seq, {"number_next_actual": 1})
print(f"reset: {len(old)} intakes, {len(moves)} bills, {len(partners)} suppliers")

F = ["name", "state", "supplier_name", "supplier_code", "supplier_ipn", "supplier_iban", "number", "date", "amount_untaxed",
     "amount_tax", "amount_total", "partner_id", "partner_status", "move_id", "duplicate_of_id", "error_count", "warn_count",
     "ai_model", "ai_neurons", "error_message"]
ids = {}
for name in ["01-nova-poshta", "02-nova-poshta-repeat", "03-bad-code"]:
    t = time.time()
    ids[name] = deliver(o, os.path.join(FIX, name + ".eml"))
    rec = o.call("bp.purchase.intake", "read", [ids[name]], F)[0]
    checks = o.call("bp.purchase.intake.check", "search_read", [("intake_id", "=", ids[name])], ["key", "name", "level", "detail"])
    exp = EXP[name]
    print(f"\n{name}: {rec['name']} state={rec['state']} in {time.time() - t:.1f}s, model {rec['ai_model']}, neurons {rec['ai_neurons']}")
    if rec["error_message"]:
        print("  error:", rec["error_message"])
    print(f"  parsed: {rec['supplier_name']} | {rec['supplier_code']} | ІПН {rec['supplier_ipn']} | {rec['supplier_iban']} | "
          f"№ {rec['number']} від {rec['date']} | {rec['amount_untaxed']} + {rec['amount_tax']} = {rec['amount_total']}")
    for c in checks:
        print(f"    [{c['level']:5s}] {c['name']}: {c['detail']}")
    check("number", rec["number"] == exp["number"], rec["number"])
    check("supplier code", rec["supplier_code"] == exp["supplier_code"], rec["supplier_code"])
    check("iban", rec["supplier_iban"] == exp["supplier_iban"], rec["supplier_iban"])
    check("total as written", abs(rec["amount_total"] - float(exp["amount_total"])) < 0.01, rec["amount_total"])
    check("supplier card unverified", rec["partner_status"] == "unverified", rec["partner_status"])
    lv = {c["key"]: c["level"] for c in checks}
    if name == "01-nova-poshta":
        check("state bill", rec["state"] == "bill", rec["state"])
        p = o.call("res.partner", "read", [rec["partner_id"][0]], ["name", "company_registry", "vat", "bp_registry_name", "bp_registry_status",
                                                               "bp_registry_head", "bp_registry_vat", "bp_registry_markers", "bank_ids"])[0]
        print(f"  supplier card: {p['name']} | ЄДРПОУ {p['company_registry']} | ІПН {p['vat']} | ЄДР: {p['bp_registry_name']} | "
              f"{p['bp_registry_status']} | {p['bp_registry_head']} | ПДВ {p['bp_registry_vat']} | маркери: {p['bp_registry_markers']!r}")
        check("ЄДР name filled", "НОВА ПОШТА" in (p["bp_registry_name"] or ""), p["bp_registry_name"])
        check("IBAN added to card", len(p["bank_ids"]) == 1)
        m = o.call("account.move", "read", [rec["move_id"][0]], ["name", "state", "move_type", "ref", "amount_untaxed", "amount_tax", "amount_total", "invoice_date", "message_main_attachment_id"])[0]
        print(f"  bill: id {m['id']} {m['move_type']} {m['state']} ref {m['ref']} {m['amount_untaxed']} + {m['amount_tax']} = {m['amount_total']} "
              f"date {m['invoice_date']} pdf {bool(m['message_main_attachment_id'])}")
        check("bill draft 19200", m["state"] == "draft" and abs(m["amount_total"] - 19200) < 0.01)
        try:
            o.call("account.move", "action_post", [m["id"]])
            check("posting blocked for unverified supplier", False, "bill was posted")
        except RuntimeError as e:
            check("posting blocked for unverified supplier", "не перевірений" in str(e), str(e)[:120])
    elif name == "02-nova-poshta-repeat":
        check("state duplicate", rec["state"] == "duplicate", rec["state"])
        check("points to the first intake", rec["duplicate_of_id"] and rec["duplicate_of_id"][0] == ids["01-nova-poshta"], rec["duplicate_of_id"])
        check("no second bill", not rec["move_id"])
    else:
        check("state review", rec["state"] == "review", rec["state"])
        check("code checksum error", lv.get("code") == "error")
        check("total mismatch error", lv.get("total") == "error")
        check("no ЄДР request", lv.get("registry") == "warn")
        check("no bill", not rec["move_id"])

print(f"\n{'ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
print("open:", f"{o.url.replace('/jsonrpc', '')}/odoo/action-bp_purchase_intake.action_purchase_intake")
sys.exit(1 if fails else 0)
