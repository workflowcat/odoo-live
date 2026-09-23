{
    "name": "Україна: контрагент з ЄДР",
    "summary": "Заповнення картки контрагента з ЄДР за ЄДРПОУ або РНОКПП: назва, адреса, "
               "КВЕД, керівник, ПДВ, стан реєстрації, маркери ризику",
    "description": "Один крок замість ручного набору реквізитів: вводимо код, картка "
                   "заповнюється з ЄДР. Назовні модуль сам не ходить - запит іде через "
                   "міст інтеграцій bp.bridge з модуля bp_bridge, де лежить єдиний токен "
                   "(BP_BRIDGE_URL і BP_BRIDGE_TOKEN), а вже міст звертається до "
                   "OpenDataBot. Заповнюються лише порожні поля картки: те, що бухгалтер "
                   "уточнив руками, запит з реєстру не затирає. Опис у "
                   "docs/base/spec-fop-migrate-edr.md.",
    "version": "19.0.1.1.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["bp_bridge", "contacts", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "wizards/ua_partner_edr_wizard_views.xml",
        "data/cron.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
