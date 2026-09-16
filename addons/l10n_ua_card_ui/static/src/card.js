import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

// Ключі дій у порядку появи в шапці картки: одна головна, дві другорядні, решта під «Ще».
const PRIMARY_KEYS = ["new_leave"];
const SECONDARY_KEYS = ["change_wage", "new_document"];
const LABEL_OVERRIDES = { doc_pack: "Перевірка документів" };

export class UaEmployeeCard extends Component {
    static template = "l10n_ua_card_ui.EmployeeCard";
    static props = { ...standardWidgetProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({ data: null, documents: [], loading: true, avatarFailed: false });

        onWillStart(() => this.loadData(this.props.record.resId));
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                return this.loadData(nextProps.record.resId);
            }
        });
    }

    async loadData(resId) {
        this.state.loading = true;
        this.state.avatarFailed = false;
        if (!resId) {
            this.state.data = null;
            this.state.loading = false;
            return;
        }
        const [data, documents] = await Promise.all([
            this.orm.call("hr.employee", "get_card_data", [resId]),
            this.orm.call("hr.employee", "get_card_documents", [resId]),
        ]);
        this.state.data = data;
        this.state.documents = documents;
        this.state.loading = false;
    }

    onAvatarError() {
        this.state.avatarFailed = true;
    }

    get allActions() {
        const actions = (this.state.data && this.state.data.actions) || [];
        return actions.map((a) => (LABEL_OVERRIDES[a.key] ? { ...a, label: LABEL_OVERRIDES[a.key] } : a));
    }

    get primaryActions() {
        return this.allActions.filter((a) => PRIMARY_KEYS.includes(a.key));
    }

    get secondaryActions() {
        return this.allActions.filter((a) => SECONDARY_KEYS.includes(a.key));
    }

    get moreActions() {
        return this.allActions.filter((a) => !PRIMARY_KEYS.includes(a.key) && !SECONDARY_KEYS.includes(a.key));
    }

    async reload() {
        await this.props.record.load();
        await this.loadData(this.props.record.resId);
    }

    async onActionClick(actionInfo) {
        const resId = this.props.record.resId;
        const result = await this.orm.call("hr.employee", actionInfo.method, [resId]);
        if (result && typeof result === "object") {
            await this.action.doAction(result, { onClose: () => this.reload() });
        } else {
            await this.reload();
        }
    }

    async onDocumentSign(doc) {
        const resId = this.props.record.resId;
        await this.orm.call("hr.employee", "action_ua_card_document_sign", [resId, doc.id]);
        await this.reload();
    }

    async onDocumentPrint(doc) {
        const resId = this.props.record.resId;
        const result = await this.orm.call("hr.employee", "action_ua_card_document_print", [resId, doc.id]);
        if (result && typeof result === "object") {
            await this.action.doAction(result);
        }
    }
}

export const uaEmployeeCard = {
    component: UaEmployeeCard,
    fieldDependencies: [],
};

registry.category("view_widgets").add("ua_employee_card", uaEmployeeCard);
