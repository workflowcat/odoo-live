{
    "name": "Люди",
    "summary": "Один екран працівників: перелік, підрозділи, схема підпорядкування і штатний розпис",
    "version": "19.0.1.0.2",
    "category": "Human Resources",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": [
        "l10n_ua_screen",
        "l10n_ua_hr_docs",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/ua_people_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_ua_people/static/src/people.scss",
            "l10n_ua_people/static/src/people.js",
            "l10n_ua_people/static/src/people.xml",
        ],
    },
    "installable": True,
}
