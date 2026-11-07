"""Позначка проводки регламентної операції: якого місяця і що за операція."""
from odoo import fields, models

CLOSE_KINDS = [
    ("depreciation", "Амортизація"),
    ("fx", "Переоцінка валюти"),
    ("fx_reverse", "Сторно переоцінки"),
    ("overhead", "Загальновиробничі витрати"),
    ("result", "Фінансовий результат"),
    ("year", "Закриття року"),
]


class AccountMove(models.Model):
    _inherit = "account.move"

    # copy=False: копія проводки - звичайна проводка, не операція закриття.
    ua_close_id = fields.Many2one("ua.period.close", "Закриття місяця", index="btree_not_null",
                                  copy=False, readonly=True, ondelete="set null")
    ua_close_kind = fields.Selection(CLOSE_KINDS, "Регламентна операція", copy=False,
                                     readonly=True)
