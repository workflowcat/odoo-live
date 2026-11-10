"""Рядок фонду оплати праці для кожного правила зарплати (Інструкція зі статистики заробітної плати).

Звіт із праці ділить нарахування на основну зарплату, додаткову (з підрядками), заохочувальні і
компенсаційні виплати та те, що до фонду не входить. Правило зарплати несе свій клас; порожній
клас означає типовий для коду правила (DEFAULT_CLASS), а невідомий код - поза фондом.
"""
from odoo import api, fields, models

PV_CLASSES = [
    ("basic", "Основна зарплата (5020)"),
    ("allowance", "Додаткова: надбавки і доплати (5040)"),
    ("bonus", "Додаткова: премії систематичні (5050)"),
    ("index", "Додаткова: індексація (5051)"),
    ("late", "Додаткова: компенсація за затримку виплати (5052)"),
    ("additional", "Додаткова: інше (5030)"),
    ("aid", "Заохочувальні: матеріальна допомога (5070)"),
    ("social", "Заохочувальні: соціальні пільги (5080)"),
    ("incentive", "Заохочувальні і компенсаційні: інше (5060)"),
    ("civil", "Договори ЦПХ і гіг-контракти (1020, 7040)"),
    ("none", "Поза фондом оплати праці"),
]
ADDITIONAL = ("allowance", "bonus", "index", "late", "additional")
INCENTIVE = ("aid", "social", "incentive")
FUND = ("basic",) + ADDITIONAL + INCENTIVE

# Типові класи правил цього продукту. Наша оцінка: поїздки (TRIP_PAY) - додаткова зарплата,
# подарунки - заохочувальні; бухгалтер змінює клас у картці правила.
DEFAULT_CLASS = {
    "BASIC": "basic", "HOURLY": "basic", "PIECE": "basic",
    "NIGHT": "allowance", "MINSAL": "allowance",
    "BONUS": "bonus", "INDEX": "index",
    "VAC": "additional", "COMP_VAC": "additional", "STUDY_PAY": "additional",
    "CHILD_VAC_PAY": "additional", "TRIP_PAY": "additional",
    "AID_FREE": "aid", "AID_TAX": "aid",
    "GIFT_FREE": "incentive", "GIFT_TAX": "incentive",
    "GPH": "civil", "GIG": "civil", "GIG_BONUS": "civil",
}
# Оплата за невідпрацьований час (рядок 5090): відпускні і компенсація за невикористану відпустку.
DEFAULT_UNWORKED = {"VAC", "COMP_VAC", "STUDY_PAY", "CHILD_VAC_PAY"}


class HrSalaryRule(models.Model):
    _inherit = "hr.salary.rule"

    ua_pv_class = fields.Selection(
        PV_CLASSES, "Рядок фонду оплати праці (1-ПВ)",
        help="Куди сума правила йде у звіті із праці. Порожньо - типове значення для коду правила; "
             "невідомий код - поза фондом.")
    ua_pv_unworked = fields.Boolean(
        "Оплата за невідпрацьований час (5090)",
        help="Відпускні, компенсація за невикористану відпустку, оплата простою, державних обов'язків.")

    def _ua_pv_effective(self):
        """(клас, невідпрацьований час?) з урахуванням типових значень."""
        self.ensure_one()
        return (self.ua_pv_class or DEFAULT_CLASS.get(self.code, "none"),
                self.ua_pv_unworked or (not self.ua_pv_class and self.code in DEFAULT_UNWORKED))

    @api.model
    def _ua_pv_fill_defaults(self):
        for rule in self.sudo().search([("ua_pv_class", "=", False)]):
            rule.write({"ua_pv_class": DEFAULT_CLASS.get(rule.code, "none"),
                        "ua_pv_unworked": rule.code in DEFAULT_UNWORKED})
