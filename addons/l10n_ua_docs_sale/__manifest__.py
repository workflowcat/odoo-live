{
    "name": "Україна: первинка із замовлення на продаж",
    "summary": "Рахунок на оплату з sale.order, номер і дата договору на замовленні",
    "description": "Міст між l10n_ua_docs і sale. Замовлення підмішує собі ua.docs.source "
                   "і тому друкується тим самим бланком рахунку, що й рахунок клієнта: "
                   "другого комплекту форм немає. Додає лише номер і дату договору - "
                   "реквізит, якого в нативному замовленні немає, а на папері він потрібен.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_docs", "sale"],
    "data": [
        "report/ua_docs_sale_reports.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": True,
}
