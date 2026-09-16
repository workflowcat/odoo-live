# -*- coding: utf-8 -*-
"""Спільна форма перевірок для документів місяця: одна форма рядка на всі моделі.

Кожен документ (табель, штатний розпис, відомість на перерахування, авансова відомість,
заява-розрахунок ПФУ, військові списки) рахує свої перевірки методом `_checks()`.
Перевірка ніколи не зберігає прапорець "ок" - вона рахується щоразу з полів документа
і пов'язаних записів. Кожна перевірка, що називає записи, несе `target`: куди клікнути,
щоб побачити саме ці записи (сторінка «Період», кошик кожного документа).

Рядок перевірки: {"level": "ok"|"warn"|"error", "text": короткий український рядок,
                   "fact": число або текст-факт, "target": {...} або None}.

target - один із трьох варіантів:
  {"model": ..., "res_id": id}           - один запис
  {"model": ..., "domain": [...]}        - список записів
  {"xmlid": "module.action_xxx"}         - дія меню (коли перевірка не про конкретні записи)
"""
from odoo import api, fields, models

LEVEL_LABELS = {"ok": "OK", "warn": "УВАГА", "error": "ПОМИЛКА"}
LEVEL_ORDER = {"error": 0, "warn": 1, "ok": 2}


class UaChecksMixin(models.AbstractModel):
    _name = "ua.checks.mixin"
    _description = "Перевірки документа: спільна форма для всіх карток місяця"

    checks_text = fields.Text("Перевірки", compute="_compute_checks_text",
                              help="Порахований список перевірок документа. Клікабельна версія - на сторінці «Період».")

    # ------------------------------------------------------------------ форма рядка
    @staticmethod
    def _check(level, text, fact="", target=None):
        """Один рядок перевірки. level: ok / warn / error."""
        return {
            "level": level,
            "text": text,
            "fact": "" if fact in (None, False) else str(fact),
            "target": target or None,
        }

    def _check_ok(self, text, fact="", target=None):
        return self._check("ok", text, fact, target)

    def _check_warn(self, text, fact="", target=None):
        return self._check("warn", text, fact, target)

    def _check_error(self, text, fact="", target=None):
        return self._check("error", text, fact, target)

    # ------------------------------------------------------------------ цілі
    @staticmethod
    def _target_record(record):
        """Ціль - один конкретний запис (форма)."""
        if not record:
            return None
        return {"model": record._name, "res_id": record.id}

    @staticmethod
    def _target_records(records, model=None):
        """Ціль - кілька записів (список за id, без побудови довгого домену)."""
        if not records:
            return None
        return {"model": model or records._name, "domain": [("id", "in", records.ids)]}

    @staticmethod
    def _target_domain(model, domain):
        """Ціль - список записів за доменом (коли записів ще не порахували в python)."""
        return {"model": model, "domain": domain}

    @staticmethod
    def _target_xmlid(xmlid):
        """Ціль - дія меню, коли перевірка не про конкретні записи (напр. відсутність довідника)."""
        return {"xmlid": xmlid}

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        """Перелік перевірок документа. Перевизначає кожна модель документа.

        Порожній список = перевірки для цієї моделі не описані (базовий клас-домішка).
        """
        self.ensure_one()
        return []

    def _checks_summary(self):
        """Найгірший рівень і кількість помилок/попереджень - для позначки на сторінці «Період»."""
        self.ensure_one()
        checks = self._checks()
        errors = sum(1 for c in checks if c["level"] == "error")
        warns = sum(1 for c in checks if c["level"] == "warn")
        level = "error" if errors else ("warn" if warns else "ok")
        return {"level": level, "errors": errors, "warns": warns, "checks": checks}

    def _compute_checks_text(self):
        for rec in self:
            if not rec.id:
                rec.checks_text = ""
                continue
            try:
                checks = sorted(rec._checks(), key=lambda c: LEVEL_ORDER.get(c["level"], 9))
            except Exception:
                rec.checks_text = "Перевірки не порахувалися."
                continue
            if not checks:
                rec.checks_text = "Перевірок немає."
                continue
            lines = []
            for c in checks:
                line = "%s: %s" % (LEVEL_LABELS.get(c["level"], c["level"].upper()), c["text"])
                if c.get("fact"):
                    line += " (%s)" % c["fact"]
                lines.append(line)
            rec.checks_text = "\n".join(lines)
