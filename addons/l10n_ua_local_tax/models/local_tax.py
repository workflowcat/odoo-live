"""Місцеві податки: нерухомість, земля, екологічний податок.

Нерухомість, відмінна від земельної ділянки (ПКУ ст. 266): юрособа сама рахує податок за рік на
1 січня, площа x ставка громади у відсотках мінімальної зарплати на 1 січня; сплата
поквартально. Частина об'єктів не є об'єктом оподаткування (пп. 266.2.2, наприклад виробничі
корпуси і склади промислових підприємств): вони лишаються в розрахунку з нулем і підставою.

Плата за землю (ст. 269-289): у власності - нормативна грошова оцінка x ставка або сума за
гектар, якщо оцінки немає; оренда - річна орендна плата за договором. Сплата щомісяця.

Зміна власника: попередній платить з 1 січня до початку місяця, в якому втратив право, новий -
з місяця, в якому набув. Тому в році рахуються місяці з місяця набуття до місяця перед втратою.

Екологічний податок (ст. 240-250): за квартал, фактичні обсяги x ставки за речовинами.

Ставки і строки - з рішення громади і чинної редакції кодексу: тут вони поля, не константи.
"""
import calendar
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round

OBJECT_KINDS = [("property", "Нежитлова нерухомість"), ("land", "Земельна ділянка у власності"),
                ("rent", "Оренда землі")]
RETURN_KINDS = [("property", "Податок на нерухоме майно"), ("land", "Плата за землю"),
                ("env", "Екологічний податок")]
ENV_KINDS = [("air", "Викиди в атмосферне повітря"), ("co2", "Викиди двоокису вуглецю"),
             ("water", "Скиди у водні об'єкти"), ("waste", "Розміщення відходів")]
STATES = [("draft", "Чернетка"), ("posted", "Нараховано")]
QUARTER_END = {1: 3, 2: 6, 3: 9, 4: 12}


def _d(day):
    return day.strftime("%d.%m.%Y") if day else ""


def _month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def _money(value):
    return float_round(value, precision_digits=2)


class UaLocalTaxObject(models.Model):
    _name = "ua.local.tax.object"
    _description = "Об'єкт місцевих податків"
    _inherit = ["mail.thread"]
    _order = "kind, name"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    name = fields.Char("Назва", required=True, tracking=True)
    kind = fields.Selection(OBJECT_KINDS, "Вид", required=True, default="property", tracking=True)
    address = fields.Char("Адреса")
    cadastral_number = fields.Char("Кадастровий або реєстраційний номер")
    territory = fields.Char("Територіальна громада", help="Куди сплачується: громада за місцем об'єкта.")
    area = fields.Float("Площа", digits=(16, 4), tracking=True,
                        help="Нерухомість - у квадратних метрах, земля - у гектарах.")
    rate_percent = fields.Float("Ставка, %", digits=(16, 4), tracking=True,
                                help="Нерухомість - відсоток мінімальної зарплати за 1 кв. м; земля - відсоток "
                                     "нормативної грошової оцінки. Рішення громади: перевірте чинне.")
    valuation = fields.Monetary("Нормативна грошова оцінка", tracking=True,
                                help="На 1 січня року, з урахуванням індексації.")
    rate_per_ha = fields.Monetary("Сума за гектар (без оцінки)", tracking=True)
    annual_rent = fields.Monetary("Орендна плата за рік", tracking=True)
    date_from = fields.Date("Право з", required=True, tracking=True)
    date_to = fields.Date("Право до", tracking=True, help="Дата продажу, припинення оренди тощо.")
    exempt = fields.Boolean("Не є об'єктом оподаткування", tracking=True)
    exempt_reason = fields.Char("Підстава", help="Наприклад, пп. 266.2.2 ПКУ: виробничий корпус.")
    expense_account_id = fields.Many2one("account.account", "Рахунок витрат", check_company=True,
                                         default=lambda self: self._ua_default_account(("92",)))
    liability_account_id = fields.Many2one("account.account", "Рахунок розрахунків", check_company=True,
                                           default=lambda self: self._ua_default_account(("6414", "642", "641")))
    currency_id = fields.Many2one(related="company_id.currency_id")
    active = fields.Boolean(default=True)
    note = fields.Text("Примітка")

    @api.model
    def _ua_default_account(self, prefixes, company=None):
        Account = self.env["account.account"]
        for prefix in prefixes:
            account = Account.search([*Account._check_company_domain(company or self.env.company),
                                      ("code", "=like", prefix + "%")], limit=1, order="code")
            if account:
                return account
        return Account

    @api.constrains("date_from", "date_to", "exempt", "exempt_reason")
    def _check_ua_object(self):
        for record in self:
            if record.date_to and record.date_to < record.date_from:
                raise ValidationError(_("Право закінчується раніше, ніж виникло: %s") % record.name)
            if record.exempt and not record.exempt_reason:
                raise ValidationError(_("Вкажіть підставу, чому %s не є об'єктом оподаткування.") % record.name)

    def ua_months(self, year):
        """Місяці року, за які платить власник: з місяця набуття до місяця перед втратою права."""
        self.ensure_one()
        first = 1 if self.date_from.year < year else (self.date_from.month if self.date_from.year == year else 13)
        if not self.date_to or self.date_to.year > year:
            last = 12
        elif self.date_to.year == year:
            last = self.date_to.month - 1
        else:
            last = 0
        return list(range(first, last + 1))

    def ua_annual(self, min_wage=0.0):
        """Сума за повний рік."""
        self.ensure_one()
        if self.exempt:
            return 0.0
        if self.kind == "property":
            return _money(self.area * min_wage * self.rate_percent / 100.0)
        if self.kind == "land":
            if self.valuation:
                return _money(self.valuation * self.rate_percent / 100.0)
            return _money(self.area * self.rate_per_ha)
        return _money(self.annual_rent)


class UaLocalTaxReturn(models.Model):
    _name = "ua.local.tax.return"
    _description = "Розрахунок місцевого податку"
    _inherit = ["mail.thread"]
    _order = "year desc, quarter desc, kind, id desc"
    _check_company_auto = True

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    kind = fields.Selection(RETURN_KINDS, "Податок", required=True, default="property", tracking=True)
    year = fields.Integer("Рік", required=True, default=lambda self: fields.Date.context_today(self).year,
                          tracking=True)
    quarter = fields.Selection([("1", "I"), ("2", "II"), ("3", "III"), ("4", "IV")], "Квартал",
                               help="Лише для екологічного податку.")
    min_wage = fields.Monetary("Мінімальна зарплата на 1 січня",
                               help="Для податку на нерухомість. Підставляється з параметрів зарплати, якщо "
                                    "вони є; перевірте закон про бюджет.")
    journal_id = fields.Many2one("account.journal", "Журнал", required=True, check_company=True,
                                 default=lambda self: self.env["account.journal"].search(
                                     [*self.env["account.journal"]._check_company_domain(self.env.company),
                                      ("type", "=", "general")], limit=1))
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True)
    line_ids = fields.One2many("ua.local.tax.line", "return_id", "Рядки", copy=True)
    move_ids = fields.Many2many("account.move", string="Проводки", copy=False, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount_total = fields.Monetary("Разом", compute="_compute_amount_total", store=True)
    due_date = fields.Date("Подати до", compute="_compute_due_date",
                           help="Декларація юрособи: за рік - до 20 лютого, екологічний податок - 40 днів "
                                "після кварталу. Перевірте чинну редакцію.")
    note = fields.Text("Примітка")


    @api.depends("kind", "year", "quarter")
    def _compute_name(self):
        kinds = dict(RETURN_KINDS)
        for record in self:
            period = (_("%(q)s квартал %(y)s", q=dict(self._fields["quarter"].selection).get(record.quarter, ""),
                        y=record.year) if record.kind == "env" else _("%s рік") % record.year)
            record.name = "%s, %s" % (kinds.get(record.kind, ""), period)

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for record in self:
            record.amount_total = sum(record.line_ids.mapped("amount"))

    @api.depends("kind", "year", "quarter")
    def _compute_due_date(self):
        for record in self:
            if not record.year:
                record.due_date = False
            elif record.kind == "env":
                record.due_date = (_month_end(record.year, QUARTER_END[int(record.quarter)]) + timedelta(days=40)
                                   if record.quarter else False)
            else:
                record.due_date = date(record.year, 2, 20)

    @api.constrains("kind", "quarter", "year", "company_id")
    def _check_period(self):
        for record in self:
            if record.kind == "env" and not record.quarter:
                raise ValidationError(_("Екологічний податок рахується за квартал: оберіть квартал."))
            if record.kind != "env" and record.quarter:
                raise ValidationError(_("Податок на нерухомість і плату за землю рахують за рік, без кварталу."))
            if self.search_count([("id", "!=", record.id), ("company_id", "=", record.company_id.id),
                                  ("kind", "=", record.kind), ("year", "=", record.year),
                                  ("quarter", "=", record.quarter)]):
                raise ValidationError(_("Такий розрахунок за цей період уже є: %s") % record.name)

    @api.onchange("kind", "year")
    def _onchange_ua_min_wage(self):
        if self.kind == "property" and self.year and not self.min_wage:
            self.min_wage = self._ua_min_wage()

    def _ua_min_wage(self):
        """Мінімальна зарплата на 1 січня з параметрів зарплати, якщо модуль зарплати встановлено."""
        self.ensure_one()
        if "ua.payroll.param" not in self.env:
            return 0.0
        Param = self.env["ua.payroll.param"].sudo()
        for company in (self.company_id.id, False):
            param = Param.search([("key", "=", "min_wage"), ("valid_from", "<=", date(self.year, 1, 1)),
                                  ("company_id", "=", company)], order="valid_from desc", limit=1)
            if param:
                return param.value
        return 0.0

    # ------------------------------------------------------------------ заповнення
    def action_fill(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            if record.kind == "env":
                raise UserError(_("Екологічний податок заповнюють речовинами або копіюють з попереднього кварталу."))
            if record.kind == "property" and not record.min_wage:
                record.min_wage = record._ua_min_wage()
            kinds = ("property",) if record.kind == "property" else ("land", "rent")
            start, end = date(record.year, 1, 1), date(record.year, 12, 31)
            objects = self.env["ua.local.tax.object"].search([
                ("company_id", "=", record.company_id.id), ("kind", "in", kinds),
                ("date_from", "<=", end), "|", ("date_to", "=", False), ("date_to", ">=", start)])
            record.line_ids.unlink()
            record.line_ids = [(0, 0, {"object_id": obj.id}) for obj in objects if obj.ua_months(record.year)]
            record.line_ids._ua_recompute()
        return True

    def action_copy_previous(self):
        """Склад речовин і ставки з попереднього кварталу, кількості - нулі."""
        for record in self:
            if record.kind != "env" or record.state != "draft":
                raise UserError(_("Копіюють склад лише в чернетку екологічного податку."))
            quarter, year = int(record.quarter) - 1, record.year
            if quarter == 0:
                quarter, year = 4, year - 1
            previous = self.search([("company_id", "=", record.company_id.id), ("kind", "=", "env"),
                                    ("year", "=", year), ("quarter", "=", str(quarter))], limit=1)
            if not previous:
                raise UserError(_("Немає розрахунку за попередній квартал."))
            have = set(record.line_ids.mapped("name"))
            record.line_ids = [(0, 0, {"name": line.name, "env_kind": line.env_kind, "rate": line.rate,
                                       "expense_account_id": line.expense_account_id.id,
                                       "liability_account_id": line.liability_account_id.id})
                               for line in previous.line_ids if line.name not in have]
        return True

    # ------------------------------------------------------------------ нарахування
    def ua_schedule(self):
        """[(дата кінця періоду, сума)] за всіма рядками."""
        self.ensure_one()
        totals = {}
        for line in self.line_ids:
            for day, amount in line.ua_split():
                totals[day] = totals.get(day, 0.0) + amount
        return [(day, _money(totals[day])) for day in sorted(totals)]

    def action_post(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Розрахунок уже нараховано."))
            if not record.line_ids:
                raise UserError(_("У розрахунку немає рядків."))
            if record.kind == "property" and not record.min_wage and record.line_ids.filtered(lambda l: not l.exempt):
                raise UserError(_("Вкажіть мінімальну зарплату на 1 січня."))
            record.line_ids._ua_recompute()
            no_account = record.line_ids.filtered(
                lambda l: l.amount and not (l.expense_account_id and l.liability_account_id))
            if no_account:
                raise UserError(_("Вкажіть рахунки витрат і розрахунків: %s") % ", ".join(no_account.mapped("name")))
            moves = self.env["account.move"]
            kind_label = dict(RETURN_KINDS)[record.kind]
            for day in sorted({day for line in record.line_ids for day, _amount in line.ua_split()}):
                debit, credit = [], {}
                for line in record.line_ids:
                    amount = dict(line.ua_split()).get(day, 0.0)
                    if not amount:
                        continue
                    debit.append((0, 0, {"name": "%s: %s" % (kind_label, line.name),
                                         "account_id": line.expense_account_id.id, "debit": amount}))
                    credit[line.liability_account_id] = credit.get(line.liability_account_id, 0.0) + amount
                if not debit:
                    continue
                lines = debit + [(0, 0, {"name": kind_label, "account_id": account.id, "credit": _money(amount)})
                                 for account, amount in credit.items()]
                moves |= self.env["account.move"].create({
                    "move_type": "entry", "journal_id": record.journal_id.id, "date": day,
                    "ref": "%s, %s" % (record.name, _d(day)), "line_ids": lines})
            moves.action_post()
            record.write({"move_ids": [(6, 0, moves.ids)], "state": "posted"})
        return True

    def action_draft(self):
        """Повернути в чернетку: проводки сторнуються."""
        for record in self:
            posted = record.move_ids.filtered(lambda m: m.state == "posted")
            if posted:
                posted._reverse_moves([{"ref": _("Сторно: %s") % move.ref, "date": move.date} for move in posted],
                                      cancel=True)
            record.move_ids.filtered(lambda m: m.state == "draft").unlink()
            record.write({"state": "draft", "move_ids": [(5, 0, 0)]})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_local_tax.action_report_ua_local_tax_return").report_action(self)

    def ua_date(self, day):
        return _d(day)

    def ua_kind_label(self):
        self.ensure_one()
        return dict(RETURN_KINDS).get(self.kind, "")

    @api.ondelete(at_uninstall=False)
    def _unlink_except_posted(self):
        if any(record.state == "posted" for record in self):
            raise UserError(_("Нарахований розрахунок не видаляють: поверніть його в чернетку."))


class UaLocalTaxLine(models.Model):
    _name = "ua.local.tax.line"
    _description = "Рядок розрахунку місцевого податку"
    _order = "return_id, id"

    return_id = fields.Many2one("ua.local.tax.return", required=True, index=True, ondelete="cascade")
    kind = fields.Selection(related="return_id.kind")
    currency_id = fields.Many2one(related="return_id.currency_id")
    object_id = fields.Many2one("ua.local.tax.object", "Об'єкт")
    name = fields.Char("Об'єкт або речовина", required=True, compute="_compute_name", store=True, readonly=False,
                       precompute=True)
    env_kind = fields.Selection(ENV_KINDS, "Вид забруднення")
    area = fields.Float("Площа", digits=(16, 4), readonly=True)
    base = fields.Monetary("База за рік", readonly=True,
                           help="Нерухомість - мінімальна зарплата x площа; земля - оцінка або площа; оренда - плата.")
    rate_percent = fields.Float("Ставка, %", digits=(16, 4), readonly=True)
    months = fields.Integer("Місяців", readonly=True)
    exempt = fields.Boolean("Не об'єкт", readonly=True)
    quantity = fields.Float("Кількість, т", digits=(16, 4))
    rate = fields.Float("Ставка, грн за т", digits=(16, 2))
    amount = fields.Monetary("Сума", compute="_compute_amount", store=True, readonly=False)
    expense_account_id = fields.Many2one("account.account", "Рахунок витрат", compute="_compute_accounts",
                                         store=True, readonly=False)
    liability_account_id = fields.Many2one("account.account", "Рахунок розрахунків", compute="_compute_accounts",
                                           store=True, readonly=False)

    @api.depends("object_id")
    def _compute_name(self):
        for line in self:
            line.name = line.object_id.name if line.object_id else line.name

    @api.depends("object_id")
    def _compute_accounts(self):
        Object = self.env["ua.local.tax.object"]
        for line in self:
            company = line.return_id.company_id or self.env.company
            line.expense_account_id = (line.object_id.expense_account_id or line.expense_account_id
                                       or Object._ua_default_account(("92",), company))
            line.liability_account_id = (line.object_id.liability_account_id or line.liability_account_id
                                         or Object._ua_default_account(("6414", "642", "641"), company))

    @api.depends("quantity", "rate")
    def _compute_amount(self):
        for line in self:
            line.amount = _money(line.quantity * line.rate) if not line.object_id else line.amount

    def _ua_recompute(self):
        """Знімок об'єкта на рік розрахунку: площа, база, ставка, місяці, сума."""
        for line in self.filtered("object_id"):
            obj, record = line.object_id, line.return_id
            months = obj.ua_months(record.year)
            annual = obj.ua_annual(record.min_wage)
            if obj.kind == "property":
                base = obj.area * record.min_wage
            elif obj.kind == "land":
                base = obj.valuation or obj.area * obj.rate_per_ha
            else:
                base = obj.annual_rent
            line.write({"name": obj.name, "area": obj.area, "base": _money(base),
                        "rate_percent": obj.rate_percent if obj.kind != "rent" else 0.0,
                        "months": len(months), "exempt": obj.exempt,
                        "amount": _money(annual * len(months) / 12.0)})

    def ua_env_kind_label(self):
        self.ensure_one()
        return dict(ENV_KINDS).get(self.env_kind, "")

    def ua_split(self):
        """[(кінець періоду, сума)]: нерухомість - квартали, земля - місяці, екологія - квартал."""
        self.ensure_one()
        record = self.return_id
        if record.kind == "env":
            return [(_month_end(record.year, QUARTER_END[int(record.quarter)]), self.amount)] if self.amount else []
        if not self.object_id or not self.amount:
            return []
        months = self.object_id.ua_months(record.year)
        annual = self.object_id.ua_annual(record.min_wage)
        if record.kind == "property":
            periods = [(QUARTER_END[q], [m for m in months if QUARTER_END[q] - 2 <= m <= QUARTER_END[q]])
                       for q in (1, 2, 3, 4)]
        else:
            periods = [(m, [m]) for m in months]
        out, done, posted = [], 0, 0.0
        for end_month, inside in periods:
            if not inside:
                continue
            done += len(inside)
            cumulative = _money(annual * done / 12.0)
            out.append((_month_end(record.year, end_month), _money(cumulative - posted)))
            posted = cumulative
        return out
