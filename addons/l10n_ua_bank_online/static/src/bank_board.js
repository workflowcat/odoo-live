/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"];

function money(value) {
    const number = Number(value || 0);
    return number.toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export class UaBankBoard extends Component {
    static template = "l10n_ua_bank_online.BankBoard";
    static props = { ...standardActionServiceProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, busy: false, journalId: null });
        this.money = money;
        this.months = MONTHS;
        onWillStart(() => this.load());
    }

    async load(period = {}) {
        this.state.loading = true;
        try {
            const data = await this.orm.call("ua.bank.board", "get_screen_data", [], period);
            this.state.data = data;
            if (!this.state.journalId && data.accounts.length) {
                this.state.journalId = data.accounts[0].journal_id;
            }
        } finally {
            this.state.loading = false;
        }
    }

    get account() {
        const accounts = (this.state.data && this.state.data.accounts) || [];
        return accounts.find((a) => a.journal_id === this.state.journalId) || accounts[0] || null;
    }

    get periodLabel() {
        const period = this.state.data.period;
        return `${MONTHS[period.month - 1]} ${period.year}`;
    }

    get statements() {
        const rows = (this.state.data && this.state.data.statements) || [];
        return this.state.journalId ? rows.filter((r) => r.journal_id === this.state.journalId) : rows;
    }

    get connectedCount() {
        const accounts = (this.state.data && this.state.data.accounts) || [];
        return accounts.filter((a) => a.provider_id).length;
    }

    get unreconciled() {
        const rows = (this.state.data && this.state.data.unreconciled) || [];
        return this.state.journalId ? rows.filter((r) => r.journal_id === this.state.journalId) : rows;
    }

    select(journalId) {
        this.state.journalId = journalId;
    }

    async shiftPeriod(delta) {
        const period = this.state.data.period;
        let year = period.year;
        let month = period.month + delta;
        if (month < 1) { month = 12; year -= 1; }
        if (month > 12) { month = 1; year += 1; }
        await this.load({ year, month });
    }

    async run(method, args, ok) {
        this.state.busy = true;
        try {
            const result = await this.orm.call("ua.bank.board", method, args);
            if (result && result.type) {
                return this.action.doAction(result);
            }
            const message = (result && result.message) || ok;
            if (message) {
                this.notification.add(message, { type: "success" });
            }
            await this.load(this.state.data.period);
        } catch (error) {
            this.notification.add(error.data ? error.data.message : String(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    pullMonth() {
        const period = this.state.data.period;
        return this.run("action_pull_month", [this.state.journalId, period.year, period.month]);
    }

    pullAll() {
        const period = this.state.data.period;
        return this.run("action_pull_all", [period.year, period.month]);
    }

    pullToday() {
        return this.run("action_pull", [this.state.journalId]);
    }

    test() {
        return this.run("action_test", [this.state.journalId]);
    }

    applyRules() {
        return this.run("action_apply_rules", [this.state.journalId]);
    }

    reconcile() {
        return this.run("action_open_reconcile", [this.state.journalId]);
    }

    openStatements() {
        return this.run("action_open_statements", [this.state.journalId]);
    }

    openLines() {
        return this.run("action_open_lines", [this.state.journalId]);
    }

    openConnect() {
        return this.run("action_open_connect", [this.state.journalId]);
    }

    importFile() {
        return this.run("action_import_file", [this.state.journalId]);
    }

    openProvider() {
        return this.run("action_open_providers", [this.state.journalId]);
    }

    createProvider(service) {
        return this.run("action_create_provider", [this.state.journalId, service]);
    }

    openLine(line) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.bank.statement.line",
            res_id: line.id,
            view_mode: "form",
            views: [[false, "form"]],
            context: { view_ref: "account_reconcile_oca.bank_statement_line_form_reconcile_view" },
        });
    }
}

registry.category("actions").add("ua_bank_board", UaBankBoard);
