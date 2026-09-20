/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const GUIDE_KEY = "ua_home_guide";
const PANEL_KEY = "ua_home_panel_collapsed";

// Позначка рівня бейджа - завжди слово поруч із кольором, ніколи сам колір.
const BADGE_WORD = { crit: "терміново", warn: "увага", done: "готово" };

// Підказки під назвою розділу в режимі «Підказки»: одне речення простою мовою.
const REGION_HINT = {
    people: "Кадрові справи: працівники, документи на підпис, прийняття, військовий облік.",
    payroll: "Розрахунок місяця: табель, аванс, розрахункові листки, накази.",
    bank: "Виписка банку і звірка платежів із нарахуваннями.",
    reporting: "Податкова звітність і подання до державних органів.",
    setup: "Анкета компанії і налаштування, за якими рахується зарплата.",
};

/**
 * Одна лінія потоку між двома картками розділів: від краю картки-джерела до краю картки-цілі,
 * ніколи не крізь третю картку. Розкладка карти стала (ПР ліворуч на всю висоту, ЗП/НЛ одне
 * над одним у центрі, БН/ЗВ одне над одним праворуч), але висота кожної картки залежить від
 * її вмісту, тому координати рахуються з реальних rect'ів на екрані (measureFlows), а не з
 * фіксованих відсотків. a/b - {left,right,top,bottom} відносно контейнера карти.
 *
 * Повертає null, якщо чистого шляху немає (картки перекриваються по обох осях) - тоді лінію
 * просто не малюємо замість того, щоб тягнути її крізь картку.
 */
function routeFlow(a, b, gap) {
    if (!a || !b) {
        return null;
    }
    const rightOf = b.left >= a.right;
    const leftOf = b.right <= a.left;
    const below = b.top >= a.bottom;
    const above = b.bottom <= a.top;

    let x1, y1, x2, y2;
    if (rightOf && !below && !above) {
        // горизонтально, на висоті перетину обох карток
        x1 = a.right; x2 = b.left;
        y1 = y2 = (Math.max(a.top, b.top) + Math.min(a.bottom, b.bottom)) / 2;
    } else if (leftOf && !below && !above) {
        x1 = a.left; x2 = b.right;
        y1 = y2 = (Math.max(a.top, b.top) + Math.min(a.bottom, b.bottom)) / 2;
    } else if (below && !rightOf && !leftOf) {
        // вертикально, по ширині перетину обох карток
        y1 = a.bottom; y2 = b.top;
        x1 = x2 = (Math.max(a.left, b.left) + Math.min(a.right, b.right)) / 2;
    } else if (above && !rightOf && !leftOf) {
        y1 = a.top; y2 = b.bottom;
        x1 = x2 = (Math.max(a.left, b.left) + Math.min(a.right, b.right)) / 2;
    } else if (rightOf && below) {
        // картка по діагоналі - кут у кут крізь порожній прогал між рядами й колонками
        x1 = a.right; y1 = a.bottom; x2 = b.left; y2 = b.top;
    } else if (rightOf && above) {
        x1 = a.right; y1 = a.top; x2 = b.left; y2 = b.bottom;
    } else if (leftOf && below) {
        x1 = a.left; y1 = a.bottom; x2 = b.right; y2 = b.top;
    } else if (leftOf && above) {
        x1 = a.left; y1 = a.top; x2 = b.right; y2 = b.bottom;
    } else {
        return null; // картки перекриваються по обох осях - чистого шляху немає
    }

    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.hypot(dx, dy);
    if (len < gap * 2) {
        return null; // картки впритул - місця для лінії й вістря нема
    }
    const ux = dx / len, uy = dy / len;
    // відступ з обох боків, щоб лінія і вістря не впирались у рамку картки
    return { x1: x1 + ux * gap, y1: y1 + uy * gap, x2: x2 - ux * gap, y2: y2 - uy * gap };
}

function readGuide() {
    try {
        return browser.localStorage.getItem(GUIDE_KEY) === "1";
    } catch {
        return false; // приватне вікно: підказки лишаються вимкненими, як і за замовчуванням
    }
}

function readPanelCollapsed() {
    try {
        return browser.localStorage.getItem(PANEL_KEY) === "1";
    } catch {
        return false;
    }
}

/** Українська форма іменника після числівника n: 1 - one, 2-4 - few, решта - many. */
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

export class UaHome extends Component {
    static template = "l10n_ua_home.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.mapRef = useRef("map");
        this.state = useState({
            data: null,
            loading: true,
            busy: false,
            opening: null, // ключ елемента, що зараз відкривається - для маленького індикатора саме на ньому
            guide: readGuide(),
            collapsed: readPanelCollapsed(),
            flowLines: [], // рахується з реальних rect'ів карток - див. measureFlows()
            recentExpanded: false, // «ще» під «Свіже» - показати решту відфільтрованого списку
            showAutomatic: false, // перемикач: включити рядки від ботів/службових акаунтів
            draftsOpen: false, // «Ваші чернетки» - згорнутий блок, розгортається кліком
        });
        this.badgeWord = (level) => BADGE_WORD[level] || level;
        this.regionHint = (key) => REGION_HINT[key] || "";
        onWillStart(() => this.load());

        // Стрілки потоку йдуть від реальних країв карток (не від фіксованих відсотків), тому
        // перераховуємо після кожного перемальовування даних і при будь-якій зміні розміру карти
        // (вікно, згортання панелі «Моє» - карта тоді стає ширшою).
        useEffect(() => this.measureFlows(), () => [this.state.data]);
        onMounted(() => {
            this.flowResizeObserver = new ResizeObserver(() => this.measureFlows());
            if (this.mapRef.el) {
                this.flowResizeObserver.observe(this.mapRef.el);
            }
        });
        onWillUnmount(() => this.flowResizeObserver && this.flowResizeObserver.disconnect());
    }

    // ------------------------------------------------------------------ завантаження
    async load(period = {}) {
        this.state.loading = true;
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const data = await this.orm.call("ua.home", "get_screen_data", [], period);
        if (seq !== this.loadSeq) {
            return; // прийшла свіжіша відповідь, поки чекали цю - застаріле відкидаємо
        }
        this.state.data = data;
        this.state.loading = false;
    }

    /** Сусідній місяць: стрілки в шапці. */
    shiftMonth(delta) {
        const { year, month } = this.state.data.period;
        const index = year * 12 + (month - 1) + delta;
        return this.load({ year: Math.floor(index / 12), month: (index % 12) + 1 });
    }

    selectPeriod(p) {
        if (p.year === this.state.data.period.year && p.month === this.state.data.period.month) {
            return;
        }
        return this.load({ year: p.year, month: p.month });
    }

    // ------------------------------------------------------------------ підказки і панель
    toggleGuide() {
        this.state.guide = !this.state.guide;
        try {
            browser.localStorage.setItem(GUIDE_KEY, this.state.guide ? "1" : "0");
        } catch {
            // приватне вікно: стан живе до перезавантаження
        }
    }

    togglePanel() {
        this.state.collapsed = !this.state.collapsed;
        try {
            browser.localStorage.setItem(PANEL_KEY, this.state.collapsed ? "1" : "0");
        } catch {
            // приватне вікно
        }
    }

    // ------------------------------------------------------------------ панель «Моє»: Свіже і чернетки
    /** «Свіже» без рядків автоматики (OdooBot тощо), доки перемикач не увімкнено - див. рядок.automatic,
     * що рахує бекенд (ua.home._is_automatic). */
    get filteredRecent() {
        const rows = (this.state.data && this.state.data.recent) || [];
        return this.state.showAutomatic ? rows : rows.filter((row) => !row.automatic);
    }

    /** Перші п'ять рядків «Свіжого», або всі відфільтровані - після «ще». */
    get visibleRecent() {
        const rows = this.filteredRecent;
        return this.state.recentExpanded ? rows : rows.slice(0, 5);
    }

    expandRecent() {
        this.state.recentExpanded = true;
    }

    toggleAutomatic() {
        this.state.showAutomatic = !this.state.showAutomatic;
    }

    toggleDrafts() {
        if (this.state.data.drafts.length) {
            this.state.draftsOpen = !this.state.draftsOpen;
        }
    }

    // ------------------------------------------------------------------ карта: пункти розділу
    /** Перші шість пунктів розділу - решта ховається за «ще N», що відкриває корінь розділу
     * (та сама ціль, що й клік по картці). Чотири були довільним лімітом; шість тримає картку
     * компактною навіть для найбільшого розділу (Працівники - 14 пунктів). */
    visibleItems(region) {
        return region.items.slice(0, 6);
    }

    // ------------------------------------------------------------------ карта і стрілки потоку
    get flowLines() {
        return this.state.flowLines;
    }

    /**
     * Перераховує лінії потоку з реальних розмірів карток розділів (getBoundingClientRect) -
     * висота картки залежить від її вмісту, тому фіксовані координати їй не відповідають. Пари
     * беруться з data.flows; пару, для якої на екрані нема обох карток або чистого шляху між
     * ними (routeFlow поверне null), просто пропускаємо - краще без стрілки, ніж крізь картку.
     */
    measureFlows() {
        const mapEl = this.mapRef.el;
        const data = this.state.data;
        if (!mapEl || !data) {
            this.state.flowLines = [];
            return;
        }
        const mapBox = mapEl.getBoundingClientRect();
        if (!mapBox.width || !mapBox.height) {
            this.state.flowLines = [];
            return;
        }
        const rects = {};
        for (const region of data.regions) {
            const el = mapEl.querySelector(".o_ua_home_region_" + region.key);
            if (!el) {
                continue;
            }
            const r = el.getBoundingClientRect();
            rects[region.key] = {
                left: r.left - mapBox.left,
                top: r.top - mapBox.top,
                right: r.right - mapBox.left,
                bottom: r.bottom - mapBox.top,
            };
        }
        const GAP = 5; // невеликий відступ від рамки картки, щоб лінія й вістря не впирались у неї
        this.state.flowLines = (data.flows || [])
            .map(([from, to], i) => {
                const line = routeFlow(rects[from], rects[to], GAP);
                return line && { key: `${from}-${to}-${i}`, light: from === "setup", ...line };
            })
            .filter(Boolean);
    }

    get primaryTodo() {
        const todo = (this.state.data && this.state.data.todo) || [];
        return todo[0] || null;
    }

    get employeeLabel() {
        const n = (this.state.data && this.state.data.company.employees) || 0;
        return `${n} ${plural(n, "працівник", "працівники", "працівників")}`;
    }

    itemsLabel(count) {
        return `${count} ${plural(count, "пункт", "пункти", "пунктів")}`;
    }

    // ------------------------------------------------------------------ відкриття цілей
    isOpening(key) {
        return this.state.busy && this.state.opening === key;
    }

    /** Єдиний прохід для всього, що клікабельне на екрані - завжди через open_target бекенда. */
    async openTarget(target, key) {
        if (!target || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.opening = key || null;
        try {
            const action = await this.orm.call("ua.home", "open_target", [target]);
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || "Помилка", { type: "danger" });
        } finally {
            this.state.busy = false;
            this.state.opening = null;
        }
    }

    /** Журнал змін місяця: та сама дія і контекст, що й на «Періоді». */
    openChangeLog() {
        const period = this.state.data.period;
        return this.openTarget(
            {
                xmlid: "l10n_ua_changes.action_ua_change_log",
                domain: [["year", "=", period.year], ["month", "=", period.month]],
                context: { search_default_f_new: 1, search_default_g_area: 1 },
            },
            "changelog"
        );
    }
}

registry.category("actions").add("ua_home", UaHome);
