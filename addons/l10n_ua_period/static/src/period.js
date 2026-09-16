/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const STATE_LABEL = { done: "готово", warn: "потребує уваги", todo: "не почато" };
const BASKET_KEY = "ua_print_basket";
const GUIDE_KEY = "ua_guide";

// Підказки при наведенні: одне речення, що означає позначка або що станеться після кліку.
const DOT_TIP = { done: "Готово", warn: "Потребує уваги", todo: "Не почато", crit: "Терміново" };
const MARK_TIP = { ok: "Виконано", warn: "Потребує уваги", crit: "Не сплачено або прострочено", todo: "Заплановано" };
const DOC_TIP = {
    print: "Документ для друку. Можна переглянути на папері і додати в кошик.",
    filing: "Подання в держорган. Має строк і квитанцію.",
    file: "Машинний файл для банку. Відкриває запис, де цей файл формують.",
};
const STATE_TIP = {
    "чернетка": "Чернетка: документ ще можна правити, номера немає.",
    "створено": "Створено: документ зафіксовано.",
    "подано": "Подано: є квитанція.",
    "сформовано": "Сформовано: файл готовий, але ще не поданий.",
    "немає": "Документа за цей місяць ще немає.",
};

function readGuide() {
    try {
        return browser.localStorage.getItem(GUIDE_KEY) !== "0";
    } catch {
        return true;
    }
}

function readBasket() {
    try {
        return JSON.parse(browser.localStorage.getItem(BASKET_KEY) || "[]");
    } catch {
        return [];
    }
}

export class UaPeriod extends Component {
    static template = "l10n_ua_period.Period";
    static props = { ...standardActionServiceProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, busy: false, open: {}, people: [], person: null,
                                selected: null, preview: null, basket: readBasket(), guide: readGuide() });
        this.dotTip = (state) => DOT_TIP[state] || "";
        this.markTip = (mark) => `${mark.date}: ${mark.label}. ${MARK_TIP[mark.state] || ""}`;
        this.docTip = (doc) => DOC_TIP[doc.kind] || "";
        this.stateTip = (state) => STATE_TIP[state] || "";
        this.previewFrame = useRef("previewFrame");
        this.stateLabel = (s) => STATE_LABEL[s] || s;
        onWillStart(() => this.load());
    }

    async load(period = {}) {
        this.state.loading = true;
        this.state.person = null;
        this.state.preview = null;
        try {
            this.state.data = await this.orm.call("ua.period.board", "get_screen_data", [], period);
            const now = this.state.data.period;
            this.state.people = await this.orm.call("ua.period.board", "get_people", [now.year, now.month]);
        } finally {
            this.state.loading = false;
        }
    }

    // ---------------------------------------------------------------- підказки
    /** Режим підказок: перші кроки, пояснення кроку, номери частин екрана. Стан пам'ятає браузер. */
    toggleGuide() {
        this.state.guide = !this.state.guide;
        try {
            browser.localStorage.setItem(GUIDE_KEY, this.state.guide ? "1" : "0");
        } catch {
            // приватне вікно: стан живе до перезавантаження
        }
    }

    get firstStepsLeft() {
        const items = (this.state.data && this.state.data.first_steps) || [];
        return items.filter((i) => !i.done).length;
    }

    helpFor(step) {
        const help = (this.state.data && this.state.data.help) || {};
        return help[step.key];
    }

    openFirstStep(item) {
        return this.openDocTarget({ target: item.action });
    }

    // ---------------------------------------------------------------- перелік і деталь
    /** Вибраний крок: явно вибраний, інакше перший, що потребує уваги, інакше перший. */
    get selectedKey() {
        const steps = (this.state.data && this.state.data.steps) || [];
        if (this.state.selected && steps.some((s) => s.key === this.state.selected)) {
            return this.state.selected;
        }
        const warn = steps.find((s) => s.state === "warn");
        return (warn || steps[0] || {}).key;
    }

    get selectedStep() {
        const steps = (this.state.data && this.state.data.steps) || [];
        return steps.find((s) => s.key === this.selectedKey);
    }

    selectStep(step) {
        this.state.selected = step.key;
        this.state.preview = null;
    }

    docsFor(step) {
        const docs = (this.state.data && this.state.data.documents) || {};
        return docs[step.key] || [];
    }

    // ---------------------------------------------------------------- перегляд і кошик
    printUrl(items, embed) {
        const params = new URLSearchParams({ items: JSON.stringify(items) });
        if (embed) {
            params.set("embed", "1");
        }
        return `/ua/print?${params.toString()}`;
    }

    previewDoc(doc) {
        const item = { r: doc.report, ids: doc.ids, t: doc.name };
        this.state.preview = { ...item, report: doc.report, name: doc.name, url: this.printUrl([item], true),
                               checks: doc.checks || [] };
    }

    isPreviewed(doc) {
        const p = this.state.preview;
        return !!p && p.r === doc.report && JSON.stringify(p.ids) === JSON.stringify(doc.ids);
    }

    closePreview() {
        this.state.preview = null;
    }

    /** Друк браузером з документа в рамці: вікна Odoo і завантаження немає. */
    printPreview() {
        const frame = this.previewFrame.el;
        if (frame && frame.contentWindow) {
            frame.contentWindow.focus();
            frame.contentWindow.print();
        }
    }

    saveBasket() {
        try {
            browser.localStorage.setItem(BASKET_KEY, JSON.stringify(this.state.basket));
        } catch {
            // приватне вікно: кошик живе до перезавантаження
        }
    }

    inBasket(doc) {
        const r = doc.report || doc.r;
        const ids = JSON.stringify(doc.ids);
        return this.state.basket.some((i) => i.r === r && JSON.stringify(i.ids) === ids);
    }

    addToBasket(doc) {
        if (this.inBasket(doc)) {
            return;
        }
        this.state.basket.push({ r: doc.report || doc.r, ids: doc.ids, t: doc.name || doc.t });
        this.saveBasket();
    }

    removeFromBasket(index) {
        this.state.basket.splice(index, 1);
        this.saveBasket();
    }

    moveBasket(index, delta) {
        const to = index + delta;
        if (to < 0 || to >= this.state.basket.length) {
            return;
        }
        const [item] = this.state.basket.splice(index, 1);
        this.state.basket.splice(to, 0, item);
        this.saveBasket();
    }

    clearBasket() {
        this.state.basket.splice(0);
        this.saveBasket();
    }

    /** Пакет відкривається у своїй вкладці: там перегляд усіх документів і друк браузером. */
    openBundle() {
        const title = `Пакет · ${this.state.data.period.label}`;
        const url = this.printUrl(this.state.basket.map(({ r, ids, t }) => ({ r, ids, t })), false) +
            `&title=${encodeURIComponent(title)}`;
        browser.open(url, "_blank");
    }

    async openDocTarget(target) {
        target = target.target || target;
        if (target.xmlid) {
            return this.open({ action: { xmlid: target.xmlid } });
        }
        if (target.model && target.res_id) {
            return this.openRecord({ model: target.model, id: target.res_id });
        }
        if (target.model && target.domain) {
            return this.openList(target.model, target.domain, "");
        }
    }

    /** Клік по рядку перевірки: та сама ціль, що й «Правити дані» документа. */
    openCheck(check) {
        if (!check.target) {
            return;
        }
        return this.openDocTarget(check.target);
    }

    /** Сусідній місяць: стрілки в шапці, коли перелік місяців не вміщається. */
    shiftMonth(delta) {
        const { year, month } = this.state.data.period;
        const index = year * 12 + (month - 1) + delta;
        return this.load({ year: Math.floor(index / 12), month: (index % 12) + 1 });
    }

    selectPeriod(period) {
        return this.load({ year: period.year, month: period.month });
    }

    toggle(step) {
        if (!step.details.length) {
            return this.open(step);
        }
        this.state.open[step.key] = !this.state.open[step.key];
    }

    isOpen(step) {
        return !!this.state.open[step.key];
    }

    async open(step) {
        this.state.busy = true;
        try {
            const action = await this.orm.call("ua.period.board", "action_open", [step.action]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async acceptAll() {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            const n = await this.orm.call("ua.period.board", "action_accept_changes", [period.year, period.month]);
            this.notification.add(`Прийнято змін: ${n}`, { type: "success" });
            await this.load({ year: period.year, month: period.month });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async closeMonth() {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            await this.orm.call("ua.period.board", "action_close_month", [period.year, period.month]);
            this.notification.add(`Місяць закрито: ${period.label}`, { type: "success" });
            await this.load({ year: period.year, month: period.month });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    // ---------------------------------------------------------------- квартал і рік у «Ще»
    quarterBlocked(data) {
        return !!(data.quarter.closed || data.quarter.blockers.length);
    }

    quarterTip(data) {
        if (data.quarter.closed) {
            return `${data.quarter.label} закрито: податкова дата блокування стоїть.`;
        }
        if (data.quarter.blockers.length) {
            return `${data.quarter.label} закрити не можна: ${data.quarter.blockers.join("; ")}.`;
        }
        return `${data.quarter.label} готовий до закриття.`;
    }

    yearBlocked(data) {
        return !!(data.year_close.closed || data.year_close.blockers.length);
    }

    yearCloseTip(data) {
        if (data.year_close.closed) {
            return `${data.year_close.label} закрито остаточно.`;
        }
        if (data.year_close.blockers.length) {
            return `${data.year_close.label} закрити не можна: ${data.year_close.blockers.join("; ")}.`;
        }
        return `${data.year_close.label} готовий до остаточного закриття.`;
    }

    attrsFor(tooltip) {
        return { "data-tooltip": tooltip };
    }

    async closeQuarter() {
        const data = this.state.data;
        if (this.quarterBlocked(data)) {
            return;
        }
        const period = data.period;
        await this.runClose("action_close_quarter", [period.year, data.quarter.quarter],
                            `Квартал закрито: ${data.quarter.label}`);
    }

    async closeYear() {
        const data = this.state.data;
        if (this.yearBlocked(data)) {
            return;
        }
        const period = data.period;
        await this.runClose("action_close_year", [period.year], `Рік закрито: ${period.year}`);
    }

    async runClose(method, args, message) {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            await this.orm.call("ua.period.board", method, args);
            this.notification.add(message, { type: "success" });
            await this.load({ year: period.year, month: period.month });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async runHeadline() {
        const period = this.state.data.period;
        const action = this.state.data.headline.action;
        if (action === "exceptions") {
            document.querySelector(".o_ua_period_section h5")?.scrollIntoView({ behavior: "smooth" });
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call("ua.period.board", "action_headline", [period.year, period.month, action]);
            if (result && result.type) {
                return this.action.doAction(result);
            }
            if (result && result.message) {
                this.notification.add(result.message, { type: "success" });
            }
            await this.load({ year: period.year, month: period.month });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async openException(row) {
        this.state.busy = true;
        try {
            const action = await this.orm.call("ua.period.board", "action_open_exception", [row]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    /** Відкрити список записів за моделлю і доменом: клік по числу веде в його джерело. */
    async openList(model, domain, name) {
        if (!model || !domain) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
            name: name || "",
        });
    }

    /** Клік по числу місяця: листки цього місяця. */
    openEstimate(kind) {
        const data = this.state.data;
        const domain = kind === "draft" ? data.estimate.draft_domain : data.estimate.domain;
        return this.openList(data.estimate.model, domain, `Листки · ${data.period.label}`);
    }

    /** Клік по рядку оборотів: проводки цього рахунку за місяць. */
    openTurnover(row) {
        return this.openList(row.model, row.domain,
            `${row.code} ${row.name} · ${this.state.data.period.label}`);
    }

    async openChange(row) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: row.model,
            domain: row.domain,
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
            name: row.label,
        });
    }

    async openPerson(row) {
        const period = this.state.data.period;
        if (this.state.person && this.state.person.employee_id === row.employee_id) {
            return this.closePerson();
        }
        try {
            this.state.person = await this.orm.call("ua.period.board", "get_person",
                [row.employee_id, period.year, period.month]);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        }
    }

    closePerson() {
        this.state.person = null;
    }

    async openPersonRecord(slipId) {
        const person = this.state.person;
        const action = await this.orm.call("ua.period.board", "action_open_person",
            [person.employee_id, slipId || false]);
        await this.action.doAction(action);
    }

    async openClose() {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            const action = await this.orm.call("ua.period.board", "action_open_close_record", [period.year, period.month]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    async openRecord(row) {
        this.state.busy = true;
        try {
            const action = await this.orm.call("ua.period.board", "action_open_record", [row.model, row.id]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("ua_period", UaPeriod);
