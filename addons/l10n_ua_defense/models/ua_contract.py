"""Оборонний контракт - договір з покупцем з позначкою «оборонний».

Що додаємо до договору:
  - замовник і закупівля: хто замовив (Міноборони, ДОТ, АОЗ, НГУ, ДПСУ, генпідрядник),
    ідентифікатор закупівлі в Prozorro або номер у реєстрі, вид ціни, аванс;
  - нормативи калькуляції (ставки у відсотках): за ними будується планова і фактична
    калькуляція. Модуль ставок не вигадує - це умови конкретного контракту і
    погоджених з замовником розрахунків;
  - графік поставки: виріб, кількість, строк; прийнято - з актів приймання.

Окремий облік (постанова КМУ № 363) вмикається з позначкою: договір отримує
аналітичний рахунок (l10n_ua_contract), і він лягає на замовлення, рахунки й закупівлі.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CUSTOMERS = [
    ("mod", "Міністерство оборони"),
    ("dot", "Державний оператор тилу"),
    ("aoz", "Агенція оборонних закупівель"),
    ("ngu", "Національна гвардія"),
    ("dpsu", "Державна прикордонна служба"),
    ("other_state", "Інший державний замовник"),
    ("prime", "Генеральний підрядник"),
]
PRICE_TYPES = [
    ("fixed", "Тверда"),
    ("fixed_review", "Тверда з переглядом"),
    ("approx", "Орієнтовна"),
    ("cost", "Відшкодування витрат"),
]


class UaContract(models.Model):
    _inherit = "ua.contract"

    ua_defense = fields.Boolean(
        "Оборонний контракт",
        help="Державний контракт (договір) з оборонних закупівель: окремий облік витрат, "
             "калькуляція ціни за статтями, графік поставки, акти приймання.")
    ua_customer_kind = fields.Selection(CUSTOMERS, "Замовник")
    ua_procurement_ref = fields.Char(
        "Ідентифікатор закупівлі", help="Номер закупівлі в Prozorro або в реєстрі замовника.")
    ua_price_type = fields.Selection(PRICE_TYPES, "Вид ціни", default="fixed")
    ua_advance_percent = fields.Float("Аванс, %")
    ua_vat_rate = fields.Float(
        "ПДВ, %", default=20.0,
        help="Нуль, якщо постачання звільнене від ПДВ (наприклад, за підрозділом 2 розділу XX "
             "Податкового кодексу). Перевірте підставу у вашого бухгалтера.")

    # Нормативи калькуляції, %
    ua_rate_additional_wage = fields.Float("05 Додаткова зарплата, % від 04")
    ua_rate_esv = fields.Float("06 ЄСВ, % від 04 і 05", default=22.0)
    ua_rate_overhead = fields.Float("08 Загальновиробничі, % від 04")
    ua_rate_other_production = fields.Float("09 Інші виробничі, % від 04")
    ua_indirect_base = fields.Selection(
        [("wage", "Основна зарплата (04)"), ("cost", "Виробнича собівартість")],
        "База адміністративних, збуту та інших", default="wage", required=True)
    ua_rate_admin = fields.Float("Адміністративні, %")
    ua_rate_selling = fields.Float("Збут, %")
    ua_rate_other_operating = fields.Float("Інші операційні, %")
    ua_rate_financial = fields.Float("Фінансові, % від виробничої собівартості")
    ua_rate_profit_purchased = fields.Float(
        "Прибуток на покупні (02), %",
        help="Норматив прибутку на вартість покупних комплектуючих і послуг сторонніх.")
    ua_rate_profit_own = fields.Float(
        "Прибуток на власні витрати, %",
        help="Норматив прибутку на повну собівартість без покупних комплектуючих (02).")

    ua_schedule_ids = fields.One2many("ua.defense.schedule", "contract_id", "Графік поставки")
    ua_calculation_ids = fields.One2many("ua.defense.calculation", "contract_id", "Калькуляції")
    ua_acceptance_ids = fields.One2many("ua.defense.acceptance", "contract_id", "Акти приймання")
    ua_production_count = fields.Integer("Замовлення на виробництво", compute="_compute_ua_defense_counts")
    ua_schedule_late = fields.Boolean("Є прострочені поставки", compute="_compute_ua_schedule_late")

    @api.onchange("ua_defense")
    def _onchange_ua_defense(self):
        if self.ua_defense:
            self.kind = "sale"
            self.separate_accounting = True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("ua_defense"):
                vals.setdefault("kind", "sale")
                vals["separate_accounting"] = True
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("ua_defense"):
            vals["separate_accounting"] = True
        return super().write(vals)

    @api.constrains("ua_defense", "kind", "separate_accounting")
    def _check_ua_defense(self):
        for contract in self.filtered("ua_defense"):
            if contract.kind != "sale":
                raise ValidationError(_("Оборонний контракт - це договір з покупцем (замовником)."))
            if not contract.separate_accounting:
                raise ValidationError(_("За оборонним контрактом окремий облік витрат обов'язковий."))

    def _compute_ua_defense_counts(self):
        Production = self.env["mrp.production"]
        for contract in self:
            contract.ua_production_count = Production.search_count(
                [("ua_contract_id", "=", contract.id)]) if contract.id else 0

    @api.depends("ua_schedule_ids.state")
    def _compute_ua_schedule_late(self):
        for contract in self:
            contract.ua_schedule_late = any(line.state == "late" for line in contract.ua_schedule_ids)

    def action_view_productions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Виробництво за контрактом"),
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("ua_contract_id", "=", self.id)],
            "context": {"default_ua_contract_id": self.id},
        }

    def action_new_plan_calculation(self):
        """Планова калькуляція на перший виріб графіка без калькуляції."""
        self.ensure_one()
        planned = self.ua_calculation_ids.filtered(lambda c: c.kind == "plan").product_id
        line = self.ua_schedule_ids.filtered(lambda s: s.product_id not in planned)[:1] or self.ua_schedule_ids[:1]
        calculation = self.env["ua.defense.calculation"].create({
            "contract_id": self.id,
            "product_id": line.product_id.id,
            "kind": "plan",
        })
        if calculation.bom_id:
            calculation.action_compute()
        return {
            "type": "ir.actions.act_window",
            "res_model": "ua.defense.calculation",
            "res_id": calculation.id,
            "view_mode": "form",
        }

    def _ua_accepted_qty(self, product):
        """Скільки виробів прийнято за затвердженими актами."""
        self.ensure_one()
        lines = self.ua_acceptance_ids.filtered(lambda a: a.state == "done").line_ids
        return sum(lines.filtered(lambda line: line.product_id == product).mapped("qty_accepted"))


class UaDefenseSchedule(models.Model):
    _name = "ua.defense.schedule"
    _description = "Графік поставки за оборонним контрактом"
    _order = "contract_id, date, id"

    contract_id = fields.Many2one("ua.contract", "Контракт", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="contract_id.company_id", store=True)
    product_id = fields.Many2one("product.product", "Виріб", required=True)
    quantity = fields.Float("Кількість", required=True, digits="Product Unit of Measure")
    date = fields.Date("Строк поставки", required=True)
    qty_accepted = fields.Float(
        "Прийнято", compute="_compute_qty_accepted", digits="Product Unit of Measure",
        help="Прийняте за актами розкладається на рядки графіка за строком: спершу найраніший.")
    state = fields.Selection(
        [("planned", "Заплановано"), ("done", "Поставлено"), ("late", "Прострочено")],
        "Стан", compute="_compute_qty_accepted")

    @api.depends("contract_id.ua_acceptance_ids.state", "contract_id.ua_acceptance_ids.line_ids.qty_accepted",
                 "quantity", "date", "product_id")
    def _compute_qty_accepted(self):
        today = fields.Date.context_today(self)
        taken = {}
        for contract in self.contract_id:
            for product in contract.ua_schedule_ids.product_id:
                left = contract._ua_accepted_qty(product)
                for line in contract.ua_schedule_ids.filtered(
                        lambda s, p=product: s.product_id == p).sorted(lambda s: (s.date, s.id)):
                    taken[line.id] = min(line.quantity, left)
                    left -= taken[line.id]
        for line in self:
            line.qty_accepted = taken.get(line.id, 0.0)
            if line.quantity and line.qty_accepted >= line.quantity:
                line.state = "done"
            elif line.date and line.date < today:
                line.state = "late"
            else:
                line.state = "planned"
