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
        # Якщо окремого запису форми немає, нічого не створюємо: картка має priority=1 і
        # стає формою за замовчуванням сама. Створений запис Odoo ставить перед рештою видів,
        # тож дія зі списком або деревом відкривалась би порожньою формою нового запису.


def repair_form_first(env):
    """Прибрати записи форми, які попередня версія хука створила першим видом дії."""
    card_view = env.ref("l10n_ua_card_ui.view_employee_form_ua_card_wrapper", raise_if_not_found=False)
    if not card_view:
        return
    records = env["ir.actions.act_window.view"].search([("view_id", "=", card_view.id), ("view_mode", "=", "form")])
    for rec in records:
        action = rec.act_window_id
        modes = (action.view_mode or "").split(",")
        # запис форми, єдиний у дії, яка починається не з форми - це саме той хибний запис
        if modes and modes[0] != "form" and len(action.view_ids) == 1:
            rec.unlink()
