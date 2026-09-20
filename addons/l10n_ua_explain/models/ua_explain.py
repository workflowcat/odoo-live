"""Диспетчер пояснення: одна точка входу "звідки взялося це число", для будь-якої моделі.

Сам нічого не рахує. Викликає `_ua_explain(res_id, field)` на моделі, яка вміє
пояснювати себе - другої, паралельної реалізації розрахунку тут за конструкцією
немає. Модель без такого методу означає, що пояснення для неї ще не написане."""

import json

from odoo import api, models
from odoo.exceptions import UserError


class UaExplain(models.AbstractModel):
    _name = "ua.explain"
    _description = "Пояснення розрахунку"

    @api.model
    def explain(self, model, res_id, field=None, when="auto"):
        """when: "auto" - заморожений слід, якщо є, інакше живий перерахунок (preview);
        "now" - завжди живий перерахунок; "frozen" - лише заморожений, інакше state "none"."""
        Model = self.env[model]
        if not hasattr(Model, "_ua_explain"):
            raise UserError(self.env._("Немає пояснення для цієї моделі."))

        trace = self.env["ua.explain.trace"]
        if when in ("auto", "frozen"):
            trace = trace.sudo().search(
                [("model_name", "=", model), ("res_id", "=", res_id)],
                order="frozen_at desc, id desc", limit=1,
            )

        if when == "frozen":
            if not trace:
                return {"state": "none"}
            return self._narrow(self._from_trace(trace), field)

        if when == "auto" and trace:
            return self._narrow(self._from_trace(trace), field)

        # when == "now", або "auto" без замороженого сліду: перерахунок наживо,
        # тим самим кодом, що рахує гроші (_ua_explain кожної моделі).
        #
        # Важливо, чому тут немає підміни. Запис, проведений до появи цього механізму,
        # замороженого сліду не має і мати не може. Ми НЕ видаємо сьогоднішній
        # перерахунок за те, що сталося тоді: відповідь чесно каже frozen = False
        # і пояснює, чому. Інакше "тоді пораховано" і "зараз" злилися б в одне.
        payload = dict(Model._ua_explain(res_id, field), state="preview", frozen=False)
        if when == "auto":
            payload["note"] = ("Заморожений слід відсутній: запис або ще не проведено, або його "
                               "провели до того, як слід почали зберігати. Показано перерахунок "
                               "за сьогоднішніми правилами і сьогоднішніми даними.")
        return self._narrow(payload, field)

    @staticmethod
    def _from_trace(trace):
        payload = json.loads(trace.payload)
        payload["state"] = "committed"
        payload["frozen"] = True
        payload["frozen_at"] = str(trace.frozen_at or "")
        payload["frozen_by"] = trace.frozen_by.name or ""
        return payload

    @staticmethod
    def _narrow(payload, field):
        """Звузити payload до кроку field і кроків, чиї результати він читає (uses_rules),
        транзитивно. Без field - повний слід як є."""
        if not field:
            return payload
        steps = payload.get("steps") or []
        by_code = {s["code"]: s for s in steps if s.get("code")}
        if field not in by_code:
            return payload
        needed = {field}
        changed = True
        while changed:
            changed = False
            for code in list(needed):
                step = by_code.get(code)
                if not step:
                    continue
                for dep in step.get("uses_rules") or []:
                    if dep not in needed:
                        needed.add(dep)
                        changed = True
        narrowed = dict(payload)
        narrowed["steps"] = [s for s in steps if s.get("code") in needed]
        return narrowed
