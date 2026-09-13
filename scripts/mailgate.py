# -*- coding: utf-8 -*-
"""Deliver .eml files to Odoo the way a mail server does (same entry point as odoo-mailgate.py):
mail.thread.message_process(model, raw_message). Usage: python3 scripts/mailgate.py file.eml [...]"""
import json, os, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env():
    vals = {}
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


class Odoo:
    def __init__(self):
        e = env()
        self.url = os.environ.get("ODOO_URL", f"http://127.0.0.1:{e.get('ODOO_PORT', '8120')}") + "/jsonrpc"
        self.db = os.environ.get("ODOO_DB", "purchase")
        self.login, self.pw = e.get("ODOO_ADMIN_USER_LOGIN", "admin"), e["ODOO_ADMIN_USER_PASSWORD"]
        self.uid = self.rpc("common", "login", self.db, self.login, self.pw)
        if not self.uid:
            sys.exit("login failed")

    def rpc(self, service, method, *args):
        body = json.dumps({"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json", "User-Agent": "curl/8.7"})
        d = json.load(urllib.request.urlopen(req, timeout=300))
        if "error" in d:
            raise RuntimeError(d["error"].get("data", {}).get("message") or d["error"])
        return d.get("result")

    def call(self, model, method, *args, **kw):
        return self.rpc("object", "execute_kw", self.db, self.uid, self.pw, model, method, list(args), kw)


def deliver(odoo, path, unique=True):
    raw = open(path, "rb").read().decode("utf-8")
    if unique:  # a Message-Id seen before is silently ignored by Odoo; make each run a new message
        raw = raw.replace("@test.example>", f".{int(time.time() * 1000)}@test.example>", 1)
    return odoo.call("mail.thread", "message_process", "bp.purchase.intake", raw)


if __name__ == "__main__":
    o = Odoo()
    for p in sys.argv[1:]:
        t = time.time()
        print(p, "->", deliver(o, p), f"{time.time() - t:.1f}s")
