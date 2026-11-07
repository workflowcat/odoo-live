{
    "name": "Україна: договори контрагентів і акт звірки",
    "summary": "Розрахунки в розрізі договорів, контроль суми договору, окремий облік через аналітику, "
               "акт звірки взаєморозрахунків",
    "description": "Договір - окремий документ на контрагента, як у 1С/BAS: номер, дата, вид (з покупцем, "
                   "з постачальником, інший), валюта, сума, строк, умови оплати. Договір ставиться на "
                   "замовлення, рахунок, оплату і кожен рядок проводки, тому заборгованість видно за "
                   "договором, а не лише за контрагентом. Сума договору контролюється при проведенні "
                   "рахунку. Для окремого обліку договір отримує свій аналітичний рахунок, і він сам "
                   "лягає на рядки рахунків і замовлень. Акт звірки бере проводки на рахунках "
                   "розрахунків (36, 37, 63, 68) за контрагентом або договором і друкується за "
                   "звичною формою з місцем для даних контрагента.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account", "sale", "purchase", "l10n_ua_docs_sale"],
    "data": [
        "security/ir.model.access.csv",
        "security/ua_contract_security.xml",
        "data/ir_sequence_data.xml",
        "data/analytic_plan_data.xml",
        "report/ua_reconciliation_act_report.xml",
        "views/ua_contract_views.xml",
        "views/ua_reconciliation_act_views.xml",
        "views/account_move_views.xml",
        "views/order_views.xml",
        "views/account_payment_views.xml",
        "views/ua_contract_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
