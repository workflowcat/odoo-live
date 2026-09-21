# -*- coding: utf-8 -*-
"""Законодавчі числа з датою початку дії.

Код ніколи не зашиває ставку або межу. Він питає параметр на дату листка. Один файл
JSON тримає всі значення разом із підставою, тому зміна закону - це зміна даних.
"""
import json
from datetime import date


class ParamError(KeyError):
    """Немає параметра на потрібну дату."""


class Params:
    def __init__(self, rows):
        # rows: [{"key":..., "valid_from":"YYYY-MM-DD", "value":..., "name":..., "source":...}]
        self.rows = sorted(rows, key=lambda r: (r["key"], r["valid_from"]))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as stream:
            return cls(json.load(stream))

    @staticmethod
    def _to_date(value):
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def get(self, key, on_date):
        on_date = self._to_date(on_date)
        best = None
        for row in self.rows:
            if row["key"] != key:
                continue
            if self._to_date(row["valid_from"]) <= on_date:
                best = row
        if best is None:
            raise ParamError("немає параметра «%s» на %s" % (key, on_date))
        return float(best["value"])

    def all(self, on_date):
        keys = {row["key"] for row in self.rows}
        return {key: self.get(key, on_date) for key in keys}

    def source(self, key):
        for row in reversed(self.rows):
            if row["key"] == key:
                return row.get("source", "")
        return ""
