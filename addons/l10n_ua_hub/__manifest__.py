{
    "name": "Головна: панель команд (Україна)",
    "summary": "Стартова сторінка з усіма командами системи, згрупованими розділами, у стилі панелі BAS/1C",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_ui"],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_hub_views.xml",
        "data/hub_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
