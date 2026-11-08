{
    "name": "Україна: галузеві каталоги",
    "summary": "Стартові довідники галузі одним кроком: категорії, одиниці, товари, "
               "дільниці, специфікації з маршрутами. Пакети - JSON у теці catalog/",
    "description": "Аналог початкового заповнення типової конфігурації 1С: пакет описує "
                   "довідники галузі (оборонне виробництво, закупівлі, магазин), "
                   "завантажувач кладе їх у вибрану компанію. Повторне завантаження "
                   "ідемпотентне. Пакет команди - модуль з теки catalog/, без Python. "
                   "Формат і правила - docs/customization.md.",
    "version": "19.0.1.1.0",
    "category": "Productivity",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["product", "uom", "l10n_ua_vat"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/ua_catalog_load_views.xml",
    ],
    "installable": True,
}
