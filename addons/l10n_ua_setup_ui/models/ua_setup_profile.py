# -*- coding: utf-8 -*-
"""Дані і дії екрана «Анкета компанії»: розширення ua.setup.profile.

Сама анкета - питання, відповіді, заповнення з каталогу, пропозиції з опису,
пробний місяць і запис у налаштування компанії - лишилась у l10n_ua_setup і
працює без цього модуля: її дії кличуть і з форми, і з перевірок.

Тут лише поверхня екрана: словник екрана (screen), короткий підсумок для
«Домівки» (get_screen_data), заголовок дня (_headline), розбір варіантів
відповіді (_options_list) і три входи, які екран має: записати відповідь,
записати опис компанії, виконати названу дію (run). Прав вони собі не додають -
кожен пише через звичайний ORM, тож ua.setup.profile / ua.setup.answer міняє
лише той, кому це дозволяє ir.model.access.csv модуля логіки.
"""
from odoo import _, api, models
from odoo.exceptions import UserError


class UaSetupProfile(models.Model):
    _inherit = "ua.setup.profile"

    @api.model
    def get_screen_data(self):
        """Коротко для робочого місця: скільки закрито і що заважає почати."""
        profile = self.profile_for()
        return {
            "id": profile.id, "state": profile.state,
            "total": profile.total_count, "missing": profile.missing_count,
            "required_missing": profile.required_missing,
            "confirmed": profile.confirmed_count, "proposed": profile.proposed_count,
        }

    # ------------------------------------------------------------------ екран анкети
    @staticmethod
    def _options_list(options):
        """Варіанти з анкети: прибираємо порожні місця для вписування."""
        out = []
        for part in (options or "").split("|"):
            text = part.strip().strip("_").strip()
            text = text.replace("→", "").strip()
            if not text or text.endswith(":"):
                continue
            out.append(text)
        return out

    @api.model
    def screen(self):
        """Усі дані екрана анкети: лічильники і питання за розділами."""
        profile = self.profile_for()
        sections, index = [], {}
        for answer in profile.answer_ids.sorted(lambda a: (a.question_id.sequence, a.id)):
            question = answer.question_id
            block = index.get(question.section)
            if not block:
                block = {"name": question.section, "questions": [], "done": 0, "total": 0,
                         "required_missing": 0}
                index[question.section] = block
                sections.append(block)
            block["total"] += 1
            if answer.state != "missing":
                block["done"] += 1
            if answer.state == "missing" and question.required:
                block["required_missing"] += 1
            block["questions"].append({
                "id": answer.id,
                "name": question.name,
                "hint": question.hint or "",
                "required": question.required,
                "kind": question.kind,
                "options": self._options_list(question.options),
                "value": answer.value or "",
                "state": answer.state,
                "source": dict(answer._fields["source"].selection).get(answer.source, ""),
                "is_setting": question.is_setting,
                "target": question.target or "",
            })
        counters = {
            "total": profile.total_count, "missing": profile.missing_count,
            "required_missing": profile.required_missing, "proposed": profile.proposed_count,
            "confirmed": profile.confirmed_count,
            "supplied": len(profile.answer_ids.filtered(lambda a: a.state == "supplied")),
        }
        counters["done"] = counters["total"] - counters["missing"]
        counters["percent"] = round(100.0 * counters["done"] / counters["total"]) if counters["total"] else 0
        return {
            "id": profile.id,
            "company": profile.company_id.name,
            "state": profile.state,
            "description": profile.description or "",
            "counters": counters,
            "sections": sections,
            "headline": profile._headline(counters),
            "apply": profile.preview_apply(),
        }

    def _headline(self, counters):
        """Одна головна дія екрана анкети."""
        self.ensure_one()
        if self.state == "active":
            return {"title": "Анкета активна", "detail": "компанія готова до розрахунку",
                    "action": "", "label": "", "tone": "ok"}
        if not self.description:
            return {"title": "Опишіть компанію своїми словами",
                    "detail": "система підставить перше наближення",
                    "action": "propose", "label": "Підказати з опису", "tone": "todo"}
        if counters["required_missing"]:
            return {"title": "Обов'язкові питання відкриті",
                    "detail": "%s без відповіді" % counters["required_missing"],
                    "action": "", "label": "", "tone": "warn"}
        if counters["proposed"]:
            return {"title": "Є що підтвердити",
                    "detail": "%s запропонованих відповідей" % counters["proposed"],
                    "action": "", "label": "", "tone": "warn"}
        return {"title": "Обов'язкові питання закриті", "detail": "можна активувати",
                "action": "activate", "label": "Затвердити", "tone": "ok"}

    @api.model
    def set_answer(self, answer_id, value, state="confirmed"):
        """Записати відповідь з екрана. Порожнє значення повертає питання у «бракує»."""
        answer = self.env["ua.setup.answer"].browse(int(answer_id))
        value = (value or "").strip()
        if not value:
            answer.write({"value": False, "state": "missing", "source": False})
        else:
            answer.write({"value": value, "state": state, "source": "accountant"})
        return self.screen()

    @api.model
    def set_description(self, text):
        profile = self.profile_for()
        profile.description = text or ""
        return self.screen()

    @api.model
    def run(self, action):
        """Дії екрана: заповнити, підказати, пробний місяць, активувати."""
        profile = self.profile_for()
        if action == "fill":
            profile.action_fill()
            return {"message": _("Анкету заповнено з каталогу."), "data": self.screen()}
        if action == "propose":
            profile.action_propose()
            return {"message": _("Пропозиції з опису готові. Перевірте жовті рядки."),
                    "data": self.screen()}
        if action == "test":
            result = profile.action_test_month()
            return {"message": result.get("message", ""), "data": self.screen()}
        if action == "apply":
            rows = profile.preview_apply()
            profile.action_apply()
            return {"message": _("Записано в налаштування: %s") % ", ".join(r["label"] for r in rows),
                    "data": self.screen()}
        if action == "activate":
            profile.action_activate()
            return {"message": _("Анкета активна."), "data": self.screen()}
        raise UserError(_("Невідома дія."))
