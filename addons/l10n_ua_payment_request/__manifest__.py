{
    "name": "Україна: заявки на оплату з погодженням",
    "summary": "Заявка на оплату постачальнику: погодження фінансиста, затвердження директора "
               "понад ліміт, платіж із затвердженої заявки, платіжний календар",
    "description": "Аналог «Заявки на витрачання коштів» в 1С. Ініціатор складає заявку (кому, "
                   "скільки, коли, за що, з якого рахунку), прив'язує рахунки постачальника і "
                   "договір. Фінансист погоджує або відхиляє з причиною; заявку понад ліміт "
                   "компанії затверджує ще й директор. Хто склав заявку, той її не погоджує. З "
                   "затвердженої заявки бухгалтер створює платіж: за рахунками - з їх закриттям, "
                   "без рахунків - аванс. Платіжний календар - заявки за датами оплати з сумами.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["account", "l10n_ua_contract"],
    "data": [
        "security/ua_payment_request_security.xml",
        "security/ir.model.access.csv",
        "data/ua_payment_request_data.xml",
        "report/ua_payment_request_report.xml",
        "views/ua_payment_request_views.xml",
        "views/res_company_views.xml",
    ],
    "installable": True,
}
