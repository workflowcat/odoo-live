#!/usr/bin/env python3
"""Нотатки між агентами (core / docs / ui / map): створити, перелічити, закрити.
Файли лежать у docs/agents/inbox (відкриті) і docs/agents/log (закриті). Див. docs/agents/README.md."""
import argparse, datetime, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "docs", "agents", "inbox")
LOG = os.path.join(ROOT, "docs", "agents", "log")
# map - карта бекенду odoo-map (репо workflowcat/odoo-map): читає знімок ядра, ядро не пише.
ROLES = ("core", "docs", "ui", "map", "andrii")
KINDS = ("request", "decision", "question", "change")


def _slug(title):
    s = re.sub(r"[^\w\-]+", "-", title.lower(), flags=re.U).strip("-")
    return s[:48] or "note"


def _read(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    head = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l) if m else {}
    return {k.strip(): v.strip() for k, v in head.items()}, (m.group(2) if m else text)


def _next_id():
    today = datetime.date.today().isoformat()
    n = 0
    for d in (INBOX, LOG):
        for f in os.listdir(d):
            if f.startswith(today):
                n = max(n, int(f[11:14]))
    return f"{today}-{n + 1:03d}"


def cmd_new(a):
    os.makedirs(INBOX, exist_ok=True)
    nid = _next_id()
    path = os.path.join(INBOX, f"{nid}-{_slug(a.title)}.md")
    body = a.body or "(що саме треба, навіщо, приклад)"
    open(path, "w", encoding="utf-8").write(
        f"---\nid: {nid}\nkind: {a.kind}\nfrom: {a.frm}\nto: {a.to}\nstatus: open\ntitle: {a.title}\n---\n{body}\n")
    print(os.path.relpath(path, ROOT))


def cmd_list(a):
    rows = []
    dirs = [INBOX] if a.open else [INBOX, LOG]
    for d in dirs:
        for f in sorted(os.listdir(d)):
            if not f.endswith(".md"):
                continue
            h, _ = _read(os.path.join(d, f))
            if a.to and h.get("to") != a.to:
                continue
            rows.append((h.get("id", f), h.get("status", "?"), h.get("kind", "?"), h.get("from", "?"), h.get("to", "?"), h.get("title", "")))
    for r in rows:
        print(f"{r[0]}  {r[1]:8} {r[2]:8} {r[3]:>6} -> {r[4]:<6} {r[5]}")
    if not rows:
        print("нотаток немає")


def cmd_close(a):
    for f in os.listdir(INBOX):
        if f.startswith(a.id):
            src = os.path.join(INBOX, f)
            text = open(src, encoding="utf-8").read().replace("status: open", f"status: {a.status}", 1)
            if a.note:
                text = text.rstrip("\n") + f"\n\n{datetime.date.today().isoformat()}: {a.note}\n"
            os.makedirs(LOG, exist_ok=True)
            open(os.path.join(LOG, f), "w", encoding="utf-8").write(text)
            os.remove(src)
            print(f"закрито: {f} ({a.status})")
            return
    sys.exit(f"нотатки {a.id} немає у inbox")


p = argparse.ArgumentParser(description=__doc__)
sub = p.add_subparsers(dest="cmd", required=True)
n = sub.add_parser("new"); n.add_argument("kind", choices=KINDS); n.add_argument("title")
n.add_argument("--from", dest="frm", choices=ROLES, required=True); n.add_argument("--to", choices=ROLES, required=True)
n.add_argument("--body"); n.set_defaults(fn=cmd_new)
l = sub.add_parser("list"); l.add_argument("--open", action="store_true"); l.add_argument("--to", choices=ROLES); l.set_defaults(fn=cmd_list)
c = sub.add_parser("close"); c.add_argument("id"); c.add_argument("--status", choices=("done", "declined"), default="done")
c.add_argument("--note"); c.set_defaults(fn=cmd_close)
a = p.parse_args(); a.fn(a)
