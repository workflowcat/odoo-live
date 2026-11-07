{
    "name": "Україна: цінники",
    "summary": "Друк цінників: назва, ціна з ПДВ, ціна за кілограм чи літр для фасованого, "
               "штрихкод, дата; аркуш A4 або етикетка 58x40",
    "description": "Цінники з картки товару або списку: ціна з обраного прайс-листа з податками, "
                   "одиниця продажу, ціна за одиницю виміру для фасованих товарів (за вмістом "
                   "упаковки), штрихкод EAN-13, EAN-8 або Code 128, дата друку і продавець. "
                   "Кілька копій кожного; аркуш A4 по 21 ціннику або окремі етикетки.",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["product", "account"],
    "data": [
        "security/ir.model.access.csv",
        "report/ua_price_label_report.xml",
        "views/price_label_views.xml",
    ],
    "installable": True,
}
