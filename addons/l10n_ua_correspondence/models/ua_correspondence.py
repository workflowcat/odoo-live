"""Реєстрація вхідної та вихідної кореспонденції.

Документ реєструють одразу: номер дає послідовність свого напрямку з початку року
(«Вх/2026/0001», «Вих/2026/0001»). Документи з грифом «Для службового користування» мають
окрему нумерацію з позначкою «-ДСК» і видні лише працівникам з допуском (група
«Кореспонденція з допуском до ДСК»): так вимагає Типова інструкція про службову інформацію
(постанова КМУ від 2016-10-19 № 736) для тих, хто отримує ДСК від замовника.

Контроль виконання: вхідний документ має виконавця і строк. Виконавцю ставиться завдання з
цим строком; після строку документ «прострочений». Якщо потрібна відповідь, вхідний закриває
вихідний лист, зареєстрований у відповідь (`reply_to_id`).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

DIRECTIONS = [("in", "Вхідний"), ("out", "Вихідний")]
KINDS = [
    ("letter", "Лист"),
    ("request", "Запит"),
    ("order", "Наказ, розпорядження"),
    ("claim", "Претензія"),
    ("act", "Акт, протокол"),
    ("contract", "Договірний документ"),
    ("other", "Інше"),
]
CHANNELS = [
    ("post", "Пошта"),
    ("email", "Електронна пошта"),
    ("edo", "Електронний документообіг"),
    ("courier", "Нарочно, кур'єр"),
    ("other", "Інше"),
]
STATES = [
    ("registered", "Зареєстровано"),
    ("in_work", "На виконанні"),
    ("done", "Виконано"),
    ("cancel", "Скасовано"),
]
OPEN_STATES = ("registered", "in_work")
RESTRICTED_GROUP = "l10n_ua_correspondence.group_ua_correspondence_restricted"
TODO = "mail.mail_activity_data_todo"


class UaCorrespondence(models.Model):
    _name = "ua.correspondence"
    _description = "Кореспонденція"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Реєстраційний номер", readonly=True, copy=False, default="/",
                       index=True)
    direction = fields.Selection(DIRECTIONS, "Напрямок", required=True, default="in",
                                 readonly=True, index=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    date = fields.Date("Дата реєстрації", required=True, default=fields.Date.context_today,
                       index=True)
    partner_id = fields.Many2one("res.partner", "Кореспондент", required=True, tracking=True,
                                 check_company=True,
                                 help="Від кого надійшов вхідний або кому надіслано вихідний.")
    partner_ref = fields.Char("Їхній номер", help="Номер документа в кореспондента.")
    partner_date = fields.Date("Їхня дата")
    kind = fields.Selection(KINDS, "Вид документа", required=True, default="letter")
    channel = fields.Selection(CHANNELS, "Як надійшов / надіслано", default="post")
    subject = fields.Char("Короткий зміст", required=True, tracking=True)
    resolution = fields.Text("Резолюція", tracking=True)
    pages = fields.Integer("Аркушів")
    restricted = fields.Boolean(
        "ДСК", readonly=True, copy=False, index=True,
        help="Гриф «Для службового користування»: окрема нумерація з позначкою ДСК, документ "
             "видно лише працівникам з допуском. Ставиться під час реєстрації і не змінюється.")
    user_id = fields.Many2one("res.users", "Зареєстрував", readonly=True, copy=False,
                              default=lambda self: self.env.user)
    signer_id = fields.Many2one("res.users", "Підписав",
                                help="Для вихідного: хто підписав документ.")
    responsible_id = fields.Many2one("res.users", "Виконавець", tracking=True,
                                     domain="[('share', '=', False)]")
    date_due = fields.Date("Строк виконання", tracking=True, index=True)
    date_done = fields.Date("Виконано", readonly=True, copy=False)
    needs_reply = fields.Boolean("Потрібна відповідь")
    state = fields.Selection(STATES, "Стан", default="registered", required=True,
                             tracking=True, copy=False, index=True)
    reply_to_id = fields.Many2one("ua.correspondence", "У відповідь на", index=True,
                                  check_company=True, domain="[('direction', '=', 'in')]")
    reply_ids = fields.One2many("ua.correspondence", "reply_to_id", "Відповіді", readonly=True)
    is_overdue = fields.Boolean("Прострочено", compute="_compute_is_overdue",
                                search="_search_is_overdue")

    # --------------------------------------------------------------- обчислення
    @api.depends("state", "date_due")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for doc in self:
            doc.is_overdue = bool(doc.state in OPEN_STATES and doc.date_due
                                  and doc.date_due < today)

    def _search_is_overdue(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Пошук за простроченням: лише «так» або «ні»."))
        domain = [("state", "in", OPEN_STATES), ("date_due", "!=", False),
                  ("date_due", "<", fields.Date.context_today(self))]
        if (operator == "=") == value:
            return domain
        return ["!", "&", "&"] + domain

    @api.constrains("reply_to_id", "direction")
    def _check_reply(self):
        for doc in self:
            if doc.reply_to_id and (doc.direction != "out" or doc.reply_to_id.direction != "in"):
                raise ValidationError(_("Відповіддю буває вихідний документ на вхідний."))
            if doc.reply_to_id.restricted and not doc.restricted:
                raise ValidationError(_("Відповідь на документ ДСК теж має гриф ДСК."))

    @api.constrains("restricted", "responsible_id")
    def _check_restricted_responsible(self):
        for doc in self:
            if doc.restricted and doc.responsible_id and not doc.responsible_id.has_group(
                    RESTRICTED_GROUP):
                raise ValidationError(_("Виконавець документа ДСК має мати допуск до ДСК."))

    # --------------------------------------------------------------- запис
    def _may_restrict(self):
        return self.env.su or self.env.user.has_group(RESTRICTED_GROUP)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("restricted") and not self._may_restrict():
                raise AccessError(_("Реєструвати документи ДСК можуть лише працівники з "
                                    "допуском."))
            if vals.get("reply_to_id"):
                vals.setdefault("direction", "out")
            if vals.get("name", "/") == "/":
                code = "ua.correspondence.%s%s" % (
                    vals.get("direction") or "in", ".dsk" if vals.get("restricted") else "")
                date = vals.get("date") or fields.Date.context_today(self)
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    code, sequence_date=fields.Date.to_date(date)) or "/"
        docs = super().create(vals_list)
        for doc in docs:
            doc._schedule_control()
            answered = doc.reply_to_id.filtered(lambda d: d.state in OPEN_STATES)
            if answered:
                answered._finish(_("Відповідь: %s") % doc.name)
        return docs

    def write(self, vals):
        if "restricted" in vals and any(doc.restricted != bool(vals["restricted"]) for doc in self):
            raise UserError(_("Гриф ДСК ставиться під час реєстрації: від нього залежить номер. "
                              "Скасуйте документ і зареєструйте його знову."))
        if "direction" in vals and any(doc.direction != vals["direction"] for doc in self):
            raise UserError(_("Напрямок зареєстрованого документа не змінюється."))
        result = super().write(vals)
        if {"responsible_id", "date_due"} & set(vals):
            for doc in self.filtered(lambda d: d.state in OPEN_STATES):
                doc._schedule_control()
        return result

    def unlink(self):
        if any(doc.state != "cancel" for doc in self):
            raise UserError(_("Зареєстрований документ не видаляють - його скасовують: "
                              "номер у журналі має лишитися."))
        return super().unlink()

    def _schedule_control(self):
        """Завдання виконавцю на строк виконання; одне на документ."""
        self.ensure_one()
        if self.direction != "in" or not self.responsible_id or not self.date_due \
                or self.state not in OPEN_STATES:
            return
        todo = self.env.ref(TODO)
        activity = self.activity_ids.filtered(lambda a: a.activity_type_id == todo)
        if activity:
            activity.write({"user_id": self.responsible_id.id, "date_deadline": self.date_due})
        else:
            self.activity_schedule(TODO, date_deadline=self.date_due,
                                   user_id=self.responsible_id.id,
                                   summary=_("Виконати: %s") % self.name)

    def _finish(self, note=False):
        today = fields.Date.context_today(self)
        for doc in self:
            doc.write({"state": "done", "date_done": today})
            doc.activity_feedback([TODO], feedback=note or False)
            if note:
                doc.message_post(body=note)

    # --------------------------------------------------------------- дії
    def action_start(self):
        for doc in self:
            if doc.state != "registered":
                raise UserError(_("На виконання передають зареєстрований документ."))
            doc.state = "in_work"
        return True

    def action_done(self):
        for doc in self:
            if doc.state not in OPEN_STATES:
                raise UserError(_("Документ %s уже закрито.") % doc.name)
            if doc.direction == "in" and doc.needs_reply and not doc.reply_ids.filtered(
                    lambda r: r.state != "cancel"):
                raise UserError(_("Документ %s потребує відповіді: зареєструйте вихідний у "
                                  "відповідь або зніміть позначку.") % doc.name)
        self._finish()
        return True

    def action_cancel(self):
        for doc in self:
            if doc.state == "done":
                raise UserError(_("Виконаний документ не скасовують."))
        self.write({"state": "cancel"})
        self.activity_unlink([TODO])
        return True

    def action_reopen(self):
        for doc in self:
            if doc.state not in ("cancel", "done"):
                raise UserError(_("Відновлюють скасований або виконаний документ."))
        self.write({"state": "registered", "date_done": False})
        for doc in self:
            doc._schedule_control()
        return True

    def _reply_values(self):
        self.ensure_one()
        if self.direction != "in":
            raise UserError(_("Відповідають на вхідний документ."))
        ref = self.partner_ref and _("№ %s") % self.partner_ref or self.name
        return {
            "direction": "out",
            "reply_to_id": self.id,
            "partner_id": self.partner_id.id,
            "kind": "letter",
            "channel": self.channel,
            "restricted": self.restricted,
            "company_id": self.company_id.id,
            "subject": _("Відповідь на %s: %s") % (ref, self.subject),
        }

    def action_reply(self):
        """Форма нового вихідного у відповідь на цей документ."""
        context = {"default_%s" % key: value for key, value in self._reply_values().items()}
        return {"type": "ir.actions.act_window", "res_model": "ua.correspondence",
                "view_mode": "form", "target": "current", "context": context}

    def action_print_register(self):
        return self.env.ref("l10n_ua_correspondence.action_report_ua_correspondence_register") \
            .report_action(self.sorted(lambda d: (d.direction, d.date, d.id)))

    @api.model
    def register_rows(self, direction, date_from, date_to, restricted=False, company=None):
        """Журнал реєстрації за період: рядки по порядку номерів.

        [{id, name, date, partner, partner_ref, partner_date, subject, responsible, date_due,
          state, done, overdue, reply}]. Документи ДСК - окремим журналом (restricted=True)."""
        company = company or self.env.company
        docs = self.search([
            ("company_id", "=", company.id), ("direction", "=", direction),
            ("restricted", "=", bool(restricted)),
            ("date", ">=", date_from), ("date", "<=", date_to)], order="date, id")
        return [{
            "id": doc.id, "name": doc.name, "date": doc.date,
            "partner": doc.partner_id.display_name, "partner_ref": doc.partner_ref or "",
            "partner_date": doc.partner_date, "subject": doc.subject,
            "responsible": doc.responsible_id.name or "", "date_due": doc.date_due,
            "state": doc.state, "done": doc.date_done, "overdue": doc.is_overdue,
            "reply": ", ".join(doc.reply_ids.filtered(
                lambda r: r.state != "cancel").mapped("name")) or (doc.reply_to_id.name or ""),
        } for doc in docs]
