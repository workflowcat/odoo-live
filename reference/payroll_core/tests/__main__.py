# -*- coding: utf-8 -*-
"""Незалежна перевірка еталонних сценаріїв.

    python3 -m reference.payroll_core.tests

Читає `addons/l10n_ua_payroll_tests/golden/scenarios.json` - той самий файл, що й тести
Odoo, - і рахує кожен сценарій наново з його ж вхідних даних. Своїх очікуваних чисел
пакет не має: порівнювати нема з чим, крім еталона.

Статуси:
    MATCH        усі рядки і проводки сценарію збіглися
    DIFF         хоч один рядок розійшовся; друкуємо код, число еталона і своє
    UNSUPPORTED  сценарій не виражається наявними правилами; друкуємо причину

Розбіжність - це не поломка перевірки. Це питання: помиляється Odoo (звідки взяті числа
еталона) чи помиляється ця перевірка. Відповідь дає бухгалтер, і вона лягає в
docs/payroll/golden-for-accountant.md.
"""
import os
import sys

from .. import Params, RuleSet, compute
from ..calc import EXTRA_FUNCS
from ..moves import balanced, build as build_moves
from ..scenarios import Unsupported, build, load_cpi, load_scenarios

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
PARAMS = os.path.join(HERE, "data", "params-ua.json")
RULES = os.path.join(HERE, "data", "rules-ua.json")
CPI = os.path.join(HERE, "data", "cpi-ua.json")
GOLDEN = os.path.join(ROOT, "addons", "l10n_ua_payroll_tests", "golden", "scenarios.json")

TOLERANCE = 0.005


def _fmt(value):
    return "-" if value is None else "%.2f" % value


def _compare_lines(golden_expect, got):
    """Розбіжності по рядках листка."""
    out = []
    for code, want in sorted(golden_expect.items()):
        value = got.get(code, 0.0)
        if abs(value - float(want)) >= TOLERANCE:
            out.append((code, float(want), value))
    return out


def _compare_moves(golden_moves, got_moves):
    """Розбіжності по проводках. Ключ - сторона і рахунок, бо порядок не важить."""
    if not golden_moves:
        return []
    want = {}
    for move in golden_moves:
        key = "%s %s" % (move["side"], move["account"])
        want[key] = want.get(key, 0.0) + float(move["amount"])
    have = {}
    for move in got_moves:
        key = "%s %s" % (move["side"], move["account"])
        have[key] = have.get(key, 0.0) + float(move["amount"])
    out = []
    for key in sorted(set(want) | set(have)):
        a, b = want.get(key), have.get(key)
        if a is None or b is None or abs(a - b) >= TOLERANCE:
            out.append((key, a, b))
    return out


def run():
    params = Params.load(PARAMS)
    ruleset = RuleSet.load(RULES)
    cpi = load_cpi(CPI)
    data = load_scenarios(GOLDEN)

    errors = ruleset.validate(EXTRA_FUNCS)
    if errors:
        print("FAIL набір правил: %s" % "; ".join(errors))
        return 1

    rows = []
    for scenario in data["scenarios"]:
        ident, title = scenario["id"], scenario["title"]
        try:
            slip = build(scenario, cpi)
        except Unsupported as reason:
            rows.append((ident, "UNSUPPORTED", title, [], str(reason)))
            continue
        result = compute(slip, params, ruleset)
        got = result.dict()
        diffs = _compare_lines(scenario.get("expect") or {}, got)
        moves = build_moves(result)
        diffs += _compare_moves(scenario.get("moves") or [], moves)
        note = ""
        ok, debit, credit = balanced(moves)
        if not ok:
            note = "проводки не сходяться: Дт %.2f, Кт %.2f" % (debit, credit)
            diffs = diffs or [("БАЛАНС", debit, credit)]
        rows.append((ident, "DIFF" if diffs else "MATCH", title, diffs, note))
    return report(rows, data)


def report(rows, data):
    width = max(len(row[2]) for row in rows)
    print("Незалежна перевірка проти %s" % os.path.relpath(GOLDEN, ROOT))
    print("Параметри %s року. Своїх очікуваних чисел перевірка не має.\n"
          % data.get("params_year", ""))
    print("%-4s %-12s %s" % ("ID", "СТАТУС", "СЦЕНАРІЙ"))
    print("-" * (18 + width))
    for ident, status, title, diffs, note in rows:
        print("%-4s %-12s %s" % (ident, status, title))
        if status == "UNSUPPORTED":
            print("     %s" % note)
        for code, want, got in diffs:
            print("     %-14s еталон %10s   перевірка %10s"
                  % (code, _fmt(want), _fmt(got)))
        if note and status != "UNSUPPORTED":
            print("     %s" % note)
    counts = {"MATCH": 0, "DIFF": 0, "UNSUPPORTED": 0}
    for row in rows:
        counts[row[1]] += 1
    print("-" * (18 + width))
    print("MATCH %s · DIFF %s · UNSUPPORTED %s · усього %s"
          % (counts["MATCH"], counts["DIFF"], counts["UNSUPPORTED"], len(rows)))
    if counts["DIFF"]:
        print("\nРозбіжність означає, що помиляється або число еталона (воно з Odoo), або ця\n"
              "перевірка. Рішення приймає бухгалтер: docs/payroll/golden-for-accountant.md.")
    return 1 if counts["DIFF"] else 0


if __name__ == "__main__":
    sys.exit(run())
