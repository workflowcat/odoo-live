"""Засоби вимірювальної техніки (ЗВТ), повірка і калібрування.

ЗВТ - це обладнання з позначкою: його вже мають облік обладнання, відповідальний,
розташування і заявки на обслуговування. Тут додаємо метрологію.

Законодавчо регульований засіб проходить періодичну повірку з інтервалом, який
встановлює уповноважений орган; інші засоби підприємство калібрує за власним графіком.
Обидва інтервали - налаштування засобу, не правило в коді: перевірте чинну редакцію
переліку і міжповірочних інтервалів.

Придатність на дату: останній результат «придатний» і строк ще не минув, засіб не
законсервовано. Останній результат «непридатний» робить засіб непридатним, поки нова
повірка чи калібрування не скаже інакше.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TODO = "mail.mail_activity_data_todo"

KINDS = [("verification", "Повірка"), ("calibration", "Калібрування")]
RESULTS = [("passed", "Придатний"), ("failed", "Непридатний")]
STATES = [
    ("none", "Не повірявся"),
    ("valid", "Придатний"),
    ("due_soon", "Скоро строк"),
    ("overdue", "Строк минув"),
    ("unfit", "Непридатний"),
    ("conserved", "Законсервовано"),
]


def _ua_date(value):
    return value.strftime("%d.%m.%Y") if value else ""


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    ua_measuring = fields.Boolean(
        "Засіб вимірювальної техніки",
        help="Інструмент або прилад, яким вимірюють під час виробництва чи контролю якості.")
    ua_regulated = fields.Boolean(
        "Законодавчо регульований",
        help="Підлягає періодичній повірці. Інакше засіб калібрують за графіком підприємства.")
    ua_measure_range = fields.Char("Діапазон вимірювань")
    ua_accuracy = fields.Char("Клас точності, похибка")
    ua_interval_months = fields.Integer(
        "Інтервал, міс.", default=12,
        help="Міжповірочний або міжкалібрувальний інтервал. Для законодавчо регульованих засобів його "
             "встановлює уповноважений орган - перевірте чинну редакцію.")
    ua_notify_days = fields.Integer("Нагадати за, днів", default=30)
    ua_conserved = fields.Boolean(
        "Законсервовано", tracking=True,
        help="Засіб тимчасово не застосовують і не повіряють. Відповіді «так» ним не приймаються.")
    ua_verification_ids = fields.One2many("ua.metrology.verification", "equipment_id", "Повірки і калібрування")
    ua_last_date = fields.Date("Остання повірка", compute="_compute_ua_metrology", store=True)
    ua_last_result = fields.Selection(RESULTS, "Останній результат", compute="_compute_ua_metrology", store=True)
    ua_valid_until = fields.Date("Придатний до", compute="_compute_ua_metrology", store=True, tracking=True)
    ua_metrology_state = fields.Selection(STATES, "Метрологічний стан", compute="_compute_ua_metrology_state")

    @api.depends("ua_verification_ids.date", "ua_verification_ids.result", "ua_verification_ids.valid_until")
    def _compute_ua_metrology(self):
        for equipment in self:
            last = equipment.ua_verification_ids.sorted(lambda v: (v.date, v.id))[-1:]
            equipment.ua_last_date = last.date
            equipment.ua_last_result = last.result
            equipment.ua_valid_until = last.valid_until if last.result == "passed" else False

    @api.depends("ua_last_result", "ua_valid_until", "ua_conserved", "ua_notify_days")
    def _compute_ua_metrology_state(self):
        today = fields.Date.context_today(self)
        for equipment in self:
            equipment.ua_metrology_state = equipment._ua_state_on(today)

    def _ua_state_on(self, day):
        self.ensure_one()
        if self.ua_conserved:
            return "conserved"
        if not self.ua_last_result:
            return "none"
        if self.ua_last_result == "failed":
            return "unfit"
        if not self.ua_valid_until or self.ua_valid_until < day:
            return "overdue"
        if self.ua_valid_until <= day + timedelta(days=max(self.ua_notify_days, 0)):
            return "due_soon"
        return "valid"

    def ua_unfit_reason(self, day=None):
        """Чому засобом не можна міряти на дату; порожньо - можна."""
        self.ensure_one()
        state = self._ua_state_on(day or fields.Date.context_today(self))
        if state in ("valid", "due_soon"):
            return ""
        return {
            "conserved": _("законсервовано"),
            "none": _("не повірявся і не калібрувався"),
            "unfit": _("визнано непридатним %s") % _ua_date(self.ua_last_date),
            "overdue": _("строк минув %s") % _ua_date(self.ua_valid_until),
        }[state]

    def ua_label(self):
        """«Штангенциркуль ШЦ-I-150 № 1234, повірка до 10.01.2027» - для відповіді ВТК і паспорта."""
        self.ensure_one()
        text = self.name or ""
        if self.serial_no:
            text += " № %s" % self.serial_no
        if self.ua_valid_until:
            text += _(", %(kind)s до %(date)s",
                      kind=_("повірка") if self.ua_regulated else _("калібрування"),
                      date=_ua_date(self.ua_valid_until))
        return text

    def _ua_remind(self, summary, deadline):
        todo = self.env.ref(TODO)
        if self.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
            return False
        user = self.technician_user_id or self.owner_user_id or self.env.user
        self.activity_schedule(TODO, date_deadline=deadline, summary=summary, user_id=user.id)
        return True

    @api.model
    def _ua_cron_metrology(self):
        """Щодня: строк близько - нагадування; строк минув - нагадування не застосовувати."""
        today = fields.Date.context_today(self)
        for equipment in self.search([("ua_measuring", "=", True), ("ua_conserved", "=", False),
                                      ("ua_last_result", "=", "passed")]):
            state = equipment._ua_state_on(today)
            kind = _("Повірка") if equipment.ua_regulated else _("Калібрування")
            if state == "due_soon":
                equipment._ua_remind(_("%(kind)s до %(date)s", kind=kind, date=_ua_date(equipment.ua_valid_until)),
                                     equipment.ua_valid_until)
            elif state == "overdue":
                equipment._ua_remind(_("%(kind)s прострочено з %(date)s: не застосовувати",
                                       kind=kind, date=_ua_date(equipment.ua_valid_until)), today)
        return True

    def action_ua_verifications(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_metrology.action_ua_metrology_verification")
        action["domain"] = [("equipment_id", "=", self.id)]
        action["context"] = {"default_equipment_id": self.id}
        return action

    def action_ua_print_schedule(self):
        return self.env.ref("l10n_ua_metrology.action_report_ua_metrology_schedule").report_action(
            self.filtered("ua_measuring"))


class UaMetrologyVerification(models.Model):
    _name = "ua.metrology.verification"
    _description = "Повірка або калібрування засобу вимірювання"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    equipment_id = fields.Many2one("maintenance.equipment", "Засіб вимірювання", required=True, index=True,
                                   ondelete="cascade", domain="[('ua_measuring', '=', True)]")
    company_id = fields.Many2one(related="equipment_id.company_id", store=True)
    kind = fields.Selection(KINDS, "Вид", required=True, compute="_compute_kind", store=True, readonly=False)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    result = fields.Selection(RESULTS, "Результат", required=True, default="passed", tracking=True)
    valid_until = fields.Date("Придатний до", compute="_compute_valid_until", store=True, readonly=False,
                              tracking=True)
    certificate = fields.Char("Свідоцтво, сертифікат №",
                              help="Номер свідоцтва про повірку, сертифіката калібрування або довідки про непридатність.")
    provider_id = fields.Many2one("res.partner", "Виконавець",
                                  help="Метрологічна служба, повірочна або калібрувальна лабораторія.")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    cost = fields.Monetary("Вартість")
    note = fields.Text("Примітки")

    @api.depends("equipment_id.ua_regulated")
    def _compute_kind(self):
        for row in self:
            if not row.kind:
                row.kind = "verification" if row.equipment_id.ua_regulated else "calibration"

    @api.depends("date", "result", "equipment_id.ua_interval_months")
    def _compute_valid_until(self):
        for row in self:
            months = row.equipment_id.ua_interval_months
            if row.result != "passed" or not row.date or months <= 0:
                row.valid_until = False
            else:
                row.valid_until = row.date + relativedelta(months=months) - timedelta(days=1)

    @api.constrains("result", "date", "valid_until")
    def _check_dates(self):
        for row in self:
            if row.result == "passed" and not row.valid_until:
                raise ValidationError(_("Для придатного засобу вкажіть, до якої дати він придатний."))
            if row.valid_until and row.valid_until < row.date:
                raise ValidationError(_("Строк придатності не може закінчуватися раніше дати повірки."))

    @api.depends("equipment_id", "kind", "date")
    def _compute_display_name(self):
        kinds = dict(KINDS)
        for row in self:
            row.display_name = "%s, %s %s" % (row.equipment_id.name or "", kinds.get(row.kind, ""),
                                             _ua_date(row.date))
