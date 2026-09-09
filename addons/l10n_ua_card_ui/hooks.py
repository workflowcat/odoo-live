"""Прив'язати дії, що відкривають форму hr.employee, до картки-обгортки OWL.

Вид-обгортка (view_employee_form_ua_card_wrapper) має priority=1, тож Odoo вже обирає
її як default_view() для будь-якої дії, де форма не закріплена явним view_id. Але деякі
дії ядра (hr.open_view_employee_list_my) мають власний запис ir.actions.act_window.view
на форму - такий запис перезаписуємо явно. Де запису немає взагалі (view_mode лише
перелічує 'form' рядком, без ir.actions.act_window.view) - створюємо його. Так дію
«Співробітники» і всі інші дії на hr.employee гарантовано відкривають картку, а не
стандартну форму Odoo; стандартна форма лишається доступною за кнопкою «Стандартна форма»
всередині самої картки.
"""


def post_init_hook(env):
    card_view = env.ref("l10n_ua_card_ui.view_employee_form_ua_card_wrapper")
    actions = env["ir.actions.act_window"].search([("res_model", "=", "hr.employee")])
    for action in actions:
        modes = (action.view_mode or "").split(",")
        if "form" not in modes:
            continue
        form_view_rec = action.view_ids.filtered(lambda v: v.view_mode == "form")
        if form_view_rec:
            form_view_rec.write({"view_id": card_view.id})
        else:
            env["ir.actions.act_window.view"].create({
                "act_window_id": action.id,
                "view_mode": "form",
                "view_id": card_view.id,
                "sequence": 1,
            })
