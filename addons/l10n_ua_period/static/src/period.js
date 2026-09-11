/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const STATE_LABEL = { done: "готово", warn: "потребує уваги", todo: "не почато" };

export class UaPeriod extends Component {
    static template = "l10n_ua_period.Period";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, busy: false, open: {}, people: [], person: null });
        this.stateLabel = (s) => STATE_LABEL[s] || s;
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

    async closeQuarter() {
        const period = this.state.data.period;
        await this.runClose("action_close_quarter", [period.year, this.state.data.quarter.quarter],
                            `Квартал закрито: ${this.state.data.quarter.label}`);
    }

    async closeYear() {
        const period = this.state.data.period;
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
