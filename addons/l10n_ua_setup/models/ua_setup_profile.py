# -*- coding: utf-8 -*-
"""Анкета компанії: що відомо, що запропоновано, що підтверджено, чого бракує.

Один запис на компанію. Він показує стан підготовки до першого розрахунку і не дає
перейти до реальної роботи, поки лишається обов'язкове питання без відповіді.

Стани відповіді:
    бракує        - питання відкрите;
    надано        - значення взяте з документа або з наявних даних системи;
    запропоновано - значення підставила система за описом компанії; потребує підтвердження;
    підтверджено  - бухгалтер погодив значення.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATES = [("draft", "Чернетка"), ("ready", "Готово до перевірки"), ("active", "Затверджено")]
ANSWER_STATES = [("missing", "Бракує"), ("supplied", "Надано"),
                 ("proposed", "Запропоновано"), ("confirmed", "Підтверджено")]


class UaSetupProfile(models.Model):
    _name = "ua.setup.profile"
    _inherit = ["mail.thread"]
    _description = "Анкета компанії"
    _order = "id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True,
                                 default=lambda s: s.env.company)
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True)
    description = fields.Text("Опис компанії своїми словами",
                              help="Наприклад: українське ТОВ, меблі, 20 працівників, "
                                   "більшість на окладі, двоє на пів ставки.")
    answer_ids = fields.One2many("ua.setup.answer", "profile_id", "Відповіді")
    total_count = fields.Integer("Питань", compute="_compute_progress")
    missing_count = fields.Integer("Бракує", compute="_compute_progress")
    required_missing = fields.Integer("Бракує обов'язкових", compute="_compute_progress")
    confirmed_count = fields.Integer("Підтверджено", compute="_compute_progress")
    proposed_count = fields.Integer("Запропоновано", compute="_compute_progress")
    note = fields.Text("Примітка")

    @api.depends("company_id")
    def _compute_name(self):
        for profile in self:
            profile.name = _("Анкета: %s") % (profile.company_id.name or "")

    @api.depends("answer_ids.state", "answer_ids.question_id")
    def _compute_progress(self):
        for profile in self:
            answers = profile.answer_ids
            profile.total_count = len(answers)
            profile.missing_count = len(answers.filtered(lambda a: a.state == "missing"))
            profile.required_missing = len(answers.filtered(
                lambda a: a.state == "missing" and a.question_id.required))
            profile.confirmed_count = len(answers.filtered(lambda a: a.state == "confirmed"))
            profile.proposed_count = len(answers.filtered(lambda a: a.state == "proposed"))

    # ------------------------------------------------------------------ дії
    def action_fill(self):
        """Створити рядки на всі питання каталогу і підставити те, що вже відоме системі."""
        Question = self.env["ua.setup.question"]
        for profile in self:
            have = profile.answer_ids.mapped("question_id")
            for question in Question.search([]) - have:
                profile.env["ua.setup.answer"].create({
                    "profile_id": profile.id, "question_id": question.id})
            profile._pull_known()
        return True

    def _pull_known(self):
        """Те, що вже є в системі, стає відповіддю зі станом «надано»."""
        self.ensure_one()
        company = self.company_id
        known = {
            "Яка назва компанії?": company.name,
            "Який ЄДРПОУ компанії?": company.company_registry,
            "Яка юридична адреса компанії?": ", ".join(
                part for part in (company.street, company.city, company.zip) if part),
            "Хто директор / підписант компанії?": company.ua_director_name,
            "Хто веде бухгалтерію (ПІБ) і в якому форматі?": company.ua_accountant_name,
        }
        for answer in self.answer_ids:
            value = known.get(answer.question_id.name)
            if value and not answer.value:
                answer.write({"value": value, "state": "supplied", "source": "system"})

    # Підказки з опису компанії. Це пошук за словами, а не модель: він дає перше
    # наближення, яке бухгалтер підтверджує. Модель згодом стане на це саме місце,
    # бо запис відповіді один і той самий.
    PROPOSALS = [
        ("Яка організаційно-правова форма компанії?", (("тов", "ТОВ"), ("фоп", "ФОП"))),
        ("Який поточний стан компанії?", ((" з нуля", "Нова (з нуля)"), ("нова", "Нова (з нуля)"),
                                          ("діюч", "Діюча, є історія обліку"),
                                          ("є історія", "Діюча, є історія обліку"))),
        ("Які форми залучення використовуєте або плануєте використовувати? (позначте все, що є)",
         (("оклад", "Штат (трудовий договір)"), ("штат", "Штат (трудовий договір)"),
          ("цпх", "ЦПХ (цивільно-правовий)"), ("фоп", "ФОП (аутстаф)"),
          ("гіг", "Гіг-контракт (Дія.City)"))),
        ("Чи ведеться індексація зарплати?", (("індексац", "Так"),)),
        ("Як плануєте організувати зарплатний проєкт для працівників?",
         (("один банк", "Через один банк для всіх працівників"),
          ("кілька банк", "Через кілька банків залежно від того, де в працівників картки"))),
        ("У якій валюті відбуваються розрахунки?", (("гривн", "UAH"), ("uah", "UAH"),
                                                    ("usd", "USD"), ("eur", "EUR"))),
        ("Чи є сумісники?", (("сумісник", "Так"),)),
        ("Чи не плануєте оклади не нижче мінімалки (8 647 грн у 2026)?",
         (("пів ставки", "Є нижчі (неповна ставка)"), ("неповн", "Є нижчі (неповна ставка)"))),
    ]

    def action_propose(self):
        """Підставити перше наближення з опису компанії. Усе - зі станом «запропоновано»."""
        for profile in self:
            text = (profile.description or "").lower()
            if not text:
                raise UserError(_("Спершу опишіть компанію своїми словами."))
            filled = 0
            for question_name, rules in self.PROPOSALS:
                answer = profile.answer_ids.filtered(lambda a: a.question_id.name == question_name)
                if not answer or answer.state in ("confirmed", "supplied"):
                    continue
                values = [value for word, value in rules if word in text]
                if not values:
                    continue
                answer.write({"value": ", ".join(dict.fromkeys(values)), "state": "proposed",
                              "source": "description"})
                filled += 1
            number = profile._people_from_text(text)
            if number:
                answer = profile.answer_ids.filtered(
                    lambda a: a.question_id.name == "Скільки людей залучено зараз?")
                if answer and answer.state not in ("confirmed", "supplied"):
                    answer.write({"value": number, "state": "proposed", "source": "description"})
                    filled += 1
            profile.message_post(body=_("Запропоновано відповідей: %s") % filled)
        return True

    @staticmethod
    def _people_from_text(text):
        """Скільки людей у компанії: перше число поруч зі словом «працівник» або «людей»."""
        import re
        match = re.search(r"(\d+)\s*(?:працівник|людей|осіб|співробітник)", text)
        if not match:
            return ""
        count = int(match.group(1))
        for limit, label in ((5, "1-5"), (15, "6-15"), (50, "16-50")):
            if count <= limit:
                return label
        return "50+"

    def action_activate(self):
        """Дозволити реальний розрахунок. Обов'язкові питання мають бути закриті."""
        for profile in self:
            if profile.required_missing:
                raise UserError(_("Лишилось обов'язкових питань без відповіді: %s.")
                                % profile.required_missing)
            profile.state = "active"
        return True

    def action_ready(self):
        self.write({"state": "ready"})
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_test_month(self):
        """Пробний місяць: система готує табель і чернетки листків за поточний місяць."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        result = self.env["ua.period.board"].with_company(self.company_id).action_prepare_month(
            today.year, today.month)
        self.message_post(body=_("Пробний місяць: %s") % result.get("message", ""))
        return result

    @api.model
    def profile_for(self, company=None):
        company = company or self.env.company
        profile = self.search([("company_id", "=", company.id)], limit=1)
        if not profile:
            profile = self.create({"company_id": company.id})
            profile.action_fill()
        return profile

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

    # ------------------------------------------------------------------ застосування
    # Як відповідь перетворюється на налаштування. Ключ - поле компанії, значення -
    # функція, яка читає текст відповіді. Пропозиції не застосовуються: тільки
    # підтверджені відповіді і те, що система знала сама.
    @staticmethod
    def _yes(value):
        text = (value or "").strip().lower()
        return text.startswith("так") or text.startswith("вже") or text.startswith("є")

    def _setting_value(self, field, value):
        text = (value or "").strip()
        if field == "ua_tax_system":
            low = text.lower()
            if "5" in low and "пдв" in low:
                return "ep3_5"
            if "3" in low and "пдв" in low:
                return "ep3_3"
            if "загальн" in low:
                return "general"
            return "undecided"
        if field == "ua_vat_payer":
            return not text.lower().startswith("ні")
        if field == "ua_index_default_off":
            return text.lower().startswith("ні")
        if field == "ua_below_min_wage":
            return "нижч" in text.lower()
        if field == "ua_has_disabled":
            return not text.lower().startswith("ні")
        if field == "ua_booking_planned":
            return not text.lower().startswith("ні") and "не вирішили" not in text.lower()
        if field == "ua_opening_balances":
            return text.lower().startswith("є")
        if field == "ua_payroll_bank_mode":
            low = text.lower()
            if "один банк" in low:
                return "one"
            if "кілька" in low:
                return "many"
            return False
        return text

    def preview_apply(self):
        """Що саме зміниться в налаштуваннях. Показуємо до запису."""
        self.ensure_one()
        rows = []
        for answer in self.answer_ids.filtered(lambda a: a.question_id.is_setting):
            target = answer.question_id.target or ""
            if not target.startswith("company.") or answer.state not in ("confirmed", "supplied"):
                continue
            field = target.split(".", 1)[1]
            if field not in self.company_id._fields:
                continue
            new = self._setting_value(field, answer.value)
            old = self.company_id[field]
            if new in (False, "", None) or new == old:
                continue
            rows.append({"field": field,
                         "label": self.company_id._fields[field].string,
                         "question": answer.question_id.name,
                         "old": str(old) if old not in (False, None) else "—",
                         "new": str(new)})
        return rows

    def action_apply(self):
        """Записати підтверджені відповіді в налаштування компанії."""
        for profile in self:
            rows = profile.preview_apply()
            if not rows:
                raise UserError(_("Немає що застосовувати: підтверджені відповіді вже в налаштуваннях."))
            values = {}
            for row in rows:
                values[row["field"]] = profile._setting_value(row["field"], next(
                    a.value for a in profile.answer_ids
                    if a.question_id.target == "company." + row["field"]))
            profile.company_id.sudo().write(values)
            profile.message_post(body=_("Застосовано налаштувань: %s (%s)") % (
                len(rows), ", ".join(row["label"] for row in rows)))
        return True

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


class UaSetupAnswer(models.Model):
    _name = "ua.setup.answer"
    _description = "Відповідь анкети"
    _order = "sequence, id"

    profile_id = fields.Many2one("ua.setup.profile", "Анкета", required=True, ondelete="cascade")
    question_id = fields.Many2one("ua.setup.question", "Питання", required=True, ondelete="restrict")
    sequence = fields.Integer(related="question_id.sequence", store=True)
    section = fields.Char(related="question_id.section", store=True)
    name = fields.Char(related="question_id.name", string="Питання", store=True)
    options = fields.Char(related="question_id.options", string="Варіанти")
    hint = fields.Char(related="question_id.hint")
    required = fields.Boolean(related="question_id.required", store=True)
    value = fields.Char("Відповідь")
    state = fields.Selection(ANSWER_STATES, "Стан", default="missing", required=True, index=True)
    source = fields.Selection([("system", "дані системи"), ("document", "документ"),
                               ("description", "опис компанії"), ("accountant", "бухгалтер")],
                              "Джерело")
    note = fields.Char("Примітка")

    _profile_question_uniq = models.Constraint("unique(profile_id, question_id)",
                                               "Питання вже є в анкеті.")

    @api.onchange("value")
    def _onchange_value(self):
        for answer in self:
            if answer.value and answer.state == "missing":
                answer.state = "confirmed"
                answer.source = "accountant"

    def action_confirm(self):
        for answer in self:
            if not (answer.value or "").strip():
                raise UserError(_("Спершу впишіть відповідь."))
            answer.write({"state": "confirmed"})
        return True

    def action_reset(self):
        self.write({"state": "missing", "value": False, "source": False})
        return True
