{
    "name": "Картка працівника (OWL)",
    "summary": "Основний екран картки працівника на OWL: особа, оплата, відпустка, військовий облік, документи, хроніка",
    "version": "19.0.1.1.0",
    "license": "LGPL-3",
    "author": "Bot&Partners",
    "category": "Human Resources/Payroll",
    # l10n_ua_hr_card тягне транзитивно l10n_ua_payroll_rules, l10n_ua_payroll_reports, l10n_ua_average,
    # l10n_ua_military - лишаємо їх явними для прямих полів, якими користується get_card_data.
    # l10n_ua_hr_docs додано понад спеку: кнопка «Наказ» друкує П-1/П-4 саме звідти (єдині наявні звіти
    # наказів на hr.version); без цієї залежності env.ref на звіт наказу впав би помилкою.
    "depends": ["l10n_ua_shell", 
        "l10n_ua_hr_card",
        "l10n_ua_military",
        "l10n_ua_payroll_rules",
        "l10n_ua_average",
        "l10n_ua_hr_docs",
        "web",
    ],
    "data": [
        "views/hr_employee_views.xml",
        "views/hr_version_views.xml",
        "views/ua_employee_document_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_card_ui/static/src/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
