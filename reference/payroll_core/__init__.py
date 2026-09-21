# -*- coding: utf-8 -*-
"""Незалежна перевірка українського розрахунку зарплати. Без Odoo, без сторонніх пакетів.

Правила живуть у `data/rules-ua.json` і більше ніде. Очікуваних чисел у пакеті немає:
їх дає єдиний спільний файл `addons/l10n_ua_payroll_tests/golden/scenarios.json`.
"""
from .calc import compute, values
from .dsl import RuleSet
from .model import CpiMonth, EarningsMonth, Employee, Leaves, Line, Result, Slip, WorkedTime
from .params import Params

__all__ = ["compute", "values", "Params", "RuleSet", "Slip", "Employee", "WorkedTime",
           "Leaves", "EarningsMonth", "CpiMonth", "Line", "Result"]
