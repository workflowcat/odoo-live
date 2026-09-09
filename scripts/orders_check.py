"""Перевірка модуля l10n_ua_hr_orders на стенді, база PAYROLL_DB (типово payroll).

Запускається через `odoo shell` (окремий короткочасний процес у тому ж контейнері), а не
через JSON-RPC: dbfilter стенду пропускає лише базу `payroll` для HTTP/JSON-RPC і друку звітів,
тож перевірка на payroll_test можлива лише зсередини процесу, який відкриває базу напряму.

Перевіряє: перенесення наявних наказів (post_init_hook) дало щонайменше 15 проведених
наказів, усі з номером; новий наказ wage створює нову версію з новим окладом і номером
К-1 = попередній максимум + 1; новий наказ leave на Мельничука створює затверджену відпустку
з номером В-2; ознайомлення проставляє дату; скасування wage- і leave-наказів прибирає
створений запис і повертає наказ у чернетку без номера; три PDF (наказ, журнал реєстрації,
пакет документів) починаються з %PDF; хоча б один працівник має ua_doc_missing_count > 0.

Запуск: PAYROLL_DB=payroll_test python3 scripts/orders_check.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
import re
import sys
from datetime import date

errors = []
total = 0


def check(label, ok, detail=""):
    global total
    total += 1
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        errors.append(label)


def num_of(name):
    m = re.match(r"\d+", name or "")
    return int(m.group()) if m else 0


Order = env['ua.hr.order'].sudo()
Employee = env['hr.employee'].sudo()
Leave = env['hr.leave'].sudo()
Version = env['hr.version'].sudo()
LeaveType = env['hr.leave.type'].sudo()
Report = env['ir.actions.report'].sudo()
Sequence = env['ir.sequence'].sudo()

# ---- 1. перенесення наявних даних (post_init_hook) --------------------------------------------------
# Знімок ДО власних тестових наказів цього прогону - щоб повторний запуск скрипту (чернетки від
# попереднього прогону могли лишитися, якщо він упав) не псував перевірку перенесення.
migrated = Order.search([])
check("перенесення дало щонайменше 15 наказів", len(migrated) >= 15, f"{len(migrated)} наказів")
posted_migrated = migrated.filtered(lambda o: o.state == 'posted')
check("усі перенесені (проведені) накази мають номер", all(o.name for o in posted_migrated), "")
check("є принаймні 15 проведених перенесених наказів", len(posted_migrated) >= 15, f"{len(posted_migrated)} проведених")

# ---- 2. новий наказ wage: нова версія з новим окладом, номер К-1 = максимум + 1 -----------------------
candidates = Employee.search([
    ('name', 'not like', 'Еталон%'), ('name', '!=', 'Мельничук Андрій Петрович'), ('name', '!=', 'Administrator'),
    ('ua_contract_kind', '=', 'employment'), ('active', '=', True), ('company_id.name', 'ilike', 'Ясен'),
], order='id')
candidate = next((e for e in candidates if e.version_id and e.version_id.wage and not e.version_id.contract_date_end), False)
if not candidate:
    print("Немає підхожого чинного працівника для тесту зміни окладу.")
    sys.exit(1)
current_version = candidate.version_id
old_wage = current_version.wage
new_wage = old_wage + 1000.0
today = date(2026, 9, 9)

# Очікуваний номер читаємо напряму з послідовності (number_next_actual - справжній наступний
# номер з postgres-послідовності; стовпець number_next лишається як був виставлений при
# post_init_hook і не оновлюється по кожному next_by_code, тож на нього не можна покладатися
# для передбачення номера після попередніх прогонів цього ж скрипту).
seq_k1 = Sequence.search([('code', '=', 'ua.hr.order.k1')], limit=1)
rng_k1 = seq_k1._get_current_sequence(today)
expected_k1_number = rng_k1.number_next_actual

wage_order = Order.create({'order_type': 'wage', 'employee_id': candidate.id, 'date': today,
                           'date_from': today, 'wage': new_wage})
check("наказ wage створено чернеткою", wage_order.state == 'draft')
wage_order.action_post()
wage_order.invalidate_recordset()
check(f"{candidate.name}: наказ wage проведено", wage_order.state == 'posted', f"номер {wage_order.name}")
check("номер wage має суфікс -к", (wage_order.name or '').endswith('-к'), wage_order.name)
check("номер wage відповідає наступному номеру послідовності К-1", num_of(wage_order.name) == expected_k1_number,
      f"{num_of(wage_order.name)} vs {expected_k1_number}")

new_version = wage_order.version_id
check("проведення створило нову версію контракту", bool(new_version) and new_version.id != current_version.id)
check("нова версія має новий оклад", new_version.wage == new_wage, f"{new_version.wage}")
check("нова версія має дату версії = дата з наказу", new_version.date_version == today, str(new_version.date_version))
check("ua_order_ref нової версії заповнено і містить номер", bool(new_version.ua_order_ref) and (wage_order.name or '') in (new_version.ua_order_ref or ''),
      new_version.ua_order_ref)
candidate.invalidate_recordset()
check(f"{candidate.name}: поточна версія - щойно створена", candidate.version_id.id == new_version.id)

# ---- 3. новий наказ leave на Мельничука: затверджена відпустка, номер В-2 -------------------------------
mel = Employee.search([('name', '=', 'Мельничук Андрій Петрович')], limit=1)
check("Мельничук Андрій Петрович знайдений у базі", bool(mel))
lt_vac = LeaveType.search([('work_entry_type_id.code', '=', 'VAC')], limit=1)
check("тип відпустки «щорічна» знайдено", bool(lt_vac))

seq_v2 = Sequence.search([('code', '=', 'ua.hr.order.v2')], limit=1)
rng_v2 = seq_v2._get_current_sequence(today)
expected_v2_number = rng_v2.number_next_actual

leave_order = Order.create({'order_type': 'leave', 'employee_id': mel.id, 'date': today,
                            'leave_type_id': lt_vac.id, 'date_from': date(2026, 9, 21), 'date_to': date(2026, 9, 23)})
leave_order.action_post()
leave_order.invalidate_recordset()
check("наказ leave проведено", leave_order.state == 'posted', leave_order.name)
check("номер leave має суфікс -в", (leave_order.name or '').endswith('-в'), leave_order.name)
check("номер leave відповідає наступному номеру послідовності В-2", num_of(leave_order.name) == expected_v2_number,
      f"{num_of(leave_order.name)} vs {expected_v2_number}")

new_leave = leave_order.leave_id
check("наказ створив і затвердив відпустку", bool(new_leave) and new_leave.state == 'validate',
      new_leave.state if new_leave else "немає leave_id")
check("ua_order_ref відпустки заповнено і містить номер", bool(new_leave.ua_order_ref) and (leave_order.name or '') in (new_leave.ua_order_ref or ''),
      new_leave.ua_order_ref)

leave_order.action_acknowledge()
leave_order.invalidate_recordset()
check("ознайомлення проставило дату", bool(leave_order.ack_date), str(leave_order.ack_date))
check("ознайомлення проставило користувача", bool(leave_order.ack_user_id))
check("стан після ознайомлення - acknowledged", leave_order.state == 'acknowledged')

# ---- 4. три PDF: наказ, журнал реєстрації, пакет документів (лише через odoo shell - дивись докстрінг) --
pdf1 = Report._render_qweb_pdf('l10n_ua_hr_orders.action_report_ua_hr_order', [wage_order.id])
content1 = pdf1[0] if isinstance(pdf1, (tuple, list)) else pdf1
check("PDF наказу про зміну окладу починається з %PDF", content1[:4] == b'%PDF', repr(content1[:12]))

reg_wizard = env['ua.hr.order.register.wizard'].sudo().create({'year': 2026, 'register': 'k1', 'company_id': candidate.company_id.id})
pdf2 = Report._render_qweb_pdf('l10n_ua_hr_orders.action_report_ua_hr_order_register', [reg_wizard.id])
content2 = pdf2[0] if isinstance(pdf2, (tuple, list)) else pdf2
check("PDF журналу реєстрації починається з %PDF", content2[:4] == b'%PDF', repr(content2[:12]))

pack_employee_ids = Employee.search([('company_id', '=', candidate.company_id.id)], limit=10).ids
pack_wizard = env['ua.hr.doc.pack.wizard'].sudo().create({'company_id': candidate.company_id.id, 'employee_ids': [(6, 0, pack_employee_ids)]})
pdf3 = Report._render_qweb_pdf('l10n_ua_hr_orders.action_report_ua_hr_doc_pack', [pack_wizard.id])
content3 = pdf3[0] if isinstance(pdf3, (tuple, list)) else pdf3
check("PDF пакета документів починається з %PDF", content3[:4] == b'%PDF', repr(content3[:12]))

# ---- 5. ua_doc_missing_count > 0 хоча б у одного працівника ---------------------------------------------
all_emps = Employee.search([('company_id', '=', candidate.company_id.id)])
with_missing = all_emps.filtered(lambda e: e.ua_doc_missing_count > 0)
check("хоча б один працівник має ua_doc_missing_count > 0", len(with_missing) > 0, f"{len(with_missing)} з {len(all_emps)}")

# ---- 6. скасування: wage і leave повертаються у чернетку без номера, створене прибирається --------------
wage_order.action_cancel()
wage_order.invalidate_recordset()
check("скасування wage повернуло стан draft", wage_order.state == 'draft', wage_order.state)
check("скасування wage прибрало номер", not wage_order.name)
check("скасування wage видалило створену версію", not Version.browse(new_version.id).exists())
candidate.invalidate_recordset()
check(f"{candidate.name}: поточна версія повернулась до початкової", candidate.version_id.id == current_version.id)
check(f"{candidate.name}: оклад повернувся до попереднього", candidate.version_id.wage == old_wage, str(candidate.version_id.wage))

leave_order.action_cancel()
leave_order.invalidate_recordset()
check("скасування leave (з ознайомленого) повернуло стан draft", leave_order.state == 'draft', leave_order.state)
check("скасування leave прибрало номер", not leave_order.name)
check("скасування leave видалило створену відпустку", not Leave.browse(new_leave.id).exists())

# прибираємо власні тестові чернетки (скасовані накази з action_cancel лишаються записом моделі,
# без номера) - щоб повторний запуск скрипту не накопичував сміття в журналі
(wage_order | leave_order).unlink()

env.cr.commit()
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
if proc.returncode != 0 and "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" not in out and "Усі перевірки пройдено" not in out:
    print("--- stderr ---")
    print(proc.stderr[-4000:])
    sys.exit(proc.returncode)
if "ПЕРЕВІРКУ НЕ ПРОЙДЕНО" in out or "Усі перевірки пройдено" not in out:
    sys.exit(1)
