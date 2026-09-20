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
    "l10n_ua_home.menu_ua_home_root": "ДМ",
    "l10n_ua_period.menu_ua_period_root": "ЗП",
    "l10n_ua_papers.menu_ua_papers_root": "ПП",
    "l10n_ua_navigation.menu_ua_people_root": "ПР",
    "l10n_ua_bank_online.menu_ua_bank_board": "БН",
    "l10n_ua_reporting.menu_ua_reporting_root": "ЗВ",
    "l10n_ua_navigation.menu_ua_setup_root": "НЛ",
};
const OURS = Object.keys(SHORT);

// Що робить кожна сторінка: одне речення в підказці переліку сторінок.
export const PAGE_HELP = {
    "l10n_ua_home.menu_ua_home_screen": "Карта п'яти розділів, потік між ними і особиста панель: що зробити зараз, що змінилося.",
    "l10n_ua_navigation.menu_ua_period_screen": "Робоче місце місяця: кроки, документи, строки і закриття.",
    "l10n_ua_papers.menu_ua_papers_screen": "Усі папери одним екраном: поля, готовий вигляд до друку і що в папір входить.",
    "l10n_ua_dashboard.menu_ua_dashboard_root": "Нарахування по підрозділах, обороти рахунків і документи місяця.",
    "payroll.hr_payslip_menu": "Листок кожного працівника за місяць: нарахування, податки, сума до виплати.",
    "payroll.hr_payslip_run_menu": "Листки всіх працівників за місяць однією групою для розрахунку і затвердження.",
    "l10n_ua_payroll_ui.menu_ua_payment_batch": "Відомості на виплату зарплати через банк і файли для банку.",
    "l10n_ua_payroll_ui.menu_ua_advance_sheet": "Відомості авансу за першу половину місяця.",
    "l10n_ua_changes.menu_ua_changes_root": "Кожна зміна суми, часу або стану після розрахунку: було, стало, хто.",
    "l10n_ua_hire.menu_ua_hire": "Кандидати і прийняття: дані, документи, перевірки, наказ і повідомлення.",
    "l10n_ua_navigation.menu_ua_people_screen": "Працівники одним екраном: перелік, підрозділи, схема підпорядкування і штатний розпис.",
    "l10n_ua_navigation.menu_ua_people_employees": "Картка працівника: договір, оклад, документи, відпустки, військовий облік.",
    "l10n_ua_navigation.menu_ua_people_org_chart": "Хто кому підпорядкований, від директора до працівників.",
    "l10n_ua_navigation.menu_ua_people_departments": "Підрозділи компанії, їхні керівники і кількість працівників.",
    "l10n_ua_navigation.menu_ua_people_orders": "Кадрові накази: прийняття, звільнення, зміна окладу, відпустки.",
    "l10n_ua_payroll_ui.menu_ua_staff_list_docs": "Штатний розпис: посади, штатні одиниці, оклади і фонд.",
    "l10n_ua_navigation.menu_ua_people_leaves": "Відпустки, лікарняні та інші відсутності працівників.",
    "l10n_ua_hr_orders.menu_ua_hr_doc_requirement": "Документи, які має мати кожен працівник, і в кого їх бракує.",
    "l10n_ua_gph.menu_ua_gph": "Виконавці за договорами ЦПХ і ФОП: суми, строки і виплати поза штатом.",
    "l10n_ua_kp.menu_ua_kp_code": "Коди професій за класифікатором ДК 003:2010: які використовує компанія і чи звірені вони.",
    "l10n_ua_navigation.menu_ua_people_timesheet": "Табель П-5: дні і години кожного працівника за місяць.",
    "l10n_ua_payroll_ui.menu_ua_military_liable": "Працівники, які перебувають на військовому обліку.",
    "l10n_ua_payroll_ui.menu_ua_military_list": "Списки персонального військового обліку для ТЦК.",
    "l10n_ua_payroll_ui.menu_ua_military_notice": "Повідомлення до ТЦК про зміну облікових даних працівників.",
    "l10n_ua_payroll_ui.menu_ua_military_reserved": "Списки заброньованих працівників.",
    "l10n_ua_payroll_ui.menu_ua_military_needs_check": "Працівники, у яких звірку з ТЦК не проведено.",
    "l10n_ua_navigation.menu_ua_bank_screen": "Залишки, виписки і звірка рахунків компанії за місяць.",
    "l10n_ua_navigation.menu_ua_setup_bank": "Підготовка підключення рахунків до автоматичних виписок банку.",
    "l10n_ua_navigation.menu_ua_reporting_screen": "Звіти до ДПС і ПФУ, облікові звіти і кадрові форми: перевірки, файли, подання.",
    "l10n_ua_payroll_ui.menu_ua_pfu_claim_docs": "Заяви-розрахунки до ПФУ на лікарняні й декретні та їх фінансування.",
    "l10n_ua_navigation.menu_ua_setup_profile": "Анкета про компанію: відповіді стають налаштуваннями розрахунку.",
    "l10n_ua_navigation.menu_ua_setup_params": "Законодавчі числа з датою дії: мінімальна зарплата, ставки, межі.",
    "l10n_ua_navigation.menu_ua_setup_cpi": "Індекси споживчих цін Держстату для індексації зарплати.",
    "l10n_ua_navigation.menu_ua_setup_accounts": "Рахунки обліку для кожного рядка розрахункового листка.",
    "l10n_ua_average.menu_ua_earnings_history": "Заробіток працівників за 12 місяців для відпускних і лікарняних.",
};

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

    pageHelp(node) {
        return PAGE_HELP[node.xmlid] || "";
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
