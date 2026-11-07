{
    "name": "Україна: фінансова звітність (Ф1, Ф2, Ф1-м, Ф2-м)",
    "summary": "Баланс і Звіт про фінансові результати за НП(С)БО 1 і НП(С)БО 25 як шаблони mis_builder",
    "description": "Форми фінансової звітності зібрані не кодом, а даними: кожен рядок офіційної "
                   "форми - це KPI шаблону mis.report з виразом за планом рахунків ua_psbo "
                   "(bale, balp, pbale, nbale, debp). Рахунок не знає про форму, форма не знає "
                   "про Python. Чотири шаблони: Ф1 «Баланс» і Ф2 «Звіт про фінансові результати» "
                   "за НП(С)БО 1, Ф1-м і Ф2-м за НП(С)БО 25. Розгорнуте сальдо рахунків 36, 63, "
                   "64, 65, 66, 67, 68, 37 робиться нативними виразами pbale/nbale - дебетові "
                   "залишки йдуть в актив, кредитові в пасив. У кожній формі є контрольний рядок "
                   "(Актив - Пасив, чистий результат проти зміни рядка 1420). Модуль логічний: "
                   "жодного OWL, жодної залежності від модулів інтерфейсу. "
                   "Опис у docs/base/spec-finrep.md.",
    "version": "19.0.1.1.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "AGPL-3",
    "depends": ["account", "l10n_ua", "mis_builder"],
    "data": [
        "data/mis_report_style.xml",
        "data/mis_report_f1.xml",
        "data/mis_report_f2.xml",
        "data/mis_report_f1m.xml",
        "data/mis_report_f2m.xml",
        "data/mis_report_instance.xml",
        "views/mis_report_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
