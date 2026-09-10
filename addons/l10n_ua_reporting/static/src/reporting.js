/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const LEVEL_COLOR = { ok: "text-success", warn: "text-warning", error: "text-danger" };
const STATE_LABEL = { draft: "Чернетка", checked: "Перевірено", generated: "Сформовано", submitted: "Подано" };
const STATE_STEPS = ["draft", "checked", "generated", "submitted"];

function fmtCell(v, money) {
    if (typeof v !== "number") {
        return v;
    }
    if (Number.isInteger(v) && !money) {
        return String(v);
    }
    return v.toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export class UaReporting extends Component {
    static template = "l10n_ua_reporting.Reporting";
    static props = { ...standardActionServiceProps };

    fmt(value, money) {
        return fmtCell(value, money);
    }

    isMoney(index) {
        const summary = this.state.data && this.state.data.summary;
        return !!(summary && (summary.money || []).includes(index));
    }

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, busy: false });
        this.levelColor = (l) => LEVEL_COLOR[l] || "";
        this.stateLabel = (s) => STATE_LABEL[s] || s;
        this.stateSteps = STATE_STEPS;
        onWillStart(() => this.load());
    }

    async load(kwargs = {}) {
        this.state.loading = true;
        try {
            const data = await this.orm.call("ua.report.run", "get_screen_data", [], kwargs);
            this.state.data = data;
        } finally {
            this.state.loading = false;
        }
    }

    async selectReport(code) {
        await this.load({ report_code: code });
    }

    async selectPeriod(period) {
        const kwargs = { report_code: this.state.data.run.report_code };
        if (period.year !== undefined) kwargs.year = period.year;
        if (period.quarter !== undefined) kwargs.quarter = period.quarter;
        if (period.month !== undefined) kwargs.month = period.month;
        if (period.date !== undefined) kwargs.date = period.date;
        await this.load(kwargs);
    }

    async _runAction(method) {
        this.state.busy = true;
        try {
            await this.orm.call("ua.report.run", method, [[this.state.data.run.id]]);
            await this.load({ run_id: this.state.data.run.id });
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    refresh() {
        return this._runAction("action_refresh");
    }

    generate() {
        return this._runAction("action_generate");
    }

    markSubmitted() {
        return this._runAction("action_mark_submitted");
    }

    resetDraft() {
        return this._runAction("action_reset");
    }

    async openCheck(check) {
        if (!check.action_model) {
            return;
        }
        const action = await this.orm.call("ua.report.check", "action_open", [[check.id]]);
        if (action) {
            this.action.doAction(action);
        }
    }

    downloadAll() {
        for (const f of this.state.data.run.files) {
            window.open("/web/content/" + f.id + "?download=true", "_blank");
        }
    }

    get hasErrors() {
        return (this.state.data && this.state.data.checks || []).some((c) => c.level === "error");
    }
}

registry.category("actions").add("ua_reporting", UaReporting);
