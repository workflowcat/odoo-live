/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const VIEW_LABELS = [
    ["list", "Перелік"],
    ["departments", "За підрозділами"],
    ["chart", "Схема"],
    ["staff", "Штатний розпис"],
];

/** Українська форма іменника після числівника n: 1 - one, 2-4 - few, решта - many.
 *  Дубльовано з home.js/papers.js: кожен екран володіє лише своїми static/src файлами. */
function plural(n, one, few, many) {
    n = Math.abs(Math.trunc(n || 0));
    if (n % 100 >= 11 && n % 100 <= 14) {
        return many;
    }
    const r = n % 10;
    if (r === 1) {
        return one;
    }
    if (r >= 2 && r <= 4) {
        return few;
    }
    return many;
}

/** Число українською без зайвого нуля: 11,5 і 17, не 11,50 і 17,0. */
function fmtNum(v, digits = 1) {
    let text = (Number(v) || 0).toLocaleString("uk-UA", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    if (text.includes(",")) {
        text = text.replace(/0+$/, "").replace(/,$/, "");
    }
    return text;
}

function fmtMoney(v) {
    return (Number(v) || 0).toLocaleString("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export class UaPeople extends Component {
    static template = "l10n_ua_people.People";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            loading: true,
            busy: false,
            opening: null, // ключ елемента, що зараз відкривається
            searchInput: "",
        });
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------ завантаження
    /** Один шлях для будь-якої зміни екрана (погляд, пошук): завжди повний
     *  get_screen_data. Захист від застарілої відповіді - як у home.js/papers.js. */
    async load(kwargs = {}) {
        this.state.loading = true;
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const data = await this.orm.call("ua.people", "get_screen_data", [], kwargs);
        if (seq !== this.loadSeq) {
            return; // прийшла свіжіша відповідь, поки чекали цю - застаріле відкидаємо
        }
        this.state.data = data;
        this.state.searchInput = data.search || "";
        this.state.loading = false;
    }

    selectView(view) {
        if (this.state.busy || view === this.state.data.view) {
            return;
        }
        return this.load({ view, search: this.state.data.search });
    }

    onSearchInput(ev) {
        this.state.searchInput = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.runSearch();
        }
    }

    runSearch() {
        if (this.state.searchInput === this.state.data.search) {
            return;
        }
        return this.load({ view: this.state.data.view, search: this.state.searchInput });
    }

    get views() {
        return VIEW_LABELS.map(([key, label]) => ({ key, label }));
    }

    // ------------------------------------------------------------------ шапка
    get summaryLabel() {
        const s = this.state.data.summary;
        const people = plural(s.people, "працівник", "працівники", "працівників");
        const deps = plural(s.departments, "підрозділ", "підрозділи", "підрозділів");
        return `${s.people} ${people} · ${s.departments} ${deps} · ${fmtNum(s.units)} штатних одиниць`;
    }

    get staffContextLabel() {
        const staff = this.state.data.staff;
        let text = `склад на ${staff.as_of}`;
        if (staff.current) {
            text += ` · чинний розпис ${staff.current.name}`;
        }
        return text;
    }

    // ------------------------------------------------------------------ дії
    isOpening(key) {
        return this.state.busy && this.state.opening === key;
    }

    /** Єдиний прохід для всього, що клікабельне на екрані - завжди через open_target
     *  бекенда, один в один як ua.home/ua.papers. */
    async openTarget(target, key) {
        if (!target || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.opening = key || null;
        try {
            const action = await this.orm.call("ua.people", "open_target", [target]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
            this.state.opening = null;
        }
    }

    async createStaffList() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.opening = "create-staff-list";
        try {
            const action = await this.orm.call("ua.people", "run_action", ["create_staff_list"]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
            this.state.opening = null;
        }
    }

    /** «Новий працівник» - стандартна форма hr.employee, без проходу через бекенд
     *  цього екрана: створення картки не входить у контракт ua.people. */
    newEmployee() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------ погляд «Схема»
    /** Дерево з manager_id сплющене у список {..row, depth} - без бібліотек і без canvas
     *  (спека: «Малюй просто - вкладені рядки з відступом. Це перелік, а не картинка»). */
    get chartRows() {
        const rows = (this.state.data && this.state.data.chart) || [];
        const byId = new Map();
        for (const r of rows) {
            byId.set(r.id, { row: r, children: [] });
        }
        const roots = [];
        for (const r of rows) {
            const node = byId.get(r.id);
            const parent = r.manager_id && byId.get(r.manager_id);
            if (parent) {
                parent.children.push(node);
            } else {
                roots.push(node);
            }
        }
        const byName = (a, b) => (a.row.name || "").localeCompare(b.row.name || "", "uk");
        roots.sort(byName);
        for (const node of byId.values()) {
            node.children.sort(byName);
        }

        const flat = [];
        const visited = new Set(); // захист від циклу в parent_id
        const walk = (node, depth) => {
            if (visited.has(node.row.id)) {
                return;
            }
            visited.add(node.row.id);
            flat.push({ ...node.row, depth });
            for (const child of node.children) {
                walk(child, depth + 1);
            }
        };
        for (const root of roots) {
            walk(root, 0);
        }
        return flat;
    }

    // ------------------------------------------------------------------ форматування
    fmtNum(v, digits) {
        return fmtNum(v, digits);
    }

    fmtMoney(v) {
        return fmtMoney(v);
    }

    wordPeople(n) {
        return plural(n, "особа", "особи", "осіб");
    }
}

registry.category("actions").add("ua_people", UaPeople);
