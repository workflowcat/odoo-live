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

ALLOWED_FUNCS = {
    "round": round, "min": min, "max": max, "abs": abs, "float": float, "int": int,
}
ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Compare, ast.Call,
    ast.Constant, ast.Name, ast.Load, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Tuple,
)


class RuleError(ValueError):
    """Вираз не можна виконати."""


def check(expression):
    """Перевірити вираз перед виконанням. Помилка каже, що саме заборонено."""
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise RuleError("заборонено: %s у «%s»" % (type(node).__name__, expression))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCS:
                raise RuleError("дозволені лише функції %s" % ", ".join(sorted(ALLOWED_FUNCS)))
    return tree


def evaluate(expression, context):
    """Порахувати вираз у контексті. Контекст - плоский словник чисел і рядків."""
    tree = check(expression)
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

    def validate(self):
        """Перевірити всі вирази набору. Повертає список помилок."""
        errors = []
        for item in self.derived + self.rules:
            for key in ("value", "when", "amount"):
                if item.get(key):
                    try:
                        check(item[key])
                    except (RuleError, SyntaxError) as error:
                        errors.append("%s.%s: %s" % (item.get("code") or item.get("name"), key, error))
        return errors
