# -*- coding: utf-8 -*-
"""Перевірка файлів ДПС: будуємо Д1 і 4ДФ з порахованих листків і звіряємо за XSD.

Запуск: python3 -m payroll_core.tests.dps
"""
import os
import sys
from datetime import date

from .. import Params, compute
from ..dps import forms
from ..dps.xml import Company, validate
from ..model import Employee, Slip, WorkedTime

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "params-ua.json")
YEAR, MONTH = 2026, 8

COMPANY = Company(name="ТОВ «Ясен Меблі»", tin="43812071", sti_code="1306", reg="13", raj="06",
                  katottg="UA80000000000093317", director_name="Тестовий Керівник",
                  director_rnokpp="1234567890", accountant_name="Тестовий Бухгалтер",
                  accountant_rnokpp="1234567891")

PEOPLE = [
    ("3000000001", "Коваленко", "Ірина", "Петрівна", "0", 30000.0),
    ("3000000002", "Шевчук", "Андрій", "Миколайович", "1", 18000.0),
]


def rows(params):
    """Рядки Д1 і 4ДФ з порахованих листків."""
    d1_rows, df_rows = [], []
    for rnokpp, last, first, middle, gender, wage in PEOPLE:
        slip = Slip(year=YEAR, month=MONTH, wage=wage,
                    employee=Employee(name=" ".join((last, first, middle)), rnokpp=rnokpp),
                    worked=WorkedTime(work_days=21, month_workdays=21))
        result = compute(slip, params).dict()
        gross = result.get("GROSS", 0.0)
        pdfo = -result.get("PDFO", 0.0)
        vz = -result.get("VZ", 0.0)
        esv = result.get("ESV", 0.0)
        d1_rows.append({
            "G5": "1", "G6": gender, "G7S": rnokpp, "G8": forms.ESV_CAT["employment"],
            "G101": MONTH, "G102": YEAR, "names": (last, first, middle),
            "G14": 31, "G16": gross, "G17": gross, "G18": None, "G19": 0.0, "G20": esv,
            "G21": "1", "G22": "0", "G23": "0", "G24": "0", "G26": "0",
        })
        df_rows.append({
            "G02": rnokpp, "G03A": gross, "G03": gross, "G04A": pdfo, "G04": pdfo,
            "G5A": vz, "G5": vz, "G05": forms.INCOME_SIGN["employment"],
            "G06D": None, "G07D": None, "G08": None, "G09": None,
        })
    return d1_rows, df_rows


def main():
    params = Params.load(DATA)
    d1_rows, df_rows = rows(params)
    fill = date(YEAR, 9, 9)
    failed = 0
    for label, (name, data), schema in (
        ("Д1", forms.build_d1(COMPANY, YEAR, MONTH, d1_rows, fill_date=fill), "J0510111"),
        ("4ДФ", forms.build_4df(COMPANY, YEAR, MONTH, df_rows, employment_count=len(df_rows),
                                fill_date=fill), "J0510411"),
    ):
        errors = validate(data, schema)
        failed += 1 if errors else 0
        print(("PASS " if not errors else "FAIL ") + "%s %s (%s байт)" % (label, name, len(data)))
        for error in errors[:5]:
            print("   ", error)
    print("ALL PASS" if not failed else "SOME FAIL: %s" % failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
