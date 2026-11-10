"""Акт приймання-передачі послуг гіг-спеціаліста резидента Дія Сіті.

Винагорода і премія записані у валюті гіг-контракту. Гривнева сума = сума у валюті × курс НБУ
на дату акта, до копійки. Курс береться з курсів валют Odoo (їх оновлює l10n_ua_nbu); його можна
вписати вручну, якщо курсу на дату ще немає. Затверджений акт іде в розрахунковий листок
гіг-спеціаліста рядками введення GIG і GIG_BONUS - у той листок, чий період містить кінець
періоду акта.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

GIG, GIG_BONUS = "GIG", "GIG_BONUS"
OPEN_SLIP_STATES = ("draft", "verify")


def _money_round(value):
    """Гроші до копійки, пів копійки вгору (як ua_round у правилах)."""
    from odoo.addons.l10n_ua_payroll_rules.models.hr_payslip import ua_round
    return ua_round(value)


class UaGigAct(models.Model):
    _name = "ua.gig.act"
    _description = "Акт гіг-спеціаліста (Дія Сіті)"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Номер", required=True, copy=False, readonly=True, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    company_currency_id = fields.Many2one(related="company_id.currency_id", string="Гривня")
    employee_id = fields.Many2one(
        "hr.employee", "Гіг-спеціаліст", required=True, tracking=True, check_company=True,
        domain="[('ua_contract_kind', '=', 'gig')]")
    date = fields.Date("Дата акта", required=True, default=fields.Date.context_today, tracking=True)
    date_from = fields.Date("Період з", required=True,
                            default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date("Період по", required=True, default=lambda s: s._default_date_to())
    description = fields.Text("Послуги (роботи)", help="Що саме надано за період: друкується в акті")
    currency_id = fields.Many2one("res.currency", "Валюта договору", required=True, tracking=True,
                                  default=lambda s: s.env.company.currency_id)
    amount_currency = fields.Monetary("Винагорода у валюті", currency_field="currency_id", tracking=True)
    bonus_currency = fields.Monetary("Премія у валюті", currency_field="currency_id", tracking=True)
    rate = fields.Float("Курс НБУ, грн за одиницю", digits=(12, 6), compute="_compute_rate", store=True,
                        readonly=False, tracking=True,
                        help="Курс на дату акта з курсів валют. Порожньо або 0 - курсу на дату немає: "
                             "оновіть курси НБУ або впишіть курс вручну.")
    amount = fields.Monetary("Винагорода, грн", currency_field="company_currency_id",
                             compute="_compute_amounts", store=True)
    bonus = fields.Monetary("Премія, грн", currency_field="company_currency_id",
                            compute="_compute_amounts", store=True)
    total = fields.Monetary("Разом, грн", currency_field="company_currency_id",
                            compute="_compute_amounts", store=True)
    total_currency = fields.Monetary("Разом у валюті", currency_field="currency_id",
                                     compute="_compute_amounts", store=True)
    state = fields.Selection([("draft", "Чернетка"), ("confirmed", "Затверджено"), ("cancel", "Скасовано")],
                             "Стан", default="draft", required=True, readonly=True, copy=False, tracking=True)
    payslip_id = fields.Many2one("hr.payslip", "Листок", compute="_compute_payslip",
                                 help="Листок, у який іде акт: період листка містить кінець періоду акта")
    note = fields.Text("Примітка")

    @api.model
    def _default_date_to(self):
        first = fields.Date.context_today(self).replace(day=1)
        return (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)

    @api.depends("currency_id", "date", "company_id")
    def _compute_rate(self):
        for act in self:
            act.rate = act._nbu_rate()

    def _nbu_rate(self):
        """Гривень за одиницю валюти на дату акта; 0, якщо курсу в базі немає."""
        self.ensure_one()
        company = self.company_id or self.env.company
        if not self.currency_id or not self.date:
            return 0.0
        if self.currency_id == company.currency_id:
            return 1.0
        has_rate = self.env["res.currency.rate"].sudo().search_count([
            ("currency_id", "=", self.currency_id.id), ("name", "<=", self.date),
            "|", ("company_id", "=", False), ("company_id", "=", company.root_id.id)])
        if not has_rate:
            return 0.0
        return self.env["res.currency"]._get_conversion_rate(
            self.currency_id, company.currency_id, company, self.date)

    @api.depends("amount_currency", "bonus_currency", "rate")
    def _compute_amounts(self):
        for act in self:
            act.amount = _money_round(act.amount_currency * act.rate)
            act.bonus = _money_round(act.bonus_currency * act.rate)
            act.total = _money_round(act.amount + act.bonus)
            act.total_currency = _money_round(act.amount_currency + act.bonus_currency)

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        emp = self.employee_id.sudo()
        if emp:
            self.currency_id = emp.ua_gig_currency_id or self.company_id.currency_id
            if emp.ua_gig_fee and not self.amount_currency:
                self.amount_currency = emp.ua_gig_fee

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for act in self:
            if act.date_from and act.date_to and act.date_from > act.date_to:
                raise ValidationError(_("Початок періоду акта пізніший за кінець."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("employee_id") and not vals.get("currency_id"):
                emp = self.env["hr.employee"].sudo().browse(vals["employee_id"])
                if emp.ua_gig_currency_id:
                    vals["currency_id"] = emp.ua_gig_currency_id.id
            if vals.get("employee_id") and "amount_currency" not in vals:
                emp = self.env["hr.employee"].sudo().browse(vals["employee_id"])
                vals["amount_currency"] = emp.ua_gig_fee or 0.0
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.gig.act") or "/"
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda a: a.state == "confirmed"):
            raise UserError(_("Затверджений акт не видаляється: спершу скасуйте його."))

    # ---- листок -----------------------------------------------------------------------
    def _slips(self, states):
        self.ensure_one()
        return self.env["hr.payslip"].search([
            ("employee_id", "=", self.employee_id.id), ("state", "in", list(states)),
            ("company_id", "=", self.company_id.id),
            ("date_from", "<=", self.date_to), ("date_to", ">=", self.date_to)])

    @api.depends("employee_id", "date_to", "state")
    def _compute_payslip(self):
        for act in self:
            act.payslip_id = act._slips(("draft", "verify", "done"))[:1] if act.employee_id and act.date_to else False

    def _check_closed_slips(self):
        for act in self:
            closed = act._slips(("done",))
            if closed:
                raise UserError(_("Листок %s за цей період уже проведено: акт у ньому змінювати не можна.")
                                % closed[0].name)

    def _recompute_slips(self):
        for act in self:
            act._slips(OPEN_SLIP_STATES).compute_sheet()

    def action_confirm(self):
        for act in self:
            if act.state != "draft":
                raise UserError(_("Затвердити можна лише чернетку."))
            if (act.employee_id.sudo().ua_contract_kind or "employment") != "gig":
                raise UserError(_("%s працює не за гіг-контрактом: акт гіг-спеціаліста не підходить.")
                                % act.employee_id.name)
            if act.amount_currency < 0 or act.bonus_currency < 0:
                raise UserError(_("Суми акта не бувають від'ємними."))
            if not act.total_currency:
                raise UserError(_("Акт без суми: впишіть винагороду або премію."))
            if not act.rate:
                raise UserError(_("Немає курсу %s на %s. Оновіть курси НБУ або впишіть курс вручну.")
                                % (act.currency_id.name, act.date.strftime("%d.%m.%Y")))
        self._check_closed_slips()
        self.write({"state": "confirmed"})
        self._recompute_slips()
        return True

    def action_cancel(self):
        for act in self:
            if act.state != "confirmed":
                raise UserError(_("Скасувати можна лише затверджений акт."))
        self._check_closed_slips()
        self.write({"state": "cancel"})
        self._recompute_slips()
        return True

    def action_draft(self):
        for act in self:
            if act.state != "cancel":
                raise UserError(_("У чернетку повертається лише скасований акт."))
        self.write({"state": "draft"})
        return True

    def action_refresh_rate(self):
        """Взяти курс НБУ на дату акта ще раз (після оновлення курсів)."""
        for act in self.filtered(lambda a: a.state == "draft"):
            act.rate = act._nbu_rate()
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_diia_city.action_report_ua_gig_act").report_action(self)

    # ---- друк -------------------------------------------------------------------------
    @api.model
    def money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    @api.model
    def rate_text(self, rate):
        return ("{:,.6f}".format(rate or 0.0).rstrip("0").rstrip(".")).replace(",", " ").replace(".", ",")
