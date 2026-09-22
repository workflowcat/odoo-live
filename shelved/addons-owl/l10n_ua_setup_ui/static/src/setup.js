/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const STATE_LABEL = {
    missing: "бракує",
    supplied: "надано",
    proposed: "запропоновано",
    confirmed: "підтверджено",
};

export class UaSetup extends Component {
    static template = "l10n_ua_setup_ui.Setup";
    static props = { ...standardActionServiceProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            loading: true,
            busy: false,
            filter: "all",
            open: {},
            description: "",
        });
        this.stateLabel = (value) => STATE_LABEL[value] || value;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("ua.setup.profile", "screen", []);
            this.state.description = this.state.data.description;
            if (!Object.keys(this.state.open).length) {
                for (const section of this.state.data.sections) {
                    this.state.open[section.name] = section.required_missing > 0;
                }
            }
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------ показ
    visible(section) {
        return this.questions(section).length > 0;
    }

    questions(section) {
        const filter = this.state.filter;
        return section.questions.filter((q) => {
            if (filter === "missing") {
                return q.state === "missing";
            }
            if (filter === "required") {
                return q.required;
            }
            if (filter === "proposed") {
                return q.state === "proposed";
            }
            return true;
        });
    }

    toggle(section) {
        this.state.open[section.name] = !this.state.open[section.name];
    }

    isOpen(section) {
        return !!this.state.open[section.name];
    }

    setFilter(value) {
        this.state.filter = value;
        if (value !== "all") {
            for (const section of this.state.data.sections) {
                this.state.open[section.name] = true;
            }
        }
    }

    // ------------------------------------------------------------------ запис
    async save(question, value) {
        this.state.busy = true;
        try {
            this.state.data = await this.orm.call("ua.setup.profile", "set_answer", [question.id, value]);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }

    showInput(question) {
        // Питання-налаштування мають закритий список: вільний текст лише через «Свій варіант».
        if (!question.is_setting) {
            return true;
        }
        if (!question.options.length) {
            return true;
        }
        return /свій варіант/i.test(question.value || "");
    }

    chosen(question, option) {
        if (question.kind !== "multi") {
            return question.value === option;
        }
        return question.value.split(", ").includes(option);
    }

    async pick(question, option) {
        if (question.kind === "multi") {
            const current = question.value ? question.value.split(", ") : [];
            const next = current.includes(option)
                ? current.filter((item) => item !== option)
                : [...current, option];
            return this.save(question, next.join(", "));
        }
        return this.save(question, question.value === option ? "" : option);
    }

    onText(question, event) {
        const value = event.target.value;
        if (value !== question.value) {
            this.save(question, value);
        }
    }

    async onDescription(event) {
        this.state.description = event.target.value;
        this.state.data = await this.orm.call("ua.setup.profile", "set_description", [event.target.value]);
    }

    // ------------------------------------------------------------------ дії
    async run(action) {
        this.state.busy = true;
        try {
            const result = await this.orm.call("ua.setup.profile", "run", [action]);
            if (result.message) {
                this.notification.add(result.message, { type: "success" });
            }
            this.state.data = result.data;
            this.state.description = result.data.description;
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("actions").add("ua_setup", UaSetup);
