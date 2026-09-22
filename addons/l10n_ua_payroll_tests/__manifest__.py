{
    "name": "Зарплата: еталонні сценарії (тести)",
    "summary": "30 еталонних сценаріїв нарахування як юніт-тести Odoo; очікувані числа лежать у golden/scenarios.json",
    "description": "Модуль без даних, без екранів і без меню. Він існує лише заради тестів. "
                   "Кожен сценарій із golden/scenarios.json будується в транзакції тесту: працівник, "
                   "версія контракту, історія заробітку, відпустки, листок. Порівнюються підсумки "
                   "рядків листка до копійки і, де еталон їх містить, обороти проводки. "
                   "Запуск: scripts/test.sh (чиста база, без стенда).",
    "version": "19.0.2.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_payroll_rules",
        "l10n_ua_average",
        # ознаки права на відпустку (УБД, одинокий батько/мати, діти) живуть у картці
        "l10n_ua_hr_card",
        "l10n_ua_index",
        "l10n_ua_payroll_account",
        "l10n_ua_chart",
        # регресії з тега ua_regress: правила звірки, журнал каси, МФО, дати документів
        "l10n_ua_bank",
        "l10n_ua_cash",
        "l10n_ua_docs",
        "l10n_ua_hr_docs",
        "account_payment_order",
        # відомість на перерахування (тег ua_payments); l10n_ua_bank_online везе ua.bank.ops -
        # дію «Застосувати правила», якою тести зводять рядки виписки з платежами
        "l10n_ua_payments",
        "l10n_ua_bank_online",
        # документи працівника на вкладеннях картки (тег ua_documents)
        "l10n_ua_hr_orders",
        # журнал змін на OCA auditlog (тег ua_changes)
        "l10n_ua_changes",
        # голий Odoo: стандартні подання, перевірки документів, місяць, прийняття,
        # звітність, анкета, картка працівника
        "l10n_ua_hire",
        "l10n_ua_reporting",
        "l10n_ua_setup",
        "l10n_ua_military",
        "l10n_ua_gph",
        # договір читання для інтерфейсу (тег ua_api)
        "l10n_ua_api",
    ],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
