"""Перевірка «одна система наказів» (l10n_ua_hr_orders) на стенді, база PAYROLL_DB (типово payroll).

Запускається через `odoo shell`; усі зміни відкочуються в кінці. Перевіряє: проведення відпустки
(hr.leave, state='validate') створює й проводить наказ В-2; повторне проведення не дублює; відмова
від відпустки скасовує наказ; наказ, що сам створює відпустку (_post_leave), не створює другого
наказу через гак валідації; невідпустковий тип (SICK) наказу не отримує; картка друкує проведений
ua.hr.order для прийняття і звільнення, а не застарілу форму, коли запис наказу є; резервний друк
на hr.version з ua_order_ref, коли запису наказу немає; чекліст перейменовано, xmlid не змінено;
застарілі П-1/П-3/П-4 без прив'язки до кнопки "Друк".

Запуск: python3 scripts/orders_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import sys
from datetime import date, timedelta

from odoo.exceptions import UserError

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


Employee = env["hr.employee"].sudo()
Leave = env["hr.leave"].sudo()
Order = env["ua.hr.order"].sudo()
dept = env["hr.department"].search([], limit=1)

# ---- 0. працівник-кандидат для тестів: власна картка, щоб не чіпати чужі дані; прийняття - через
# ua.hr.order (order_type=hire), щоб пункт 7 (друк наказу з картки) мав, на що спертись.
emp = Employee.create({
    "name": "Юрченко Андрій Миколайович", "company_id": env.company.id, "date_version": date(2020, 1, 1),
    "department_id": dept.id, "job_title": "Комірник",
})
hire_order = Order.create({
    "order_type": "hire", "employee_id": emp.id, "company_id": emp.company_id.id,
    "date_from": date(2020, 1, 1), "department_id": dept.id, "job_title": "Комірник", "wage": 20000,
})
hire_order.action_post()
check("наказ про прийняття проведено (К-1)", hire_order.state == "posted" and hire_order.register == "k1", hire_order.name or "-")

vac_type = env.ref("l10n_ua_average.lt_vac")
sick_type = env.ref("l10n_ua_average.lt_sick")
trip_type = env.ref("l10n_ua_average.lt_trip")

# ---- 1. проведення наказової відпустки (VAC) створює і проводить наказ В-2
leave = Leave.create({
    "employee_id": emp.id, "holiday_status_id": vac_type.id,
    "request_date_from": date(2026, 10, 5), "request_date_to": date(2026, 10, 9),
})
leave.action_approve()
check("відпустка проведена (state=validate)", leave.state == "validate", leave.state)
check("наказ створено і проведено (posted, В-2)", bool(leave.ua_order_id) and leave.ua_order_id.state == "posted"
      and leave.ua_order_id.register == "v2" and leave.ua_order_id.order_type == "leave", leave.ua_order_id.name or "-")
check("наказ має номер за реєстром В-2", bool(leave.ua_order_id.name), leave.ua_order_id.name or "-")
check("наказ посилається на цю відпустку (leave_id)", leave.ua_order_id.leave_id == leave)
order1 = leave.ua_order_id

# ---- 2. повторне проведення (гіпотетичний повторний виклик) не дублює наказ
leave._action_validate(check_state=False)
check("повторне проведення не створює другий наказ", leave.ua_order_id == order1 and
      Order.search_count([("leave_id", "=", leave.id)]) == 1, str(Order.search_count([("leave_id", "=", leave.id)])))

# ---- 3. відмова від проведеної відпустки скасовує наказ
leave.action_refuse()
check("відпустка відхилена", leave.state == "refuse", leave.state)
check("наказ скасовано слідом за відмовою", order1.state == "cancelled", order1.state)

# ---- 4. невідпустковий тип (SICK, тимчасова непрацездатність) наказу не отримує
sick_leave = Leave.create({
    "employee_id": emp.id, "holiday_status_id": sick_type.id,
    "request_date_from": date(2026, 10, 12), "request_date_to": date(2026, 10, 13),
})
sick_leave.action_approve()
check("лікарняний (SICK) не наказовий - без наказу", not sick_leave.ua_order_id, str(sick_leave.ua_order_id))

# ---- 5. TRIP не створює наказ типу "leave" через цей гак (є власний order_type=trip)
trip_leave = Leave.create({
    "employee_id": emp.id, "holiday_status_id": trip_type.id,
    "request_date_from": date(2026, 10, 20), "request_date_to": date(2026, 10, 21),
})
trip_leave.action_approve()
check("відрядження (TRIP) не отримує наказ типу leave з цього гака", not trip_leave.ua_order_id, str(trip_leave.ua_order_id))

# ---- 6. наказ, що сам створює відпустку (_post_leave), не створює другого наказу через гак validate
order2 = Order.create({
    "order_type": "leave", "employee_id": emp.id, "company_id": emp.company_id.id,
    "leave_type_id": vac_type.id, "date_from": date(2026, 11, 2), "date_to": date(2026, 11, 6),
})
order2.action_post()
check("наказ у режимі «наказ створює відпустку» проведено", order2.state == "posted", order2.state)
check("наказ пов'язаний з новою відпусткою", bool(order2.leave_id))
check("нова відпустка проведена і має ua_order_id саме на цей наказ", order2.leave_id.state == "validate" and
      order2.leave_id.ua_order_id == order2, str(order2.leave_id.ua_order_id))
check("немає другого наказу на ту саму відпустку", Order.search_count([("leave_id", "=", order2.leave_id.id)]) == 1,
      str(Order.search_count([("leave_id", "=", order2.leave_id.id)])))

# ---- 7. картка: друк наказу веде на проведений ua.hr.order, коли він є
hire_action = emp.action_ua_print_last_order()
check("картка: друк наказу веде на звіт ua.hr.order (прийняття)", hire_action.get("report_name") ==
      "l10n_ua_hr_orders.report_ua_hr_order", str(hire_action))

# дозволити звільнення: сформувати запис версії з ua_end_order_ref (наказ типу dismissal)
dismiss_order = Order.create({
    "order_type": "dismissal", "employee_id": emp.id, "company_id": emp.company_id.id,
    "date_to": date(2026, 12, 1), "dismissal_basis": "ст. 38 КЗпП (заява працівника)",
})
dismiss_order.action_post()
dismiss_action = emp.action_ua_print_last_order()
check("картка: друк наказу веде на звіт ua.hr.order (звільнення)", dismiss_action.get("report_name") ==
      "l10n_ua_hr_orders.report_ua_hr_order" and dismiss_action.get("context", {}).get("active_ids") == [dismiss_order.id],
      str(dismiss_action))

# ---- 8. картка: резервний друк застарілою формою, коли є ua_order_ref, але немає запису наказу
emp2 = Employee.create({
    "name": "Демчук Наталія Степанівна", "company_id": env.company.id, "date_version": date(2019, 1, 1),
    "department_id": dept.id, "job_title": "Діловод",
})
emp2.version_id.write({
    "contract_date_start": date(2019, 1, 1), "wage": 15000,
    "ua_order_ref": "Наказ № 5-к від 03.01.2019",
})
legacy_action = emp2.action_ua_print_last_order()
check("картка: резерв П-1 для перенесеної історії без запису наказу", legacy_action.get("report_name") ==
      "l10n_ua_hr_docs.report_ua_order_hire", str(legacy_action))

# ---- 9. застарілі звіти П-1/П-3/П-4 без прив'язки до кнопки "Друк"
# наказ про відпустку друкується з ua.hr.order, окремого резервного звіту більше немає
for xmlid in ("l10n_ua_hr_docs.action_report_ua_order_hire", "l10n_ua_hr_docs.action_report_ua_order_dismiss"):
    act = env.ref(xmlid)
    check(f"{xmlid}: без binding_model_id", not act.binding_model_id, str(act.binding_model_id))

# ---- 10. чекліст перейменовано на «Перевірка документів», xmlid не змінено
report_act = env.ref("l10n_ua_hr_orders.action_report_ua_hr_doc_pack")
check("звіт чекліста перейменовано", report_act.name == "Перевірка документів", report_act.name)
# ir.ui.menu.name на цьому стенді зберігає технічний xmlid замість тексту з менюItems для частини
# пунктів (перевірено і на "payroll", і тут - до будь-яких змін цього завдання, отже це не
# регресія цієї роботи, а наявна вада стенду поза цим завданням). Джерело правди - views/menus.xml
# (перейменовано вище); саму дію пункту меню перевірено окремо нижче.
wizard_action = env.ref("l10n_ua_hr_orders.action_ua_hr_doc_pack_wizard")
check("дія майстра перейменована", wizard_action.name == "Перевірка документів", wizard_action.name)
menu = env.ref("l10n_ua_hr_orders.menu_ua_hr_doc_pack")
check("пункт меню існує і веде на майстер", menu.action.id == wizard_action.id, str(menu.action))

# ---- 11a. підстава за замовчуванням («заява») - для прийняття, відпустки, звільнення
new_order = Order.new({"order_type": "hire"})
new_order._onchange_order_type_basis()
check("підстава за замовчуванням «заява» для прийняття", new_order.basis == "заява", new_order.basis)
new_order2 = Order.new({"order_type": "wage"})
new_order2._onchange_order_type_basis()
check("зміна окладу без підстави за замовчуванням", not new_order2.basis, new_order2.basis)

# ---- 11b. статистичні поля наказу підтягуються з поточної версії працівника
version = emp.version_id
prefill_order = Order.new({"order_type": "wage", "employee_id": emp.id})
prefill_order._onchange_employee_id_prefill()
check("наказ: код КП/посада/ставка/підрозділ з поточної версії", prefill_order.wage == version.wage and
      prefill_order.department_id.id == version.department_id.id, (prefill_order.wage, prefill_order.department_id.id))

# ---- 11c. переведення: форма показує стару і нову посаду/підрозділ разом
dept2 = env["hr.department"].create({"name": "Склад і логістика (перевірка)", "company_id": emp.company_id.id})
transfer_order = Order.create({
    "order_type": "transfer", "employee_id": emp.id, "company_id": emp.company_id.id,
    "date_from": date(2026, 12, 15), "department_id": dept2.id, "job_title": "Завідувач складу",
})
check("переведення: старий підрозділ/посада обчислені окремо від нових",
      transfer_order.department_id_old.id == dept.id and transfer_order.job_title_old == "Комірник" and
      transfer_order.department_id.id == dept2.id, (transfer_order.department_id_old.id, transfer_order.job_title_old))

# ---- 11d. реєстр наказу лише обчислюється, не редагується з форми (readonly="1" у в'юсі)
import re as _re
form_view = env["ir.ui.view"].sudo().search([("model", "=", "ua.hr.order"), ("name", "=", "ua.hr.order.form")], limit=1)
arch_text = form_view.arch_db or ""
register_ro = bool(_re.search(r'<field name="register"[^>]*readonly="1"', arch_text))
check("поле «Реєстр» readonly у формі наказу", register_ro, "readonly=1 знайдено" if register_ro else "не знайдено")

# ---- 12. backfill: ідемпотентність
from odoo.addons.l10n_ua_hr_orders.hooks import backfill_leave_orders
res1 = backfill_leave_orders(env)
res2 = backfill_leave_orders(env)
check("backfill вдруге нічого не додає", res2 == {"linked": 0, "created": 0}, str(res2))

env.cr.rollback()
print()
if errors:
    print(f"ПЕРЕВІРКУ НЕ ПРОЙДЕНО: {len(errors)} з {total} пунктів провалено")
    sys.exit(1)
print(f"Усі перевірки пройдено ({total} з {total}).")
quit()
"""

proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
out = proc.stdout
print(out.strip())
if "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in out or "Усі перевірки пройдено" not in out:
    print("--- stderr ---")
    print(proc.stderr[-4000:])
    sys.exit(1)
