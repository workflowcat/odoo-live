"""Рекламація - претензія замовника до якості виробу з серійним номером.

Порядок:

    зареєстровано -> розслідування -> рішення -> закрито
                 \\---------------------------\\-> скасовано

Строки - умови контракту в календарних днях від надходження: відповісти замовнику і
усунути. Поки відповіді немає, нагадування відповідальному стоїть на строк відповіді, потім -
на строк усунення.

Гарантія: строк на виробі (місяців) від акта приймання, а без акта - від дати
виготовлення. Рішення приймає керівник: власний дефект у гарантії не відхиляють, відмова і
будь-яке рішення поза гарантією мають обґрунтування. Конструкторська причина відкриває
повідомлення про зміну (l10n_ua_eco).
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

STATES = [
    ("received", "Зареєстровано"),
    ("investigation", "Розслідування"),
    ("decided", "Рішення прийнято"),
    ("closed", "Закрито"),
    ("cancel", "Скасовано"),
]
OPEN_STATES = ("received", "investigation", "decided")
CAUSES = [
    ("manufacturing", "Виробничий дефект"),
    ("component", "Дефект покупного комплектуючого"),
    ("design", "Конструкторський недолік"),
    ("operation", "Порушення умов експлуатації"),
    ("transport", "Пошкодження під час транспортування"),
    ("not_confirmed", "Несправність не підтвердилась"),
]
OUR_CAUSES = ("manufacturing", "component", "design")
DECISIONS = [
    ("repair", "Ремонт виробу"),
    ("component", "Заміна складової"),
    ("replace", "Заміна виробу"),
    ("refund", "Повернення коштів"),
    ("reject", "Відмова: не гарантійний випадок"),
]
RESPONSE_DAYS = 10
FIX_DAYS = 30
MANAGER = "l10n_ua_claim.group_ua_claim_manager"
TODO = "mail.mail_activity_data_todo"


class UaContract(models.Model):
    _inherit = "ua.contract"

    ua_claim_response_days = fields.Integer(
        "Відповідь на рекламацію, днів", default=RESPONSE_DAYS,
        help="Календарні дні від надходження рекламації до відповіді замовнику.")
    ua_claim_fix_days = fields.Integer(
        "Усунення за рекламацією, днів", default=FIX_DAYS,
        help="Календарні дні від надходження рекламації до усунення несправності.")


class UaClaim(models.Model):
    _name = "ua.claim"
    _description = "Рекламація"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_received desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection(STATES, "Стан", default="received", required=True, tracking=True,
                             copy=False, index=True)
    lot_id = fields.Many2one("stock.lot", "Серійний номер", required=True, index=True,
                             tracking=True, check_company=True)
    product_id = fields.Many2one(related="lot_id.product_id", store=True, string="Виріб")
    contract_id = fields.Many2one(
        "ua.contract", "Контракт", compute="_compute_contract", store=True, readonly=False,
        precompute=True,
        check_company=True, tracking=True)
    partner_id = fields.Many2one(
        "res.partner", "Замовник", compute="_compute_partner", store=True, readonly=False,
        precompute=True,
        required=True, tracking=True)
    partner_ref = fields.Char("Акт замовника №", help="Номер рекламаційного акта замовника.")
    partner_date = fields.Date("Акт замовника від")
    date_received = fields.Date("Надійшла", required=True, default=fields.Date.context_today,
                                tracking=True)
    date_failure = fields.Date("Дата відмови", required=True, default=fields.Date.context_today)
    symptom = fields.Text("Опис несправності", required=True)
    conditions = fields.Text("Умови експлуатації")
    operating_hours = fields.Float("Наробіток, год")
    component_lot_id = fields.Many2one(
        "stock.lot", "Складова, що відмовила", check_company=True,
        help="Серійний номер складової з паспорта виробу.")
    user_id = fields.Many2one("res.users", "Відповідальний", required=True, tracking=True,
                              default=lambda self: self.env.user)

    warranty_start = fields.Date("Гарантія від", compute="_compute_warranty", store=True)
    warranty_end = fields.Date("Гарантія до", compute="_compute_warranty", store=True)
    in_warranty = fields.Boolean("У гарантії", compute="_compute_warranty", store=True)

    date_response_due = fields.Date("Відповісти до", compute="_compute_due", store=True,
                                    readonly=False, precompute=True, tracking=True)
    date_due = fields.Date("Усунути до", compute="_compute_due", store=True, readonly=False,
                           precompute=True, tracking=True)
    date_responded = fields.Date("Відповідь надіслано", readonly=True, copy=False)
    date_closed = fields.Date("Закрито", readonly=True, copy=False)
    is_overdue = fields.Boolean("Прострочено", compute="_compute_is_overdue",
                                search="_search_is_overdue")

    cause = fields.Selection(CAUSES, "Причина", tracking=True)
    root_cause = fields.Text("Висновок розслідування")
    supplier_id = fields.Many2one("res.partner", "Постачальник складової",
                                  help="Для претензії постачальнику, якщо відмовило покупне.")
    decision = fields.Selection(DECISIONS, "Рішення", tracking=True)
    decision_note = fields.Text("Обґрунтування рішення")
    replacement_lot_id = fields.Many2one("stock.lot", "Виріб на заміну", check_company=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    cost_amount = fields.Monetary("Витрати на усунення")
    eco_id = fields.Many2one("ua.eco", "Повідомлення про зміну", readonly=True, copy=False)
    repeat_count = fields.Integer("Подібних рекламацій", compute="_compute_repeat_count",
                                  help="Інші рекламації на той самий виріб з тією самою складовою, "
                                       "що відмовила, або з тією самою причиною.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.claim", sequence_date=vals.get("date_received")) or "/"
        claims = super().create(vals_list)
        for claim in claims:
            claim._schedule_control()
        return claims

    def write(self, vals):
        result = super().write(vals)
        if {"user_id", "date_response_due", "date_due", "date_responded"} & set(vals):
            for claim in self:
                claim._schedule_control()
        return result

    def unlink(self):
        if any(claim.state != "cancel" for claim in self):
            raise UserError(_("Рекламацію не видаляють - її скасовують: номер у журналі має "
                              "лишитися."))
        return super().unlink()

    # --------------------------------------------------------------- обчислення
    @api.depends("lot_id")
    def _compute_contract(self):
        for claim in self:
            claim.contract_id = claim.lot_id.sudo()._ua_contract() if claim.lot_id else False

    @api.depends("contract_id")
    def _compute_partner(self):
        for claim in self:
            claim.partner_id = claim.contract_id.sudo().partner_id or claim.partner_id

    @api.depends("lot_id", "lot_id.ua_acceptance_id.date", "lot_id.product_id", "date_failure")
    def _compute_warranty(self):
        for claim in self:
            lot = claim.lot_id.sudo()
            start = lot.ua_acceptance_id.date
            if not start and lot.ua_production_id.date_finished:
                start = lot.ua_production_id.date_finished.date()
            months = lot.product_id.product_tmpl_id.ua_warranty_months
            end = start + relativedelta(months=months) if start and months else False
            claim.warranty_start = start or False
            claim.warranty_end = end
            claim.in_warranty = bool(end and claim.date_failure and claim.date_failure <= end)

    @api.depends("date_received", "contract_id")
    def _compute_due(self):
        for claim in self:
            contract = claim.contract_id.sudo()
            response = contract.ua_claim_response_days if contract else RESPONSE_DAYS
            fix = contract.ua_claim_fix_days if contract else FIX_DAYS
            received = claim.date_received
            claim.date_response_due = received + relativedelta(days=response) if received else False
            claim.date_due = received + relativedelta(days=fix) if received else False

    def _overdue_domain(self):
        today = fields.Date.context_today(self)
        return ["&", ("state", "in", OPEN_STATES),
                "|", "&", ("date_responded", "=", False), ("date_response_due", "<", today),
                ("date_due", "<", today)]

    @api.depends("state", "date_responded", "date_response_due", "date_due")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for claim in self:
            late_answer = not claim.date_responded and claim.date_response_due \
                and claim.date_response_due < today
            late_fix = claim.date_due and claim.date_due < today
            claim.is_overdue = bool(claim.state in OPEN_STATES and (late_answer or late_fix))

    def _search_is_overdue(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Пошук за простроченням: лише «так» або «ні»."))
        if (operator == "=") == value:
            return self._overdue_domain()
        return [("id", "not in", self.search(self._overdue_domain()).ids)]

    @api.depends("product_id", "component_lot_id", "cause")
    def _compute_repeat_count(self):
        Claim = self.sudo()
        for claim in self:
            if not claim.product_id or not (claim.component_lot_id or claim.cause):
                claim.repeat_count = 0
                continue
            domain = [("product_id", "=", claim.product_id.id), ("state", "!=", "cancel"),
                      ("company_id", "=", claim.company_id.id)]
            if isinstance(claim.id, int):
                domain.append(("id", "!=", claim.id))
            if claim.component_lot_id:
                domain.append(("component_lot_id.product_id", "=",
                               claim.component_lot_id.product_id.id))
            else:
                domain.append(("cause", "=", claim.cause))
            claim.repeat_count = Claim.search_count(domain)

    @api.constrains("date_failure", "date_received")
    def _check_dates(self):
        for claim in self:
            if claim.date_failure and claim.date_received and claim.date_failure > claim.date_received:
                raise ValidationError(_("Відмова не може статися пізніше, ніж надійшла рекламація."))

    @api.constrains("lot_id", "component_lot_id", "replacement_lot_id")
    def _check_lots(self):
        for claim in self:
            if claim.component_lot_id and claim.component_lot_id == claim.lot_id:
                raise ValidationError(_("Складова, що відмовила, - це інший серійний номер, не "
                                        "сам виріб."))
            if claim.replacement_lot_id and claim.replacement_lot_id == claim.lot_id:
                raise ValidationError(_("На заміну йде інший виріб, не той, на який рекламація."))
            if claim.replacement_lot_id and claim.replacement_lot_id.product_id != claim.product_id:
                raise ValidationError(_("На заміну йде такий самий виріб: %s.")
                                      % claim.product_id.display_name)

    # --------------------------------------------------------------- нагадування
    def _schedule_control(self):
        """Одне нагадування відповідальному: до відповіді - на строк відповіді, далі - на усунення."""
        self.ensure_one()
        deadline = self.date_due if self.date_responded else self.date_response_due
        if self.state not in OPEN_STATES or not deadline or not self.user_id:
            return
        todo = self.env.ref(TODO)
        summary = (_("Усунути: %s") if self.date_responded else _("Відповісти: %s")) % self.name
        activity = self.activity_ids.filtered(lambda a: a.activity_type_id == todo)
        if activity:
            activity.write({"user_id": self.user_id.id, "date_deadline": deadline,
                            "summary": summary})
        else:
            self.activity_schedule(TODO, date_deadline=deadline, user_id=self.user_id.id,
                                   summary=summary)

    def _check_manager(self):
        if not self.env.user.has_group(MANAGER):
            raise AccessError(_("Рішення за рекламацією приймає керівник."))

    # --------------------------------------------------------------- дії
    def action_start(self):
        for claim in self:
            if claim.state != "received":
                raise UserError(_("Розслідування починають із зареєстрованої рекламації."))
            claim.state = "investigation"
        return True

    def action_respond(self):
        """Відповідь замовнику надіслано (рекламацію прийнято до розгляду)."""
        today = fields.Date.context_today(self)
        for claim in self:
            if claim.state not in OPEN_STATES:
                raise UserError(_("Відповідають на відкриту рекламацію."))
            if not claim.date_responded:
                claim.date_responded = today
                claim.message_post(body=_("Відповідь замовнику надіслано."))
        return True

    def action_decide(self):
        self._check_manager()
        for claim in self:
            if claim.state not in ("received", "investigation"):
                raise UserError(_("Рішення приймають за відкритою рекламацією до рішення."))
            if not claim.cause or not claim.decision:
                raise UserError(_("Для рішення потрібні причина і рішення."))
            note = (claim.decision_note or "").strip()
            if claim.decision == "reject":
                if claim.cause in OUR_CAUSES and claim.in_warranty:
                    raise UserError(_("Причина - власний дефект, виріб у гарантії: відмовити не "
                                      "можна. Оберіть ремонт, заміну або повернення коштів."))
                if not note:
                    raise UserError(_("Відмову обґрунтовують: напишіть, чому випадок не гарантійний."))
            elif not claim.in_warranty and not note:
                raise UserError(_("Виріб поза гарантією: напишіть, на яких умовах його "
                                  "ремонтують чи замінюють."))
            values = {"state": "decided"}
            if not claim.date_responded:
                values["date_responded"] = fields.Date.context_today(self)
            claim.write(values)
            claim.message_post(body=_("Рішення: %(decision)s. Причина: %(cause)s.",
                                      decision=dict(DECISIONS)[claim.decision],
                                      cause=dict(CAUSES)[claim.cause]))
        return True

    def action_close(self):
        today = fields.Date.context_today(self)
        for claim in self:
            if claim.state != "decided":
                raise UserError(_("Закривають рекламацію з прийнятим рішенням."))
            if claim.decision == "replace" and not claim.replacement_lot_id:
                raise UserError(_("Вкажіть серійний номер виробу, що пішов на заміну."))
            claim.write({"state": "closed", "date_closed": today})
            claim.activity_feedback([TODO], feedback=_("Закрито"))
        return True

    def action_cancel(self):
        for claim in self:
            if claim.state == "closed":
                raise UserError(_("Закриту рекламацію не скасовують - її відкривають знову."))
            claim.state = "cancel"
            claim.activity_unlink([TODO])
        return True

    def action_reopen(self):
        self._check_manager()
        for claim in self:
            if claim.state not in ("decided", "closed", "cancel"):
                raise UserError(_("Відкривають знову рішену, закриту або скасовану рекламацію."))
            claim.write({"state": "investigation", "date_closed": False})
            claim._schedule_control()
        return True

    def action_create_eco(self):
        """Конструкторська причина: чернетка повідомлення про зміну на виріб."""
        self.ensure_one()
        if self.cause != "design":
            raise UserError(_("Повідомлення про зміну складають, коли причина - конструкторський "
                              "недолік."))
        if not self.eco_id:
            template = self.product_id.product_tmpl_id
            if not self.env["mrp.bom"].sudo().search_count([("product_tmpl_id", "=", template.id)]):
                raise UserError(_("У виробу %s немає специфікації - змінювати нічого.")
                                % template.display_name)
            self.eco_id = self.env["ua.eco"].create({
                "product_tmpl_id": template.id, "company_id": self.company_id.id,
                "reason": "defect",
                "description": _("Рекламація %(claim)s, серійний номер %(lot)s: %(text)s",
                                 claim=self.name, lot=self.lot_id.name,
                                 text=(self.root_cause or self.symptom or "").strip()),
            })
            self.message_post(body=_("Складено повідомлення про зміну %s.") % self.eco_id.name)
        return {"type": "ir.actions.act_window", "res_model": "ua.eco", "res_id": self.eco_id.id,
                "view_mode": "form", "target": "current"}

    def action_print(self):
        return self.env.ref("l10n_ua_claim.action_report_ua_claim").report_action(self)
