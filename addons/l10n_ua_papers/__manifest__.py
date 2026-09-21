{
    "name": "Папери",
    "summary": "Один екран усіх друкованих паперів: період угорі, перегляд і джерела поруч",
    "version": "19.0.1.0.2",
    "category": "Human Resources",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_screen",
        "l10n_ua_hr_docs",
        "l10n_ua_payroll_reports",
        "l10n_ua_payments",
        "l10n_ua_hr_orders",
        "l10n_ua_hr_card",
        "l10n_ua_hire",
        "l10n_ua_military",
        "l10n_ua_period",
        "l10n_ua_explain",
        # ua.period.close, для позначки "закритий/відкритий" місяць у смузі періоду
        "l10n_ua_changes",
        "payroll",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_papers_line_views.xml",
        "views/ua_papers_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_papers/static/src/papers.scss",
            "l10n_ua_papers/static/src/papers.js",
            "l10n_ua_papers/static/src/papers.xml",
        ],
    },
    "installable": True,
}
