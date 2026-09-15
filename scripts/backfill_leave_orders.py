"""Заднім числом проводить накази В-2 для вже підтверджених відпусток, у яких ще немає наказу,
і підтягує hr.leave.ua_order_id там, де наказ уже існує (order.leave_id), але поле ще порожнє.
Ідемпотентно - повторний запуск нічого не дублює. База PAYROLL_DB (типово payroll).

Запуск: python3 scripts/backfill_leave_orders.py
        PAYROLL_DB=payroll_orders python3 scripts/backfill_leave_orders.py"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("PAYROLL_DB", "payroll").strip()

SCRIPT = r"""
from odoo.addons.l10n_ua_hr_orders.hooks import backfill_leave_orders

result = backfill_leave_orders(env)
env.cr.commit()
print(f"ua_order_id підтягнуто: {result['linked']}")
print(f"нових наказів В-2 проведено: {result['created']}")
quit()
"""

proc = subprocess.run(
    ["docker", "compose", "exec", "-T", "odoo", "sh", "-c",
     f"odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo --db_password=odoo -d {DB} --no-http --log-level=warn"],
    input=SCRIPT, capture_output=True, text=True, cwd=ROOT,
)
print(proc.stdout.strip())
if proc.returncode != 0 or "підтягнуто" not in proc.stdout:
    print("--- stderr ---")
    print(proc.stderr[-4000:])
    sys.exit(1)
