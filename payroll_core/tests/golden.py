# -*- coding: utf-8 -*-
"""Еталонні сценарії: ті самі числа, що рахує стенд.

Запуск: python3 -m payroll_core.tests.golden
Джерело чисел: docs/payroll/golden-scenarios.md і scripts/payroll_check.py.
Якщо сценарій не збігся, винен розрахунок, а не тест.
"""
import os
import sys
from datetime import date

from .. import Params, compute
from ..model import CpiMonth, EarningsMonth, Employee, Leaves, Slip, WorkedTime

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "params-ua.json")
YEAR, MONTH, NORM = 2026, 8, 21.0


WORK_DAYS = {(2025, 8): 21, (2025, 9): 22, (2025, 10): 23, (2025, 11): 20, (2025, 12): 23,
             (2026, 1): 21, (2026, 2): 20, (2026, 3): 22, (2026, 4): 22, (2026, 5): 20,
             (2026, 6): 22, (2026, 7): 23, (2026, 8): 21}
# лютий і березень дають наростаючий 103,1 %; серпень навмисно великий і не застосовується
CPI = [CpiMonth(2026, 2, 101.5), CpiMonth(2026, 3, 101.6), CpiMonth(2026, 8, 110.0)]


def history(gross=30000.0, months=12):
    """Історія заробітку за 12 повних місяців перед серпнем 2026."""
    rows, year, month = [], 2025, 8
    for _i in range(months):
        rows.append(EarningsMonth(month=date(year, month, 1), gross=gross,
                                  work_days=WORK_DAYS.get((year, month), 21)))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return rows


def slip(wage=30000.0, work_days=NORM, absences=None, employee=None, inputs=None,
         leaves=None, hist=None, cpi=None, aid_used=0.0):
    return Slip(
        year=YEAR, month=MONTH, wage=wage,
        employee=employee or Employee(),
        worked=WorkedTime(work_days=work_days, month_workdays=NORM, absence_work_days=absences or {}),
        leaves=leaves or Leaves(),
        inputs=inputs or {},
        history=hist or [],
        cpi=cpi or [],
        aid_used_year=aid_used,
    )


SCENARIOS = [
    ("1 Повний місяць, оклад", slip(),
     {"PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
    ("2 Неповний місяць (з 17-го, 11 з 21 днів)", slip(work_days=11.0),
     {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
    ("3 Сумісник (0,5 ставки, оклад 10 000)",
     slip(wage=10000.0, employee=Employee(main_job=False, fte=0.5)),
     {"BASIC": 5000.00, "PDFO": -900.00, "VZ": -250.00, "NET": 3850.00, "ESV": 1100.00}),
    ("4 ПСП базова (0,5 ставки, оклад 9 000)",
     slip(wage=9000.0, employee=Employee(psp="base", fte=0.5)),
     {"BASIC": 4500.00, "PDFO": -510.48, "VZ": -225.00, "NET": 3764.52, "ESV": 1902.34}),
    ("5 Інвалідність", slip(wage=20000.0, employee=Employee(disabled=True)),
     {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 1682.00}),
    ("6 Відпустка 14 к.д. (3-16 серпня)",
     slip(absences={"VAC": 10}, leaves=Leaves(vac_days=14), hist=history()),
     {"BASIC": 15714.29, "VAC": 13808.22, "GROSS": 29522.51, "PDFO": -5314.05, "VZ": -1476.13,
      "NET": 22732.33, "ESV": 6494.95}),
    ("7 Лікарняний 10 к.д. (10-19 серпня), стаж 6 років",
     slip(absences={"SICK": 8}, leaves=Leaves(sick_emp_days=5, sick_pfu_days=5),
          employee=Employee(insurance_years=6), hist=history()),
     {"BASIC": 18571.43, "SICK_EMP": 3452.05, "SICK_PFU": 3452.05, "GROSS": 25475.53,
      "PDFO": -4585.60, "VZ": -1273.78, "NET": 19616.15, "ESV": 5604.62}),
    ("8 Звільнення 31 серпня, 10 днів компенсації",
     slip(inputs={"COMP_DAYS": 10}, hist=history()),
     {"BASIC": 30000.00, "COMP_VAC": 9863.01, "GROSS": 39863.01, "PDFO": -7175.34,
      "VZ": -1993.15, "NET": 30694.52, "ESV": 8769.86}),
    ("9 ЦПХ", slip(wage=0.0, employee=Employee(contract_kind="gph", main_job=False),
                   inputs={"GPH": 20000}),
     {"PDFO": -3600.00, "VZ": -1000.00, "NET": 15400.00, "ESV": 4400.00}),
    ("10 Аліменти + максимальна база", slip(wage=200000.0, inputs={"ALIM_PCT": 25}),
     {"PDFO": -36000.00, "VZ": -10000.00, "ALIM": -38500.00, "NET": 115500.00, "ESV": 38046.80}),
    ("11 Повторне прийняття 17 серпня", slip(work_days=11.0),
     {"BASIC": 15714.29, "PDFO": -2828.57, "VZ": -785.71, "NET": 12100.01, "ESV": 3457.14}),
    ("12 Половина ставки (0,5), оклад 20 000", slip(wage=20000.0, employee=Employee(fte=0.5)),
     {"BASIC": 10000.00, "PDFO": -1800.00, "VZ": -500.00, "NET": 7700.00, "ESV": 2200.00}),
    ("13 Аванс 50 % 20-го, остаточний розрахунок", slip(inputs={"ADVANCE": 15000}),
     {"GROSS": 30000.00, "PDFO": -5400.00, "VZ": -1500.00, "ADV_PAID": -15000.00,
      "NET": 8100.00, "ESV": 6600.00}),
    ("14 ФОП-підрядник (ознака 157)",
     slip(wage=0.0, employee=Employee(contract_kind="fop", main_job=False), inputs={"FOP_PAY": 40000}),
     {"GROSS": 40000.00, "NET": 40000.00}),
    ("15 Декретна відпустка 126 к.д. з 10 серпня",
     slip(absences={"MAT": 16}, leaves=Leaves(mat_days=126, mat_cover_days=22), hist=history()),
     {"BASIC": 7142.86, "MAT": 124273.97, "GROSS": 7142.86, "PDFO": -1285.71, "VZ": -357.14,
      "NET": 129773.98, "ESV": 28911.70}),
    ("16 Індексація 500", slip(inputs={"INDEX": 500}),
     {"INDEX": 500.00, "GROSS": 30500.00, "PDFO": -5490.00, "VZ": -1525.00, "NET": 23485.00,
      "ESV": 6710.00}),
    ("17 Індексація автоматично (базовий січень, наростаючий 103,1 %)",
     slip(employee=Employee(index_base=date(2026, 1, 1)), cpi=CPI),
     {"INDEX": 103.17, "GROSS": 30103.17, "PDFO": -5418.57, "VZ": -1505.16, "NET": 23179.44,
      "ESV": 6622.70}),
    ("27 Індексації немає: наростаючий індекс нижчий за поріг",
     slip(employee=Employee(index_base=date(2026, 2, 1)), cpi=CPI),
     {"GROSS": 30000.00, "PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
    ("28 Індекс місяця листка не застосовується",
     slip(employee=Employee(index_base=date(2026, 7, 1)), cpi=CPI),
     {"GROSS": 30000.00, "PDFO": -5400.00, "VZ": -1500.00, "NET": 23100.00, "ESV": 6600.00}),
    ("29 Відрядження: середня за два місяці вища за оклад",
     slip(absences={"TRIP": 5}, leaves=Leaves(trip_days=5, trip_work_days=5), hist=history(45000.0)),
     {"BASIC": 22857.14, "TRIP_PAY": 10000.00, "GROSS": 32857.14, "PDFO": -5914.29,
      "VZ": -1642.86, "NET": 25299.99, "ESV": 7228.57}),
    ("30 Декрет із низьким заробітком: мінімальний ЄСВ за кожен місяць",
     slip(wage=8000.0, absences={"MAT": 16},
          leaves=Leaves(mat_days=126, mat_cover_days=22,
                        mat_start=date(2026, 8, 10), mat_end=date(2026, 12, 13))),
     {"BASIC": 1904.76, "MINSAL": 154.05, "MAT": 33139.73, "GROSS": 2058.81, "NET": 34725.01,
      "ESV": 9511.70}),
    ("18 Навчальна відпустка 10 к.д. (3-12 серпня)",
     slip(absences={"STUDY": 8}, leaves=Leaves(study_days=10), hist=history()),
     {"BASIC": 18571.43, "STUDY_PAY": 9863.01, "GROSS": 28434.44, "PDFO": -5118.20,
      "VZ": -1421.72, "NET": 21894.52, "ESV": 6255.58}),
    ("19 Відрядження 5 робочих днів (3-7 серпня) з добовими",
     slip(absences={"TRIP": 5}, leaves=Leaves(trip_days=5, trip_work_days=5),
          inputs={"DAILY": 1500}, hist=history()),
     {"BASIC": 22857.14, "TRIP_PAY": 7142.86, "DAILY": 1500.00, "GROSS": 30000.00,
      "PDFO": -5400.00, "VZ": -1500.00, "NET": 24600.00, "ESV": 6600.00}),
    ("20 Догляд за хворою дитиною 7 к.д. (10-16 серпня), стаж 6 років",
     slip(absences={"SICK_CARE": 5}, leaves=Leaves(sick_care_days=7),
          employee=Employee(insurance_years=6), hist=history()),
     {"BASIC": 22857.14, "SICK_CARE_PAY": 4832.88, "GROSS": 27690.02, "PDFO": -4984.20,
      "VZ": -1384.50, "NET": 21321.32, "ESV": 6091.80}),
    ("21 Доплата до мінімальної зарплати (оклад 8 000)", slip(wage=8000.0),
     {"BASIC": 8000.00, "MINSAL": 647.00, "GROSS": 8647.00, "PDFO": -1556.46, "VZ": -432.35,
      "NET": 6658.19, "ESV": 1902.34}),
    ("22 Доплати до мінімальної немає: оклад вищий", slip(wage=12000.0),
     {"BASIC": 12000.00, "GROSS": 12000.00, "PDFO": -2160.00, "VZ": -600.00, "NET": 9240.00,
      "ESV": 2640.00}),
    ("23 Матеріальна допомога 6 000 (межа 4 660 на рік)", slip(inputs={"AID": 6000}),
     {"BASIC": 30000.00, "AID_FREE": 4660.00, "AID_TAX": 1340.00, "GROSS": 30000.00,
      "PDFO": -5641.20, "VZ": -1567.00, "NET": 28791.80, "ESV": 6600.00}),
    ("24 Подарунок 3 000 (межа 25 % МЗП = 2 161,75)", slip(wage=20000.0, inputs={"GIFT": 3000}),
     {"BASIC": 20000.00, "GIFT_FREE": 2161.75, "GIFT_TAX": 838.25, "GROSS": 20000.00,
      "PDFO": -3750.89, "VZ": -1041.91, "NET": 18207.20, "ESV": 4400.00}),
    ("25 Вихідна допомога 30 000 і виконавчий документ 20 %",
     slip(inputs={"SEVERANCE": 30000, "EXEC_PCT": 20}),
     {"BASIC": 30000.00, "SEVERANCE": 30000.00, "GROSS": 30000.00, "PDFO": -10800.00,
      "VZ": -3000.00, "EXEC_DOC": -9240.00, "NET": 36960.00, "ESV": 6600.00}),
    ("26 Профспілковий внесок 1 % і відшкодування шкоди 500",
     slip(wage=25000.0, inputs={"UNION_PCT": 1, "DAMAGE_AMT": 500}),
     {"BASIC": 25000.00, "GROSS": 25000.00, "PDFO": -4500.00, "VZ": -1250.00, "UNION": -250.00,
      "DAMAGE": -500.00, "NET": 18500.00, "ESV": 5500.00}),
]


def main():
    params = Params.load(DATA)
    failed = 0
    for name, data, expect in SCENARIOS:
        got = compute(data, params).dict()
        parts, ok = [], True
        for code, want in expect.items():
            value = got.get(code, 0.0 if want == 0 else None)
            good = value is not None and abs(value - want) < 0.005
            ok &= good
            parts.append("%s %s %s %s" % (code, value, "==" if good else "!=", want))
        failed += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + name + " | " + "; ".join(parts))
    print("ALL PASS" if not failed else "SOME FAIL: %s" % failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
