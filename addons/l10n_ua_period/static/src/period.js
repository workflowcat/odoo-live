/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const GUIDE_KEY = "ua_guide";

// Підказки при наведенні: одне речення, що означає позначка кроку/рядка або дата в смузі строків.
const DOT_TIP = { ok: "Готово", warn: "Потребує уваги", crit: "Заважає закрити місяць", idle: "Ще не почато" };
const MARK_TIP = { ok: "Виконано", warn: "Потребує уваги", crit: "Не сплачено або прострочено", todo: "Заплановано" };

function readGuide() {
    try {
        return browser.localStorage.getItem(GUIDE_KEY) !== "0";
    } catch {
        return true;
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
        this.act = useService("ua_act");
        this.state = useState({ data: null, loading: true, busy: false, people: [], person: null,
                                selected: null, guide: readGuide() });
        this.dotTip = (mark) => DOT_TIP[mark] || "";
        this.markTip = (mark) => `${mark.date}: ${mark.label}. ${MARK_TIP[mark.state] || ""}`;
        onWillStart(() => this.load());
    }

    async load(period = {}) {
        this.state.loading = true;
        this.state.person = null;
        try {
            this.state.data = await this.orm.call("ua.period.board", "get_screen_data", [], period);
            const now = this.state.data.period;
            this.state.people = await this.orm.call("ua.period.board", "get_people", [now.year, now.month]);
        } finally {
            this.state.loading = false;
        }
    }

    // ---------------------------------------------------------------- підказки
    /** Режим підказок: пояснення відкритого кроку. Стан пам'ятає браузер. */
    toggleGuide() {
        this.state.guide = !this.state.guide;
        try {
            browser.localStorage.setItem(GUIDE_KEY, this.state.guide ? "1" : "0");
        } catch {
            // приватне вікно: стан живе до перезавантаження
        }
    }

    helpFor(step) {
        const help = (this.state.data && this.state.data.help) || {};
        return help[step.key];
    }

    // ---------------------------------------------------------------- смуга кроків і тіло
    /** Відкритий крок: явно вибраний клієнтом, інакше підказка сервера (перший crit,
     * інакше перший warn, інакше перший узагалі - ua_period_board.get_screen_data). */
    get selectedKey() {
        const steps = (this.state.data && this.state.data.steps) || [];
        if (this.state.selected && steps.some((s) => s.key === this.state.selected)) {
            return this.state.selected;
        }
        const current = steps.find((s) => s.current);
        return (current || steps[0] || {}).key;
    }

    get selectedStep() {
        const steps = (this.state.data && this.state.data.steps) || [];
        return steps.find((s) => s.key === this.selectedKey);
    }

    /** Клік по кроку в смузі: лише перемикає, дані вже завантажені разом з місяцем. */
    selectStep(step) {
        this.state.selected = step.key;
    }

    // ---------------------------------------------------------------- рядки кроку
    /** Клік по рядку тіла кроку: документ, проблема чи ціль «Заважає закрити». */
    openRow(row) {
        if (!row || !row.action || !row.target) {
            return;
        }
        return this.openDocTarget(row.target);
    }

    async openDocTarget(target) {
        target = target.target || target;
        if (target.step) {
            // рядок «Заважає закрити місяць»: веде на крок, не на запис - огляд, без RPC.
            return this.selectStep({ key: target.step });
        }
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

    /** Сусідній місяць: стрілки в шапці, коли перелік місяців не вміщається. */
    shiftMonth(delta) {
        const { year, month } = this.state.data.period;
        const index = year * 12 + (month - 1) + delta;
        return this.load({ year: Math.floor(index / 12), month: (index % 12) + 1 });
    }

    selectPeriod(period) {
        return this.load({ year: period.year, month: period.month });
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

    /** «Прийняти всі зміни»: клас «узгодження» (action-model.md) - коротка дія,
     * без плану, зі смугою скасування 20 с (action_undo_accept_changes на сервері
     * реально повертає щойно прийняті рядки журналу назад у «нові», не ховає результат). */
    async acceptAll() {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            await this.act.run({
                model: "ua.period.board",
                id: period.year * 100 + period.month,
                method: "action_accept_changes",
                undo: "action_undo_accept_changes",
                undoLabel: "Скасувати",
                kwargs: { year: period.year, month: period.month },
                openTarget: (target) => this.openDocTarget(target),
                onDone: () => this.load({ year: period.year, month: period.month }),
            });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    /** «Закрити місяць»: клас «проведення» (action-model.md) - план перед дією,
     * наслідки після, без скасування (відкрити місяць знову - окрема свідома дія,
     * див. openClose()). `id` - рік і місяць запаковані в одне число (рік*100+місяць):
     * план-крок сервісу ua_act викликає ORM без жодних kwargs, тому єдиний спосіб
     * донести період до action_close_month_plan - через сам id. */
    async closeMonth() {
        this.state.busy = true;
        try {
            const period = this.state.data.period;
            await this.act.run({
                model: "ua.period.board",
                id: period.year * 100 + period.month,
                method: "action_close_month",
                plan: "action_close_month_plan",
                confirm: "Закрити місяць",
                kwargs: { year: period.year, month: period.month },
                openTarget: (target) => this.openDocTarget(target),
                onDone: () => this.load({ year: period.year, month: period.month }),
            });
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
        // Закриття місяця - зобов'язання: воно йде тим самим шляхом, що й кнопка «Закрити місяць»,
        // з планом і наслідками, а не тихо з головної кнопки.
        if (action === "close") {
            return this.closeMonth();
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
    openTotals(kind) {
        const data = this.state.data;
        const domain = kind === "draft" ? data.totals.draft_domain : data.totals.domain;
        return this.openList(data.totals.model, domain, `Листки · ${data.period.label}`);
    }

    /** Клік по рядку оборотів: проводки цього рахунку за місяць. */
    openTurnover(row) {
        return this.openList(row.model, row.domain,
            `${row.code} ${row.name} · ${this.state.data.period.label}`);
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
