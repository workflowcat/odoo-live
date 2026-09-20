{
    "name": "Вхідні рахунки",
    "summary": "Рахунки постачальників з пошти: розбір PDF через Workers AI, неперевірений постачальник, дані з ЄДР, чернетка рахунку",
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["purchase", "account", "mail", "bp_kyc"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/intake_views.xml",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
