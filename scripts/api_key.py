"""Службовий користувач складу і ключ API для зовнішнього клієнта.

Відповідь на запит docs/agents/inbox/2026-09-22-008. Зовнішній складський екран
не повинен ходити логіном і паролем адміністратора: заводимо окремого
користувача «склад» (`sklad_api`) з правами складу і виробництва, без жодної
бухгалтерської групи, і видаємо йому ключ. Далі клієнт іде на `/json/2` із
заголовком `Authorization: Bearer <ключ>`.

Чому скриптом, а не руками в інтерфейсі. Ключ у Odoo 19 програмно робиться лише
приватним `res.users.apikeys._generate(scope, name, expiration_date)`: публічний
`generate()` спершу перевіряє ВЖЕ наявний ключ того самого користувача, а це
курка і яйце. Тому перший ключ видає `odoo shell`, а далі користувач може крутити
свої ключі сам.

Два знання, без яких нічого не працює:

* `_generate` записує ключ ТОМУ користувачеві, що сидить в `env.user`, а не
  тому, кого передали. Тому виклик іде через `with_user(user).sudo()`: `with_user`
  ставить власника, `sudo` дозволяє безстроковий ключ (без sudo Odoo вимагає дату
  закінчення в межах `api_key_duration` групи);
* безстроковий ключ має бути ГЛОБАЛЬНИМ, тобто `scope=None`. Перевірка bearer
  кличе `_check_credentials(scope='rpc')`, а такої області насправді немає:
  підходить лише ключ без області. Ключ, створений з `scope="rpc"`, мовчки не
  пускає.

Скрипт ідемпотентний щодо користувача і груп: другий запуск не створює двійника,
а лише видає НОВИЙ ключ (старі лишаються чинними, зняти їх можна у формі
користувача).

Запуск:

    python3 scripts/api_key.py --db payroll            # стенд 8130, наявний контейнер
    python3 scripts/api_key.py --db cw_test --once     # разовий контейнер, свіжа база
    python3 scripts/api_key.py --db payroll --days 90  # ключ зі строком

Надрукований ключ показується ОДИН раз - Odoo зберігає лише його хеш. Покласти
його треба в менеджер паролів, а не у файл поруч із кодом.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Значення підставляються окремим заголовком, щоб у самому скрипті можна було
# спокійно писати «%s» у повідомленнях.
HEADER = "LOGIN = %r\nLABEL = %r\nKEY_NAME = %r\nDAYS = %r\n"

SCRIPT = r"""
import datetime
import sys

GROUPS = ["base.group_user", "stock.group_stock_user", "mrp.group_mrp_user"]
FORBIDDEN = ["account.group_account_user", "account.group_account_manager",
             "account.group_account_invoice", "base.group_system"]

groups = env["res.groups"]
for xmlid in GROUPS:
    group = env.ref(xmlid, raise_if_not_found=False)
    if not group:
        print("НЕМАЄ ГРУПИ %s - чи встановлено модуль?" % xmlid)
        sys.exit(1)
    groups |= group

user = env["res.users"].with_context(active_test=False).search(
    [("login", "=", LOGIN)], limit=1)
if user:
    print("користувач %s уже є (id %s)" % (LOGIN, user.id))
    user.write({"active": True, "group_ids": [(6, 0, groups.ids)]})
else:
    user = env["res.users"].create({
        "name": LABEL,
        "login": LOGIN,
        "group_ids": [(6, 0, groups.ids)],
    })
    print("створено користувача %s (id %s)" % (LOGIN, user.id))

user.invalidate_recordset()
extra = [xmlid for xmlid in FORBIDDEN
         if env.ref(xmlid, raise_if_not_found=False)
         and user.has_group(xmlid)]
if extra:
    print("У КОРИСТУВАЧА ЗАЙВІ ПРАВА: %s" % ", ".join(extra))
    sys.exit(1)
print("групи: %s" % ", ".join(sorted(user.all_group_ids.mapped("full_name"))[:12]))

expiration = None
if DAYS:
    expiration = datetime.datetime.now() + datetime.timedelta(days=int(DAYS))
# scope=None - ключ глобальний: перевірка bearer приймає лише такий.
key = env["res.users.apikeys"].with_user(user).sudo()._generate(None, KEY_NAME, expiration)
env.cr.commit()
print("КЛЮЧ: %s" % key)
print("строк: %s" % (expiration.strftime("%Y-%m-%d") if expiration else "безстроковий"))
quit()
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("PAYROLL_DB", "payroll"),
                        help="база даних (типово payroll)")
    parser.add_argument("--login", default="sklad_api", help="логін службового користувача")
    parser.add_argument("--label", default="склад", help="назва користувача")
    parser.add_argument("--key-name", default="Складський клієнт", help="назва ключа")
    parser.add_argument("--days", type=int, default=0,
                        help="строк ключа в днях; 0 - безстроковий")
    parser.add_argument("--once", action="store_true",
                        help="разовий контейнер замість наявного (свіжа база, стенд не чіпаємо)")
    args = parser.parse_args()

    payload = HEADER % (args.login, args.label, args.key_name, args.days or 0) + SCRIPT
    shell = ("odoo shell -c /etc/odoo/odoo.conf --db_host=db --db_user=odoo "
             "--db_password=odoo --db-filter='.*' -d %s --no-http --log-level=warn" % args.db)
    if args.once:
        command = ["docker", "compose", "run", "--rm", "--no-deps", "-T", "odoo",
                   "sh", "-c", shell]
    else:
        command = ["docker", "compose", "exec", "-T", "odoo", "sh", "-c", shell]

    proc = subprocess.run(command, input=payload, capture_output=True, text=True, cwd=ROOT)
    out = proc.stdout.strip()
    print(out)
    if "КЛЮЧ: " not in out:
        print("--- stderr (odoo shell) ---")
        print(proc.stderr[-4000:])
        return proc.returncode or 1
    print()
    print("Ключ показано один раз: Odoo зберігає лише хеш. "
          "Покладіть його в менеджер паролів.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
