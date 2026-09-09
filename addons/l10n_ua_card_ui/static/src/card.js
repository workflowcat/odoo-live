import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";

export class UaEmployeeCard extends Component {
    static template = "l10n_ua_card_ui.EmployeeCard";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({ data: null, loading: true, avatarFailed: false });

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
        this.state.data = await this.orm.call("hr.employee", "get_card_data", [resId]);
        this.state.loading = false;
    }

    onAvatarError() {
        this.state.avatarFailed = true;
    }

    get headerActions() {
        return (this.state.data && this.state.data.actions || []).filter((a) => a.group === "header");
    }

    get footerActions() {
        return (this.state.data && this.state.data.actions || []).filter((a) => a.group === "footer");
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
}

export const uaEmployeeCard = {
    component: UaEmployeeCard,
    fieldDependencies: [],
};

registry.category("view_widgets").add("ua_employee_card", uaEmployeeCard);
