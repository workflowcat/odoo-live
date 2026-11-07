{
    "name": "Україна: класифікатор ДК 021:2015 (CPV)",
    "summary": "Єдиний закупівельний словник: коди товарів і послуг для Prozorro, "
               "річного плану закупівель і звітів",
    "description": "Повний класифікатор ДК 021:2015 (9458 кодів) з ієрархією: розділ, група, "
                   "клас, категорія, підкатегорії. Код на товарі, на рядку закупівлі і в "
                   "аналізі закупівель за кодом. Дані - відкритий словник ProzorroUKR/standards "
                   "(Apache-2.0), оновлення - заміна data/dk021_uk.json і оновлення модуля.",
    "version": "19.0.1.0.0",
    "category": "Inventory/Purchase",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["product", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/dk021_load.xml",
        "views/ua_dk021_views.xml",
    ],
    "installable": True,
}
