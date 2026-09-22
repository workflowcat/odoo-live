# -*- coding: utf-8 -*-
"""Compare Workers AI models on the fixture invoices: toMarkdown once, then the same prompt and schema per model.
Usage: python3 scripts/purchase/ai_probe.py [model ...]   (token from .cf/token, account from CF_ACCOUNT_ID or wrangler default)"""
import json, os, sys, time, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # корінь репозиторію
ACC = os.environ.get("CF_ACCOUNT_ID", "5f1d89c39916440b30eed21bc37c1efd")
TOK = open(os.path.join(ROOT, ".cf/token")).read().strip()
SPEC = json.load(open(os.path.join(ROOT, "addons/bp_purchase_intake/data/extract_invoice.json"), encoding="utf-8"))
EXP = json.load(open(os.path.join(ROOT, "scripts/purchase/fixtures/expected.json"), encoding="utf-8"))["invoices"]
API = f"https://api.cloudflare.com/client/v4/accounts/{ACC}/ai"
H = {"Authorization": f"Bearer {TOK}", "User-Agent": "curl/8.7"}
MODELS = sys.argv[1:] or ["@cf/google/gemma-4-26b-a4b-it", "@cf/meta/llama-4-scout-17b-16e-instruct",
                          "@cf/mistralai/mistral-small-3.1-24b-instruct", "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                          "@cf/zai-org/glm-5.3-flash", "@cf/qwen/qwen3.8-27b"]


def to_markdown(path):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{os.path.basename(path)}\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(f"{API}/tomarkdown", data=body, method="POST",
                                 headers={**H, "Content-Type": f"multipart/form-data; boundary={b}"})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    return d["result"][0]


def run(model, text):
    payload = {"messages": [{"role": "system", "content": SPEC["system"]},
                            {"role": "user", "content": "Документ:\n\n" + text}],
               "response_format": {"type": "json_schema", "json_schema": SPEC["schema"]},
               "max_tokens": 2500, "temperature": 0}
    req = urllib.request.Request(f"{API}/run/{model}", data=json.dumps(payload).encode(), method="POST",
                                 headers={**H, "Content-Type": "application/json"})
    t = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.HTTPError as e:
        return None, round(time.time() - t, 1), {"error": e.read().decode()[:300]}
    r = d.get("result", {})
    out = r.get("response")
    if out is None and r.get("choices"):
        out = r["choices"][0]["message"].get("content")
    if isinstance(out, str):
        s = out.strip().strip("`")
        s = s[s.find("{"):s.rfind("}") + 1] if "{" in s else s
        try:
            out = json.loads(s)
        except ValueError:
            return None, round(time.time() - t, 1), {"error": "not json", "raw": out[:300]}
    return out, round(time.time() - t, 1), r.get("usage", {})


def score(out, exp):
    if not out:
        return 0, ["no output"]
    s = out.get("supplier", {}) or {}
    checks = {
        "number": out.get("number") == exp["number"],
        "code": "".join(ch for ch in str(s.get("code", "")) if ch.isdigit()) == exp["supplier_code"],
        "ipn": "".join(ch for ch in str(s.get("ipn", "")) if ch.isdigit()) == exp["supplier_ipn"],
        "iban": str(s.get("iban", "")).replace(" ", "") == exp["supplier_iban"],
        "untaxed": abs(float(out.get("amount_untaxed") or 0) - float(exp["amount_untaxed"])) < 0.01,
        "tax": abs(float(out.get("amount_tax") or 0) - float(exp["amount_tax"])) < 0.01,
        "total": abs(float(out.get("amount_total") or 0) - float(exp["amount_total"])) < 0.01,
        "lines": len(out.get("lines") or []) == exp["lines"],
        "date": bool(str(out.get("date", "")).startswith("2026-09")),
    }
    return sum(checks.values()), [k for k, v in checks.items() if not v]


docs = {}
for name in ["01-nova-poshta", "03-bad-code"]:
    md = to_markdown(os.path.join(ROOT, "scripts/purchase/fixtures", name + ".pdf"))
    docs[name] = md["data"]
    print(f"== toMarkdown {name}: {md.get('tokens')} tokens, {len(md['data'])} chars")
print(docs["01-nova-poshta"][:1500])
print()
results = {}
for m in MODELS:
    for name, text in docs.items():
        out, secs, usage = run(m, text)
        pts, miss = score(out, EXP[name])
        results.setdefault(m, []).append(out)
        print(f"{m:48s} {name:16s} {pts}/9  {secs:5.1f}s  miss={miss}  usage={usage}")
os.makedirs(os.path.join(ROOT, "demo-out"), exist_ok=True)
json.dump(results, open(os.path.join(ROOT, "demo-out/ai_probe.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
