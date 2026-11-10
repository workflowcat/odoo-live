// Vchasno.EDO adapter for the /api/edo routes (contract: docs/base/spec-edo.md).
// API: "API Вчасно.ЕДО" instruction, host https://edo.vchasno.ua, header "Authorization: <token>".
// One token per company (user + company in Vchasno): secret VCHASNO_TOKENS = {"<ЄДРПОУ>": "<token>"},
// or VCHASNO_TOKEN for a single company. Odoo never sees these tokens.
//
// Our document id is "vchasno:<ЄДРПОУ>:<Vchasno id>", so every later call knows which token to use.
// Vchasno does not sign for us: a document is signed with a qualified key in the service. "sign" therefore
// hands the document to the company's signers (VCHASNO_SIGNERS = {"<ЄДРПОУ>": ["<role id>", ...]}) and
// answers "to_sign"; Odoo learns "signed" from the status later.

const API = "https://edo.vchasno.ua";
const PAGE_LIMIT = 20; // pages of the incoming list per call
const INBOX_BATCH = 30; // documents with files per call

// Vchasno status -> contract status. Outgoing and incoming documents share the codes.
export const STATUS = {
  7000: "queued", 7001: "to_sign", 7002: "sent", 7003: "to_sign", 7004: "sent", 7006: "rejected",
  7007: "delivered", 7008: "signed", 7010: "sent", 7011: "revoked",
};
const KIND_TO_CATEGORY = { act: 1, invoice: 2, contract: 3, waybill: 5, reconciliation: 16, other: 15 };
const CATEGORY_TO_KIND = { 1: "act", 2: "invoice", 3: "contract", 4: "contract", 5: "waybill", 16: "reconciliation" };

export class EdoError extends Error {
  constructor(message, status = 502) { super(message); this.status = status; }
}

export function encodeId(company, id) { return `vchasno:${company}:${id}`; }

export function decodeId(value) {
  const m = /^vchasno:(\d{8,10}):([\w-]+)$/.exec(String(value || ""));
  if (!m) throw new EdoError("невідомий номер документа", 404);
  return { company: m[1], id: m[2] };
}

function tokenFor(env, company) {
  let map = {};
  if (env.VCHASNO_TOKENS) {
    try { map = JSON.parse(env.VCHASNO_TOKENS); } catch { throw new EdoError("VCHASNO_TOKENS is not JSON", 500); }
  }
  const token = map[company] || env.VCHASNO_TOKEN;
  if (!token) throw new EdoError(`немає токена Вчасно для ЄДРПОУ ${company || "?"}`, 400);
  return token;
}

const b64 = (buf) => {
  const bytes = new Uint8Array(buf); let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
const unb64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
const clean = (text, max = 80) => String(text || "").replace(/[_/\\:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "").slice(0, max) || "-";
const kopecks = (amount) => (amount == null ? null : Math.round(Number(amount) * 100));

async function call(env, token, method, path, { params, json, form, binary } = {}) {
  const url = new URL(path, env.VCHASNO_API || API);
  for (const [k, v] of Object.entries(params || {})) {
    for (const item of Array.isArray(v) ? v : [v]) if (item != null && item !== "") url.searchParams.append(k, String(item));
  }
  const init = { method, headers: { Authorization: token }, signal: AbortSignal.timeout(40000) };
  if (json) { init.headers["content-type"] = "application/json"; init.body = JSON.stringify(json); }
  if (form) init.body = form;
  const r = await fetch(url, init);
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    let message = text.slice(0, 300);
    try { const data = JSON.parse(text); message = data.reason || data.message || data.error || message; } catch { /* text */ }
    throw new EdoError(`Вчасно ${r.status}: ${message}`, r.status >= 500 ? 502 : r.status);
  }
  if (binary) return r.arrayBuffer();
  const text = await r.text();
  return text ? JSON.parse(text) : {};
}

// ---------------------------------------------------------------- idempotency (D1, created on first use)
let tableReady = false;
async function remembered(env, uuid) {
  if (!env.DB || !uuid) return null;
  if (!tableReady) {
    await env.DB.prepare("CREATE TABLE IF NOT EXISTS edo_sent (uuid TEXT PRIMARY KEY, provider_id TEXT NOT NULL, created_at TEXT NOT NULL)").run();
    tableReady = true;
  }
  const row = await env.DB.prepare("SELECT provider_id FROM edo_sent WHERE uuid = ?1").bind(uuid).first();
  return row ? row.provider_id : null;
}
async function remember(env, uuid, providerId) {
  if (!env.DB || !uuid) return;
  await env.DB.prepare("INSERT OR IGNORE INTO edo_sent (uuid, provider_id, created_at) VALUES (?1, ?2, ?3)")
    .bind(uuid, providerId, new Date().toISOString()).run();
}
export function resetForTests() { tableReady = false; }

// ---------------------------------------------------------------- documents
async function findDocument(env, token, id) {
  for (const path of ["/api/v2/documents", "/api/v2/incoming-documents"]) {
    const data = await call(env, token, "GET", path, { params: { ids: id } });
    const doc = (data.documents || []).find((d) => d.id === id);
    if (doc) return doc;
  }
  throw new EdoError("документа немає у Вчасно", 404);
}

function view(company, doc) {
  return { id: encodeId(company, doc.id), status: STATUS[doc.status] || `vchasno_${doc.status}`, url: doc.url || null };
}

export async function send(env, payload) {
  const company = String(payload?.sender?.code || "");
  const token = tokenFor(env, company);
  const known = await remembered(env, payload.id);
  if (known) {
    const { id } = decodeId(known);
    return view(company, await findDocument(env, token, id));
  }
  const recipient = payload.recipient || {};
  const file = payload.file || {};
  if (!file.data) throw new EdoError("немає файла документа", 400);
  if (!/^\d{8}$|^\d{10}$/.test(String(recipient.code || ""))) throw new EdoError("немає ЄДРПОУ чи РНОКПП контрагента", 400);
  const date = String(payload.date || "").replaceAll("-", "");
  const ext = (/\.[a-z0-9]{2,5}$/i.exec(file.name || "") || [".pdf"])[0].toLowerCase();
  const title = clean(String(file.name || payload.kind || "Документ").replace(/\.[a-z0-9]{2,5}$/i, ""));
  // Name in Vchasno's own format, so the service shows the parties even without the parameters below.
  const parts = [company, recipient.code, date, title, clean(payload.number, 40)];
  if (recipient.email) parts.push(String(recipient.email).split(/[,;\s]+/)[0], payload.id);
  const form = new FormData();
  form.append("file", new Blob([unb64(file.data)], { type: file.mimetype || "application/pdf" }), parts.join("_") + ext);
  const params = {
    title, doc_number: payload.number, date_document: payload.date, amount: kopecks(payload.amount),
    category: KIND_TO_CATEGORY[payload.kind] ?? 15, recipient_edrpou: recipient.code,
    recipient_emails: recipient.email ? String(recipient.email).split(/[,;\s]+/).filter(Boolean) : null,
  };
  const data = await call(env, token, "POST", "/api/v2/documents", { params, form });
  const doc = (data.documents || [])[0];
  if (!doc || !doc.id) throw new EdoError("Вчасно не повернуло номер документа");
  const out = view(company, doc);
  await remember(env, payload.id, out.id);
  if (payload.note) {
    await call(env, token, "POST", `/api/v2/documents/${doc.id}/comments`, { json: { text: payload.note, is_internal: false } })
      .catch(() => null); // a comment is optional; the document is already there
  }
  return out;
}

export async function status(env, providerId) {
  const { company, id } = decodeId(providerId);
  const token = tokenFor(env, company);
  const doc = await findDocument(env, token, id);
  const out = view(company, doc);
  if (doc.date_finished) out.signed_at = doc.date_finished;
  if (doc.status === 7006) {
    const data = await call(env, token, "GET", `/api/v2/documents/${id}/comments`).catch(() => ({}));
    const rejection = (data.comments || []).filter((c) => c.type === "rejection").pop();
    out.reason = rejection ? rejection.text : null;
  }
  if (doc.status === 7008) {
    const p7s = await call(env, token, "GET", `/api/v2/documents/${id}/p7s`, { binary: true }).catch(() => null);
    if (p7s) out.signed_file = { name: `${clean(doc.title || id)}.p7s`, mimetype: "application/pkcs7-mime", data: b64(p7s) };
  }
  return out;
}

export async function revoke(env, providerId) {
  const { company, id } = decodeId(providerId);
  const token = tokenFor(env, company);
  const doc = await findDocument(env, token, id);
  if (doc.status === 7008) throw new EdoError("документ уже підписано сторонами: його видаляють запитом до контрагента", 409);
  await call(env, token, "DELETE", `/api/v2/documents/${id}`);
  return { id: providerId, status: "revoked" };
}

export async function reject(env, providerId, body) {
  const { company, id } = decodeId(providerId);
  const reason = String(body?.reason || "").trim();
  if (!reason) throw new EdoError("вкажіть причину відхилення", 400);
  await call(env, tokenFor(env, company), "POST", `/api/v2/documents/${id}/reject`, { json: { text: reason } });
  return { id: providerId, status: "rejected" };
}

export async function sign(env, providerId) {
  const { company, id } = decodeId(providerId);
  const token = tokenFor(env, company);
  const doc = await findDocument(env, token, id);
  if (doc.status === 7008) return view(company, doc);
  let roles = [];
  if (env.VCHASNO_SIGNERS) {
    try { roles = JSON.parse(env.VCHASNO_SIGNERS)[company] || []; } catch { throw new EdoError("VCHASNO_SIGNERS is not JSON", 500); }
  }
  if (roles.length) {
    await call(env, token, "POST", `/api/v2/documents/${id}/signers`, {
      json: { signer_entities: roles.map((role) => ({ type: "role", id: role })), is_parallel: true } });
  }
  // The signature itself is made with a qualified key in Vchasno; Odoo sees "signed" on the next status check.
  return { ...view(company, doc), status: "to_sign" };
}

export async function inbox(env, body) {
  const company = String(body?.company || "");
  const token = tokenFor(env, company);
  const since = body?.after || new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 16);
  const all = [];
  let cursor = null;
  for (let page = 0; page < PAGE_LIMIT; page++) {
    const data = await call(env, token, "GET", "/api/v2/incoming-documents",
      { params: { date_created_from: since.slice(0, 16), cursor, with_recipients: 1 } });
    all.push(...(data.documents || []));
    cursor = data.next_cursor;
    if (!cursor) break;
  }
  all.sort((a, b) => String(a.date_created).localeCompare(String(b.date_created)));
  const batch = all.slice(0, INBOX_BATCH);
  const documents = [];
  for (const doc of batch) {
    const original = await call(env, token, "GET", `/api/v2/documents/${doc.id}/original`, { binary: true }).catch(() => null);
    documents.push({
      id: encodeId(company, doc.id), kind: CATEGORY_TO_KIND[doc.category] || "other", number: doc.number || null,
      date: doc.date ? String(doc.date).slice(0, 10) : null, amount: doc.amount == null ? 0 : doc.amount / 100,
      currency: "UAH", status: STATUS[doc.status] || `vchasno_${doc.status}`, url: doc.url || null,
      note: doc.title || null, sender: { code: doc.edrpou_owner || null, name: doc.company_name || null },
      file: original ? { name: `${clean(doc.title || doc.id)}${doc.extension || ".pdf"}`,
                         mimetype: doc.extension === ".xml" ? "application/xml" : "application/pdf", data: b64(original) } : null,
    });
  }
  // Next call starts from the last document taken (inclusive, minute precision); Odoo skips ids it already has.
  const last = batch.length ? String(batch[batch.length - 1].date_created) : null;
  return { documents, cursor: last ? last.slice(0, 16) : (body?.after || null) };
}
