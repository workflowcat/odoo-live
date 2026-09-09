/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/** Українське форматування суми: 12345.6 -> "12 345,60". */
function fmt(value) {
    return (value || 0).toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** state_class платежу / level попередження -> клас кольору Bootstrap. */
const STATE_COLOR = { ok: "text-success", warn: "text-warning", todo: "text-danger", plan: "text-muted" };
const LEVEL_COLOR = { danger: "text-danger", warning: "text-warning", info: "text-muted" };

export class UaDashboard extends Component {
    static template = "l10n_ua_dashboard.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true });
        this.fmt = fmt;
        this.stateColor = (cls) => STATE_COLOR[cls] || "";
        this.levelColor = (level) => LEVEL_COLOR[level] || "";
        onWillStart(() => this.load());
    }

    async load(year, month) {
        this.state.loading = true;
        const kwargs = {};
        if (year) {
            kwargs.year = year;
        }
        if (month) {
            kwargs.month = month;
        }
        const data = await this.orm.call("ua.dashboard", "get_data", [], kwargs);
        this.state.data = data;
        this.state.loading = false;
    }

    async onSelectPeriod(period) {
        await this.load(period.year, period.month);
    }

    /** Відкрити пункт пульту команд (ua.hub.item.action_open). */
    async openHubItem(id) {
        if (!id) {
            return;
        }
        const action = await this.orm.call("ua.hub.item", "action_open", [id]);
        this.action.doAction(action);
    }

    /** Відкрити рядок «потребує уваги» або «документи»: спершу пункт пульту (action),
     * далі відфільтрований список (res_model + domain), далі форма одного запису (res_model + res_id). */
    async openRow(row) {
        if (row.action) {
            await this.openHubItem(row.action);
        } else if (row.res_model && row.domain) {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: row.res_model,
                domain: row.domain,
                views: [[false, "list"], [false, "form"]],
                name: row.title || row.name || "",
                target: "current",
            });
        } else if (row.res_model && row.res_id) {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: row.res_model,
                res_id: row.res_id,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }
}

registry.category("actions").add("ua_dashboard", UaDashboard);
