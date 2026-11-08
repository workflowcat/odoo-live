"""Періодичні і типові випробування серійних виробів.

Періодичні: виріб з періодичністю N місяців. Протокол з результатом «витримано» діє до
дата + N місяців - 1 день. Поки перших випробувань не було, приймання дозволене до дати
«перші періодичні - до» (якщо її задано). Не витримано, строк минув або перші прострочені -
акт приймання не затверджується.

Типові: після зміни конструкції, яка їх вимагає, виріб позначається «потрібні типові
випробування»; протокол типових з результатом «витримано» знімає позначку.
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TODO = "mail.mail_activity_data_todo"
KINDS = [("periodic", "Періодичні"), ("type", "Типові"), ("qualification", "Кваліфікаційні"),
         ("other", "Інші")]


def _d(day):
    return day.strftime("%d.%m.%Y") if day else ""


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_periodic_months = fields.Integer("Періодичні випробування, раз на (міс.)", tracking=True,
                                        help="0 - виріб періодичних випробувань не проходить.")
    ua_periodic_first_due = fields.Date("Перші періодичні - до",
                                        help="До перших випробувань приймання дозволене до цієї дати.")
    ua_test_program = fields.Char("Програма і методика випробувань")
    ua_test_notify_days = fields.Integer("Нагадати про випробування за, днів", default=30)
    ua_type_test_required = fields.Boolean("Потрібні типові випробування", tracking=True)
    ua_type_test_reason = fields.Char("Чому потрібні типові", tracking=True)
    ua_test_ids = fields.One2many("ua.product.test", "product_tmpl_id", "Випробування")
    ua_periodic_valid_until = fields.Date("Періодичні діють до", compute="_compute_ua_periodic", store=True)
    ua_periodic_last_id = fields.Many2one("ua.product.test", "Останні періодичні",
                                          compute="_compute_ua_periodic", store=True)

    @api.depends("ua_test_ids.state", "ua_test_ids.kind", "ua_test_ids.date", "ua_test_ids.result",
                 "ua_test_ids.valid_until")
    def _compute_ua_periodic(self):
        for template in self:
            done = template.ua_test_ids.filtered(lambda t: t.state == "done" and t.kind == "periodic")
            last = done.sorted(lambda t: (t.date, t.id))[-1:]
            template.ua_periodic_last_id = last
            template.ua_periodic_valid_until = last.valid_until if last.result == "passed" else False

    def ua_acceptance_block(self, day):
        """Чому виріб зараз не можна приймати, або порожній рядок."""
        self.ensure_one()
        reasons = []
        if self.ua_type_test_required:
            reasons.append(_("потрібні типові випробування (%s)") % (self.ua_type_test_reason or _("зміна конструкції")))
        if self.ua_periodic_months > 0:
            last = self.ua_periodic_last_id
            if not last:
                if self.ua_periodic_first_due and day > self.ua_periodic_first_due:
                    reasons.append(_("перші періодичні випробування мали бути до %s") % _d(self.ua_periodic_first_due))
            elif last.result != "passed":
                reasons.append(_("періодичні випробування не витримано (протокол %(name)s від %(date)s)",
                                 name=last.name, date=_d(last.date)))
            elif not self.ua_periodic_valid_until or self.ua_periodic_valid_until < day:
                reasons.append(_("строк періодичних випробувань минув %s") % _d(self.ua_periodic_valid_until))
        return "; ".join(reasons)

    def ua_test_status(self, day=None):
        """Коротко для списку і картки виробу."""
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        block = self.ua_acceptance_block(day)
        if block:
            return _("приймання призупинено: %s") % block
        if self.ua_periodic_valid_until:
            return _("періодичні діють до %s") % _d(self.ua_periodic_valid_until)
        return ""

    @api.model
    def _ua_cron_periodic_tests(self):
        today = fields.Date.context_today(self)
        todo = self.env.ref(TODO)
        for template in self.search([("ua_periodic_months", ">", 0)]):
            due = template.ua_periodic_valid_until or (not template.ua_periodic_last_id and template.ua_periodic_first_due)
            if not due or due > today + timedelta(days=max(template.ua_test_notify_days, 0)):
                continue
            summary = _("Періодичні випробування «%(product)s» - до %(date)s", product=template.name, date=_d(due))
            if template.activity_ids.filtered(lambda a: a.activity_type_id == todo and a.summary == summary):
                continue
            user = template.responsible_id if "responsible_id" in template._fields else False
            template.activity_schedule(TODO, date_deadline=due, summary=summary,
                                       user_id=(user or self.env.user).id)
        return True


class UaProductTest(models.Model):
    _name = "ua.product.test"
    _description = "Протокол випробувань виробу"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер протоколу", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    product_tmpl_id = fields.Many2one("product.template", "Виріб", required=True, index=True, tracking=True)
    kind = fields.Selection(KINDS, "Вид", required=True, default="periodic", tracking=True)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    result = fields.Selection([("passed", "Витримано"), ("failed", "Не витримано")], "Результат",
                              required=True, default="passed", tracking=True)
    lot_ids = fields.Many2many("stock.lot", string="Зразки (серійні номери)",
                               domain="[('product_id.product_tmpl_id', '=', product_tmpl_id)]")
    program = fields.Char("Програма і методика", compute="_compute_program", store=True, readonly=False)
    eco_id = fields.Many2one("ua.eco", "Зміна конструкції", domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    basis = fields.Char("Підстава", help="План-графік, рішення, повідомлення про зміну.")
    place = fields.Char("Де випробовували", help="Підприємство, полігон, випробувальна лабораторія.")
    representative = fields.Char("Представник замовника")
    valid_until = fields.Date("Діють до", compute="_compute_valid_until", store=True, readonly=False,
                              precompute=True)
    findings = fields.Text("Результати і висновки")
    state = fields.Selection([("draft", "Чернетка"), ("done", "Затверджено")], "Стан", required=True,
                             default="draft", tracking=True)

    @api.depends("product_tmpl_id")
    def _compute_program(self):
        for test in self:
            if not test.program:
                test.program = test.product_tmpl_id.ua_test_program

    @api.depends("kind", "date", "result", "product_tmpl_id.ua_periodic_months")
    def _compute_valid_until(self):
        for test in self:
            months = test.product_tmpl_id.ua_periodic_months
            if test.kind == "periodic" and test.result == "passed" and test.date and months > 0:
                test.valid_until = test.date + relativedelta(months=months) - timedelta(days=1)
            else:
                test.valid_until = False

    @api.constrains("kind", "result", "valid_until", "date")
    def _check_valid_until(self):
        for test in self:
            if test.valid_until and test.valid_until < test.date:
                raise ValidationError(_("Строк дії не може бути раніше за дату протоколу."))

    def action_done(self):
        for test in self:
            if test.state != "draft":
                continue
            if not test.lot_ids and test.kind in ("periodic", "type"):
                raise UserError(_("Протокол %s: вкажіть зразки, які випробовували.") % test.name)
            test.state = "done"
            template = test.product_tmpl_id
            label = dict(KINDS)[test.kind]
            if test.result == "passed":
                if test.kind == "type" and template.ua_type_test_required:
                    template.write({"ua_type_test_required": False, "ua_type_test_reason": False})
                template.message_post(body=_("%(kind)s випробування витримано: протокол %(name)s від %(date)s.",
                                             kind=label, name=test.name, date=_d(test.date)))
            else:
                template.message_post(body=_(
                    "%(kind)s випробування не витримано: протокол %(name)s від %(date)s. Приймання призупинено "
                    "до повторних випробувань.", kind=label, name=test.name, date=_d(test.date)))
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_product_tests.action_report_ua_product_test").report_action(self)

    def ua_kind_label(self):
        self.ensure_one()
        return dict(KINDS).get(self.kind, "")

    def ua_date(self, day):
        return _d(day)

    def unlink(self):
        if any(test.state == "done" for test in self):
            raise UserError(_("Затверджений протокол не видаляють."))
        return super().unlink()


class UaDefenseAcceptance(models.Model):
    _inherit = "ua.defense.acceptance"

    def action_done(self):
        for act in self:
            products = act.line_ids.filtered(lambda line: line.result == "accepted").product_id.product_tmpl_id
            blocks = [(template, template.ua_acceptance_block(act.date)) for template in products]
            blocks = [(template, reason) for template, reason in blocks if reason]
            if blocks:
                raise UserError(_("Приймання призупинено:\n%s") % "\n".join(
                    "%s: %s" % (template.display_name, reason) for template, reason in blocks))
        return super().action_done()


class UaEco(models.Model):
    _inherit = "ua.eco"

    ua_type_test = fields.Boolean("Потрібні типові випробування", tracking=True,
                                  help="Після застосування зміни приймання виробу стоїть до типових випробувань.")

    def _apply(self):
        result = super()._apply()
        if self.ua_type_test:
            self._ua_request_type_test()
        return result

    def _ua_request_type_test(self):
        self.ensure_one()
        self.product_tmpl_id.write({"ua_type_test_required": True,
                                    "ua_type_test_reason": _("зміна %s") % self.name})
        self.message_post(body=_("Виріб чекає типових випробувань: до них приймання призупинено."))
