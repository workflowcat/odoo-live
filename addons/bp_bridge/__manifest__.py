{
    "name": "Міст інтеграцій",
    "summary": "Єдині двері назовні: абстрактна модель bp.bridge, один URL і один токен на всю систему",
    "description": "Odoo не тримає ключів постачальників даних - тільки адресу моста "
                   "(BP_BRIDGE_URL) і токен (BP_BRIDGE_TOKEN). Модуль дає одну абстрактну "
                   "модель bp.bridge з методом call(method, path, payload, params): вона "
                   "підписує запит, ходить у Worker odoo-live і повертає пару (статус, дані). "
                   "Налаштування береться зі змінних середовища, а якщо їх немає - з "
                   "параметрів bp_bridge.url / bp_bridge.token (старі ключі "
                   "bp_kyc.bridge_url / bp_kyc.bridge_token теж читаються). Моделей, "
                   "екранів і меню тут немає: це залежність для модулів, яким потрібен "
                   "зовнішній запит. Опис у docs/ARCHITECTURE.md.",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Bot&Partners",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "application": False,
    "auto_install": False,
}
