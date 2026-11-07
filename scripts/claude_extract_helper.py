"""Локальний помічник розпізнавання для справи прийняття (тестовий режим).

Odoo в Docker надсилає сюди файли кандидата і список полів. Помічник кладе файли в тимчасову теку,
запускає локальний Claude Code (`claude -p`) і повертає пропозиції значень. Ключ API не потрібен:
працює вхід Claude Code на цьому комп'ютері (`claude`, потім `/login`). Файли видаляються одразу після відповіді.

Межі (документи пише кандидат, тому їхній текст - чужий):
  - Claude читає лише тимчасову теку: режим dontAsk, дозволено тільки Read(./**), Bash, запис і мережа
    заборонені; налаштування, хуки, MCP і CLAUDE.md оператора не підвантажуються (--setting-sources project).
  - Кожен запит несе токен (Authorization: Bearer, UA_EXTRACT_TOKEN), Host - лише локальний,
    тіло - лише JSON до 40 МБ. Слухає тільки 127.0.0.1.

Налаштування (один раз):
  python3 scripts/claude_extract_helper.py --new-token   # пише UA_EXTRACT_TOKEN у .env, не друкує його
  у .env: UA_EXTRACT_URL=http://host.docker.internal:8765, потім docker compose up -d odoo

Запуск:  python3 scripts/claude_extract_helper.py        (порт 8765; токен з UA_EXTRACT_TOKEN або .env)"""
import base64
import hmac
import json
import secrets
import os
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("UA_EXTRACT_PORT", "8765"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")
MAX_BODY = 40 * 1024 * 1024
HOSTS = {"127.0.0.1", "localhost", "host.docker.internal"} | {
    h.strip() for h in os.environ.get("UA_EXTRACT_HOSTS", "").split(",") if h.strip()}
# Claude читає лише теку з файлами кандидата, нічого не запускає і не пише.
CLAUDE_LIMITS = [
    "--setting-sources", "project",        # без налаштувань, хуків і дозволів оператора
    "--strict-mcp-config",                 # без MCP-серверів
    "--permission-mode", "dontAsk",        # усе, що не дозволено нижче, - відмова без питань
    "--allowedTools", "Read(./**)",
    "--disallowedTools", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
    "--no-session-persistence",
]
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
MODEL = os.environ.get("UA_EXTRACT_MODEL", "")
TIMEOUT = int(os.environ.get("UA_EXTRACT_TIMEOUT", "180"))  # менше за 200 с очікування Odoo (limit_time_real = 240)

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


def read_env_token():
    token = os.environ.get("UA_EXTRACT_TOKEN") or ""
    if not token and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            if line.startswith("UA_EXTRACT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
    return token


def write_new_token():
    """Новий токен у .env (замість порожнього або старого рядка). Значення не друкується."""
    token = secrets.token_urlsafe(32)
    lines = open(ENV_FILE, encoding="utf-8").read().splitlines() if os.path.exists(ENV_FILE) else []
    lines = [line for line in lines if not line.startswith("UA_EXTRACT_TOKEN=")] + ["UA_EXTRACT_TOKEN=" + token]
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)
    print("UA_EXTRACT_TOKEN записано в %s. Перезапустіть Odoo (docker compose up -d odoo), щоб він його взяв." % ENV_FILE)


TOKEN = ""


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
        cmd = [CLAUDE, "-p", prompt, "--output-format", "json"] + CLAUDE_LIMITS
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
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return {"error": "answer is not valid JSON: %s" % m.group()[:300]}
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

    def _allowed(self):
        """Токен, локальний Host. Інакше - відповідь 403 і False."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        given = self.headers.get("Authorization") or ""
        expected = "Bearer " + TOKEN
        if host not in HOSTS or not hmac.compare_digest(given.encode(), expected.encode()):
            self._send(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        if self.path == "/health":
            status = auth_status()
            self._send(200, {"ok": bool(status.get("loggedIn")), "logged_in": bool(status.get("loggedIn")),
                             "claude": CLAUDE, "error": "" if status.get("loggedIn") else "Claude Code не увійшов: запустіть claude і /login"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return
        if self.path != "/extract":
            self._send(404, {"error": "not found"})
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._send(415, {"error": "JSON only"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            self._send(413, {"error": "body size"})
            return
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
    if "--new-token" in sys.argv:
        write_new_token()
        sys.exit(0)
    TOKEN = read_env_token()
    if len(TOKEN) < 24:
        sys.exit("Немає UA_EXTRACT_TOKEN (24+ символи). Створіть: python3 scripts/claude_extract_helper.py --new-token")
    print("claude: %s, port %s, лише 127.0.0.1, токен з UA_EXTRACT_TOKEN" % (CLAUDE, PORT))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
