"""Відправлення: номер перевізника, стан, хід доставки, що з ним робити.

Вхідні - від постачальників (номер приходить у листі чи рахунку), вихідні - покупцям і
військовим частинам. Стан підтягується за розкладом; що вимагає дії людини, стає справою
відповідального: забрати з відділення до платного зберігання, з'ясувати невдалу спробу,
відповісти митниці.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import parcel_core as core
from .carrier import to_utc

TODO = "mail.mail_activity_data_todo"


class UaParcel(models.Model):
    _name = "ua.parcel"
    _description = "Відправлення"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "attention desc, last_event_date desc, id desc"
    _rec_names_search = ["name", "description", "partner_id"]

    name = fields.Char("Номер", required=True, index=True, tracking=True, copy=False)
    carrier_id = fields.Many2one("ua.parcel.carrier", "Перевізник", required=True, index=True,
                                 tracking=True, ondelete="restrict")
    direction = fields.Selection([("in", "До нас"), ("out", "Від нас")], "Напрям", required=True,
                                 default="in", tracking=True)
    partner_id = fields.Many2one("res.partner", "Від кого чи кому", index=True, tracking=True)
    description = fields.Char("Що всередині")
    user_id = fields.Many2one("res.users", "Відповідальний", default=lambda self: self.env.user,
                              tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    purchase_id = fields.Many2one("purchase.order", "Замовлення постачальнику", index="btree_not_null")
    picking_id = fields.Many2one("stock.picking", "Складський документ", index="btree_not_null")
    origin = fields.Char("Інший документ", help="Номер замовлення покупця, акта передачі чи листа.")

    state = fields.Selection(core.STATES, "Стан", required=True, default="new", tracking=True, index=True)
    status_text = fields.Char("Як пише перевізник", readonly=True)
    found = fields.Boolean("Перевізник знає номер", default=True, readonly=True)
    closed = fields.Boolean("Закрито вручну", tracking=True,
                            help="Більше не перевіряти: наприклад, посилку забрали, а перевізник мовчить.")
    done = fields.Boolean("Завершено", compute="_compute_done", store=True, index=True)
    event_ids = fields.One2many("ua.parcel.event", "parcel_id", "Хід доставки")
    last_event_date = fields.Datetime("Остання подія", readonly=True)
    last_check = fields.Datetime("Перевірено", readonly=True)
    check_error = fields.Char("Помилка перевірки", readonly=True)

    expected_date = fields.Date("Очікується", tracking=True)
    delivered_date = fields.Datetime("Отримано", readonly=True)
    storage_from = fields.Date("Платне зберігання з")
    from_place = fields.Char("Звідки")
    to_place = fields.Char("Куди")
    weight = fields.Float("Вага, кг")
    seats = fields.Integer("Місць")
    cost = fields.Monetary("Доставка коштує")
    cod_amount = fields.Monetary("Накладений платіж", help="Сума, яку перевізник бере з одержувача.")
    phone = fields.Char("Телефон для перевірки",
                        help="Телефон відправника чи одержувача з накладної: з ним Нова пошта показує все.")

    attention = fields.Boolean("Потребує уваги", readonly=True, index=True)
    attention_reason = fields.Char("Що не так", readonly=True)
    tracking_link = fields.Char("Сторінка перевізника", compute="_compute_tracking_link")

    _number_uniq = models.Constraint("unique(company_id, carrier_id, name)",
                                     "Відправлення з таким номером у цього перевізника вже є.")

    @api.depends("state", "closed")
    def _compute_done(self):
        for parcel in self:
            parcel.done = parcel.closed or parcel.state in core.FINAL_STATES

    @api.depends("name", "carrier_id.tracking_url")
    def _compute_tracking_link(self):
        for parcel in self:
            parcel.tracking_link = parcel.carrier_id._ua_link(parcel.name) if parcel.carrier_id else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name"):
                vals["name"] = core.clean_number(vals["name"])
            self._ua_fill_from_documents(vals)
        parcels = super().create(vals_list)
        parcels._ua_refresh_attention()
        return parcels

    def write(self, vals):
        if vals.get("name"):
            vals["name"] = core.clean_number(vals["name"])
        res = super().write(vals)
        if {"state", "closed", "expected_date", "storage_from", "last_event_date", "check_error"} & set(vals):
            self._ua_refresh_attention()
        return res

    @api.model
    def _ua_fill_from_documents(self, vals):
        """Контрагент і напрям із замовлення чи складського документа, якщо їх не вказали."""
        if vals.get("picking_id"):
            picking = self.env["stock.picking"].browse(vals["picking_id"])
            vals.setdefault("partner_id", picking.partner_id.id)
            vals.setdefault("direction", "out" if picking.picking_type_code == "outgoing" else "in")
            if picking.purchase_id:
                vals.setdefault("purchase_id", picking.purchase_id.id)
        if vals.get("purchase_id"):
            vals.setdefault("partner_id", self.env["purchase.order"].browse(vals["purchase_id"]).partner_id.id)
            vals.setdefault("direction", "in")

    def _ua_phone(self):
        self.ensure_one()
        return "".join(c for c in (self.phone or self.carrier_id.phone or "") if c.isdigit())

    # --------------------------------------------------------------- перевірка стану
    def action_ua_track(self):
        """Спитати перевізника зараз. Помилка одного перевізника не зупиняє інших."""
        errors = self._ua_track()
        if errors and len(self) == 1:
            raise UserError(errors[0])
        return True

    def _ua_track(self):
        errors = []
        for carrier in self.carrier_id:
            parcels = self.filtered(lambda p, c=carrier: p.carrier_id == c)
            if carrier.connector == "manual":
                continue
            try:
                with self.env.cr.savepoint():
                    results = carrier._ua_fetch(parcels)
            except UserError as e:
                message = str(e.args[0] if e.args else e)
                parcels.write({"check_error": message[:250], "last_check": fields.Datetime.now()})
                errors.append(message)
                continue
            for parcel in parcels:
                parcel._ua_apply(results.get(parcel.name))
        return errors

    def _ua_apply(self, result):
        """Записати відповідь перевізника: нові події, стан, дати, суми."""
        self.ensure_one()
        now = fields.Datetime.now()
        vals = {"last_check": now, "check_error": False}
        if not result:
            vals.update({"found": False, "status_text": _("Перевізник ще не має цього номера")})
            self.write(vals)
            return
        known = {(e.code, e.text, e.date) for e in self.event_ids}
        last = self.event_ids[:1]
        new_events = []
        for event in result.get("events") or []:
            when = to_utc(event.get("date")) or now
            key = (event.get("code") or False, event.get("text") or False, when)
            if key in known:
                continue
            # Нова пошта віддає лише поточний стан: той самий код і текст - не нова подія.
            if len(result["events"]) == 1 and last and (last.code, last.text) == key[:2]:
                continue
            known.add(key)
            new_events.append({"parcel_id": self.id, "date": when, "code": event.get("code"),
                               "text": event.get("text"), "place": event.get("place"),
                               "state": event.get("state") or result["state"]})
        if new_events:
            self.env["ua.parcel.event"].create(new_events)
            dates = [e["date"] for e in new_events] + ([self.last_event_date] if self.last_event_date else [])
            vals["last_event_date"] = max(dates)
        events = result.get("events") or []
        vals.update({
            "found": result.get("found", True),
            "state": result.get("state") or self.state,
            "status_text": (events[-1].get("text") if events else self.status_text) or self.status_text,
        })
        for field, key in (("expected_date", "expected"), ("storage_from", "storage_from")):
            if result.get(key):
                vals[field] = result[key].date()
        if result.get("delivered"):
            vals["delivered_date"] = to_utc(result["delivered"])
        for field, key in (("cost", "cost"), ("weight", "weight"), ("seats", "seats"),
                           ("cod_amount", "cod"), ("from_place", "from_place"), ("to_place", "to_place")):
            if result.get(key):
                vals[field] = result[key]
        if result.get("reason"):
            vals["status_text"] = "%s: %s" % (vals["status_text"] or "", result["reason"])
        old_state = self.state
        self.write(vals)
        if self.state != old_state:
            self._ua_on_state(old_state)

    def _ua_on_state(self, old_state):
        """Що робити людям після зміни стану."""
        self.ensure_one()
        if self.state == "at_pickup" and self.direction == "in" and self.user_id:
            if not self.storage_from:
                self.storage_from = fields.Date.context_today(self) + timedelta(days=self.carrier_id.pickup_days)
            self._ua_todo(_("Забрати відправлення %s") % self.name, self.storage_from - timedelta(days=1))
        elif self.state in ("failed_attempt", "returning", "exception", "customs") and self.user_id:
            self._ua_todo(_("%(state)s: %(number)s", state=core.STATE_LABELS[self.state], number=self.name),
                          fields.Date.context_today(self))
        elif self.state in core.FINAL_STATES:
            self.activity_ids.filtered(lambda a: a.activity_type_id == self.env.ref(TODO)).action_feedback(
                feedback=core.STATE_LABELS[self.state])
            if self.state == "delivered":
                note = _("Відправлення %(number)s (%(carrier)s) отримано.", number=self.name,
                         carrier=self.carrier_id.name)
                for doc in (self.purchase_id, self.picking_id):
                    if doc:
                        doc.message_post(body=note)

    def _ua_todo(self, summary, deadline):
        todo = self.env.ref(TODO)
        activity = self.activity_ids.filtered(lambda a: a.activity_type_id == todo)
        deadline = max(deadline, fields.Date.context_today(self))
        if activity:
            activity.write({"summary": summary, "date_deadline": deadline, "user_id": self.user_id.id})
        else:
            self.activity_schedule(TODO, date_deadline=deadline, user_id=self.user_id.id, summary=summary)

    def _ua_refresh_attention(self):
        """Позначка «Потребує уваги» і причина одним рядком."""
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        for parcel in self:
            reason = False
            if parcel.done:
                reason = False
            elif parcel.check_error:
                reason = _("Не вдалося перевірити: %s") % parcel.check_error
            elif parcel.state == "at_pickup" and parcel.direction == "in":
                reason = _("Чекає у відділенні")
                if parcel.storage_from:
                    reason += _(", платне зберігання з %s") % parcel.storage_from.strftime("%d.%m")
            elif parcel.state in core.ATTENTION_STATES:
                reason = core.STATE_LABELS[parcel.state]
            elif not parcel.found and parcel.create_date and parcel.create_date < now - timedelta(days=2):
                reason = _("Перевізник не знає номер понад 2 дні")
            elif parcel.expected_date and parcel.expected_date < today:
                reason = _("Запізнюється: мало бути %s") % parcel.expected_date.strftime("%d.%m")
            else:
                since = parcel.last_event_date or parcel.create_date
                days = parcel.carrier_id.stuck_days
                if since and days and parcel.state != "new" and since < now - timedelta(days=days):
                    reason = _("Без руху %s дн.") % (now - since).days
            values = {"attention": bool(reason), "attention_reason": reason}
            if (parcel.attention, parcel.attention_reason or False) != (values["attention"], reason):
                super(UaParcel, parcel).write(values)

    @api.model
    def _cron_ua_track(self):
        """Перевірити відкриті відправлення, яким настав час, і оновити позначки уваги."""
        now = fields.Datetime.now()
        open_parcels = self.search([("done", "=", False)])
        due = open_parcels.filtered(
            lambda p: p.carrier_id.connector != "manual"
            and (not p.last_check or p.last_check <= now - timedelta(hours=p.carrier_id.check_hours or 3)))
        due._ua_track()
        open_parcels._ua_refresh_attention()

    # --------------------------------------------------------------- дії
    def action_ua_close(self):
        self.write({"closed": True})

    def action_ua_reopen(self):
        self.write({"closed": False})

    def action_ua_open_carrier(self):
        self.ensure_one()
        if not self.tracking_link:
            raise UserError(_("У картці перевізника немає сторінки відстеження."))
        return {"type": "ir.actions.act_url", "url": self.tracking_link, "target": "new"}

    @api.model
    def _ua_summary(self, domain=None):
        """Зведення для панелей: скільки в якому стані, скільки чекає уваги, накладені платежі в дорозі."""
        domain = list(domain or []) + [("done", "=", False)]
        by_state = dict(self._read_group(domain, ["state"], ["__count"]))
        cod = self._read_group(domain + [("direction", "=", "out")], [], ["cod_amount:sum"])[0][0]
        return {
            "open": sum(by_state.values()),
            "attention": self.search_count(domain + [("attention", "=", True)]),
            "by_state": [{"state": code, "label": label, "count": by_state.get(code, 0)}
                         for code, label in core.STATES if by_state.get(code)],
            "cod_in_transit": cod or 0.0,
        }


class UaParcelEvent(models.Model):
    _name = "ua.parcel.event"
    _description = "Подія відправлення"
    _order = "date desc, id desc"

    parcel_id = fields.Many2one("ua.parcel", required=True, ondelete="cascade", index=True)
    date = fields.Datetime("Коли", required=True)
    code = fields.Char("Код перевізника")
    text = fields.Char("Подія")
    place = fields.Char("Де")
    state = fields.Selection(core.STATES, "Стан")
    company_id = fields.Many2one(related="parcel_id.company_id", store=True)
