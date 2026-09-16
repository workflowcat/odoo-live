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

// Секції "поле - значення": порожні рядки картка ховає, «Показати всі» відкриває решту.
// Стан збережено в localStorage per section key, не per employee - раз обрано «показати
// всі» для «Оплата», так лишається для кожного працівника.
const FIELD_SECTIONS = ["person", "pay", "vacation", "military"];
const SHOW_ALL_PREFIX = "l10n_ua_card_show_all_";
// Хроніка за замовчуванням показує 12 останніх подій.
const TIMELINE_LIMIT = 12;
const TIMELINE_KEY = "timeline";

function readShowAll(key) {
    try {
        return window.localStorage.getItem(SHOW_ALL_PREFIX + key) === "1";
    } catch {
        return false;
    }
}

function writeShowAll(key, value) {
    try {
        if (value) {
            window.localStorage.setItem(SHOW_ALL_PREFIX + key, "1");
        } else {
            window.localStorage.removeItem(SHOW_ALL_PREFIX + key);
        }
    } catch {
        // приватний режим/квота - «Показати всі» просто не запам'ятається
    }
}

export class UaEmployeeCard extends Component {
    static template = "l10n_ua_card_ui.EmployeeCard";
    static props = { ...standardWidgetProps };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const showAll = {};
        for (const key of FIELD_SECTIONS) {
            showAll[key] = readShowAll(key);
        }
        showAll[TIMELINE_KEY] = readShowAll(TIMELINE_KEY);

        this.state = useState({ data: null, documents: [], loading: true, avatarFailed: false, showAll });

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

    toggleShowAll(key) {
        this.state.showAll[key] = !this.state.showAll[key];
        writeShowAll(key, this.state.showAll[key]);
    }

    // Рядки секції: приховує порожні, якщо «Показати всі» не увімкнено для цієї секції.
    sectionRows(key) {
        const rows = (this.state.data && this.state.data[key]) || [];
        return this.state.showAll[key] ? rows : rows.filter((row) => !row.empty);
    }

    sectionHasValues(key) {
        const rows = (this.state.data && this.state.data[key]) || [];
        return rows.some((row) => !row.empty);
    }

    get contextLine() {
        const h = this.state.data && this.state.data.header;
        if (!h) {
            return "";
        }
        return [h.job_title, h.department, "з " + h.since, "таб. № " + h.badge_number].join(" · ");
    }

    get statusPill() {
        const badges = (this.state.data && this.state.data.header && this.state.data.header.badges) || [];
        return badges[0] || null;
    }

    get extraBadges() {
        const badges = (this.state.data && this.state.data.header && this.state.data.header.badges) || [];
        return badges.slice(1);
    }

    get documentsToSignCount() {
        return this.state.documents.filter((d) => d.can_sign).length;
    }

    get visibleTimeline() {
        const events = (this.state.data && this.state.data.timeline) || [];
        return this.state.showAll[TIMELINE_KEY] ? events : events.slice(0, TIMELINE_LIMIT);
    }

    get hasMoreTimeline() {
        const events = (this.state.data && this.state.data.timeline) || [];
        return events.length > TIMELINE_LIMIT;
    }

    // Хроніка і документи ведуть до свого запису (листок, наказ/версія, відпустка...) звичайною
    // формою моделі - без спеціального серверного методу, це просто відкриття форми за id.
    async openRecord(resModel, resId) {
        if (!resModel || !resId) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
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
