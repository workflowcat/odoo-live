{
    "name": "Україна: митні декларації на імпорт",
    "summary": "Митна декларація (ІМ-40): мито, акциз і збори в собівартість отриманих товарів, "
               "митний ПДВ у податковий кредит, розрахунок митних платежів",
    "description": "Документ митної декларації поверх надходження. Митна вартість за курсом НБУ на "
                   "дату декларації, мито за ставкою товару, акциз, база і сума ПДВ за ст. 190 ПКУ. "
                   "Проведення розносить мито, акциз і митні збори на отримані товари нативним "
                   "landed cost (Дт 20x / Кт 3771) і бере ПДВ у кредит (Дт 6412 / Кт 3771). "
                   "Рахунок 3771 закривається оплатою митниці.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_vat", "stock_landed_costs", "purchase_stock"],
    "data": [
        "security/ir.model.access.csv",
        "security/ua_customs_security.xml",
        "data/product_data.xml",
        "report/ua_customs_report.xml",
        "views/ua_customs_declaration_views.xml",
    ],
    "installable": True,
}
