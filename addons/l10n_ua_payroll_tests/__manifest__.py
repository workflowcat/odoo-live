{
    "name": "Зарплата: еталонні сценарії (тести)",
    "summary": "30 еталонних сценаріїв нарахування як юніт-тести Odoo; очікувані числа лежать у golden/scenarios.json",
    "description": "Модуль без даних, без екранів і без меню. Він існує лише заради тестів. "
                   "Кожен сценарій із golden/scenarios.json будується в транзакції тесту: працівник, "
                   "версія контракту, історія заробітку, відпустки, листок. Порівнюються підсумки "
                   "рядків листка до копійки і, де еталон їх містить, обороти проводки. "
                   "Запуск: scripts/test.sh (чиста база, без стенда).",
    "version": "19.0.1.0.0",
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
    ],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
