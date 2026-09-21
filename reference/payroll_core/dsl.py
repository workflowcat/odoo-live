# -*- coding: utf-8 -*-
"""Правила як дані: вираз замість коду.

Правило описується рядком-виразом. Вираз рахує безпечний обчислювач: дозволені числа,
імена з контексту, арифметика, порівняння, `and/or/not`, умовний вираз і кілька функцій.
Виклик будь-чого іншого, доступ до атрибутів, імпорт і присвоєння заборонені.

Навіщо: набір правил стає даними. Його можна читати, показувати бухгалтеру, зберігати
версіями з датою дії, давати моделі на пропозицію зміни і перевіряти еталонними
сценаріями перед увімкненням. Оболонка при цьому не має значення.
"""
import ast
import json

def _round_money(value, digits=2):
    """Округлення грошей у виразах: ROUND_HALF_UP, а не банківське."""
    from .calc import _r2
    return _r2(value, digits)


ALLOWED_FUNCS = {
    "round": _round_money, "min": min, "max": max, "abs": abs, "float": float, "int": int,
}
ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Compare, ast.Call,
    ast.Constant, ast.Name, ast.Load, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Tuple,
)


class RuleError(ValueError):
    """Вираз не можна виконати."""


def check(expression, extra_funcs=()):
    """Перевірити вираз перед виконанням. Помилка каже, що саме заборонено.

    `extra_funcs` - імена алгоритмів, які дає рушій (наприклад помісячний ЄСВ)."""
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise RuleError("заборонено: %s у «%s»" % (type(node).__name__, expression))
        if isinstance(node, ast.Call):
            allowed = set(ALLOWED_FUNCS) | set(extra_funcs)
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed:
                raise RuleError("дозволені лише функції %s" % ", ".join(sorted(allowed)))
    return tree


def evaluate(expression, context, extra_funcs=()):
    """Порахувати вираз у контексті. Контекст - плоский словник чисел і рядків."""
    tree = check(expression, extra_funcs)
    names = dict(ALLOWED_FUNCS)
    names.update(context)
    return eval(compile(tree, "<rule>", "eval"), {"__builtins__": {}}, names)   # noqa: S307 - вираз перевірено вище


class RuleSet:
    """Набір правил: похідні значення і самі правила в порядку номерів."""

    def __init__(self, data):
        self.name = data.get("name", "")
        self.valid_from = data.get("valid_from", "")
        self.derived = data.get("derived", [])
        self.rules = sorted(data["rules"], key=lambda r: r["sequence"])

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))

    def validate(self, extra_funcs=()):
        """Перевірити всі вирази набору. Повертає список помилок."""
        errors = []
        for item in self.derived + self.rules:
            for key in ("value", "when", "amount"):
                if item.get(key):
                    try:
                        check(item[key], extra_funcs)
                    except (RuleError, SyntaxError) as error:
                        errors.append("%s.%s: %s" % (item.get("code") or item.get("name"), key, error))
        return errors
