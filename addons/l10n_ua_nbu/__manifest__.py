{
    "name": "Україна: курси НБУ",
    "summary": "Постачальник курсів «НБУ» для OCA currency_rate_update: офіційний курс гривні щодня",
    "description": "Тонка надбудова над OCA currency_rate_update. Уся механіка - модель "
                   "res.currency.rate.provider, крон, вікно оновлення, запис у res.currency.rate - "
                   "уже є в OCA. Наше тут рівно одне: провайдер «НБУ», який бере офіційні курси з "
                   "відкритого API bank.gov.ua і переводить їх у курс Odoo. НБУ публікує гривні за "
                   "одиницю валюти (а для деяких валют - за 10 або 100 одиниць), Odoo тримає "
                   "обернений курс, тож переведення робиться тут. Провайдер для компанії з "
                   "гривнею створюється при встановленні: щодня, USD EUR PLN GBP. "
                   "Опис у docs/base/spec-assets-nbu.md.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["currency_rate_update"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
