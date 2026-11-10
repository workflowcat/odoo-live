"""Рядки Д1 і 4ДФ перед формуванням файлів: бухгалтер бачить і править їх у майстрі.

Рядок зберігає графи як є; «Сформувати» перетворює рядки назад у словники графів і будує
з них XML тим самим кодом, що й без правок. Нуль у днях і в графі 18 означає «порожньо»."""
from odoo import fields, models

FLAG = [("0", "ні"), ("1", "так")]
D1_EMPTY_IF_ZERO = ("G12", "G13", "G14", "G15", "G18")


class UaPayrollReportD1Line(models.TransientModel):
    _name = "ua.payroll.report.d1.line"
    _description = "Рядок Д1 перед формуванням"
    _order = "sequence, id"

    wizard_id = fields.Many2one("ua.payroll.report.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer("№")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    g5 = fields.Selection(FLAG, "Громадянин України (5)", default="1")
    g6 = fields.Char("Стать (6)", size=1)
    g7s = fields.Char("РНОКПП (7)", size=10)
    g8 = fields.Char("Категорія ЗО (8)", size=2)
    g9 = fields.Char("Код типу нарахувань (9)", size=2)
    g101 = fields.Integer("Місяць (10)")
    g102 = fields.Integer("Рік (10)")
    g111s = fields.Char("Прізвище (11)")
    g112s = fields.Char("Ім'я (11)")
    g113s = fields.Char("По батькові (11)")
    g12 = fields.Integer("Дні непрацездатності (12)")
    g13 = fields.Integer("Дні без збереження зарплати (13)")
    g14 = fields.Integer("Дні трудових відносин (14)")
    g15 = fields.Integer("Дні декретної відпустки (15)")
    g16 = fields.Float("Нараховано всього (16)", digits=(16, 2))
    g17 = fields.Float("У межах максимуму (17)", digits=(16, 2))
    g18 = fields.Float("Різниця до мінімальної (18)", digits=(16, 2))
    g19 = fields.Float("Утримано ЄСВ (19)", digits=(16, 2))
    g20 = fields.Float("Нараховано ЄСВ (20)", digits=(16, 2))
    g21 = fields.Selection(FLAG, "Основне місце роботи (21)", default="0")
    g22 = fields.Selection(FLAG, "Неповний час (22)", default="0")
    g23 = fields.Selection(FLAG, "Спецстаж (23)", default="0")
    g24 = fields.Selection(FLAG, "Нове робоче місце (24)", default="0")
    g26 = fields.Selection(FLAG, "Нефіксований час (26)", default="0")
    rate = fields.Float("Ставка ЄСВ, %", digits=(6, 2),
                        help="Ставка, за якою рядок іде в розділ ЄСВ головної форми (22 або 8,41).")

    COLS = ("G5", "G6", "G7S", "G8", "G9", "G101", "G102", "G12", "G13", "G14", "G15", "G16", "G17", "G18",
            "G19", "G20", "G21", "G22", "G23", "G24", "G26")

    def _vals_from_row(self, wizard, row, sequence):
        vals = {"wizard_id": wizard.id, "sequence": sequence, "employee_id": row.get("employee_id") or False,
                "rate": row.get("rate") or 0.0}
        for col in self.COLS:
            value = row.get(col)
            vals[col.lower()] = (value if value is not None else False) if col not in ("G16", "G17", "G18", "G19", "G20") \
                else (value or 0.0)
        names = row.get("names") or ("", "", "")
        vals.update({"g111s": names[0], "g112s": names[1], "g113s": names[2]})
        return vals

    def _as_row(self):
        self.ensure_one()
        row = {"employee_id": self.employee_id.id, "rate": self.rate,
               "names": (self.g111s or "", self.g112s or "", self.g113s or "")}
        for col in self.COLS:
            value = self[col.lower()]
            if col in D1_EMPTY_IF_ZERO and not value:
                value = None
            elif value is False or value == "":
                value = None
            row[col] = value
        return row


class UaPayrollReportDfLine(models.TransientModel):
    _name = "ua.payroll.report.df.line"
    _description = "Рядок 4ДФ перед формуванням"
    _order = "sequence, id"

    wizard_id = fields.Many2one("ua.payroll.report.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer("№")
    employee_id = fields.Many2one("hr.employee", "Працівник")
    g02 = fields.Char("РНОКПП", size=10)
    g03a = fields.Float("Нараховано доходу", digits=(16, 2))
    g03 = fields.Float("Виплачено доходу", digits=(16, 2))
    g04a = fields.Float("ПДФО нараховано", digits=(16, 2))
    g04 = fields.Float("ПДФО перераховано", digits=(16, 2))
    g5a = fields.Float("ВЗ нараховано", digits=(16, 2))
    g5 = fields.Float("ВЗ перераховано", digits=(16, 2))
    g05 = fields.Char("Ознака доходу", size=3)
    g06d = fields.Date("Дата прийняття")
    g07d = fields.Date("Дата звільнення")
    g08 = fields.Char("Ознака пільги", size=2)

    COLS = ("G02", "G03A", "G03", "G04A", "G04", "G5A", "G5", "G05", "G06D", "G07D", "G08")

    def _vals_from_row(self, wizard, row, sequence):
        vals = {"wizard_id": wizard.id, "sequence": sequence, "employee_id": row.get("employee_id") or False}
        for col in self.COLS:
            value = row.get(col)
            vals[col.lower()] = value if value is not None else False
        return vals

    def _as_row(self):
        self.ensure_one()
        row = {"employee_id": self.employee_id.id, "G09": None}
        for col in self.COLS:
            value = self[col.lower()]
            row[col] = None if value is False or value == "" else value
        return row
