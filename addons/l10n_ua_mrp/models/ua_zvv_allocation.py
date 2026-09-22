# -*- coding: utf-8 -*-
"""Розподіл загальновиробничих витрат за нормальною потужністю.

Пункт 16 П(С)БО 16 ділить ЗВВ надвоє. Змінні (те, що росте разом з випуском -
матеріали цеху, енергія на обладнання) розподіляють повністю, на фактичну
потужність. Постійні (амортизація цеху, оренда, зарплата майстра) розподіляють
за НОРМАЛЬНОЮ потужністю: у собівартість продукції потрапляє тільки та частка,
що відповідає фактичному завантаженню, а решта - нерозподілені постійні ЗВВ -
йде прямо у собівартість реалізації періоду і в запасах не осідає.

Приклад, на якому стоїть тест: постійні ЗВВ 10 000 грн, нормальна потужність
1 000 год, фактично відпрацьовано 800 год. Коефіцієнт 0,8, розподілено
8 000 грн (Дт 231), нерозподілено 2 000 грн (Дт 901).

Нативний Odoo цього не вміє взагалі: у нього є рахунок накладних витрат
виробництва і чарівник незавершеного виробництва, але немає ні поняття
нормальної потужності, ні поділу на розподілені й нерозподілені. Тому це
окремий документ за місяць - з базою, коефіцієнтом, рядками за рахунками ЗВВ і
однією проводкою.

Чого документ навмисно НЕ робить: не переносить розподілені ЗВВ з 231 на 26.
Нативна оцінка запасів веде вартість продукції за матеріалами й оплатою праці,
і якщо дописати туди ЗВВ проводкою, сальдо 26 розійдеться зі звітом оцінки
запасів. Розподілені ЗВВ лишаються на 231 як незавершене виробництво періоду -
це питання до бухгалтера, воно записане в docs/base/spec-mrp-stock.md.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

# Рахунки, з якими працює документ (xmlid шаблону ua_psbo).
ACC_ZVV = "ua_psbp_91"
ACC_WIP = "ua_psbp_231"
ACC_COGS = "ua_psbp_901"


class UaZvvAllocation(models.Model):
    _name = "ua.zvv.allocation"
    _description = "Розподіл загальновиробничих витрат"
    _order = "date_from desc, id desc"
    _rec_name = "name"

    name = fields.Char("Номер", readonly=True, copy=False, default="Новий", index=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    date_from = fields.Date(
        "Початок періоду", required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date("Кінець періоду", required=True, compute="_compute_date_to",
                          store=True, readonly=False, precompute=True)
    state = fields.Selection(
        [("draft", "Чернетка"), ("posted", "Проведено")],
        string="Стан", default="draft", required=True, copy=False)

    normal_hours = fields.Float(
        "Нормальна потужність, год", default=0.0,
        help="Скільки годин цех відпрацьовує при нормальному завантаженні. "
             "Показник із планових розрахунків, а не з факту.")
    actual_hours = fields.Float(
        "Фактично відпрацьовано, год",
        help="Сума тривалості нарядів виробничих замовлень, закритих у періоді. "
             "Кнопка «Розрахувати» заповнює його, руками можна виправити.")
    fixed_share = fields.Float(
        "Частка постійних ЗВВ, %", default=100.0,
        help="Яку частину ЗВВ періоду вважаємо постійною. Змінні ЗВВ "
             "розподіляються повністю, постійні - за коефіцієнтом завантаження.")

    amount_base = fields.Monetary("ЗВВ періоду", currency_field="currency_id", readonly=True)
    amount_fixed = fields.Monetary("Постійні ЗВВ", currency_field="currency_id", readonly=True)
    amount_variable = fields.Monetary("Змінні ЗВВ", currency_field="currency_id", readonly=True)
    coefficient = fields.Float("Коефіцієнт завантаження", readonly=True, digits=(12, 4))
    amount_allocated = fields.Monetary(
        "Розподілено (Дт 231)", currency_field="currency_id", readonly=True)
    amount_unallocated = fields.Monetary(
        "Нерозподілено (Дт 901)", currency_field="currency_id", readonly=True)

    line_ids = fields.One2many("ua.zvv.allocation.line", "allocation_id", string="Рядки")
    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)
    note = fields.Char("Підстава")

    _dates = models.Constraint(
        "CHECK (date_to >= date_from)",
        "Кінець періоду не може бути раніший за початок.",
    )

    @api.depends("date_from")
    def _compute_date_to(self):
        for record in self:
            if record.date_from:
                record.date_to = record.date_from + relativedelta(months=1, days=-1)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "Новий") in (False, "", "Новий"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.zvv.allocation") or "Новий"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Службове
    # ------------------------------------------------------------------
    def _account(self, xmlid):
        self.ensure_one()
        from ..hooks import account_by_xmlid
        account = account_by_xmlid(self.env, self.company_id, xmlid)
        if not account:
            raise UserError(
                "У плані рахунків компанії «%s» немає рахунку %s."
                % (self.company_id.name, xmlid.rsplit("_", 1)[-1]))
        return account

    def _journal(self):
        self.ensure_one()
        journal = self.company_id.account_stock_journal_id or self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.company_id.id)], limit=1)
        if not journal:
            raise UserError("Немає журналу для проводки розподілу ЗВВ.")
        return journal

    def _zvv_balance_by_account(self):
        """Обороти рахунків 91* за період: Дт мінус Кт, по кожному рахунку.

        Власна проводка розподілу кредитує 91, тому повторний розрахунок після
        проведення дає нуль і документ не подвоюється.
        """
        self.ensure_one()
        zvv = self._account(ACC_ZVV)
        accounts = self.env["account.account"].search([
            ("company_ids", "in", self.company_id.id),
            ("code", "=like", zvv.code.rstrip("0") + "%"),
        ])
        if not accounts:
            return []
        groups = self.env["account.move.line"]._read_group(
            [("account_id", "in", accounts.ids),
             ("company_id", "=", self.company_id.id),
             ("parent_state", "=", "posted"),
             ("date", ">=", self.date_from),
             ("date", "<=", self.date_to)],
            ["account_id"], ["balance:sum"])
        return [(account, balance) for account, balance in groups
                if not self.currency_id.is_zero(balance)]

    def _actual_hours_from_orders(self):
        """Години нарядів виробничих замовлень, закритих у періоді."""
        self.ensure_one()
        productions = self.env["mrp.production"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("date_finished", ">=", fields.Datetime.to_datetime(self.date_from)),
            ("date_finished", "<", fields.Datetime.to_datetime(self.date_to) +
             relativedelta(days=1)),
        ])
        minutes = sum(productions.workorder_ids.mapped("duration"))
        return round(minutes / 60.0, 2)

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_compute(self):
        """Зібрати базу, години і коефіцієнт. Рядки перезаписуються."""
        for record in self:
            if record.state != "draft":
                raise UserError("Проведений розподіл не перераховують.")
            balances = record._zvv_balance_by_account()
            base = sum(balance for _account, balance in balances)
            if not record.actual_hours:
                record.actual_hours = record._actual_hours_from_orders()
            fixed = round(base * (record.fixed_share or 0.0) / 100.0, 2)
            variable = round(base - fixed, 2)
            coefficient = 0.0
            if record.normal_hours > 0:
                coefficient = min(record.actual_hours / record.normal_hours, 1.0)
            allocated_fixed = round(fixed * coefficient, 2)
            record.line_ids = [(5, 0, 0)] + [
                (0, 0, {
                    "account_id": account.id,
                    "amount": balance,
                    "amount_allocated": round(
                        balance / base * (variable + allocated_fixed), 2) if base else 0.0,
                })
                for account, balance in balances
            ]
            record.write({
                "amount_base": base,
                "amount_fixed": fixed,
                "amount_variable": variable,
                "coefficient": coefficient,
                "amount_allocated": round(variable + allocated_fixed, 2),
                "amount_unallocated": round(fixed - allocated_fixed, 2),
            })
        return True

    def action_post(self):
        """Одна проводка: Дт 231 розподілене, Дт 901 нерозподілене, Кт 91 усе."""
        for record in self:
            if record.state == "posted":
                raise UserError("Розподіл «%s» уже проведено." % record.name)
            record.action_compute()
            if record.currency_id.is_zero(record.amount_base):
                raise UserError(
                    "За період %s - %s немає загальновиробничих витрат до розподілу."
                    % (record.date_from, record.date_to))
            wip = record._account(ACC_WIP)
            cogs = record._account(ACC_COGS)
            lines = []
            if not record.currency_id.is_zero(record.amount_allocated):
                lines.append((0, 0, {
                    "account_id": wip.id,
                    "name": "Розподілені ЗВВ %s" % record.name,
                    "balance": record.amount_allocated,
                }))
            if not record.currency_id.is_zero(record.amount_unallocated):
                lines.append((0, 0, {
                    "account_id": cogs.id,
                    "name": "Нерозподілені постійні ЗВВ %s" % record.name,
                    "balance": record.amount_unallocated,
                }))
            for line in record.line_ids:
                lines.append((0, 0, {
                    "account_id": line.account_id.id,
                    "name": "Списання ЗВВ %s" % record.name,
                    "balance": -line.amount,
                }))
            move = self.env["account.move"].create({
                "journal_id": record._journal().id,
                "company_id": record.company_id.id,
                "date": record.date_to,
                "ref": "Розподіл ЗВВ %s" % record.name,
                "move_type": "entry",
                "line_ids": lines,
            })
            move.action_post()
            record.write({"move_id": move.id, "state": "posted"})
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
        }


class UaZvvAllocationLine(models.Model):
    _name = "ua.zvv.allocation.line"
    _description = "Рядок розподілу ЗВВ"
    _order = "id"

    allocation_id = fields.Many2one("ua.zvv.allocation", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="allocation_id.company_id", store=True)
    currency_id = fields.Many2one(related="allocation_id.currency_id")
    account_id = fields.Many2one("account.account", string="Рахунок", required=True)
    amount = fields.Monetary("Сума за період", currency_field="currency_id")
    amount_allocated = fields.Monetary("З них розподілено", currency_field="currency_id")
