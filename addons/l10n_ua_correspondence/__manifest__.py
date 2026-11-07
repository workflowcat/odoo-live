{
    "name": "Україна: реєстрація вхідної та вихідної кореспонденції",
    "summary": "Журнали вхідних і вихідних документів, виконавець і строк, відповіді, "
               "окремий облік документів з грифом ДСК",
    "description": "Канцелярія як у 1С «Документообіг»: реєстраційний номер за роком, "
                   "кореспондент з їхнім номером і датою, виконавець, строк і нагадування, "
                   "відповідь вихідним листом, що закриває вхідний, журнал реєстрації до друку. "
                   "Документи «Для службового користування» реєструються окремо, з позначкою ДСК "
                   "у номері, і видно їх лише працівникам з допуском.",
    "version": "19.0.1.0.1",
    "category": "Productivity",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["mail"],
    "data": [
        "security/ua_correspondence_security.xml",
        "security/ir.model.access.csv",
        "data/ua_correspondence_data.xml",
        "report/ua_correspondence_report.xml",
        "views/ua_correspondence_views.xml",
    ],
    "installable": True,
}
