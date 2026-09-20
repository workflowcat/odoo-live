/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const GROUPS = [
    ["candidate", "Кандидати"],
    ["onboarding", "Оформлення"],
    ["hired", "Прийнято"],
    ["declined", "Відмова"],
];
const FIELD_TIP = {
    missing: "Обов'язкове поле без значення",
    proposed: "Є значення з документа. Підтвердіть або відхиліть.",
    provided: "Заповнено",
    empty: "Необов'язкове поле",
};
const CONF_LABEL = { high: "висока", medium: "середня", low: "низька" };
const REQ_TIP = {
    done: "Файл є в справі",
    missing: "Кандидат має принести цей документ",
    later: "Система створить документ під час прийняття",
};

export class UaHire extends Component {
    static template = "l10n_ua_hire.Hire";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.act = useService("ua_act");
        this.state = useState({
            data: null, loading: true, busy: false, creating: false,
            draft: { last_name: "", first_name: "", job_title: "" },
            showClosed: false, helper: null, extracting: false, declining: false, declineReason: "",
            openMilitary: false, preview: false,
            tab: null, otherFilesOpen: false, printOpen: false,
        });
        this.previewFrame = useRef("previewFrame");
        this.groups = GROUPS;
        this.fieldTip = (s) => FIELD_TIP[s] || "";
        this.confLabel = (c) => CONF_LABEL[c] || c;
        this.reqTip = (s) => REQ_TIP[s] || "";
        onWillStart(() => this.load());
    }

    get data() {
        return this.state.data;
    }

    get caseData() {
        return this.state.data && this.state.data.case;
    }

    async load(caseId) {
        const current = caseId || (this.caseData && this.caseData.id) || null;
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const data = await this.orm.call("ua.hire.case", "get_screen_data", [], { case_id: current });
        if (seq !== this.loadSeq) {
            return; // уже є свіжіший запит - ця відповідь застаріла
        }
        this.state.data = data;
        this.state.loading = false;
        const c = this.caseData;
        if (c && c.files.length && !this.state.helper) {
            this.orm.call("ua.hire.case", "extract_status", []).then((s) => (this.state.helper = s));
        }
    }

    casesIn(stage) {
        return this.data.cases.filter((c) => c.stage === stage);
    }

    async select(id) {
        this.state.declining = false;
        this.state.preview = false;
        this.state.openMilitary = false;
        this.state.tab = null;
        this.state.otherFilesOpen = false;
        this.state.printOpen = false;
        await this.load(id);
    }

    // ---- створення
    startCreate() {
        this.state.creating = true;
        this.state.draft = { last_name: "", first_name: "", job_title: "" };
    }

    async create() {
        const d = this.state.draft;
        if (!d.last_name.trim()) {
            this.notification.add("Вкажіть прізвище.", { type: "warning" });
            return;
        }
        const id = await this.orm.call("ua.hire.case", "create_case", [], d);
        this.state.creating = false;
        await this.load(id);
    }

    // ---- поля
    meta(name) {
        return this.data.meta[name];
    }

    value(name) {
        return this.caseData.values[name];
    }

    inputValue(name) {
        const v = this.value(name);
        const m = this.meta(name);
        if (m.type === "many2one") {
            return v ? String(v[0]) : "";
        }
        if (v === false || v === null || v === undefined) {
            return "";
        }
        if ((m.type === "monetary" || m.type === "integer" || m.type === "float") && !v) {
            return "";
        }
        return String(v);
    }

    get readonly() {
        return ["hired", "declined"].includes(this.caseData.stage);
    }

    async save(name, ev) {
        const m = this.meta(name);
        const raw = m.type === "boolean" ? ev.target.checked : ev.target.value;
        if (m.type !== "boolean" && raw === this.inputValue(name)) {
            return;
        }
        try {
            await this.orm.call("ua.hire.case", "set_value", [[this.caseData.id], name, raw]);
        } finally {
            await this.load();
        }
    }

    sectionVisible(section) {
        if (section.key !== "military") {
            return true;
        }
        return this.caseData.military_required || this.value("mil_status") || this.state.openMilitary;
    }

    // ---- вкладки середини (спека 2026-09-21, п.3): справжні вкладки, не якорі.
    // Вибір тримається в state компонента, скидається лише при виборі іншої справи (select()).
    get activeTab() {
        const c = this.caseData;
        if (!c || !c.sections.length) {
            return null;
        }
        const keys = c.sections.map((s) => s.key);
        return keys.includes(this.state.tab) ? this.state.tab : keys[0];
    }

    setTab(key) {
        this.state.tab = key;
    }

    // ---- пропозиції
    async accept(p) {
        await this.orm.call("ua.hire.proposal", "action_accept", [[p.id]]);
        await this.load();
    }

    async reject(p) {
        await this.orm.call("ua.hire.proposal", "action_reject", [[p.id]]);
        await this.load();
    }

    async acceptAll() {
        const ids = [];
        for (const list of Object.values(this.caseData.proposals)) {
            if (list.length === 1 && !list[0].conflict && list[0].confidence === "high") {
                ids.push(list[0].id);
            }
        }
        if (!ids.length) {
            return;
        }
        await this.orm.call("ua.hire.proposal", "action_accept", [ids]);
        await this.load();
    }

    get safeProposalCount() {
        if (!this.caseData) {
            return 0;
        }
        return Object.values(this.caseData.proposals).filter(
            (l) => l.length === 1 && !l[0].conflict && l[0].confidence === "high"
        ).length;
    }

    get dateFromLabel() {
        const v = this.caseData && this.caseData.values.date_from;
        if (!v) {
            return "";
        }
        const [y, m, d] = v.split("-");
        return `${d}.${m}.${y}`;
    }

    get missingCount() {
        if (!this.caseData) {
            return 0;
        }
        return Object.values(this.caseData.states).filter((s) => s === "missing").length;
    }

    get proposedCount() {
        if (!this.caseData) {
            return 0;
        }
        return Object.values(this.caseData.states).filter((s) => s === "proposed").length;
    }

    get hireBlockedReason() {
        const c = this.caseData;
        if (c && c.stage === "onboarding" && !c.can_hire) {
            return "неможливо прийняти: спершу виправте помилки в перевірках";
        }
        return "";
    }

    // ---- файли
    async upload(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        if (!files.length) {
            return;
        }
        this.state.busy = true;
        try {
            for (const file of files) {
                const data = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
                    reader.onerror = reject;
                    reader.readAsDataURL(file);
                });
                await this.orm.call("ua.hire.case", "add_file", [[this.caseData.id], file.name, data, guessType(file.name)]);
            }
        } finally {
            this.state.busy = false;
            await this.load();
        }
    }

    // ---- Резерв+ (витяг): необов'язковий файл, не через ua.hire.file - окреме поле картки
    async uploadReserveFile(ev) {
        const file = ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        this.state.busy = true;
        try {
            const data = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
            await this.orm.call("ua.hire.case", "set_reserve_file", [[this.caseData.id], file.name, data]);
        } finally {
            this.state.busy = false;
            await this.load();
        }
    }

    openReserveFile() {
        window.open(`/web/content/ua.hire.case/${this.caseData.id}/mil_reserve_file?download=false&filename_field=mil_reserve_filename`, "_blank");
    }

    async clearReserveFile() {
        await this.orm.call("ua.hire.case", "clear_reserve_file", [[this.caseData.id]]);
        await this.load();
    }

    async setDocType(f, ev) {
        await this.orm.call("ua.hire.file", "set_doc_type", [[f.id], ev.target.value]);
        await this.load();
    }

    async removeFile(f) {
        await this.orm.unlink("ua.hire.file", [f.id]);
        await this.load();
    }

    openFile(f) {
        window.open(`/web/content/ua.hire.file/${f.id}/file?download=false`, "_blank");
    }

    async extract() {
        this.state.extracting = true;
        try {
            const res = await this.orm.call("ua.hire.case", "action_extract", [[this.caseData.id]]);
            this.notification.add(`Пропозицій: ${res.created}`, { type: res.created ? "success" : "info" });
        } finally {
            this.state.extracting = false;
            await this.load();
        }
    }

    get extractBlock() {
        const c = this.caseData;
        if (!c.files.length) {
            return "Завантажте файли";
        }
        if (!c.values.pd_consent) {
            return "Потрібна згода на обробку персональних даних";
        }
        if (this.state.helper && !this.state.helper.ok) {
            return this.state.helper.error || "Помічник розпізнавання недоступний";
        }
        return "";
    }

    // ---- етапи
    async startOnboarding() {
        await this.orm.call("ua.hire.case", "action_start_onboarding", [[this.caseData.id]]);
        await this.load();
    }

    async decline() {
        await this.orm.call("ua.hire.case", "action_decline", [[this.caseData.id]], { reason: this.state.declineReason });
        this.state.declining = false;
        this.state.declineReason = "";
        await this.load();
    }

    async reopen() {
        await this.orm.call("ua.hire.case", "action_reopen", [[this.caseData.id]]);
        await this.load();
    }

    async hire() {
        this.state.busy = true;
        try {
            // Модель дії (docs/payroll/action-model.md): план перед проведенням, потім
            // наслідки рядок за рядком. Немає чесного скасування прийняття - undo не передаємо.
            await this.act.run({
                model: "ua.hire.case", id: this.caseData.id, method: "action_hire",
                plan: "action_hire_plan", confirm: "Прийняти на роботу",
                openTarget: (target) => this.openResult(target),
                onDone: () => this.load(),
            });
        } finally {
            this.state.busy = false;
        }
    }

    openResult(r) {
        if (r.run_id) {
            this.action.doAction({ type: "ir.actions.client", tag: "ua_reporting", params: { run_id: r.run_id } });
            return;
        }
        this.action.doAction({ type: "ir.actions.act_window", res_model: r.model, res_id: r.res_id, views: [[false, "form"]] });
    }

    // ---- пакет першого дня
    get packageItems() {
        return this.caseData.package.filter((d) => d.on).map((d) => d.item);
    }

    packageUrl(embed) {
        const items = encodeURIComponent(JSON.stringify(this.packageItems));
        const title = encodeURIComponent(`Пакет першого дня: ${this.caseData.name}`);
        return `/ua/print?items=${items}&title=${title}${embed ? "&embed=1" : ""}`;
    }

    async togglePackageDoc(d, ev) {
        await this.orm.call("ua.hire.case", "set_package_doc", [[this.caseData.id], d.key, ev.target.checked]);
        await this.load();
    }

    // ---- пакет за джерелом (спека docs/payroll/spec-intake.md, 2026-09-21): package_split
    // ділить документи на «від працівника» і «від компанії». Поки бекенд не додав ключ -
    // caseData.package_split відсутній, і шаблон малює старі чотири стовпчики без змін.
    rowMark(state) {
        if (state === "have") {
            return "provided";
        }
        if (state === "expired") {
            // є, але недійсний - та сама мова кольору, що й «пропозиція чекає підтвердження»
            return "proposed";
        }
        if (state === "missing") {
            return "missing";
        }
        return "empty"; // not_needed - те саме порожнє кільце, що й у полів без стану
    }

    employeeRowText(row) {
        if (row.state === "missing") {
            return "немає";
        }
        if (row.state === "not_needed") {
            return "не потрібен";
        }
        return row.note || row.when || "";
    }

    companyRowText(row) {
        if (row.sign === "signed") {
            return row.when ? `підписано ${row.when}` : "підписано";
        }
        if (row.sign === "to_sign") {
            return "не підписано";
        }
        if (row.sign === "not_needed") {
            return "не потрібен";
        }
        // sign відсутній - документ не підписний (наприклад наказ - "проведено", опис -
        // "не створено"); слово вже готове в note з бекенда.
        return row.note || row.when || "";
    }

    // «Інші файли» дає лише {name, doc_type, target}: обгортка дає id, яким уже вміють
    // користуватися setDocType/removeFile/openFile нижче.
    otherFileRecord(x) {
        return { id: x.target && x.target.res_id, name: x.name, doc_type: x.doc_type };
    }

    // Єдиний прохід для будь-якого "target" з пакета (рядок вимоги, інший файл, посилання
    // на довідник у settings) - та сама дорога, якою openResult вище відкриває цілі.
    openRowTarget(target) {
        if (!target) {
            return;
        }
        if (target.section) {
            this.setTab(target.section);
            return;
        }
        if (target.model && target.res_id) {
            this.action.doAction({ type: "ir.actions.act_window", res_model: target.model, res_id: target.res_id, views: [[false, "form"]] });
            return;
        }
        if (target.xmlid) {
            this.action.doAction(target.xmlid);
        }
    }

    showPackage() {
        if (!this.packageItems.length) {
            this.notification.add("Позначте хоча б один документ.", { type: "warning" });
            return;
        }
        this.state.preview = true;
    }

    printPackage() {
        const frame = this.previewFrame.el;
        if (frame && frame.contentWindow) {
            frame.contentWindow.focus();
            frame.contentWindow.print();
        } else {
            window.open(this.packageUrl(false), "_blank");
        }
    }

    printResult(r) {
        const items = encodeURIComponent(JSON.stringify([r.print]));
        window.open(`/ua/print?items=${items}&title=${encodeURIComponent(r.print.t)}`, "_blank");
    }
}

function guessType(name) {
    const n = name.toLowerCase();
    const rules = [
        ["passport", /паспорт|passport|id.?card|id-карт/],
        ["rnokpp", /рнокпп|ідентиф|інн|ipn|rnokpp|tax/],
        ["military_id", /військов|military|резерв|reserve|приписн/],
        ["diploma", /диплом|diploma/],
        ["labor_book", /трудов|labor|labour/],
        ["statement", /заява|statement|application/],
        ["consent", /згода|consent/],
    ];
    const hit = rules.find(([, re]) => re.test(n));
    return hit ? hit[0] : "other";
}

registry.category("actions").add("ua_hire", UaHire);
