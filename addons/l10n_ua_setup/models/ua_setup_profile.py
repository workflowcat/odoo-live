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

STATES = [("draft", "Заповнення"), ("ready", "Готово до перевірки"), ("active", "Працює")]
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
