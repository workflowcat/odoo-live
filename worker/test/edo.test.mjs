// node --test worker/test/*.test.mjs  (no dependencies). Vchasno is a fake: globalThis.fetch is replaced.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { edoRoute } from "../src/edo.js";
import { resetForTests } from "../src/vchasno.js";

const OWNER = "87654321", BUYER = "12345678", DOC = "04ff160b-b051-42a0-9a07-35c7a4d7f0d8";
const env = () => ({ VCHASNO_TOKENS: JSON.stringify({ [OWNER]: "tok-owner" }), DB: fakeDb() });
let calls = [], docs = {}, incoming = [];

function fakeDb() {
  const rows = new Map();
  return { prepare: (sql) => ({ bind: (...a) => ({
    first: async () => (rows.has(a[0]) ? { provider_id: rows.get(a[0]) } : null),
    run: async () => { if (sql.startsWith("INSERT")) rows.set(a[0], a[1]); } }),
    run: async () => {} }) };
}

const reply = (data, status = 200) => new Response(typeof data === "string" ? data : JSON.stringify(data), { status });

beforeEach(() => {
  calls = []; docs = {}; incoming = []; resetForTests();
  globalThis.fetch = async (url, init = {}) => {
    const u = new URL(url); const method = init.method || "GET";
    calls.push({ method, path: u.pathname, params: u.searchParams, init });
    assert.equal(init.headers.Authorization, "tok-owner", "token of the company");
    if (method === "POST" && u.pathname === "/api/v2/documents") {
      const doc = { id: DOC, status: 7001, url: `https://edo.vchasno.ua/app/documents/${DOC}`, title: "Акт" };
      docs[DOC] = doc; return reply({ documents: [doc] });
    }
    if (method === "GET" && u.pathname === "/api/v2/documents") return reply({ documents: Object.values(docs).filter((d) => u.searchParams.getAll("ids").includes(d.id)) });
    if (method === "GET" && u.pathname === "/api/v2/incoming-documents") {
      const ids = u.searchParams.getAll("ids");
      return reply({ documents: ids.length ? incoming.filter((d) => ids.includes(d.id)) : incoming, next_cursor: null });
    }
    if (u.pathname.endsWith("/comments") && method === "GET") return reply({ comments: [{ type: "comment", text: "x" }, { type: "rejection", text: "Не та сума" }] });
    if (u.pathname.endsWith("/comments")) return reply({});
    if (u.pathname.endsWith("/p7s") || u.pathname.endsWith("/original")) return new Response(new Uint8Array([1, 2, 3]));
    if (method === "DELETE") { delete docs[DOC]; return reply(""); }
    if (u.pathname.endsWith("/reject") || u.pathname.endsWith("/signers")) return reply({});
    return reply({ reason: "no route" }, 404);
  };
});

const req = (method, path, body) => new Request(`https://bridge.example.com${path}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const payload = { id: "uuid-1", provider: "vchasno", kind: "act", number: "INV/2026/00012", date: "2026-10-31",
  amount: 1500.0, currency: "UAH", sender: { code: OWNER, name: "ТОВ Компанія" },
  recipient: { code: BUYER, name: "ТОВ Покупець", email: "buyer@example.com" }, note: "Підпишіть, будь ласка",
  file: { name: "Акт INV-2026-00012.pdf", mimetype: "application/pdf", data: btoa("%PDF-1.4") } };

test("send: upload with parameters, one document per uuid", async () => {
  const e = env();
  const [status, data] = await edoRoute(e, req("POST", "/api/edo/documents", payload), "/api/edo/documents");
  assert.equal(status, 200);
  assert.deepEqual(data, { id: `vchasno:${OWNER}:${DOC}`, status: "to_sign", url: `https://edo.vchasno.ua/app/documents/${DOC}` });
  const upload = calls.find((c) => c.method === "POST" && c.path === "/api/v2/documents");
  assert.equal(upload.params.get("amount"), "150000", "сума в копійках");
  assert.equal(upload.params.get("category"), "1", "акт наданих послуг");
  assert.equal(upload.params.get("recipient_edrpou"), BUYER);
  assert.equal(upload.params.get("doc_number"), "INV/2026/00012");
  const file = upload.init.body.get("file");
  assert.equal(file.name, `${OWNER}_${BUYER}_20261031_Акт-INV-2026-00012_INV-2026-00012_buyer@example.com_uuid-1.pdf`);
  assert.ok(calls.some((c) => c.path.endsWith("/comments")), "коментар контрагенту");

  const uploads = () => calls.filter((c) => c.method === "POST" && c.path === "/api/v2/documents").length;
  const [, again] = await edoRoute(e, req("POST", "/api/edo/documents", payload), "/api/edo/documents");
  assert.equal(again.id, data.id);
  assert.equal(uploads(), 1, "повтор не завантажує вдруге");
});

test("status: codes, rejection reason, signed container", async () => {
  docs[DOC] = { id: DOC, status: 7004, url: "u", title: "Акт" };
  const path = `/api/edo/documents/${encodeURIComponent(`vchasno:${OWNER}:${DOC}`)}`;
  assert.equal((await edoRoute(env(), req("GET", path), path))[1].status, "sent");
  docs[DOC] = { id: DOC, status: 7006, url: "u", title: "Акт", date_finished: "2026-11-02T10:00:00+02:00" };
  const [, rejected] = await edoRoute(env(), req("GET", path), path);
  assert.deepEqual([rejected.status, rejected.reason], ["rejected", "Не та сума"]);
  docs[DOC] = { id: DOC, status: 7008, url: "u", title: "Акт", date_finished: "2026-11-03T10:00:00+02:00" };
  const [, signed] = await edoRoute(env(), req("GET", path), path);
  assert.equal(signed.status, "signed");
  assert.equal(signed.signed_at, "2026-11-03T10:00:00+02:00");
  assert.deepEqual(signed.signed_file, { name: "Акт.p7s", mimetype: "application/pkcs7-mime", data: "AQID" });
});

test("revoke, reject, sign; unknown ids and adapters", async () => {
  docs[DOC] = { id: DOC, status: 7004, url: "u" };
  const id = encodeURIComponent(`vchasno:${OWNER}:${DOC}`);
  const p = (s) => `/api/edo/documents/${id}/${s}`;
  assert.deepEqual((await edoRoute(env(), req("POST", p("revoke"), {}), p("revoke")))[1].status, "revoked");
  assert.ok(calls.some((c) => c.method === "DELETE"));

  incoming = [{ id: DOC, status: 7004, url: "u" }];
  const [rs, rd] = await edoRoute(env(), req("POST", p("reject"), {}), p("reject"));
  assert.deepEqual([rs, rd.error], [400, "вкажіть причину відхилення"]);
  await edoRoute(env(), req("POST", p("reject"), { reason: "Чужий документ" }), p("reject"));
  const rej = calls.find((c) => c.path.endsWith("/reject"));
  assert.equal(JSON.parse(rej.init.body).text, "Чужий документ");

  const e = { ...env(), VCHASNO_SIGNERS: JSON.stringify({ [OWNER]: ["role-1"] }) };
  const [, signed] = await edoRoute(e, req("POST", p("sign"), {}), p("sign"));
  assert.equal(signed.status, "to_sign", "підпис ставлять КЕП у сервісі");
  assert.deepEqual(JSON.parse(calls.find((c) => c.path.endsWith("/signers")).init.body).signer_entities, [{ type: "role", id: "role-1" }]);

  const bad = "/api/edo/documents/medoc%3A1";
  assert.equal((await edoRoute(env(), req("GET", bad), bad))[0], 501);
  const [s2, d2] = await edoRoute(env(), req("POST", "/api/edo/documents", { ...payload, sender: { code: "11111111" } }), "/api/edo/documents");
  assert.deepEqual([s2, d2.error], [400, "немає токена Вчасно для ЄДРПОУ 11111111"]);
});

test("inbox: incoming documents with files, cursor from the last one", async () => {
  incoming = [
    { id: "b", status: 7004, category: 5, number: "ВН-7", date: "2026-11-05", amount: 120050, edrpou_owner: BUYER,
      company_name: "ТОВ Постачальник", title: "Накладна", extension: ".pdf", url: "ub", date_created: "2026-11-05T09:30:00+02:00" },
    { id: "a", status: 7004, category: 2, number: "СФ-1", date: "2026-11-04", amount: 5000, edrpou_owner: BUYER,
      company_name: "ТОВ Постачальник", title: "Рахунок", extension: ".pdf", url: "ua", date_created: "2026-11-04T08:00:00+02:00" },
  ];
  const [status, data] = await edoRoute(env(), req("POST", "/api/edo/inbox", { company: OWNER, provider: "vchasno", after: "2026-11-01T00:00" }), "/api/edo/inbox");
  assert.equal(status, 200);
  assert.deepEqual(data.documents.map((d) => [d.id, d.kind, d.amount]), [[`vchasno:${OWNER}:a`, "invoice", 50], [`vchasno:${OWNER}:b`, "waybill", 1200.5]]);
  assert.deepEqual(data.documents[1].sender, { code: BUYER, name: "ТОВ Постачальник" });
  assert.equal(data.documents[0].file.data, "AQID");
  assert.equal(data.cursor, "2026-11-05T09:30");
  assert.equal(calls[0].params.get("date_created_from"), "2026-11-01T00:00");
});
