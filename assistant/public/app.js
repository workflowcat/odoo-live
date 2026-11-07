/* Помічник для працівників - client. Plain DOM, no framework. */
(function () {
  "use strict";
  const app = document.getElementById("app");
  const S = { me: null, tab: "chat", messages: [], busy: false, slips: null, slipId: null, leaves: null, requests: null, password: "" };
  const QUICK = [
    "Скільки днів відпустки в мене лишилось?",
    "Поясни мій останній розрахунковий листок.",
    "Скільки я отримав на руки за останні три місяці?",
    "Чому сума на руки менша за оклад?",
    "Який у мене страховий стаж і скільки платять за лікарняний?",
    "Які відпустки в мене були цього року?",
  ];

  // ---------- helpers ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : String(kid));
    return el;
  }
  function sp(name, big) {
    const c = h("canvas", { class: "sp" + (big ? " big" : ""), "aria-hidden": "true" });
    try { PixelKit.drawSprite(c, name, null, true); } catch (e) {}
    return c;
  }
  const money = (n) => {
    if (n === null || n === undefined) return "-";
    const [i, d] = Math.abs(Number(n)).toFixed(2).split(".");
    return (n < 0 ? "-" : "") + i.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + "," + d;
  };
  const num = (n) => String(Math.round(Number(n || 0) * 10) / 10).replace(".", ",");
  const date = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join(".") : "");
  const time = () => new Date().toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" });
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const stateClass = (s) => ({ validate: "ok", confirm: "warn", validate1: "warn", refuse: "crit", cancel: "faint", done: "ok", verify: "warn" })[s] || "muted";
  const store = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(k) || "null"); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };

  async function api(path, opts) {
    const o = Object.assign({ headers: {} }, opts || {});
    if (o.body && typeof o.body !== "string") { o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
    let slow = setTimeout(() => wake(true), 4000);
    try {
      const res = await fetch(path, o);
      const data = await res.json().catch(() => ({}));
      if (res.status === 401 && data.access) { S.me = null; renderLogin(data.error, true); throw new Error(data.error); }
      if (res.status === 401 && path !== "/api/login") { S.me = null; renderLogin(); throw new Error(data.error || "Потрібно увійти."); }
      if (!res.ok) throw new Error(data.error || "Помилка " + res.status);
      return data;
    } finally { clearTimeout(slow); wake(false); }
  }
  function wake(on) {
    let w = document.getElementById("wake");
    if (on && !w) { w = h("div", { id: "wake", class: "toast" }, "Odoo запускається. Це займає до 30 секунд."); document.body.append(w); }
    if (!on && w) w.remove();
  }
  function toast(text) {
    const t = h("div", { class: "toast", role: "status" }, text);
    document.body.append(t);
    setTimeout(() => t.remove(), 4200);
  }

  // Light markdown: paragraphs, "- " lists, **bold**, numbers in mono.
  function rich(text) {
    const lines = esc(text).split(/\n/);
    let html = "", list = false, para = [];
    const flush = () => { if (para.length) { html += "<p>" + para.join("<br>") + "</p>"; para = []; } };
    for (const raw of lines) {
      const line = raw.trim();
      const li = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (li) { flush(); if (!list) { html += "<ul>"; list = true; } html += "<li>" + li[1] + "</li>"; continue; }
      if (list) { html += "</ul>"; list = false; }
      if (!line) { flush(); continue; }
      para.push(line);
    }
    flush(); if (list) html += "</ul>";
    return html
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(>«:])(-?\d[\d  ]*(?:[.,]\d+)?(?:\s?%)?)/g, (m, pre, n) => pre + '<span class="num">' + n + "</span>");
  }

  // ---------- login ----------
  function renderLogin(err, accessOnly) {
    app.replaceChildren();
    const pwd = h("input", { type: "password", id: "pw", autocomplete: "current-password", required: true });
    const error = h("p", { class: "error", role: "alert" }, err || "");
    const pick = h("div", { class: "pick", hidden: true });
    const btn = h("button", { type: "submit" }, "Увійти");
    const form = h("form", {
      onsubmit: async (e) => {
        e.preventDefault(); error.textContent = ""; btn.disabled = true;
        try {
          S.password = pwd.value;
          const r = await api("/api/login", { method: "POST", body: { password: pwd.value } });
          if (r.ok) return boot();
          if (r.pick) {
            form.hidden = true; pick.hidden = false; title.textContent = "Оберіть працівника";
            lead.textContent = "Це тестовий стенд. Оберіть, від чийого імені перевірити помічника.";
            pick.replaceChildren(...r.pick.map((p) => h("button", { type: "button", onclick: () => choose(p.id) },
              sp("person"), h("span", {}, p.name), h("span", { class: "sub" }, [p.job, p.department].filter(Boolean).join(" · ")))));
          }
        } catch (x) { error.textContent = x.message; } finally { btn.disabled = false; }
      },
    }, h("div", { class: "field" }, h("label", { for: "pw" }, "Пароль"), pwd), btn);
    async function choose(id) {
      try { await api("/api/login", { method: "POST", body: { password: S.password, employee_id: id } }); S.password = ""; boot(); }
      catch (x) { error.textContent = x.message; }
    }
    const title = h("h1", {}, "Помічник для працівників");
    const lead = h("p", { class: "lead" }, "Питання про відпустки, зарплату і довідки. Відповіді беруться з облікової системи компанії.");
    if (accessOnly) form.hidden = true;   // вхід лише через Cloudflare Access: пароля тут немає
    app.append(h("div", { class: "login" }, h("div", { class: "brand" }, sp("catvader", true), title), lead, form, pick, error));
    if (!accessOnly) setTimeout(() => pwd.focus(), 30);
  }

  // ---------- shell ----------
  async function boot() {
    try { S.me = await api("/api/me"); }
    catch (e) { if (!S.me) { if (document.querySelector(".login")) return; return renderLogin(e.message === "Потрібно увійти." ? "" : e.message); } }
    S.messages = store.get("chat:" + S.me.profile.id) || [];
    S.slips = S.leaves = S.requests = null;
    renderShell();
  }

  function renderShell() {
    const p = S.me.profile;
    const top = h("header", { class: "top" }, sp("catvader"),
      h("div", {}, h("div", { class: "name" }, "Помічник"), h("div", { class: "company" }, p.company)),
      h("div", { class: "spacer" }),
      h("div", { class: "user" }, p.name, h("br"), h("span", { class: "faint" }, S.me.dev ? "локальний режим" : p.email)),
      S.me.dev ? null : h("button", { class: "line small", onclick: logout }, "Вийти"));

    const last = S.me.lastSlip;
    const aside = h("aside", {},
      h("div", { class: "me" }, h("h1", {}, p.name), h("p", { class: "role" }, [p.job, p.department].filter(Boolean).join(", ")),
        p.manager ? h("p", { class: "faint mono", style: "font-size:12px;margin-top:4px" }, "Керівник: " + p.manager) : null),
      h("div", { class: "stats" },
        stat("clock", "Залишок відпустки", num(p.vacation.balance), "дн."),
        stat("calc", last ? "На руки, " + last.period : "Останній листок", last ? money(last.net) : "-", last ? "грн" : ""),
        stat("money", "Оклад", money(p.wage), "грн"),
        stat("books", "Страховий стаж", num(p.insuranceYears), "р."),
        stat("heart", "Лікарняні", num(p.sickPercent), "%")),
      h("div", { class: "actions" }, h("h3", {}, "Запити"),
        ...Object.entries(S.me.requests).map(([k, r]) => h("div", { class: "act" }, sp(r.sprite), h("button", { class: "line", onclick: () => openForm(k) }, r.label)))));

    const tabs = h("nav", { class: "tabs", role: "tablist" },
      tab("chat", "Розмова"), tab("slips", "Розрахункові листки"), tab("leaves", "Відпустки"), tab("requests", "Мої запити"));
    const view = h("section", { class: "view", id: "view" });
    app.replaceChildren(top, h("div", { class: "shell" }, aside, h("main", {}, tabs, view)));
    renderView();
  }
  function stat(sprite, k, v, unit) {
    return h("div", { class: "stat" }, sp(sprite), h("div", { class: "k" }, k), h("div", { class: "v" }, v, unit ? h("small", {}, " " + unit) : null));
  }
  function tab(id, label) {
    return h("button", { role: "tab", "aria-selected": String(S.tab === id), onclick: () => { S.tab = id; renderShell(); } }, label);
  }
  async function logout() { await fetch("/api/logout", { method: "POST" }); S.me = null; renderLogin(); }

  function renderView() {
    const view = document.getElementById("view");
    if (S.tab === "chat") return renderChat(view);
    if (S.tab === "slips") return renderSlips(view);
    if (S.tab === "leaves") return renderLeaves(view);
    if (S.tab === "requests") return renderRequests(view);
  }

  // ---------- chat ----------
  function renderChat(view) {
    const log = h("div", { class: "log", id: "log" });
    if (!S.messages.length) {
      log.append(h("div", { class: "msg" }, sp("catvader"), h("div", { class: "who" }, "Помічник"),
        h("div", { class: "text" }, h("div", { class: "empty" },
          h("p", {}, "Я відповідаю на питання про вашу відпустку, розрахункові листки і стаж. Дані беру з облікової системи. Запит до HR можна подати кнопкою ліворуч."),
          h("div", { class: "chips" }, ...QUICK.map((q) => h("button", { class: "line", onclick: () => send(q) }, q)))))));
    }
    for (const m of S.messages) log.append(messageRow(m));
    const ta = h("textarea", { id: "q", rows: "1", placeholder: "Напишіть питання", "aria-label": "Питання" });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 180) + "px"; });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(ta.value); } });
    const composer = h("div", { class: "composer" },
      S.messages.length ? h("div", { class: "chips" }, ...QUICK.slice(0, 4).map((q) => h("button", { class: "line", onclick: () => send(q), disabled: S.busy }, q))) : null,
      h("div", { class: "row" }, ta, h("button", { onclick: () => send(ta.value), disabled: S.busy }, "Надіслати")),
      h("div", { class: "hint" }, "Enter надсилає. Shift+Enter переносить рядок." + (S.messages.length ? " " : ""),
        S.messages.length ? h("button", { class: "quiet small", onclick: clearChat }, "Почати нову розмову") : null));
    view.replaceChildren(log, composer);
    log.scrollTop = log.scrollHeight;
    if (!S.busy) ta.focus();
  }
  function messageRow(m) {
    const mine = m.role === "user";
    const text = h("div", { class: "text", html: mine ? esc(m.content).replace(/\n/g, "<br>") : rich(m.content) });
    const row = h("div", { class: "msg" + (mine ? " user" : "") }, sp(mine ? "person" : "catvader"),
      h("div", { class: "who" }, (mine ? "Ви" : "Помічник") + (m.at ? " · " + m.at : "")), text);
    if (!mine && m.action && S.me.requests[m.action]) {
      const r = S.me.requests[m.action];
      row.append(h("div", { class: "suggest" }, h("button", { onclick: () => openForm(m.action) }, r.label)));
    }
    return row;
  }
  async function send(q) {
    q = String(q || "").trim();
    if (!q || S.busy) return;
    S.busy = true;
    S.messages.push({ role: "user", content: q, at: time() });
    renderChat(document.getElementById("view"));
    const log = document.getElementById("log");
    const pending = h("div", { class: "msg" }, sp("catvader"), h("div", { class: "who" }, "Помічник"), h("div", { class: "text muted" }, "Готую відповідь ", h("span", { class: "cursor" })));
    log.append(pending); log.scrollTop = log.scrollHeight;
    try {
      const r = await api("/api/chat", { method: "POST", body: { messages: S.messages.map(({ role, content }) => ({ role, content })) } });
      S.messages.push({ role: "assistant", content: r.text || "Відповіді немає. Спробуйте поставити питання інакше.", action: r.action, at: time() });
    } catch (e) {
      S.messages.push({ role: "assistant", content: "Не вдалося отримати відповідь: " + e.message, at: time() });
    } finally {
      S.busy = false;
      store.set("chat:" + S.me.profile.id, S.messages.slice(-40));
      if (S.tab === "chat") renderChat(document.getElementById("view"));
    }
  }
  function clearChat() { S.messages = []; store.set("chat:" + S.me.profile.id, []); renderChat(document.getElementById("view")); }

  // ---------- payslips ----------
  async function renderSlips(view) {
    view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "muted mono" }, "Завантажую листки")));
    try { if (!S.slips) S.slips = (await api("/api/payslips")).payslips; } catch (e) { return view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "error" }, e.message))); }
    if (!S.slips.length) return view.replaceChildren(h("div", { class: "pane" }, h("h2", {}, "Розрахункові листки"), h("p", { class: "muted" }, "Закритих листків ще немає.")));
    if (!S.slipId) S.slipId = S.slips[0].id;
    const cur = S.slips.find((s) => s.id === S.slipId) || S.slips[0];
    const list = h("div", { class: "rows" }, ...S.slips.map((s) => h("button", { class: "rowi", "aria-current": String(s.id === cur.id), onclick: () => { S.slipId = s.id; renderSlips(view); } },
      sp("calc"), h("span", { class: "t" }, s.period), h("span", { class: "r" }, money(s.net), h("small", {}, "на руки")),
      h("span", { class: "s " + stateClass(s.state) }, s.stateLabel + (s.number ? " · " + s.number : "")))));
    const table = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Рядок"), h("th", {}, "Сума, грн"))),
      h("tbody", {}, ...cur.lines.map((l) => h("tr", { class: l.code === "NET" ? "total" : "" }, h("td", {}, l.name), h("td", { class: "amt" }, money(l.total))))));
    const detail = h("div", { style: "display:grid;gap:22px" },
      h("div", { class: "head" }, h("h2", {}, "Листок за " + cur.period),
        h("a", { class: "btn line small", href: "/api/payslips/" + cur.id + "/pdf", target: "_blank", rel: "noopener" }, "Відкрити PDF"),
        h("button", { class: "small", onclick: () => { S.tab = "chat"; renderShell(); send("Поясни мій розрахунковий листок за " + cur.period + "."); } }, "Пояснити в розмові")),
      h("div", { class: "bigrow" },
        h("div", { class: "big" }, h("span", { class: "v" }, money(cur.gross)), h("span", { class: "k" }, "нараховано, грн")),
        h("div", { class: "big" }, h("span", { class: "v ok" }, money(cur.net)), h("span", { class: "k" }, "на руки, грн"))),
      h("p", { class: "faint mono", style: "font-size:12px" }, date(cur.from) + " - " + date(cur.to) + " · " + cur.stateLabel),
      table);
    view.replaceChildren(h("div", { class: "pane" }, h("div", { class: "slipgrid" }, list, detail)));
  }

  // ---------- leaves ----------
  async function renderLeaves(view) {
    view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "muted mono" }, "Завантажую відпустки")));
    let d;
    try { d = S.leaves || (S.leaves = await api("/api/leaves")); } catch (e) { return view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "error" }, e.message))); }
    const v = d.vacation || { perYear: 0, accrued: 0, used: 0, balance: 0 };
    const total = Math.max(v.perYear, v.balance + v.used, 1);
    const bar = h("div", { class: "bar", role: "img", "aria-label": "Використано " + num(v.used) + ", залишок " + num(v.balance) + " днів" },
      h("i", { class: "used", style: "width:" + (v.used / total) * 100 + "%" }), h("i", { style: "width:" + (v.balance / total) * 100 + "%" }), h("i", { class: "rest" }));
    view.replaceChildren(h("div", { class: "pane" },
      h("div", { class: "head" }, h("h2", {}, "Щорічна відпустка"), h("button", { class: "small", onclick: () => openForm("leave") }, "Подати заяву")),
      h("div", { class: "bigrow" },
        h("div", { class: "big" }, h("span", { class: "v ok" }, num(v.balance)), h("span", { class: "k" }, "залишок, дн.")),
        h("div", { class: "big" }, h("span", { class: "v" }, num(v.used)), h("span", { class: "k" }, "використано, дн.")),
        h("div", { class: "big" }, h("span", { class: "v" }, num(v.accrued)), h("span", { class: "k" }, "накопичено цього року, дн.")),
        h("div", { class: "big" }, h("span", { class: "v" }, v.perYear), h("span", { class: "k" }, "днів на рік"))),
      bar,
      h("h2", {}, "Відпустки, лікарняні, відрядження"),
      d.leaves.length ? h("div", { class: "rows" }, ...d.leaves.map((l) => h("div", { class: "rowi" }, sp(/непрацезд|хвор/i.test(l.type) ? "heart" : /відряд/i.test(l.type) ? "truck" : "clock"),
        h("span", { class: "t" }, l.type), h("span", { class: "r" }, num(l.days), h("small", {}, "дн.")),
        h("span", { class: "s" }, date(l.from) + " - " + date(l.to) + " · ", h("span", { class: stateClass(l.state) }, l.stateLabel)))))
        : h("p", { class: "muted" }, "Записів немає.")));
  }

  // ---------- requests ----------
  async function renderRequests(view) {
    view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "muted mono" }, "Завантажую запити")));
    let d;
    try { d = S.requests || (S.requests = await api("/api/requests")); } catch (e) { return view.replaceChildren(h("div", { class: "pane" }, h("p", { class: "error" }, e.message))); }
    const rows = [
      ...d.leaves.map((l) => h("div", { class: "rowi" }, sp("clock"), h("span", { class: "t" }, l.type), h("span", { class: "r " + stateClass(l.state) }, l.stateLabel),
        h("span", { class: "s" }, date(l.from) + " - " + date(l.to) + " · " + num(l.days) + " дн."))),
      ...d.requests.map((r) => h("div", { class: "rowi" }, sp(spriteFor(r.title)), h("span", { class: "t" }, r.title), h("span", { class: "r warn" }, "в роботі"),
        h("span", { class: "s" }, "подано " + date(r.created) + " · виконавець " + r.owner + " · строк " + date(r.deadline)))),
    ];
    view.replaceChildren(h("div", { class: "pane" },
      h("div", { class: "head" }, h("h2", {}, "Мої запити"), h("button", { class: "line small", onclick: () => { S.requests = null; renderRequests(view); } }, "Оновити")),
      rows.length ? h("div", { class: "rows" }, ...rows) : h("p", { class: "muted" }, "Відкритих запитів немає. Виконані запити зникають з цього переліку."),
      rows.length ? h("p", { class: "note" }, "Виконані запити зникають з цього переліку.") : null));
  }
  function spriteFor(title) {
    const e = Object.values(S.me.requests).find((r) => r.label === title);
    return e ? e.sprite : "doc";
  }

  // ---------- request forms ----------
  function openForm(kind) {
    const def = S.me.requests[kind];
    if (!def) return;
    const p = S.me.profile;
    const fields = kind === "leave" ? [
      { name: "type", label: "Вид відпустки", type: "select", options: S.me.leaveTypes.map((t) => t.name), required: true },
      { name: "date_from", label: "Перший день", type: "date", required: true },
      { name: "date_to", label: "Останній день", type: "date", required: true },
      { name: "note", label: "Коментар", type: "textarea" },
    ] : def.fields;
    const err = h("p", { class: "error", role: "alert" });
    const submit = h("button", { type: "submit" }, "Надіслати");
    const inputs = fields.map((f) => {
      const id = "f-" + f.name;
      let input;
      if (f.type === "select") input = h("select", { id, name: f.name, required: f.required }, ...f.options.map((o) => h("option", { value: o }, o)));
      else if (f.type === "textarea") input = h("textarea", { id, name: f.name, rows: "3", required: f.required, placeholder: f.placeholder });
      else input = h("input", { id, name: f.name, type: f.type, required: f.required, placeholder: f.placeholder, value: f.value, min: f.type === "number" ? "1" : null });
      if (f.type === "date") input.min = S.me.today;
      return h("div", { class: "field" }, h("label", { for: id }, f.label + (f.required ? "" : " · необов'язково")), input);
    });
    const close = () => { scrim.remove(); panel.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    const form = h("form", {
      onsubmit: async (e) => {
        e.preventDefault(); err.textContent = ""; submit.disabled = true;
        const values = Object.fromEntries(new FormData(form).entries());
        try {
          const r = await api("/api/requests", { method: "POST", body: { kind, values } });
          close(); toast(r.message);
          S.requests = null; S.leaves = null;
          S.messages.push({ role: "assistant", content: r.message, at: time() });
          store.set("chat:" + p.id, S.messages.slice(-40));
          if (S.tab === "chat") renderChat(document.getElementById("view")); else renderView();
        } catch (x) { err.textContent = x.message; } finally { submit.disabled = false; }
      },
    },
      kind === "leave" ? h("p", { class: "note" }, "Залишок щорічної відпустки: ", h("span", { class: "num" }, num(p.vacation.balance)), " дн. Заява піде на погодження керівнику.") :
        h("p", { class: "note" }, "Запит отримає HR у системі обліку. Відповідь прийде від HR."),
      ...inputs, err, h("div", { class: "btns" }, submit, h("button", { type: "button", class: "line", onclick: () => close() }, "Скасувати")));
    const scrim = h("div", { class: "scrim", onclick: () => close() });
    const panel = h("div", { class: "panel", role: "dialog", "aria-modal": "true", "aria-label": def.label },
      h("div", { class: "ph" }, sp(def.sprite), h("h2", {}, def.label), h("button", { class: "quiet", onclick: () => close(), "aria-label": "Закрити" }, "Закрити")), form);
    document.body.append(scrim, panel);
    document.addEventListener("keydown", onKey);
    setTimeout(() => panel.querySelector("input,select,textarea")?.focus(), 30);
  }

  boot();
})();
