{
    "name": "Україна: Дія Сіті - акти гіг-спеціалістів",
    "summary": "Винагорода гіг-спеціаліста у валюті за курсом НБУ, акт у двох валютах, премія окремим рядком, "
               "суми в розрахунковий листок",
    "description": "Ставки Дія Сіті (ПДФО 5 %, мінімальний ЄСВ) і документ «Дія Сіті за місяцями» живуть у "
                   "модулі правил зарплати. Цей модуль додає роботу з гіг-спеціалістами: винагорода за "
                   "місяць у валюті договору в картці, акт приймання-передачі послуг з курсом НБУ на дату "
                   "акта (курси з res.currency.rate, їх оновлює l10n_ua_nbu), суми в гривнях і у валюті на "
                   "друкованій формі. Затверджений акт іде в листок рядками «Винагорода за гіг-контрактом» "
                   "(GIG) і «Премія гіг-спеціалісту» (GIG_BONUS).",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Payroll",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["l10n_ua_payroll_rules"],
    "data": [
        "security/ir.model.access.csv",
        "security/ua_gig_act_security.xml",
        "data/ua_gig_act_data.xml",
        "report/ua_gig_act_report.xml",
        "views/hr_employee_views.xml",
        "views/ua_gig_act_views.xml",
    ],
    "installable": True,
}
