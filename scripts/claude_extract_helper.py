"""Локальний помічник розпізнавання для справи прийняття (тестовий режим).

Odoo в Docker надсилає сюди файли кандидата і список полів. Помічник кладе файли в тимчасову теку,
запускає локальний Claude Code (`claude -p`) з доступом лише на читання цієї теки і повертає
пропозиції значень. Ключ API не потрібен: працює вхід Claude Code на цьому Mac (`claude`, потім `/login`).
Файли видаляються одразу після відповіді.

Запуск:  python3 scripts/claude_extract_helper.py        (порт 8765, лише 127.0.0.1)
Odoo звертається на http://host.docker.internal:8765 (змінна UA_EXTRACT_URL у контейнері)."""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("UA_EXTRACT_PORT", "8765"))
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
MODEL = os.environ.get("UA_EXTRACT_MODEL", "")
TIMEOUT = int(os.environ.get("UA_EXTRACT_TIMEOUT", "540"))

PROMPT = """You extract data for a Ukrainian employee hiring file.

Read every file in the current directory with the Read tool. The files are scans or photos of a candidate's documents: passport or ID card, RNOKPP (tax number) card, military registration document, diploma, labour book, application.

Target fields (JSON: field key -> label, type, allowed options for selection fields):
{fields}

Files (name -> declared document type):
{files}

Rules:
- Propose a value only when a document shows it. Do not guess. Omit fields that no document shows.
- Write names and text in Ukrainian exactly as printed. Names in the nominative case.
- Dates: YYYY-MM-DD.
- Selection fields: return the option key, not the label.
- id_doc_type: passport_book for the booklet passport, id_card for the ID card, residence_permit for a residence permit.
- rnokpp: 10 digits only. id_doc_unzr: 13 digits without the dash.
- sex: take it from the document (Стать / Sex: Ч/M = male, Ж/F = female).
- quote: the exact short text fragment from the document that shows the value.
- confidence: high (clearly printed), medium (partly readable), low (unclear).
- If two documents disagree, return both values as separate proposals.

Answer with one JSON object and nothing else:
{{"proposals": [{{"field": "<key>", "value": "<value>", "file": "<file name>", "quote": "<fragment>", "confidence": "high|medium|low"}}]}}
"""


def auth_status():
    try:
        out = subprocess.run([CLAUDE, "auth", "status"], capture_output=True, text=True, timeout=20).stdout
        return json.loads(out)
    except Exception as e:  # noqa: BLE001
        return {"loggedIn": False, "error": str(e)[:200]}


def safe_name(name, used):
    base = re.sub(r"[^\w.\-]+", "_", os.path.basename(name or "file"), flags=re.UNICODE).strip("._") or "file"
    candidate, n = base, 1
    while candidate in used:
        stem, ext = os.path.splitext(base)
        candidate = "%s_%s%s" % (stem, n, ext)
        n += 1
    used.add(candidate)
    return candidate


def extract(payload):
    tmp = tempfile.mkdtemp(prefix="ua_hire_")
    try:
        used, names, original = set(), {}, {}
        for f in payload.get("files") or []:
            name = safe_name(f.get("name"), used)
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(base64.b64decode(f.get("data") or ""))
            names[name] = f.get("doc_type") or "other"
            original[name] = f.get("name")
        if not names:
            return {"error": "no files"}
        prompt = PROMPT.format(fields=json.dumps(payload.get("fields") or {}, ensure_ascii=False, indent=1),
                               files=json.dumps(names, ensure_ascii=False))
        cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--allowedTools", "Read", "--strict-mcp-config"]
        if MODEL:
            cmd += ["--model", MODEL]
        proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT)
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"error": "claude output is not JSON: %s" % (proc.stdout or proc.stderr)[-300:]}
        text = envelope.get("result") or ""
        if envelope.get("is_error"):
            return {"error": text[:300]}
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            return {"error": "no JSON in answer: %s" % text[:300]}
        data = json.loads(m.group())
        proposals = []
        for p in data.get("proposals") or []:
            if isinstance(p, dict) and p.get("field"):
                p["file"] = original.get(p.get("file"), p.get("file"))
                proposals.append(p)
        model = ", ".join((envelope.get("modelUsage") or {}).keys())
        return {"proposals": proposals, "model": model, "cost_usd": envelope.get("total_cost_usd")}
    except subprocess.TimeoutExpired:
        return {"error": "claude timed out after %s s" % TIMEOUT}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            status = auth_status()
            self._send(200, {"ok": bool(status.get("loggedIn")), "logged_in": bool(status.get("loggedIn")),
                             "claude": CLAUDE, "error": "" if status.get("loggedIn") else "Claude Code не увійшов: запустіть claude і /login"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/extract":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, {"error": "bad JSON"})
            return
        result = extract(payload)
        self._send(200 if not result.get("error") else 502, result)

    def log_message(self, fmt, *args):
        sys.stderr.write("[extract] %s\n" % (fmt % args))


if __name__ == "__main__":
    print("claude: %s, port %s" % (CLAUDE, PORT))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
