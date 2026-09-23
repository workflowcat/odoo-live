{
    "name": "Україна: каса (ПКО/ВКО, КО-4)",
    "summary": "Касові ордери на нативних платежах, друк КО-1 і КО-2, касова книга КО-4, ліміт каси, авансові звіти",
    "description": "Прибутковий і видатковий касові ордери - це нативний account.payment у журналі "
                   "типу «Каса»: проводка йде через рахунок каси 301, оплату можна звірити з рахунком "
                   "клієнта або постачальника нативними засобами. Наше тут тонке: номер ордера за "
                   "реєстром і роком, кореспондуючий рахунок, від кого прийнято / кому видано, "
                   "документ одержувача, друковані форми КО-1 і КО-2, аркуш касової книги КО-4 з "
                   "контролем ліміту та авансовий звіт, що закриває 372.",
    "version": "19.0.1.2.0",
    "category": "Accounting",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account", "l10n_ua"],
    "post_init_hook": "post_init_hook",
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "report/ua_cash_reports.xml",
        "views/res_company_views.xml",
        "views/account_payment_views.xml",
        "views/ua_advance_report_views.xml",
        "views/ua_cash_book_views.xml",
        "views/ua_cash_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
