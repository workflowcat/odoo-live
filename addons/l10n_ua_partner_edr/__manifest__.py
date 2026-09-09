{
    "name": "Контрагенти з ЄДР (OpenDataBot)",
    "summary": "Заповнення картки контрагента з ЄДР за ЄДРПОУ або РНОКПП через міст odoo-live: назва, адреса, КВЕД, керівник, ПДВ, стан, маркери ризику",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Contacts",
    "depends": ["bp_kyc", "contacts"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_partner_views.xml",
        "wizards/ua_partner_edr_wizard_views.xml",
        "data/cron.xml",
    ],
    "installable": True,
}
