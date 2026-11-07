// What the assistant knows about one employee. Every query filters by the employee id from the session.
import { call } from "./odoo.js";

export const LEAVE_KINDS = ["Щорічна відпустка", "Відпустка без збереження зарплати", "Навчальна відпустка", "Додаткова відпустка на дітей"];
export const LEAVE_STATE = { confirm: "очікує погодження", validate1: "друге погодження", validate: "погоджено", refuse: "відхилено", cancel: "скасовано" };
export const SLIP_STATE = { draft: "чернетка", verify: "перевіряється", done: "закрито", cancel: "скасовано" };
const CONTRACT = { employment: "трудовий договір", gph: "договір ЦПХ", fop: "ФОП-підрядник" };
const FTE = { "1": "повна ставка", "0.75": "0,75 ставки", "0.5": "0,5 ставки", "0.25": "0,25 ставки" };
const PSP = { none: "немає", base: "базова", child: "на дітей", child150: "на дітей, 150 %", s150: "підвищена 150 %", s200: "підвищена 200 %" };
const MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"];

export const REQUESTS = {
  leave: { label: "Заява на відпустку", sprite: "clock" },
  sick: { label: "Лікарняний", sprite: "heart", fields: [
    { name: "date_from", label: "Перший день", type: "date", required: true },
    { name: "date_to", label: "Останній день, якщо відомий", type: "date" },
    { name: "number", label: "Номер листка непрацездатності", type: "text" },
    { name: "note", label: "Коментар", type: "textarea" } ] },
  cert_work: { label: "Довідка з місця роботи", sprite: "doc", fields: [
    { name: "purpose", label: "Куди потрібна довідка", type: "text", required: true },
    { name: "copies", label: "Кількість примірників", type: "number", value: "1" } ] },
  cert_income: { label: "Довідка про доходи", sprite: "money", fields: [
    { name: "period", label: "За який період", type: "text", required: true, placeholder: "січень - серпень 2026" },
    { name: "purpose", label: "Куди потрібна довідка", type: "text", required: true } ] },
  data_change: { label: "Зміна особистих даних", sprite: "key", fields: [
    { name: "what", label: "Що змінити", type: "select", options: ["адреса", "телефон", "банківський рахунок", "прізвище", "інше"], required: true },
    { name: "value", label: "Нове значення", type: "text", required: true },
    { name: "note", label: "Коментар", type: "textarea" } ] },
  question: { label: "Питання до HR або бухгалтерії", sprite: "mail", fields: [
    { name: "to", label: "Кому", type: "select", options: ["HR", "бухгалтерія"], required: true },
    { name: "text", label: "Питання", type: "textarea", required: true } ] },
};

export const kyivToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Kyiv" }).format(new Date());
export const fmtDate = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join(".") : "");
export function fmtMoney(n) {
  const [i, d] = Math.abs(Number(n || 0)).toFixed(2).split(".");
  return (n < 0 ? "-" : "") + i.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + "," + d;
}
const fmtNum = (n) => String(Math.round(Number(n || 0) * 10) / 10).replace(".", ",");
const m2o = (v) => (Array.isArray(v) ? v[1] : "");
const period = (from) => { const [y, m] = from.split("-"); return `${MONTHS[Number(m) - 1]} ${y}`; };

const EMP_FIELDS = ["name", "job_title", "department_id", "parent_id", "company_id", "work_email", "ua_hire_date", "ua_contract_kind", "ua_fte",
  "ua_main_job", "ua_current_wage", "ua_vacation_balance", "ua_vacation_accrued", "ua_vacation_used", "ua_vacation_days_year",
  "ua_insurance_years", "ua_sick_percent", "ua_psp", "ua_psp_children", "ua_days_in_company"];

// Exactly one employee with exactly this work email (case aside), or null. LIKE wildcards in the
// address are escaped, so "%" or "_" never match someone else.
export async function employeeByEmail(env, email) {
  const want = String(email || "").trim().toLowerCase();
  if (!want.includes("@")) return null;
  const pattern = want.replace(/[\\%_]/g, (c) => "\\" + c);
  const r = await call(env, "hr.employee", "search_read", [[["work_email", "=ilike", pattern]]], { fields: ["name", "work_email"], limit: 2 });
  const exact = r.filter((e) => String(e.work_email || "").trim().toLowerCase() === want);
  return exact.length === 1 ? exact[0] : null;
}

export async function pickList(env) {
  const r = await call(env, "hr.employee", "search_read", [[["work_email", "!=", false]]], { fields: ["name", "job_title", "department_id"], order: "name" });
  return r.map((e) => ({ id: e.id, name: e.name, job: e.job_title || "", department: m2o(e.department_id) }));
}

export async function profile(env, id) {
  const r = await call(env, "hr.employee", "read", [[id]], { fields: EMP_FIELDS });
  if (!r.length) return null;
  const e = r[0];
  return {
    id: e.id, name: e.name, job: e.job_title || "", department: m2o(e.department_id), manager: m2o(e.parent_id), company: m2o(e.company_id),
    email: e.work_email || "", hireDate: e.ua_hire_date || "", contract: CONTRACT[e.ua_contract_kind] || "", fte: FTE[e.ua_fte] || "",
    mainJob: !!e.ua_main_job, wage: e.ua_current_wage || 0, vacation: { perYear: e.ua_vacation_days_year || 0, accrued: e.ua_vacation_accrued || 0,
      used: e.ua_vacation_used || 0, balance: e.ua_vacation_balance || 0 },
    insuranceYears: e.ua_insurance_years || 0, sickPercent: e.ua_sick_percent || 0, psp: PSP[e.ua_psp] || "", children: e.ua_psp_children || 0,
    daysInCompany: e.ua_days_in_company || 0,
  };
}

export async function payslips(env, id, limit = 6) {
  const slips = await call(env, "hr.payslip", "search_read", [[["employee_id", "=", id], ["state", "in", ["done", "verify"]]]],
    { fields: ["name", "number", "date_from", "date_to", "state"], order: "date_from desc, id desc", limit });
  if (!slips.length) return [];
  const lines = await call(env, "hr.payslip.line", "search_read", [[["slip_id", "in", slips.map((s) => s.id)], ["appears_on_payslip", "=", true]]],
    { fields: ["slip_id", "code", "name", "total", "category_id"], order: "sequence, id" });
  return slips.map((s) => {
    const own = lines.filter((l) => l.slip_id[0] === s.id).map((l) => ({ code: l.code, name: l.name, total: l.total, category: m2o(l.category_id) }));
    const by = (code) => own.find((l) => l.code === code)?.total ?? null;
    return { id: s.id, number: s.number || "", title: s.name, period: period(s.date_from), from: s.date_from, to: s.date_to,
      state: s.state, stateLabel: SLIP_STATE[s.state] || s.state, gross: by("GROSS"), net: by("NET"), lines: own };
  });
}

export async function leaves(env, id) {
  const r = await call(env, "hr.leave", "search_read", [[["employee_id", "=", id]]],
    { fields: ["holiday_status_id", "request_date_from", "request_date_to", "number_of_days", "state", "private_name"], order: "request_date_from desc", limit: 20 });
  return r.map((l) => ({ id: l.id, type: m2o(l.holiday_status_id), from: l.request_date_from, to: l.request_date_to, days: l.number_of_days,
    state: l.state, stateLabel: LEAVE_STATE[l.state] || l.state, note: l.private_name || "" }));
}

export async function openRequests(env, id) {
  const r = await call(env, "mail.activity", "search_read", [[["res_model", "=", "hr.employee"], ["res_id", "=", id], ["summary", "=like", "Запит:%"]]],
    { fields: ["summary", "date_deadline", "create_date", "user_id"], order: "create_date desc" });
  return r.map((a) => ({ id: a.id, title: a.summary.replace(/^Запит:\s*/, ""), created: a.create_date, deadline: a.date_deadline, owner: m2o(a.user_id) }));
}

export async function leaveTypes(env) {
  const r = await call(env, "hr.leave.type", "search_read", [[["name", "in", LEAVE_KINDS]]], { fields: ["name"] });
  return LEAVE_KINDS.map((n) => r.find((t) => t.name === n)).filter(Boolean).map((t) => ({ id: t.id, name: t.name }));
}

// Plain-text data block for the model. Only this employee's records.
export function contextText(p, slips, lvs, reqs) {
  const out = [];
  out.push(`Сьогодні: ${fmtDate(kyivToday())}.`);
  out.push(`Працівник: ${p.name}. Посада: ${p.job || "не вказано"}. Підрозділ: ${p.department || "не вказано"}. Керівник: ${p.manager || "не вказано"}. Компанія: ${p.company}.`);
  out.push(`Вид відносин: ${p.contract || "не вказано"}. Ставка: ${p.fte || "не вказано"}. Основне місце роботи: ${p.mainJob ? "так" : "ні"}. Дата прийняття: ${fmtDate(p.hireDate) || "не вказано"}. Днів у компанії: ${p.daysInCompany}.`);
  out.push(`Оклад: ${fmtMoney(p.wage)} грн. Страховий стаж: ${fmtNum(p.insuranceYears)} р. Оплата лікарняних: ${fmtNum(p.sickPercent)} % від середньої. Податкова соціальна пільга: ${p.psp || "немає"}. Дітей до 18 років: ${p.children}.`);
  out.push(`Щорічна відпустка: днів на рік ${p.vacation.perYear}; накопичено ${fmtNum(p.vacation.accrued)}; використано ${fmtNum(p.vacation.used)}; залишок ${fmtNum(p.vacation.balance)} дн.`);
  out.push("Відпустки, лікарняні, відрядження:");
  if (!lvs.length) out.push("- записів немає");
  for (const l of lvs) out.push(`- ${l.type}: ${fmtDate(l.from)} - ${fmtDate(l.to)}, ${fmtNum(l.days)} дн., стан: ${l.stateLabel}`);
  out.push("Розрахункові листки, від нових до старих:");
  if (!slips.length) out.push("- листків немає");
  for (const s of slips) {
    out.push(`- ${s.title} (${fmtDate(s.from)} - ${fmtDate(s.to)}), стан: ${s.stateLabel}.`);
    for (const l of s.lines) out.push(`  ${l.name} [${l.code}, ${l.category}]: ${fmtMoney(l.total)} грн`);
  }
  out.push("Відкриті запити до HR:");
  if (!reqs.length) out.push("- немає");
  for (const r of reqs) out.push(`- ${r.title}, створено ${fmtDate(r.created)}, виконавець ${r.owner}, строк ${fmtDate(r.deadline)}`);
  return out.join("\n");
}
