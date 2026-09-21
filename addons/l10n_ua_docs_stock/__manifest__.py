{
    "name": "Україна: первинка з доставки (видаткова, ТТН)",
    "summary": "Видаткова накладна і спрощена ТТН з stock.picking, довіреність одержувача",
    "description": "Міст між l10n_ua_docs і stock. Доставка підмішує ua.docs.source і "
                   "друкується тим самим бланком видаткової накладної, що й рахунок. "
                   "Додає довіреність одержувача (номер, дата, ПІБ) і спрощену ТТН: "
                   "пункти навантаження й розвантаження, вага, місця для перевізника, "
                   "автомобіля і водія. Товарно-транспортна накладна тут навмисно проста - "
                   "повна форма № 1-ТН з усіма розділами не вміщається в тонкий міст.",
    "version": "19.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_docs", "stock"],
    "data": [
        "report/ua_docs_stock_reports.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": True,
}
