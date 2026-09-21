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
        // стан документа словом, колір - лише контуром пігулки
        this.docPill = (state) => {
            const s = (state || "").toLowerCase();
            if (s.includes("затверд") || s.includes("подано") || s.includes("оплач")) {
                return "o_ua_pill_ok";
            }
            if (s.includes("чернетк")) {
                return "";
            }
            return "o_ua_pill_warn";
        };
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
        const data = await this.orm.call("ua.dashboard", "get_screen_data", [], kwargs);
        this.state.data = data;
        this.state.loading = false;
    }

    async onSelectPeriod(period) {
        await this.load(period.year, period.month);
    }

    /** Ціль рядка: власне поле target або сам рядок, якщо він і є ціллю (обороти). */
    targetOf(row) {
        if (!row) {
            return false;
        }
        if (row.target) {
            return row.target;
        }
        return row.model && (row.domain || row.res_id) ? row : false;
    }

    /** Чи веде рядок кудись. */
    hasTarget(row) {
        return Boolean(this.targetOf(row));
    }

    /** Відкриває все на цьому екрані один вхід - ua.screen.open_target на сервері. */
    async openTarget(target) {
        if (!target) {
            return;
        }
        const action = await this.orm.call("ua.dashboard", "open_target", [target]);
        await this.action.doAction(action);
    }

    async openRow(row) {
        await this.openTarget(this.targetOf(row));
    }
}

registry.category("actions").add("ua_dashboard", UaDashboard);
