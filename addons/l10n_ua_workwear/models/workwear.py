"""Спецодяг і малоцінні предмети в експлуатації.

Як у 1С/BAS «Передача в експлуатацію»: предмет зі складу списується на витрати в момент
видачі, а далі обліковується кількісно за працівником до повернення чи списання.

Склад. Видача - рух зі складу в місце «В експлуатації» з рахунком витрат документа
(для кожного рахунку своє місце, як місця списання в Odoo). Це місце не тримає залишків,
тож вартість іде в витрати проводкою оцінки складу. Повернення - рух назад на склад за
ціною видачі: витрати сторнуються на цю суму.

Облік у працівника - рядки відомостей: працівник, предмет, кількість, з якої дати і до
якої (строк носіння), стан. Норми безоплатної видачі - на посаду; що бракує працівнику,
рахується як норма мінус предмети, чий строк ще не минув.
"""
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

LINE_STATES = [
    ("draft", "Не видано"),
    ("in_use", "В експлуатації"),
    ("returned", "Повернуто"),
    ("written_off", "Списано"),
    ("cancel", "Скасовано"),
]


def _ua_date(value):
    return value.strftime("%d.%m.%Y") if value else ""


class StockLocation(models.Model):
    _inherit = "stock.location"

    ua_in_use = fields.Boolean("Предмети в експлуатації", readonly=True,
                               help="Місце, куди видаються предмети працівникам; вартість - у витрати.")


class StockMove(models.Model):
    _inherit = "stock.move"

    ua_workwear_line_id = fields.Many2one("ua.workwear.line", "Предмет в експлуатації",
                                          index="btree_not_null", readonly=True, copy=False)

    @api.depends("ua_workwear_line_id.issue_id.name")
    def _compute_reference(self):
        # рух без складського документа: Odoo 19 лишає посилання порожнім, а проведення його вимагає
        super()._compute_reference()
        for move in self:
            if not move.reference and move.ua_workwear_line_id:
                move.reference = move.ua_workwear_line_id.issue_id.name


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ua_wear_auto_write_off = fields.Boolean(
        "Списувати після строку автоматично",
        help="Предмет в експлуатації, чий строк минув, списується сам в останній день місяця "
             "(малоцінні предмети з відомим строком використання).")


class UaWorkwearNorm(models.Model):
    _name = "ua.workwear.norm"
    _description = "Норма видачі спецодягу на посаду"
    _order = "job_id, sequence, id"

    job_id = fields.Many2one("hr.job", "Посада", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="job_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", "Предмет", required=True,
                                 domain="[('type', '=', 'consu')]")
    quantity = fields.Float("Кількість", default=1.0, required=True, digits="Product Unit")
    wear_months = fields.Integer(
        "Строк носіння, міс.", default=12,
        help="Нуль - до зносу. Строки беруться з норм безоплатної видачі для професії; "
             "перевірте чинну редакцію.")
    reference = fields.Char("Пункт норм", help="Звідки норма: пункт галузевих норм, колективного договору.")

    @api.constrains("quantity", "wear_months")
    def _check_values(self):
        for norm in self:
            if norm.quantity <= 0 or norm.wear_months < 0:
                raise ValidationError(_("Кількість за нормою - більше нуля, строк носіння - не менше нуля."))


class HrJob(models.Model):
    _inherit = "hr.job"

    ua_workwear_norm_ids = fields.One2many("ua.workwear.norm", "job_id", "Норми спецодягу")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_workwear_line_ids = fields.One2many("ua.workwear.line", "employee_id", "Предмети в експлуатації")

    def ua_tab_number(self):
        """Табельний номер для картки: поле є не в кожній збірці Odoo, і воно закрите групою."""
        self.ensure_one()
        employee = self.sudo()
        return employee["registration_number"] or "" if "registration_number" in employee._fields else ""
    ua_workwear_count = fields.Integer("В експлуатації", compute="_compute_ua_workwear_count")

    def _compute_ua_workwear_count(self):
        counts = dict(self.env["ua.workwear.line"].sudo()._read_group(
            [("employee_id", "in", self.ids), ("state", "=", "in_use")], ["employee_id"], ["__count"]))
        for employee in self:
            employee.ua_workwear_count = counts.get(employee, 0)

    def ua_workwear_due(self, day=None):
        """Чого бракує за нормами посади на дату: [{product, norm, in_use, due, months, reference}]."""
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        valid = defaultdict(float)
        for line in self.ua_workwear_line_ids.filtered(
                lambda l: l.state == "in_use" and (not l.date_until or l.date_until >= day)):
            valid[line.product_id] += line.quantity
        rows = []
        for norm in self.job_id.ua_workwear_norm_ids:
            in_use = valid.get(norm.product_id, 0.0)
            due = norm.product_id.uom_id.round(norm.quantity - in_use)
            rows.append({"product": norm.product_id, "norm": norm.quantity, "in_use": in_use,
                         "due": max(due, 0.0), "months": norm.wear_months, "reference": norm.reference or ""})
        return rows

    def action_ua_workwear(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_workwear.action_ua_workwear_line")
        action["domain"] = [("employee_id", "=", self.id)]
        action["context"] = {"search_default_in_use": 1}
        return action

    def action_ua_print_workwear_card(self):
        return self.env.ref("l10n_ua_workwear.action_report_ua_workwear_card").report_action(self)


class UaWorkwearIssue(models.Model):
    _name = "ua.workwear.issue"
    _description = "Відомість видачі в експлуатацію"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    location_id = fields.Many2one(
        "stock.location", "Склад", required=True, check_company=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1).lot_stock_id)
    expense_account_id = fields.Many2one(
        "account.account", "Рахунок витрат", required=True, check_company=True,
        help="Куди списується вартість виданого: 91 - цех, 92 - управління, 93 - збут, 23 - "
             "конкретне виробництво.")
    employee_ids = fields.Many2many("hr.employee", string="Працівники",
                                    help="Кому заповнювати відомість за нормами посад.")
    line_ids = fields.One2many("ua.workwear.line", "issue_id", "Рядки", copy=True)
    state = fields.Selection([("draft", "Чернетка"), ("done", "Видано"), ("cancel", "Скасовано")],
                             "Стан", required=True, default="draft", tracking=True)
    amount_total = fields.Monetary("Вартість", compute="_compute_amount_total",
                                   currency_field="company_currency_id")
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    note = fields.Text("Примітки")

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for issue in self:
            issue.amount_total = sum(issue.line_ids.mapped("amount"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.workwear.issue", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    def unlink(self):
        if any(issue.state == "done" for issue in self):
            raise UserError(_("Проведену відомість не видаляють: поверніть або спишіть предмети."))
        return super().unlink()

    def action_fill(self):
        """Додати рядки з того, чого працівникам бракує за нормами посад."""
        for issue in self:
            if issue.state != "draft":
                raise UserError(_("Заповнювати можна лише чернетку."))
            if not issue.employee_ids:
                raise UserError(_("Оберіть працівників, яким видаєте."))
            present = {(line.employee_id, line.product_id) for line in issue.line_ids}
            commands = []
            for employee in issue.employee_ids:
                for row in employee.ua_workwear_due(issue.date):
                    if row["due"] > 0 and (employee, row["product"]) not in present:
                        commands.append((0, 0, {"employee_id": employee.id, "product_id": row["product"].id,
                                                "quantity": row["due"], "wear_months": row["months"]}))
            if not commands:
                raise UserError(_("За нормами посад обраним працівникам видавати нічого."))
            issue.write({"line_ids": commands})
        return True

    def _ua_in_use_location(self):
        """Місце «В експлуатації» з рахунком витрат документа; одне на рахунок."""
        self.ensure_one()
        Location = self.env["stock.location"].sudo()
        location = Location.search([("ua_in_use", "=", True), ("company_id", "=", self.company_id.id),
                                    ("valuation_account_id", "=", self.expense_account_id.id)], limit=1)
        if not location:
            # Odoo 19: місця обліку втрат без батьківського «Virtual Locations», як рідні
            location = Location.create({
                "name": _("В експлуатації: %s") % self.expense_account_id.code,
                "usage": "inventory", "company_id": self.company_id.id, "ua_in_use": True,
                "valuation_account_id": self.expense_account_id.id})
        return location

    def action_done(self):
        for issue in self:
            if issue.state != "draft":
                raise UserError(_("Видати можна лише чернетку."))
            if not issue.line_ids:
                raise UserError(_("У відомості %s немає рядків.") % issue.name)
            missing = issue.line_ids.filtered(lambda l: not l.employee_id)
            if missing:
                raise UserError(_("Вкажіть працівника в кожному рядку."))
            destination = issue._ua_in_use_location()
            for line in issue.line_ids:
                move = line._ua_move(issue.location_id, destination, line.quantity)
                value = move.sudo().value or line.quantity * move.product_id.standard_price
                line.write({"state": "in_use", "move_id": move.id,
                            "price_unit": value / line.quantity if line.quantity else 0.0})
            issue.state = "done"
        return True

    def action_cancel(self):
        for issue in self:
            if issue.state == "done":
                raise UserError(_("Видану відомість не скасовують: поверніть предмети на склад."))
        self.write({"state": "cancel"})
        self.line_ids.write({"state": "cancel"})
        return True

    def action_draft(self):
        self.filtered(lambda i: i.state == "cancel").write({"state": "draft"})
        self.line_ids.filtered(lambda l: l.state == "cancel").write({"state": "draft"})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_workwear.action_report_ua_workwear_issue").report_action(self)


class UaWorkwearLine(models.Model):
    _name = "ua.workwear.line"
    _description = "Предмет в експлуатації"
    _order = "date desc, employee_id, id"
    _check_company_auto = True

    issue_id = fields.Many2one("ua.workwear.issue", "Відомість", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="issue_id.company_id", store=True)
    date = fields.Date(related="issue_id.date", store=True, string="Видано")
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, index=True, check_company=True)
    job_id = fields.Many2one(related="employee_id.job_id", string="Посада")
    product_id = fields.Many2one("product.product", "Предмет", required=True,
                                 domain="[('type', '=', 'consu')]")
    quantity = fields.Float("Кількість", default=1.0, required=True, digits="Product Unit")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Одиниця")
    wear_months = fields.Integer("Строк носіння, міс.", help="Нуль - до зносу.")
    date_until = fields.Date("Носити до", compute="_compute_date_until", store=True)
    state = fields.Selection(LINE_STATES, "Стан", required=True, default="draft", index=True)
    price_unit = fields.Float("Ціна видачі", digits="Product Price", readonly=True)
    amount = fields.Monetary("Вартість", compute="_compute_amount", store=True,
                             currency_field="company_currency_id")
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    move_id = fields.Many2one("stock.move", "Рух видачі", readonly=True, copy=False)
    return_move_id = fields.Many2one("stock.move", "Рух повернення", readonly=True, copy=False)
    date_closed = fields.Date("Повернуто або списано", readonly=True, copy=False)
    close_reason = fields.Char("Підстава списання", copy=False)

    @api.depends("date", "wear_months")
    def _compute_date_until(self):
        for line in self:
            line.date_until = (line.date + relativedelta(months=line.wear_months)
                               if line.date and line.wear_months > 0 else False)

    @api.depends("quantity", "price_unit")
    def _compute_amount(self):
        for line in self:
            line.amount = line.company_currency_id.round(line.quantity * line.price_unit)

    @api.onchange("employee_id", "product_id")
    def _onchange_norm(self):
        norm = self.employee_id.job_id.ua_workwear_norm_ids.filtered(lambda n: n.product_id == self.product_id)[:1]
        if norm:
            self.wear_months = norm.wear_months
            self.quantity = norm.quantity

    @api.constrains("quantity", "wear_months")
    def _check_values(self):
        for line in self:
            if line.quantity <= 0 or line.wear_months < 0:
                raise ValidationError(_("Кількість - більше нуля, строк носіння - не менше нуля."))

    def write(self, vals):
        locked = {"employee_id", "product_id", "quantity", "issue_id"}
        if locked & set(vals) and any(line.state not in ("draft", "cancel") for line in self):
            raise UserError(_("Виданий предмет не змінюють: поверніть його і видайте заново."))
        return super().write(vals)

    def _ua_move(self, source, destination, quantity, price_unit=None, origin_move=None):
        """Один рух предмета, одразу проведений. Повернення оцінюється за рухом видачі."""
        self.ensure_one()
        product = self.product_id
        values = {
            "product_id": product.id, "product_uom_qty": quantity, "product_uom": product.uom_id.id,
            "location_id": source.id, "location_dest_id": destination.id,
            "company_id": self.company_id.id, "origin": self.issue_id.name,
            "ua_workwear_line_id": self.id, "date": fields.Datetime.now(),
        }
        if price_unit is not None:
            values["price_unit"] = price_unit
        if origin_move:
            values["origin_returned_move_id"] = origin_move.id
        move = self.env["stock.move"].sudo().create(values)
        move._action_confirm()
        if source.usage == "internal":
            move._action_assign()
            if product.uom_id.compare(move.quantity, quantity) < 0:
                raise UserError(_(
                    "%(where)s: «%(product)s» є %(have)s, а видати треба %(need)s.",
                    where=source.display_name, product=product.display_name,
                    have="%g" % move.quantity, need="%g" % quantity))
        else:
            move.quantity = quantity
        move.picked = True
        move._action_done()
        return move

    def action_return(self, location=None):
        """Повернути з експлуатації на склад відомості за ціною видачі."""
        for line in self:
            if line.state != "in_use":
                raise UserError(_("Повернути можна лише предмет в експлуатації."))
            move = line._ua_move(line.move_id.location_dest_id, location or line.issue_id.location_id,
                                 line.quantity, price_unit=line.price_unit, origin_move=line.move_id)
            line.write({"state": "returned", "return_move_id": move.id,
                        "date_closed": fields.Date.context_today(line)})
        return True

    def action_write_off(self, reason=None):
        """Списати з експлуатації: вартість уже у витратах, лишається акт."""
        for line in self:
            if line.state != "in_use":
                raise UserError(_("Списати можна лише предмет в експлуатації."))
            line.write({"state": "written_off", "date_closed": fields.Date.context_today(line),
                        "close_reason": reason or line.close_reason or _("знос")})
        return True

    @api.model
    def _ua_auto_write_off(self, day=None):
        """Списати предмети з позначкою автосписання, чий строк минув на дату (типово - сьогодні)."""
        day = day or fields.Date.context_today(self)
        lines = self.search([("state", "=", "in_use"), ("date_until", "!=", False), ("date_until", "<=", day),
                             ("product_id.ua_wear_auto_write_off", "=", True)])
        lines.write({"state": "written_off", "date_closed": day,
                     "close_reason": _("строк використання минув")})
        return lines

    @api.model
    def _ua_cron_auto_write_off(self):
        """Щоденна задача; списує лише в останній день місяця."""
        day = fields.Date.context_today(self)
        if (day + relativedelta(days=1)).day != 1:
            return self.browse()
        return self._ua_auto_write_off(day)

    def action_print_write_off(self):
        lines = self.filtered(lambda l: l.state == "written_off")
        if not lines:
            raise UserError(_("Оберіть списані предмети."))
        return self.env.ref("l10n_ua_workwear.action_report_ua_workwear_write_off").report_action(lines)

    def ua_period(self):
        """«12 міс.» або «до зносу» - для друку."""
        self.ensure_one()
        return _("%s міс.") % self.wear_months if self.wear_months else _("до зносу")

    @staticmethod
    def ua_date(value):
        return _ua_date(value)

    @staticmethod
    def money(value):
        """10 000,00 - гроші для друку."""
        text = "{:,.2f}".format(value or 0.0)
        return text.replace(",", " ").replace(".", ",")
