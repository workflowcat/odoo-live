/** @odoo-module **/
/**
 * Смуга навігації ліворуч для всіх застосунків.
 *
 * Замінює вкладки зверху і кнопку переліку застосунків. Застосунок - значок;
 * наведення показує його сторінки, закріплення лишає перелік відкритим.
 * Дані беремо зі стандартного сервісу меню, тому права доступу, адреси сторінок
 * і кнопка «назад» працюють як раніше.
 */
import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";

const PIN_KEY = "ua_rail_pinned";
// нижче цієї ширини закріплений перелік забирав би забагато місця: відкривається лише наведенням
const PIN_MIN_WIDTH = 1200;

// скорочення для значків; решта - перші дві літери назви
const SHORT = {
    "l10n_ua_period.menu_ua_period_root": "ЗП",
    "l10n_ua_navigation.menu_ua_people_root": "ПР",
    "l10n_ua_bank_online.menu_ua_bank_board": "БН",
    "l10n_ua_reporting.menu_ua_reporting_root": "ЗВ",
    "l10n_ua_navigation.menu_ua_setup_root": "НЛ",
};
const OURS = Object.keys(SHORT);

function readPin() {
    try {
        return browser.localStorage.getItem(PIN_KEY) === "1";
    } catch {
        return false;
    }
}

export class UaSideRail extends Component {
    static template = "l10n_ua_shell.SideRail";
    static props = {};

    setup() {
        this.menu = useService("menu");
        this.state = useState({ hoverId: null, pinned: readPin(), tick: 0, wide: browser.innerWidth >= PIN_MIN_WIDTH });
        this.closeTimer = null;
        const rerender = () => {
            this.state.tick++;
            this.applyBodyClass();
        };
        this.env.bus.addEventListener("MENUS:APP-CHANGED", rerender);
        const onResize = () => {
            const wide = browser.innerWidth >= PIN_MIN_WIDTH;
            if (wide !== this.state.wide) {
                this.state.wide = wide;
                this.applyBodyClass();
            }
        };
        browser.addEventListener("resize", onResize);
        onWillUnmount(() => {
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", rerender);
            browser.removeEventListener("resize", onResize);
        });
        this.applyBodyClass();
    }

    applyBodyClass() {
        document.body.classList.add("o_ua_rail_on");
        document.body.classList.toggle("o_ua_rail_pinned", this.state.pinned && this.state.wide && !!this.currentApp);
    }

    get apps() {
        this.state.tick; // залежність для перерендеру
        return this.menu.getApps();
    }

    get ourApps() {
        return this.apps
            .filter((a) => OURS.includes(a.xmlid))
            .sort((a, b) => OURS.indexOf(a.xmlid) - OURS.indexOf(b.xmlid));
    }

    get otherApps() {
        return this.apps.filter((a) => !OURS.includes(a.xmlid));
    }

    get currentApp() {
        this.state.tick;
        return this.menu.getCurrentApp();
    }

    short(app) {
        if (SHORT[app.xmlid]) {
            return SHORT[app.xmlid];
        }
        const words = (app.name || "").split(/\s+/).filter(Boolean);
        return words.length > 1
            ? (words[0][0] + words[1][0]).toUpperCase()
            : (app.name || "?").slice(0, 2).toUpperCase();
    }

    /** Застосунок, чий перелік показуємо: наведений, інакше закріплений поточний. */
    get panelApp() {
        const id = this.state.hoverId;
        if (id) {
            return this.menu.getMenu(id);
        }
        return this.state.pinned && this.state.wide ? this.currentApp : null;
    }

    sections(app) {
        const tree = this.menu.getMenuAsTree(app.id);
        return tree.childrenTree || [];
    }

    isActiveApp(app) {
        return this.currentApp && this.currentApp.id === app.id;
    }

    onEnter(app) {
        clearTimeout(this.closeTimer);
        this.state.hoverId = app.id;
    }

    onLeave() {
        clearTimeout(this.closeTimer);
        this.closeTimer = setTimeout(() => (this.state.hoverId = null), 180);
    }

    onPanelEnter() {
        clearTimeout(this.closeTimer);
    }

    async openApp(app) {
        this.state.hoverId = null;
        // застосунок без власної дії відкриває першу сторінку з дією
        const first = this.firstLeaf(this.menu.getMenuAsTree(app.id));
        await this.menu.selectMenu(first || app);
    }

    firstLeaf(node) {
        if (node.actionID) {
            return node;
        }
        for (const child of node.childrenTree || []) {
            const found = this.firstLeaf(child);
            if (found) {
                return found;
            }
        }
        return null;
    }

    async openMenu(node) {
        this.state.hoverId = null;
        await this.menu.selectMenu(node);
    }

    togglePin() {
        this.state.pinned = !this.state.pinned;
        try {
            browser.localStorage.setItem(PIN_KEY, this.state.pinned ? "1" : "0");
        } catch {
            // приватне вікно: закріплення живе до перезавантаження
        }
        this.applyBodyClass();
    }
}

registry.category("main_components").add("UaSideRail", { Component: UaSideRail });
