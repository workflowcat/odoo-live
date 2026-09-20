/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const SIDE_KEY = "ua_papers_side_collapsed";

function readSideCollapsed() {
    try {
        return browser.localStorage.getItem(SIDE_KEY) === "1";
    } catch {
        return false; // приватне вікно: права колонка лишається розгорнутою, як і за замовчуванням
    }
}

/** Українська форма іменника після числівника n: 1 - one, 2-4 - few, решта - many.
 *  Дубльовано з home.js: кожен екран володіє лише своїми static/src файлами (див. примітку
 *  на початку home.scss), спільного utils-модуля для цього немає. */
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

export class UaPapers extends Component {
    static template = "l10n_ua_papers.Papers";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            loading: true,
            busy: false,
            opening: null, // ключ елемента, що зараз відкривається - для маленького індикатора саме на ньому
            sideCollapsed: readSideCollapsed(),
        });
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------ завантаження
    /** Один шлях для будь-якої зміни екрана (місяць, папір, поле): завжди повний
     *  get_screen_data з усіма аргументами, які мають лишитися. Захист від застарілої
     *  відповіді - той самий лічильник loadSeq, що й у home.js. */
    async load(kwargs = {}) {
        this.state.loading = true;
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const data = await this.orm.call("ua.papers", "get_screen_data", [], kwargs);
        if (seq !== this.loadSeq) {
            return; // прийшла свіжіша відповідь, поки чекали цю - застаріле відкидаємо
        }
        this.state.data = data;
        this.state.loading = false;
    }

    /** Сусідній місяць: стрілки в смузі періоду. Папір лишається вибраним (спека: "зміна
     *  місяця міняє period.label і не ламає вибраний папір"), а params полів скидаються -
     *  вони рахувались для старого періоду і для нового вже не мають сенсу; бекенд сам
     *  підставить дефолти нового періоду для того самого paper. Це рішення спека прямо не
     *  описує (вона лише каже, що params - "як їх повернув попередній виклик", без слова
     *  про зміну місяця), тому винесено в звіт як припущення. */
    shiftMonth(delta) {
        const { year, month } = this.state.data.period;
        const index = year * 12 + (month - 1) + delta;
        return this.load({
            year: Math.floor(index / 12),
            month: (index % 12) + 1,
            paper: this.state.data.paper.key,
        });
    }

    selectPeriod(p) {
        const period = this.state.data.period;
        if (p.year === period.year && p.month === period.month) {
            return;
        }
        return this.load({ year: p.year, month: p.month, paper: this.state.data.paper.key });
    }

    /** Клік по рядку паперу в лівій колонці: той самий період, інший папір, поля з нуля. */
    selectPaper(key) {
        if (this.state.busy || key === this.state.data.paper.key) {
            return;
        }
        const { year, month } = this.state.data.period;
        return this.load({ year, month, paper: key });
    }

    /** Поточні значення полів вибраного паперу - params для наступного виклику. Бекенд не
     *  повертає params назад як єдиний словник, лише масив fields зі значенням кожного,
     *  тому клієнт збирає params сам з того, що зараз намальовано на екрані. */
    currentParams() {
        const params = {};
        for (const f of this.state.data.paper.fields) {
            params[f.key] = f.value;
        }
        return params;
    }

    /** Зміна будь-якого поля паперу: одразу новий get_screen_data з оновленим params,
     *  перегляд і перевірки перемальовуються разом з полями. */
    changeField(key, value) {
        const { year, month } = this.state.data.period;
        const params = this.currentParams();
        params[key] = value;
        return this.load({ year, month, paper: this.state.data.paper.key, params });
    }

    // ------------------------------------------------------------------ дії паперу
    /** Кнопки з paper.actions (шапка і повтор під переглядом - однакові, той самий метод).
     *  Усі три дії зрізу (print/compose/edit) - огляд або чернетка, жодна не проведення:
     *  без діалогу плану, просто виклик і або reload, або дія action-сервісу. */
    get secondaryActions() {
        // Головна дія малюється в шапці, тут - лише решта.
        return (this.state.data?.paper?.actions || []).filter((a) => !a.primary);
    }

    async runAction(a) {
        if (!a.enabled || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.opening = "action-" + a.key;
        try {
            const { year, month } = this.state.data.period;
            const result = await this.orm.call("ua.papers", "run_action", [], {
                paper: this.state.data.paper.key,
                action_key: a.key,
                year,
                month,
                params: this.currentParams(),
            });
            if (result && result.reload) {
                await this.load({ year, month, paper: this.state.data.paper.key, params: this.currentParams() });
            } else {
                await this.action.doAction(result);
            }
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
            this.state.opening = null;
        }
    }

    // ------------------------------------------------------------------ відкриття цілей
    isOpening(key) {
        return this.state.busy && this.state.opening === key;
    }

    /** Єдиний прохід для всього, що клікабельне на екрані - завжди через open_target бекенда,
     *  один в один як ua.home.open_target. */
    async openTarget(target, key) {
        if (!target || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.opening = key || null;
        try {
            const action = await this.orm.call("ua.papers", "open_target", [target]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
            this.state.opening = null;
        }
    }

    // ------------------------------------------------------------------ права колонка
    toggleSide() {
        this.state.sideCollapsed = !this.state.sideCollapsed;
        try {
            browser.localStorage.setItem(SIDE_KEY, this.state.sideCollapsed ? "1" : "0");
        } catch {
            // приватне вікно: стан живе до перезавантаження
        }
    }

    // ------------------------------------------------------------------ похідні дані для шаблону
    /** Список паперів лівої колонки, згрупований за group у порядку першої появи - бекенд
     *  віддає плаский масив (як у спеці), групування - справа клієнта. */
    get paperGroups() {
        const groups = [];
        const byKey = new Map();
        for (const p of (this.state.data.papers || [])) {
            let g = byKey.get(p.group);
            if (!g) {
                g = { key: p.group, label: p.group_label, papers: [] };
                byKey.set(p.group, g);
                groups.push(g);
            }
            g.papers.push(p);
        }
        return groups;
    }

    get employeeLabel() {
        const n = (this.state.data && this.state.data.period.employees) || 0;
        return `${n} ${plural(n, "працівник", "працівники", "працівників")}`;
    }
}

registry.category("actions").add("ua_papers", UaPapers);
