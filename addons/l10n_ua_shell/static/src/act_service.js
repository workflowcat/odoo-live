/** @odoo-module **/
/**
 * Сервіс ua_act: модель дії з docs/payroll/action-model.md.
 *
 * Огляд лишається миттєвим; чернетка лишається звичайним редагуванням. Цей
 * сервіс - для двох повільніших класів, «узгодження» і «проведення»: план
 * перед дією (якщо є), виконання, показ наслідків рядок за рядком, вікно
 * скасування 20 с. Усе інше - навігація, дані екрана - не чіпаємо.
 *
 * Використання з будь-якого власного OWL-екрана:
 *
 *   const act = useService("ua_act");
 *   await act.run({
 *       model: "ua.hire.case", id, method: "action_hire",
 *       plan: "action_hire_plan",
 *       confirm: "Прийняти на роботу",
 *       undo: "action_reopen",
 *       onDone: () => this.load(),
 *       openTarget: (target) => this.openResult(target),
 *   });
 *
 * Якщо метод дії поверне словник дії Odoo (є "type", що починається на
 * "ir.actions."), він піде у сервіс дій так само, як і завжди - жодна наявна
 * поведінка не ламається. Якщо ні plan, ні undo не дані, і відповідь не має
 * масиву done, run() поводиться як звичайний orm.call + onDone.
 */
import { Component, reactive, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";
import { browser } from "@web/core/browser/browser";

const LEVEL_WORDS = { info: "інфо", warn: "увага", crit: "критично" };

// Спека задає лише розкриття рядків наслідку (~400 мс/рядок, разом не
// більше 2 с). Скільки панель лишається на екрані після повного розкриття,
// щоб рядок можна було прочитати й, за наявності цілі, клікнути, спека не
// задає - тут власний, короткий та однаковий для всіх екранів вибір.
const CONSEQUENCE_HOLD_MS = 2200;
const UNDO_WINDOW_MS = 20000;

function reducedMotion() {
    try {
        return browser.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
        return false;
    }
}

function sleep(ms) {
    return new Promise((resolve) => browser.setTimeout(resolve, ms));
}

/**
 * Позначає елемент (рядок таблиці, картку) щойно зміненим: підсвітка 1200 мс,
 * що згасає (вимикається на prefers-reduced-motion через саму анімацію в
 * act.scss). Екрани звуть це самі після перемальовки, на свій DOM-вузол:
 *
 *   this.rowRef.el && markChanged(this.rowRef.el);
 */
export function markChanged(el) {
    if (!el) {
        return;
    }
    el.classList.remove("o_ua_act_flash");
    void el.offsetWidth; // перезапустити анімацію, якщо клас уже був застосований
    el.classList.add("o_ua_act_flash");
}

// Крок 1: діалог плану. Відкривається лише коли plan-метод дав непорожній
// перелік. Кнопка підтвердження називає дію словом (options.confirm), не
// «ОК»; «Скасувати» закриває і нічого не робить.
class ActPlanDialog extends Component {
    static template = "l10n_ua_shell.ActPlanDialog";
    static components = { Dialog };
    static props = {
        title: String,
        lines: Array,
        confirmLabel: String,
        onConfirm: Function,
        onCancel: Function,
        close: Function,
    };

    levelWord(level) {
        return LEVEL_WORDS[level] || LEVEL_WORDS.info;
    }

    confirm() {
        this.props.onConfirm();
        this.props.close();
    }

    cancel() {
        this.props.onCancel();
        this.props.close();
    }
}

// Кроки 3-4: постійний компонент (як UaSideRail), змонтований раз на сесію.
// Стан ділиться з сервісом через один реактивний об'єкт, переданий у props -
// той самий патерн, що й у стандартного notification-сервісу Odoo.
class UaActPanel extends Component {
    static template = "l10n_ua_shell.ActPanel";
    static props = { state: Object };

    setup() {
        this.state = useState(this.props.state);
    }

    onLineClick(item) {
        const cons = this.state.consequence;
        if (!cons || !item.target || !cons.openTarget) {
            return;
        }
        cons.openTarget(item.target);
    }

    skip() {
        this.state.consequence?.skip();
    }

    runUndo() {
        this.state.undo?.run();
    }
}

export const uaActService = {
    dependencies: ["orm", "dialog", "action"],

    start(env, { orm, dialog, action }) {
        const state = reactive({ consequence: null, undo: null });
        let undoTimer = null;

        registry.category("main_components").add("UaActPanel", {
            Component: UaActPanel,
            props: { state },
        });

        function clearUndoTimer() {
            if (undoTimer) {
                browser.clearInterval(undoTimer);
                undoTimer = null;
            }
        }

        function askPlan(title, lines, confirmLabel) {
            return new Promise((resolve) => {
                let settled = false;
                const settle = (value) => {
                    if (!settled) {
                        settled = true;
                        resolve(value);
                    }
                };
                dialog.add(
                    ActPlanDialog,
                    {
                        title,
                        lines,
                        confirmLabel,
                        onConfirm: () => settle(true),
                        onCancel: () => settle(false),
                    },
                    { onClose: () => settle(false) } // X, Esc, клік поза діалогом = скасувати
                );
            });
        }

        // Крок 3: рядки наслідку розкриваються по одному, ~400 мс/рядок,
        // разом не більше 2 с; «Пропустити» показує решту одразу.
        // prefers-reduced-motion: reduce - весь перелік одразу, без затримок.
        async function revealDone(lines, openTarget) {
            const reduced = reducedMotion();
            const items = lines.map((l, i) => ({ text: l.text, target: l.target || null, key: i }));
            const ctl = { stopped: reduced };
            const panel = reactive({
                items,
                revealed: reduced ? items.length : 0,
                openTarget: openTarget || null,
            });
            panel.skip = () => {
                ctl.stopped = true;
                panel.revealed = items.length;
            };
            state.consequence = panel;

            if (!reduced && items.length) {
                const perLine = Math.min(400, 2000 / items.length);
                for (let i = 0; i < items.length && !ctl.stopped; i++) {
                    await sleep(perLine);
                    if (!ctl.stopped) {
                        panel.revealed = i + 1;
                    }
                }
            }
            return panel;
        }

        function holdThenHidePanel(panel) {
            browser.setTimeout(() => {
                if (state.consequence === panel) {
                    state.consequence = null;
                }
            }, CONSEQUENCE_HOLD_MS);
        }

        // Крок 4: смуга «Скасувати» на 20 с. Лічильник видно, але тихо - без
        // кольору тривоги. Клік поза смугою не ховає її; друга дія заміняє.
        function startUndo({ model, id, method, label, onDone }) {
            clearUndoTimer();
            const startedAt = Date.now();
            const bar = reactive({
                label,
                secondsLeft: Math.ceil(UNDO_WINDOW_MS / 1000),
                run: async () => {
                    clearUndoTimer();
                    state.undo = null;
                    await orm.call(model, method, [[id]]);
                    if (onDone) {
                        await onDone();
                    }
                },
            });
            state.undo = bar;
            undoTimer = browser.setInterval(() => {
                const left = Math.max(0, Math.ceil((UNDO_WINDOW_MS - (Date.now() - startedAt)) / 1000));
                if (state.undo === bar) {
                    bar.secondsLeft = left;
                }
                if (Date.now() - startedAt >= UNDO_WINDOW_MS) {
                    clearUndoTimer();
                    if (state.undo === bar) {
                        state.undo = null;
                    }
                }
            }, 250);
        }

        async function run(options) {
            const {
                model,
                id,
                method,
                plan: planMethod,
                confirm: confirmLabel,
                title,
                undo: undoMethod,
                undoLabel = "Скасувати",
                kwargs = {},
                onDone,
                openTarget,
            } = options || {};

            if (!model || !id || !method) {
                throw new Error("ua_act.run: потрібні model, id і method");
            }

            // Крок 1: план (лише для класу «проведення»; порожній план = без діалогу).
            if (planMethod) {
                const lines = await orm.call(model, planMethod, [[id]]);
                if (Array.isArray(lines) && lines.length) {
                    const proceed = await askPlan(title || confirmLabel || "Дія", lines, confirmLabel || "Підтвердити");
                    if (!proceed) {
                        return undefined;
                    }
                }
            }

            // Крок 2: виконання. Стан «зайнято» на кнопці - турбота екрана
            // (той самий патерн, що й сьогодні); решта екрана лишається живою.
            const result = await orm.call(model, method, [[id]], kwargs);

            // Словник дії Odoo - як і раніше, без змін поведінки.
            if (
                result &&
                typeof result === "object" &&
                !Array.isArray(result) &&
                typeof result.type === "string" &&
                result.type.startsWith("ir.actions.")
            ) {
                action.doAction(result);
                return result;
            }

            // Крок 3: наслідки, якщо є.
            const doneLines = result && Array.isArray(result.done) ? result.done : [];
            let panel = null;
            if (doneLines.length) {
                panel = await revealDone(doneLines, openTarget);
            }

            // Крок 4: вікно скасування, якщо задано.
            if (undoMethod) {
                startUndo({ model, id, method: undoMethod, label: undoLabel, onDone });
            }

            // Крок 5: фініш - викликаємо onDone, щоб екран перемалював дані.
            if (onDone) {
                await onDone();
            }

            if (panel) {
                holdThenHidePanel(panel);
            }

            return result;
        }

        return { run, markChanged };
    },
};

registry.category("services").add("ua_act", uaActService);
