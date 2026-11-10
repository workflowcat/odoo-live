from odoo import fields, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    ua_order_ref = fields.Char("Наказ про прийняття (№ і дата)", groups="hr.group_hr_user", help="Наприклад: Наказ № 12 від 17.08.2026")
    ua_end_order_ref = fields.Char("Наказ про звільнення (№ і дата)", groups="hr.group_hr_user")
    ua_dismissal_basis = fields.Char("Підстава припинення", groups="hr.group_hr_user", help="Наприклад: п. 1 ст. 36 КЗпП (угода сторін)")
    ua_kp_code = fields.Char("Код КП", size=10, groups="hr.group_hr_user", help="Код за Класифікатором професій ДК 003, наприклад 2411.2")
    ua_prof_name = fields.Char("Професійна назва роботи", groups="hr.group_hr_user")
    ua_internal_parttime = fields.Boolean("Внутрішній сумісник", groups="hr.group_hr_user")
    # Ознаки рядка Д1 (графи 23, 24, 26): стабільні на весь строк умов договору, тому - на версії договору.
    ua_special_seniority = fields.Boolean(
        "Спецстаж (пільгова пенсія)", groups="hr.group_hr_user",
        help="Робота дає право на пенсію на пільгових умовах або за вислугу років: графа 23 Д1 = 1. "
             "Періоди спецстажу подаються окремо (додаток Д6).")
    ua_special_seniority_code = fields.Char(
        "Код підстави спецстажу", size=8, groups="hr.group_hr_user",
        help="Вісім знаків з довідника підстав для обліку спецстажу (додаток 3 до Порядку № 4), "
             "наприклад ЗПЗ055Е2 для лікаря. Графа 07 додатка Д6.")
    ua_special_attest_number = fields.Char(
        "Наказ про атестацію робочого місця, №", groups="hr.group_hr_user",
        help="Графа 14 Д6. Лише коли спецстаж залежить від атестації робочого місця (списки 1 і 2).")
    ua_special_attest_date = fields.Date(
        "Дата наказу про атестацію", groups="hr.group_hr_user", help="Графа 15 Д6.")
    ua_new_workplace = fields.Boolean(
        "Нове робоче місце", groups="hr.group_hr_user",
        help="Працівника прийнято на нове робоче місце, за яке роботодавець отримує компенсацію ЄСВ: графа 24 Д1 = 1.")
    ua_new_workplace_until = fields.Date(
        "Нове робоче місце до", groups="hr.group_hr_user",
        help="Останній день, коли діє ознака нового робочого місця. Порожньо - поки діє версія договору.")
    ua_unfixed_hours = fields.Boolean(
        "Нефіксований робочий час", groups="hr.group_hr_user",
        help="Трудовий договір з нефіксованим робочим часом (ст. 21-1 КЗпП): графа 26 Д1 = 1.")
