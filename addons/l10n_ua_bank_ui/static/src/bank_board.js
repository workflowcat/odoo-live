/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

function money(value) {
    const number = Number(value || 0);
    return number.toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export class UaBankBoard extends Component {
    static template = "l10n_ua_bank_ui.BankBoard";
    static props = { ...standardActionServiceProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ data: null, loading: true, busy: false, journalId: null });
        this.money = money;
        onWillStart(() => this.load());
    }

    async load(period = {}) {
        this.state.loading = true;
        try {
            const kwargs = {};
            if (period.year) { kwargs.year = period.year; }
            if (period.month) { kwargs.month = period.month; }
            const data = await this.orm.call("ua.bank.board", "get_screen_data", [], kwargs);
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
        return this.state.data.period.label;
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

    /** Дія екрана: ключ зі списку ua.bank.board.ACTIONS і названі параметри.
     *  Імені методу клієнт не називає - сервер сам вирішує, що за ключем стоїть. */
    async run(key, params, ok) {
        this.state.busy = true;
        try {
            const result = await this.orm.call("ua.bank.board", "run_action", [key, params || {}]);
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
        return this.run("pull_month", { journal_id: this.state.journalId, year: period.year, month: period.month });
    }

    pullAll() {
        const period = this.state.data.period;
        return this.run("pull_all", { year: period.year, month: period.month });
    }

    pullToday() {
        return this.run("pull", { journal_id: this.state.journalId });
    }

    test() {
        return this.run("test", { journal_id: this.state.journalId });
    }

    applyRules() {
        return this.run("apply_rules", { journal_id: this.state.journalId });
    }

    reconcile() {
        return this.run("open_reconcile", { journal_id: this.state.journalId });
    }

    openStatements() {
        return this.run("open_statements", { journal_id: this.state.journalId });
    }

    openLines() {
        return this.run("open_lines", { journal_id: this.state.journalId });
    }

    openConnect() {
        return this.run("open_connect", { journal_id: this.state.journalId });
    }

    importFile() {
        return this.run("import_file", { journal_id: this.state.journalId });
    }

    openProvider() {
        return this.run("open_providers", { journal_id: this.state.journalId });
    }

    createProvider(service) {
        return this.run("create_provider", { journal_id: this.state.journalId, service: service });
    }

    /** Рядок виписки відкриває спільний open_target - подання звірки там уже зашите. */
    async openLine(line) {
        const action = await this.orm.call("ua.bank.board", "open_target", [
            { model: "account.bank.statement.line", res_id: line.id },
        ]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ua_bank_board", UaBankBoard);
