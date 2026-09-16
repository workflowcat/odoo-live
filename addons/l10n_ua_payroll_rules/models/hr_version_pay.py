# -*- coding: utf-8 -*-
"""Вид оплати на версії контракту (оклад/погодинна) і дні виплат компанії.

Окреме нове поле - окремий файл, а не hr_version.py/ua_advance_sheet.py напряму,
щоб не заважати іншим агентам, які паралельно правлять інші поля тих моделей.
"""
from odoo import api, fields, models

PAY_TYPES = [("monthly", "Оклад (місячна)"), ("hourly", "Погодинна")]

# Код КП (перші цифри) -> скорочена норма годин на тиждень (ст. 51 КЗпП і галузеві норми).
# Водії (Порядок 340) мають добову, а не тижневу межу - формулою тут не покрито,
# типова ставка 40 год лишається за замовчуванням, як для решти професій без пільги.
PROFESSION_NORM_HOURS = [
    ("222", 38.5, "лікарі"),
    ("223", 38.5, "середній медичний персонал"),
    ("224", 38.5, "фармацевти та інший медичний персонал"),
    ("233", 36.0, "педагогічні професіонали (середня/вища освіта)"),
    ("234", 36.0, "педагоги дошкільної та початкової освіти"),
]


def ua_profession_norm_hours(kp_code):
    """Типова тижнева норма годин за префіксом коду КП; 40, якщо пільги немає."""
    code = (kp_code or "").strip()
    for prefix, hours, _label in PROFESSION_NORM_HOURS:
        if code.startswith(prefix):
            return hours
    return 40.0


class HrVersion(models.Model):
    _inherit = "hr.version"

    ua_pay_type = fields.Selection(PAY_TYPES, "Вид оплати", default="monthly", required=True, groups="hr.group_hr_user",
                                   help="Погодинна: оклад (BASIC) не рахується, натомість нараховується HOURLY = ставка/год × факт годин")
    ua_hour_rate = fields.Monetary("Ставка, грн/год", groups="hr.group_hr_user",
                                   help="Обов'язково для погодинної оплати; для окладу використовується як довідкова еквівалентна ставка")
    ua_weekly_hours = fields.Float("Норма годин на тиждень", default=40.0, groups="hr.group_hr_user",
                                   help="40 типово; 38,5 медичні, 36 педагоги (ст. 51 КЗпП); неповний робочий час "
                                        "(сумісники, часткова ставка) - вказати менше значення напряму. "
                                        "Підказка за кодом КП підставляється в полі, редагується вручну")
    ua_night_shifts = fields.Boolean("Працює в нічну зміну", groups="hr.group_hr_user")

    @api.onchange("ua_kp_code")
    def _onchange_ua_kp_code_weekly_hours(self):
        # ua_kp_code живе в l10n_ua_payroll_reports (залежить від цього модуля, не навпаки) - onchange,
        # а не @api.depends stored-compute, бо той вимагає поле в тій самій моделі при реєстрації цього модуля.
        if "ua_kp_code" in self._fields:
            self.ua_weekly_hours = ua_profession_norm_hours(self.ua_kp_code)


class ResCompanyPay(models.Model):
    _inherit = "res.company"

    def _ua_pay_terms(self):
        """Дні виплат компанії для інших модулів (авансова відомість, наказ про прийняття).

        Поля живуть у l10n_ua_hr_orders (ua_pay_advance_day, ua_pay_advance_percent,
        ua_pay_final_day) - той модуль залежить від цього, не навпаки, тому тут лише
        безпечне читання (getattr), без дублювання полів і без зворотної залежності."""
        self.ensure_one()
        return {
            "advance_day": getattr(self, "ua_pay_advance_day", 20) or 20,
            "salary_day": getattr(self, "ua_pay_final_day", 7) or 7,
            "advance_percent": getattr(self, "ua_pay_advance_percent", 50.0) or 50.0,
        }
