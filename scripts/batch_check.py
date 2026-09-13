# -*- coding: utf-8 -*-
"""Run the varied batch (scripts/fixtures/batch/*.eml) through the stand and score it against expected.json.
Real Workers AI and real bridge. Writes demo-out/batch_results.json. Usage: python3 scripts/batch_check.py [id-prefix ...]"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailgate import Odoo, deliver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = os.environ.get("BATCH_DIR") or os.path.join(ROOT, "scripts/fixtures/batch")
EXP = json.load(open(os.path.join(BATCH, "expected.json"), encoding="utf-8"))
only = sys.argv[1:]
o = Odoo()

ids = [k for k in EXP if not only or any(k.startswith(p) for p in only)]
numbers = [EXP[k]["number"] for k in ids]
subjects = [EXP[k]["subject"] for k in ids]
old = o.call("bp.purchase.intake", "search", ["|", ("number", "in", numbers), ("email_subject", "in", subjects)])
if old:
    moves = o.call("account.move", "search", [("bp_intake_id", "in", old)])
    if moves:
        o.call("account.move", "unlink", moves)
    o.call("bp.purchase.intake", "unlink", old)
print(f"reset {len(old)} earlier batch intakes\n")

F = ["name", "state", "source_kind", "doc_type", "supplier_name", "supplier_code", "number", "date", "prices_include_vat", "vat_rate",
     "amount_untaxed", "amount_tax", "amount_total", "line_ids", "partner_id", "partner_status", "move_id", "error_count", "warn_count",
     "ai_model", "ai_neurons", "error_message"]
results = []
for k in ids:
    exp = EXP[k]
    t = time.time()
    try:
        rid = deliver(o, os.path.join(BATCH, k + ".eml"))
    except RuntimeError as e:
        print(k, "DELIVERY FAILED", e); continue
    rec = o.call("bp.purchase.intake", "read", [rid], F)[0]
    checks = o.call("bp.purchase.intake.check", "search_read", [("intake_id", "=", rid)], ["key", "name", "level", "detail"])
    bill_total = o.call("account.move", "read", [rec["move_id"][0]], ["amount_total"])[0]["amount_total"] if rec["move_id"] else None
    fields_ok = {
        "number": (rec["number"] or "") == exp["number"],
        "code": (rec["supplier_code"] or "") == exp["supplier_code"],
        "date": (rec["date"] or "") == exp["date"],
        "total": abs((rec["amount_total"] or 0) - float(exp["amount_total"])) < 0.011,
        "tax": abs((rec["amount_tax"] or 0) - float(exp["amount_tax"])) < 0.011,
        "lines": len(rec["line_ids"]) == exp["lines"],
    }
    row = {"id": k, "variant": exp["variant"], "record": rec["name"], "record_id": rid, "state": rec["state"], "expect": exp["expect"],
           "as_expected": rec["state"] == exp["expect"], "read_as": rec["source_kind"], "doc_type": rec["doc_type"],
           "fields_ok": sum(fields_ok.values()), "fields_missed": [f for f, v in fields_ok.items() if not v],
           "parsed": {f: rec[f] for f in ["supplier_name", "supplier_code", "number", "date", "amount_untaxed", "amount_tax", "amount_total",
                                          "prices_include_vat", "vat_rate"]} | {"lines": len(rec["line_ids"])},
           "expected": {f: exp[f] for f in ["supplier", "supplier_code", "number", "date", "amount_untaxed", "amount_tax", "amount_total", "lines"]},
           "bill_total": bill_total, "errors": [f"{c['name']}: {c['detail']}" for c in checks if c["level"] == "error"],
           "warnings": [f"{c['name']}: {c['detail']}" for c in checks if c["level"] == "warn"],
           "checks": checks, "model": rec["ai_model"], "neurons": rec["ai_neurons"], "seconds": round(time.time() - t, 1),
           "error_message": rec["error_message"], "file": exp["file"]}
    results.append(row)
    print(f"{k:32s} {rec['state']:9s} {'✓' if row['as_expected'] else '✗ want ' + exp['expect']:14s} read={rec['source_kind'] or '-':5s} "
          f"fields {row['fields_ok']}/6 {row['fields_missed'] or ''} {row['seconds']}s {rec['ai_neurons']:.0f}n")
    for e in row["errors"]:
        print("      error:", e)
    if rec["error_message"]:
        print("      failed:", rec["error_message"][:200])

os.makedirs(os.path.join(ROOT, "demo-out"), exist_ok=True)
json.dump(results, open(os.path.join(ROOT, "demo-out", os.environ.get("RESULTS_FILE", "batch_results.json")), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
n = len(results)
print(f"\nstate as expected {sum(r['as_expected'] for r in results)}/{n}; fields right {sum(r['fields_ok'] for r in results)}/{6 * n}; "
      f"neurons {sum(r['neurons'] for r in results):.0f}; time {sum(r['seconds'] for r in results):.0f}s")
