# -*- coding: utf-8 -*-
"""Дані одного розрахункового листка. Ніяких посилань на базу даних.

Оболонка (Odoo або будь-яка інша) заповнює ці структури зі своїх записів і віддає
в `calc.compute`. Так формули не залежать від того, де лежать дані.
"""
from dataclasses import dataclass, field
from datetime import date

CONTRACT_KINDS = ("employment", "gph", "gig", "fop")


@dataclass
class Employee:
    """Працівник у тому обсязі, який впливає на суми."""
    name: str = ""
    rnokpp: str = ""
    main_job: bool = True                 # основне місце роботи: від цього мінімальний ЄСВ
    contract_kind: str = "employment"     # employment | gph | gig | fop
    disabled: bool = False                # ставка ЄСВ 8,41 %
    psp: str = "none"                     # none | base | child | child150 | s150 | s200
    psp_children: int = 0
    fte: float = 1.0                      # ставка: 1, 0.75, 0.5, 0.25
    insurance_years: float = 0.0
    sick_percent: float = 0.0             # 0 = порахувати за стажем
    index_base: date = None               # базовий місяць індексації
    index_paid_month: date = None         # місяць останньої виплаченої індексації
    index_off: bool = False


@dataclass
class WorkedTime:
    """Відпрацьований час. Дні - робочі за графіком, не календарні."""
    work_days: float = 0.0                # відпрацьовано плюс дні відсутності в періоді роботи
    month_workdays: float = 0.0           # норма робочих днів місяця
    absence_work_days: dict = field(default_factory=dict)   # {"VAC": 10, "SICK": 8, ...}
    time_ratio: float = -1.0              # частка часу із затвердженого табеля; -1 = табеля немає

    def worked(self):
        """Робочі дні, за які платиться оклад."""
        return self.work_days - sum(abs(v) for v in self.absence_work_days.values())


@dataclass
class Leaves:
    """Календарні дні відсутностей у місяці листка."""
    vac_days: float = 0.0
    sick_emp_days: float = 0.0            # перші 5 днів хвороби
    sick_pfu_days: float = 0.0            # з шостого дня
    sick_care_days: float = 0.0           # догляд за хворим, ПФУ з першого дня
    mat_days: float = 0.0                 # декрет: усі дні листка непрацездатності
    mat_cover_days: float = 0.0           # дні декрету, що припадають на цей місяць
    study_days: float = 0.0
    child_vac_days: float = 0.0
    child3_days: float = 0.0
    unpaid_days: float = 0.0
    trip_days: float = 0.0
    trip_work_days: float = 0.0
    mil_days: float = 0.0                 # військова служба: місце роботи зберігається, без зарплати
    mat_start: date = None                # межі листка непрацездатності: потрібні для
    mat_end: date = None                  # помісячного розподілу допомоги і мінімального ЄСВ


@dataclass
class EarningsMonth:
    """Один місяць історії заробітку для середньої."""
    month: date
    gross: float
    calendar_days: float = 0.0            # 0 = взяти з календаря
    work_days: float = 0.0                # фактично відпрацьовані робочі дні; 0 = невідомо
    excluded_days: float = 0.0


@dataclass
class CpiMonth:
    """Індекс споживчих цін за місяць, як публікує Держстат: 100,5."""
    year: int
    month: int
    value: float
    published_on: date = None             # дата оприлюднення Держстатом


@dataclass
class Slip:
    """Листок: період, працівник, оклад, час, відсутності, введення."""
    year: int
    month: int
    employee: Employee = field(default_factory=Employee)
    wage: float = 0.0
    worked: WorkedTime = field(default_factory=WorkedTime)
    leaves: Leaves = field(default_factory=Leaves)
    inputs: dict = field(default_factory=dict)             # {"BONUS": 1000.0, ...}
    history: list = field(default_factory=list)            # [EarningsMonth, ...]
    cpi: list = field(default_factory=list)                # [CpiMonth, ...]
    aid_used_year: float = 0.0                             # уже видана матдопомога цього року
    diia_city: str = ""                                    # "" | compliant | noncompliant (резидент Дія Сіті)

    def date_to(self):
        import calendar
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])


@dataclass
class Line:
    """Рядок листка."""
    code: str
    name: str
    category: str
    amount: float


@dataclass
class Result:
    lines: list
    categories: dict

    def total(self, code):
        return sum(line.amount for line in self.lines if line.code == code)

    def dict(self):
        return {line.code: line.amount for line in self.lines}
