# -*- coding: utf-8 -*-
"""Відповіді на пункти перевірки ВТК по наряду - для кіоску цеху.

Що вміє нативний CE 19. Наряд (`mrp.workorder`) пишеться нативно:
`button_start()` запускає таймер і ставить стан «В роботі», `button_pending()`
ставить на паузу, `button_finish()` закриває наряд і позначає взятими
комплектуючі цієї операції. Нічого свого для цього не треба.

Чого нема. Контрольні точки якості з відповідями «так / ні» - це Enterprise
(`quality_control`). У нас пункти перевірки лежать текстом на операції маршруту
(`mrp.routing.workcenter.ua_checks`, по пункту в рядок), тож відповідь теж тонка:
один запис на пункт наряду - номер пункту, текст на момент відповіді, «так / ні»,
примітка, хто і коли.

Номер пункту - порядок рядка в `ua_checks`, з одиниці, як `pos` у складальній
карті. Текст пункту в записі - знімок: якщо технолог переписав перевірку після
відповіді, у відповіді лишається те, на що відповідали.

Закриття наряду відповіді не блокують: `button_finish()` лишається нативним.
Кіоск бачить невідповідані і «ні» у `ua_check_rows()` і сам вирішує, чи пускати
людину далі; жорстке правило - окреме рішення, і тоді воно ляже сюди.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

RESULTS = [("ok", "Так"), ("fail", "Ні")]


class UaWorkorderCheck(models.Model):
    _name = "ua.workorder.check"
    _description = "Відповідь на пункт перевірки наряду"
    _order = "workorder_id, sequence"

    workorder_id = fields.Many2one(
        "mrp.workorder", string="Наряд", required=True, ondelete="cascade", index=True)
    production_id = fields.Many2one(
        related="workorder_id.production_id", store=True, string="Замовлення")
    company_id = fields.Many2one(
        related="workorder_id.production_id.company_id", store=True, string="Компанія")
    sequence = fields.Integer("Пункт", required=True, help="Номер пункту з одиниці.")
    name = fields.Char("Пункт перевірки", required=True)
    result = fields.Selection(RESULTS, string="Відповідь", required=True)
    note = fields.Char("Примітка")
    user_id = fields.Many2one(
        "res.users", string="Хто відповів", default=lambda self: self.env.user)
    date = fields.Datetime("Коли", default=fields.Datetime.now)

    _ua_one_answer = models.Constraint(
        "UNIQUE(workorder_id, sequence)",
        "На пункт перевірки наряду вже є відповідь - її оновлюють, а не додають.",
    )


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    ua_check_ids = fields.One2many(
        "ua.workorder.check", "workorder_id", string="Відповіді на перевірку")

    def _ua_check_items(self):
        """Пункти перевірки операції цього наряду, по рядку."""
        self.ensure_one()
        text = self.operation_id.ua_checks or ""
        return [line.strip() for line in text.splitlines() if line.strip()]

    def ua_check_rows(self):
        """Пункти перевірки наряду з відповідями.

        Повертає [{index, text, result, note, user, date}]: index з одиниці, result
        `ok` | `fail` | False (ще не відповідали), user - [id, імʼя] або False.
        Відповідь на пункт, якого в операції вже немає, теж іде в перелік - з тим
        текстом, на який відповідали.
        """
        self.ensure_one()
        answers = {check.sequence: check for check in self.ua_check_ids}
        items = self._ua_check_items()
        rows = []
        for index in sorted(set(range(1, len(items) + 1)) | set(answers)):
            answer = answers.get(index)
            rows.append({
                "index": index,
                "text": answer.name if answer else items[index - 1],
                "result": answer.result if answer else False,
                "note": (answer.note or "") if answer else "",
                "user": [answer.user_id.id, answer.user_id.name]
                        if answer and answer.user_id else False,
                "date": fields.Datetime.to_string(answer.date)
                        if answer and answer.date else False,
            })
        return rows

    def ua_answer_check(self, index, result, note=None):
        """Записати відповідь на пункт перевірки. Повторна відповідь оновлює першу.

        index - номер пункту з одиниці; result - `ok` або `fail`. Закритий або
        скасований наряд відповідей не приймає. Повертає `ua_check_rows()`.
        """
        self.ensure_one()
        if self.state in ("done", "cancel"):
            raise UserError("Наряд %s уже закрито - відповіді на перевірку не приймаються."
                            % self.display_name)
        if result not in dict(RESULTS):
            raise UserError("Відповідь на перевірку - «ok» або «fail», а прийшло «%s»." % result)
        items = self._ua_check_items()
        index = int(index)
        if not 1 <= index <= len(items):
            raise UserError("В операції «%s» пунктів перевірки %d, пункту %d немає."
                            % (self.operation_id.name or self.name, len(items), index))
        values = {"result": result, "note": note or False, "name": items[index - 1],
                  "user_id": self.env.user.id, "date": fields.Datetime.now()}
        answer = self.ua_check_ids.filtered(lambda check: check.sequence == index)
        if answer:
            answer.write(values)
        else:
            self.env["ua.workorder.check"].create(
                dict(values, workorder_id=self.id, sequence=index))
        return self.ua_check_rows()


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_client_ref = fields.Char(
        "Мітка операції", index=True, copy=False,
        help="Мітка зовнішнього клієнта. Не повторюється в межах компанії: повторне "
             "створення з тією самою міткою віддає те саме замовлення.")

    _ua_client_ref_unique = models.Constraint(
        "UNIQUE(company_id, ua_client_ref)",
        "Замовлення на виробництво з такою міткою операції в цій компанії вже є.",
    )

    @api.model
    def ua_get_or_create(self, client_ref, vals=None):
        """Замовлення за міткою клієнта: є - віддаємо, немає - створюємо.

        Той самий захист від подвійного запису, що на `stock.picking` і
        `ua.stock.inventory`: другий виклик із тією самою міткою повертає перше
        замовлення і не чіпає його вміст.
        """
        if not client_ref:
            raise UserError("Без мітки операції замовлення не створюється.")
        values = dict(vals or {})
        company_id = values.get("company_id") or self.env.company.id
        existing = self.search([("ua_client_ref", "=", client_ref),
                                ("company_id", "=", company_id)], limit=1)
        if existing:
            return existing
        values.update(ua_client_ref=client_ref, company_id=company_id)
        return self.create(values)
