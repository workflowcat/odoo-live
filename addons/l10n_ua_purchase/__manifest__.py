{
    "name": "Україна: закупівлі (паспорт постачальника, запити, пад)",
    "summary": "Ризик постачальника і історія закупівель у картці контрагента, підрозділ і "
               "рахунок витрат на запиті OCA, ліміт погодження, пад швидкого замовлення",
    "description": "Український шар поверх нативної закупівлі Odoo і OCA purchase_request. "
                   "Нативне: запит пропозиції, замовлення, прийом, рахунок, двоступеневе "
                   "погодження замовлення за сумою (po_double_validation). OCA: внутрішній "
                   "запит на закупівлю purchase.request і чарівник «запит -> замовлення» - "
                   "взято без змін. Наше тонко зверху: оцінка ризику постачальника з "
                   "сигналів ЄДР, ПДВ, KYC і власної історії оплат; зведення закупівель у "
                   "картці контрагента; підрозділ і рахунок витрат, що їдуть із запиту в "
                   "замовлення і далі в рахунок; ліміт суми, вище якого запит погоджує лише "
                   "керівник закупівель; пад швидкого замовлення (встав артикули - отримай "
                   "запит). Власних екранів немає: стандартні подання, кнопки і чарівники. "
                   "Опис у docs/base/spec-purchase.md.",
    "version": "19.0.1.1.0",
    "category": "Inventory/Purchase",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["purchase_request", "account", "hr", "l10n_ua"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_company_views.xml",
        "views/res_partner_views.xml",
        "views/purchase_request_views.xml",
        "views/purchase_order_views.xml",
        "wizard/ua_purchase_pad_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
