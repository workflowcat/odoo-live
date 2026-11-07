"""Калькуляція ціни виробу за статтями постанови КМУ № 309.

Планова калькуляція будується зі специфікації (mrp.bom) на один виріб:
  - рядки специфікації з власною специфікацією розкладаються до матеріалів і операцій;
  - товар лягає на свою статтю (01, 02 або 03, поле на товарі);
  - побічна продукція специфікації - зворотні відходи (10), за обліковою ціною;
  - операція маршруту дає години: години x основна зарплата за годину центру (04),
    x енергія за годину (03), x вартість години центру (07).
Фактична калькуляція бере закриті замовлення на виробництво за контрактом і цим виробом:
  - матеріали і комплектуючі - вартість списаних компонентів, за статтею товару;
  - години - фактична тривалість нарядів;
  - послуги сторонніх (02) - рахунки постачальників з аналітикою контракту на послуги,
    частка виробу - за кількістю випущеного серед усіх виробів контракту.
Далі для обох однаково, ставки з контракту:
  05 = 04 x ставка;  06 = (04 + 05) x ЄСВ;  08 = 04 x ставка;  09 = 04 x ставка;
  виробнича собівартість = 01 + ... + 09 - 10;
  адміністративні, збут, інші операційні = база x ставка, база - 04 або виробнича собівартість;
  фінансові = виробнича собівартість x ставка;
  повна собівартість = виробнича + адміністративні + збут + інші операційні + фінансові;
  прибуток = 02 x норматив на покупні + (повна - 02) x норматив на власні;
  ціна = повна + прибуток; ПДВ = ціна x ставка ПДВ контракту.
Рядки 11-20 - підсумки цієї калькуляції, а не номери статей постанови.

У фактичній калькуляції 05, 06, 08, 09 і непрямі витрати рахуються тими самими
нормативами від фактичної 04: фактичні загальновиробничі розподіляє документ ЗВВ
(l10n_ua_mrp), і для звіту замовнику їх беруть звідти.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_DEPTH = 10

ITEMS = [
    ("01", "Сировина і матеріали"),
    ("02", "Покупні комплектуючі, напівфабрикати, роботи і послуги сторонніх"),
    ("03", "Паливо й енергія на технологічні цілі"),
    ("04", "Основна заробітна плата"),
    ("05", "Додаткова заробітна плата"),
    ("06", "Єдиний соціальний внесок"),
    ("07", "Витрати на утримання та експлуатацію обладнання"),
    ("08", "Загальновиробничі витрати"),
    ("09", "Інші виробничі витрати"),
    ("10", "Зворотні відходи (вираховуються)"),
    ("11", "Виробнича собівартість"),
    ("12", "Адміністративні витрати"),
    ("13", "Витрати на збут"),
    ("14", "Інші операційні витрати"),
    ("15", "Фінансові витрати"),
    ("16", "Повна собівартість"),
    ("17", "Прибуток"),
    ("18", "Ціна без ПДВ"),
    ("19", "ПДВ"),
    ("20", "Ціна з ПДВ"),
]
TOTALS = {"11", "16", "18", "20"}


def _round(value):
    return round(value + 0.0, 2)


class UaDefenseCalculation(models.Model):
    _name = "ua.defense.calculation"
    _description = "Калькуляція ціни за постановою КМУ № 309"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    contract_id = fields.Many2one(
        "ua.contract", "Контракт", required=True, index=True, check_company=True,
        domain="[('ua_defense', '=', True)]")
    company_id = fields.Many2one(related="contract_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    kind = fields.Selection(
        [("plan", "Планова"), ("actual", "Фактична")], "Вид", required=True, default="plan")
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    product_id = fields.Many2one("product.product", "Виріб", required=True)
    bom_id = fields.Many2one(
        "mrp.bom", "Специфікація", compute="_compute_bom_id", store=True, readonly=False,
        domain="['|', ('product_id', '=', product_id), '&', ('product_id', '=', False), "
               "('product_tmpl_id.product_variant_ids', 'in', product_id)]")
    plan_id = fields.Many2one(
        "ua.defense.calculation", "Планова калькуляція",
        domain="[('kind', '=', 'plan'), ('contract_id', '=', contract_id), ('product_id', '=', product_id)]",
        help="Фактична калькуляція порівнюється з цією плановою.")
    quantity = fields.Float(
        "Кількість виробів", readonly=True, digits="Product Unit of Measure",
        help="Для фактичної: скільки виробів випущено за закритими замовленнями.")
    hours = fields.Float("Години на виріб", readonly=True)
    state = fields.Selection(
        [("draft", "Чернетка"), ("approved", "Затверджено")], "Стан", default="draft",
        required=True, tracking=True)
    line_ids = fields.One2many("ua.defense.calculation.line", "calculation_id", "Статті", copy=False)
    component_ids = fields.One2many(
        "ua.defense.calculation.component", "calculation_id", "Розшифровка матеріалів", copy=False)
    production_ids = fields.Many2many("mrp.production", string="Замовлення на виробництво", copy=False)
    price_unit = fields.Monetary("Ціна без ПДВ", compute="_compute_prices", store=True)
    price_unit_vat = fields.Monetary("Ціна з ПДВ", compute="_compute_prices", store=True)
    note = fields.Text("Примітки")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "l10n_ua_defense.calculation", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    @api.depends("product_id")
    def _compute_bom_id(self):
        Bom = self.env["mrp.bom"]
        for calculation in self:
            if calculation.bom_id and calculation.bom_id.product_tmpl_id == calculation.product_id.product_tmpl_id:
                continue
            boms = Bom._bom_find(calculation.product_id, company_id=calculation.company_id.id) \
                if calculation.product_id else {}
            calculation.bom_id = boms.get(calculation.product_id, Bom)

    @api.depends("line_ids.amount")
    def _compute_prices(self):
        for calculation in self:
            amounts = {line.code: line.amount for line in calculation.line_ids}
            calculation.price_unit = amounts.get("18", 0.0)
            calculation.price_unit_vat = amounts.get("20", 0.0)

    # ------------------------------------------------------------------
    # Прямі витрати
    # ------------------------------------------------------------------
    def _ua_explode(self, bom, factor, acc, rows, depth=0):
        """Розкласти специфікацію на factor виробів: прямі витрати у acc, рядки у rows."""
        batch = bom.product_qty or 1.0
        for line in bom.bom_line_ids:
            product = line.product_id
            quantity = line.product_uom_id._compute_quantity(
                line.product_qty, product.uom_id, round=False) * factor / batch
            child = line.child_bom_id
            if child and child.type in ("normal", "phantom") and depth < MAX_DEPTH:
                self._ua_explode(child, quantity, acc, rows, depth + 1)
                continue
            item = product.ua_cost_item or "01"
            amount = quantity * (product.standard_price or 0.0)
            acc[item] += amount
            rows.append({"item": item, "product_id": product.id, "quantity": quantity,
                         "price": product.standard_price or 0.0, "amount": amount})
        for operation in bom.operation_ids:
            hours = (operation.time_cycle_manual or 0.0) / 60.0 * factor / batch
            self._ua_hours(operation.workcenter_id, hours, acc)
        for byproduct in bom.byproduct_ids:
            product = byproduct.product_id
            quantity = byproduct.product_uom_id._compute_quantity(
                byproduct.product_qty, product.uom_id, round=False) * factor / batch
            amount = quantity * (product.standard_price or 0.0)
            acc["10"] += amount
            rows.append({"item": "10", "product_id": product.id, "quantity": quantity,
                         "price": product.standard_price or 0.0, "amount": amount})

    @staticmethod
    def _ua_hours(workcenter, hours, acc):
        acc["hours"] += hours
        acc["04"] += hours * (workcenter.ua_wage_hour or 0.0)
        acc["03"] += hours * (workcenter.ua_energy_hour or 0.0)
        acc["07"] += hours * (workcenter.costs_hour or 0.0)

    def _ua_plan_direct(self):
        self.ensure_one()
        if not self.bom_id:
            raise UserError(_("У виробу %(product)s немає специфікації: планову калькуляцію "
                              "немає з чого скласти.", product=self.product_id.display_name))
        acc, rows = defaultdict(float), []
        self._ua_explode(self.bom_id, 1.0, acc, rows)
        return acc, rows, 1.0

    def _ua_actual_productions(self):
        self.ensure_one()
        return self.env["mrp.production"].search([
            ("ua_contract_id", "=", self.contract_id.id),
            ("product_id", "=", self.product_id.id),
            ("state", "=", "done"),
        ])

    def _ua_actual_direct(self):
        """Прямі витрати за закритими замовленнями, поділені на випуск."""
        self.ensure_one()
        productions = self._ua_actual_productions()
        quantity = sum(productions.mapped("qty_produced"))
        if not productions or not quantity:
            raise UserError(_("За контрактом немає закритих замовлень на виробництво виробу %(product)s.",
                              product=self.product_id.display_name))
        acc, rows = defaultdict(float), []
        by_product = defaultdict(lambda: [0.0, 0.0])
        for production in productions:
            for move in production.move_raw_ids.filtered(lambda m: m.state == "done"):
                product = move.product_id
                item = product.ua_cost_item or "01"
                amount = abs(move.value or 0.0)
                acc[item] += amount
                by_product[(item, product.id)][0] += move.quantity
                by_product[(item, product.id)][1] += amount
            for move in production.move_finished_ids.filtered(
                    lambda m: m.state == "done" and m.product_id != production.product_id):
                amount = abs(move.value or 0.0)
                acc["10"] += amount
                by_product[("10", move.product_id.id)][0] += move.quantity
                by_product[("10", move.product_id.id)][1] += amount
            for workorder in production.workorder_ids:
                self._ua_hours(workorder.workcenter_id, (workorder.duration or 0.0) / 60.0, acc)
        services = self._ua_actual_services()
        acc["02"] += services
        for (item, product_id), (qty, amount) in sorted(by_product.items()):
            rows.append({"item": item, "product_id": product_id, "quantity": qty / quantity,
                         "price": amount / qty if qty else 0.0, "amount": amount / quantity})
        for key in list(acc):
            acc[key] = acc[key] / quantity
        self.production_ids = [(6, 0, productions.ids)]
        return acc, rows, quantity

    def _ua_actual_services(self):
        """Послуги сторонніх за контрактом, частка цього виробу за випуском."""
        self.ensure_one()
        analytic = self.contract_id.analytic_account_id
        if not analytic:
            return 0.0
        lines = self.env["account.move.line"].search([
            ("parent_state", "=", "posted"),
            ("move_id.move_type", "in", ("in_invoice", "in_refund")),
            ("display_type", "=", "product"),
            ("analytic_distribution", "in", [analytic.id]),
            ("company_id", "=", self.company_id.id),
        ])
        lines = lines.filtered(lambda line: line.product_id.type == "service"
                               and (line.product_id.ua_cost_item or "02") == "02")
        total = sum(line.balance * (line.analytic_distribution or {}).get(str(analytic.id), 0.0) / 100.0
                    for line in lines)
        if not total:
            return 0.0
        all_done = self.env["mrp.production"].search([
            ("ua_contract_id", "=", self.contract_id.id), ("state", "=", "done")])
        everything = sum(all_done.mapped("qty_produced"))
        mine = sum(all_done.filtered(lambda p: p.product_id == self.product_id).mapped("qty_produced"))
        return total * mine / everything if everything else 0.0

    # ------------------------------------------------------------------
    # Повна калькуляція
    # ------------------------------------------------------------------
    def _ua_rates(self):
        c = self.contract_id
        return {
            "additional": c.ua_rate_additional_wage / 100.0,
            "esv": c.ua_rate_esv / 100.0,
            "overhead": c.ua_rate_overhead / 100.0,
            "other_production": c.ua_rate_other_production / 100.0,
            "admin": c.ua_rate_admin / 100.0,
            "selling": c.ua_rate_selling / 100.0,
            "other_operating": c.ua_rate_other_operating / 100.0,
            "financial": c.ua_rate_financial / 100.0,
            "profit_purchased": c.ua_rate_profit_purchased / 100.0,
            "profit_own": c.ua_rate_profit_own / 100.0,
            "vat": c.ua_vat_rate / 100.0,
            "base": c.ua_indirect_base,
        }

    @staticmethod
    def _ua_assemble(direct, rates):
        """Статті 01-20 на один виріб з прямих витрат і ставок. Округлення - до копійки на статтю."""
        a = {code: _round(direct.get(code, 0.0)) for code in ("01", "02", "03", "04", "07", "10")}
        a["05"] = _round(a["04"] * rates["additional"])
        a["06"] = _round((a["04"] + a["05"]) * rates["esv"])
        a["08"] = _round(a["04"] * rates["overhead"])
        a["09"] = _round(a["04"] * rates["other_production"])
        a["11"] = _round(sum(a[c] for c in ("01", "02", "03", "04", "05", "06", "07", "08", "09")) - a["10"])
        base = a["04"] if rates["base"] == "wage" else a["11"]
        a["12"] = _round(base * rates["admin"])
        a["13"] = _round(base * rates["selling"])
        a["14"] = _round(base * rates["other_operating"])
        a["15"] = _round(a["11"] * rates["financial"])
        a["16"] = _round(a["11"] + a["12"] + a["13"] + a["14"] + a["15"])
        a["17"] = _round(a["02"] * rates["profit_purchased"] + (a["16"] - a["02"]) * rates["profit_own"])
        a["18"] = _round(a["16"] + a["17"])
        a["19"] = _round(a["18"] * rates["vat"])
        a["20"] = _round(a["18"] + a["19"])
        return a

    def action_compute(self):
        for calculation in self:
            if calculation.state == "approved":
                raise UserError(_("Затверджену калькуляцію не перераховують. Поверніть її в чернетку."))
            if calculation.kind == "plan":
                direct, rows, quantity = calculation._ua_plan_direct()
            else:
                direct, rows, quantity = calculation._ua_actual_direct()
                if not calculation.plan_id:
                    calculation.plan_id = self.search([
                        ("kind", "=", "plan"), ("contract_id", "=", calculation.contract_id.id),
                        ("product_id", "=", calculation.product_id.id)], limit=1)
            amounts = self._ua_assemble(direct, calculation._ua_rates())
            plan = {line.code: line.amount for line in calculation.plan_id.line_ids}
            calculation.line_ids = [(5, 0, 0)] + [(0, 0, {
                "code": code,
                "name": name,
                "amount": amounts[code],
                "amount_total": _round(amounts[code] * quantity),
                "plan_amount": plan.get(code, 0.0),
                "is_total": code in TOTALS,
            }) for code, name in ITEMS]
            calculation.component_ids = [(5, 0, 0)] + [(0, 0, {
                "item": row["item"],
                "product_id": row["product_id"],
                "quantity": row["quantity"],
                "price": row["price"],
                "amount": _round(row["amount"]),
            }) for row in rows]
            calculation.write({"quantity": quantity, "hours": round(direct.get("hours", 0.0), 4)})
        return True

    def action_approve(self):
        for calculation in self:
            if not calculation.line_ids:
                raise UserError(_("Спершу перерахуйте калькуляцію."))
        self.write({"state": "approved"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_print(self):
        return self.env.ref("l10n_ua_defense.action_report_ua_defense_calculation").report_action(self)

    def _ua_amount(self, code):
        self.ensure_one()
        return sum(self.line_ids.filtered(lambda line: line.code == code).mapped("amount"))


class UaDefenseCalculationLine(models.Model):
    _name = "ua.defense.calculation.line"
    _description = "Стаття калькуляції"
    _order = "calculation_id, code"

    calculation_id = fields.Many2one(
        "ua.defense.calculation", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="calculation_id.currency_id")
    code = fields.Char("Код", required=True)
    name = fields.Char("Стаття", required=True)
    amount = fields.Monetary("На виріб")
    amount_total = fields.Monetary("На випуск")
    plan_amount = fields.Monetary("План на виріб")
    difference = fields.Monetary("Відхилення від плану", compute="_compute_difference")
    is_total = fields.Boolean("Підсумок")

    @api.depends("amount", "plan_amount", "calculation_id.kind")
    def _compute_difference(self):
        for line in self:
            line.difference = (line.amount - line.plan_amount) if line.calculation_id.kind == "actual" else 0.0


class UaDefenseCalculationComponent(models.Model):
    _name = "ua.defense.calculation.component"
    _description = "Розшифровка матеріалів калькуляції"
    _order = "calculation_id, item, id"

    calculation_id = fields.Many2one(
        "ua.defense.calculation", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="calculation_id.currency_id")
    item = fields.Selection(
        [("01", "01"), ("02", "02"), ("03", "03"), ("10", "10")], "Стаття", required=True)
    product_id = fields.Many2one("product.product", "Матеріал, комплектуючий", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    quantity = fields.Float("Норма на виріб", digits="Product Unit of Measure")
    price = fields.Float("Ціна", digits="Product Price")
    amount = fields.Monetary("Сума на виріб")
