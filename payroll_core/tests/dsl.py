# -*- coding: utf-8 -*-
"""Ті самі 26 сценаріїв, але правила беруться з JSON, а не з коду.

Запуск: python3 -m payroll_core.tests.dsl
Сенс перевірки: набір правил-даних дає ті самі числа, що й код. Якщо так, правила можна
редагувати як дані - бухгалтером, моделлю або скриптом - і перевіряти сценаріями.
"""
import os
import sys

from .. import Params
from ..calc import compute, compute_rules
from ..dsl import RuleSet
from .golden import SCENARIOS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(BASE, "data", "params-ua.json")
RULES = os.path.join(BASE, "data", "rules-ua.json")


def main():
    params = Params.load(PARAMS)
    ruleset = RuleSet.load(RULES)
    from ..calc import EXTRA_FUNCS
    errors = ruleset.validate(EXTRA_FUNCS)
    print(("PASS " if not errors else "FAIL ") + "усі вирази набору безпечні | %s" % (errors or "помилок немає"))
    failed = 1 if errors else 0
    for name, slip, expect in SCENARIOS:
        from_code = compute(slip, params).dict()
        from_data = compute_rules(slip, params, ruleset).dict()
        diff = [code for code in set(from_code) | set(from_data)
                if abs(from_code.get(code, 0.0) - from_data.get(code, 0.0)) > 0.005]
        ok_expect = all(abs(from_data.get(code, 0.0) - want) < 0.005 for code, want in expect.items())
        ok = not diff and ok_expect
        failed += 0 if ok else 1
        detail = ("розбіжність: %s" % ", ".join(sorted(diff))) if diff else (
            "усі рядки збіглися" if ok_expect else "не збіглося з еталоном")
        print(("PASS " if ok else "FAIL ") + name + " | " + detail)
    print("ALL PASS" if not failed else "SOME FAIL: %s" % failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
