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
        this.state = useState({ data: null, loading: true, busy: false, open: {} });
        this.stateLabel = (s) => STATE_LABEL[s] || s;
        onWillStart(() => this.load());
    }

    async load(period = {}) {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("ua.period.board", "get_screen_data", [], period);
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
