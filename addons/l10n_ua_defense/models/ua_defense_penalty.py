"""Пеня і штраф за прострочення поставки за оборонним контрактом.

Розмір санкцій - умова контракту: пеня (відсоток за кожен день прострочення) від вартості
товару, з яким допущено прострочення, і штраф (відсоток тієї самої вартості), коли
прострочення довше за вказану кількість днів. Типове формулювання державних контрактів -
0,1 % за день і 7 % за прострочення понад 30 днів; значення стоять на контракті, щоб їх
звірили з його текстом.

Розрахунок на дату:

    прийняте за затвердженими актами (до дати розрахунку) розкладається на рядки графіка
    за строком, спершу найраніший, - так само, як стан рядка графіка;
    частина, прийнята після строку, - прострочення від строку до дати акта;
    частина, не прийнята на дату розрахунку, - прострочення від строку до цієї дати;
    днів прострочення = дата поставки (або розрахунку) - строк;
    пеня = вартість частини x ставка пені x днів; штраф = вартість частини x ставка штрафу,
    якщо днів більше за поріг.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UaContract(models.Model):
    _inherit = "ua.contract"

    ua_penalty_rate = fields.Float(
        "Пеня, % за день", default=0.1, digits=(16, 4),
        help="Умова контракту: відсоток вартості простроченого товару за кожен день прострочення.")
    ua_fine_rate = fields.Float(
        "Штраф, %", default=7.0,
        help="Умова контракту: відсоток вартості товару, простроченого довше за поріг днів.")
    ua_fine_days = fields.Integer(
        "Штраф після, днів", default=30,
        help="Штраф нараховується, коли прострочення довше за стільки днів.")
    ua_penalty_amount = fields.Monetary(
        "Пеня і штраф на сьогодні", compute="_compute_ua_penalty_amount",
        help="Сума санкцій, яку замовник може нарахувати за графіком поставки на сьогодні.")

    @api.depends("ua_schedule_ids.state", "ua_schedule_ids.price_unit", "ua_penalty_rate",
                 "ua_fine_rate", "ua_fine_days")
    def _compute_ua_penalty_amount(self):
        for contract in self:
            if not contract.ua_defense or not isinstance(contract.id, int):
                contract.ua_penalty_amount = 0.0
                continue
            totals = contract.ua_penalty_totals()
            contract.ua_penalty_amount = totals["penalty"] + totals["fine"]

    def _ua_deliveries(self, product, date):
        """[[дата акта, прийнято]] за затвердженими актами до дати, у порядку актів."""
        self.ensure_one()
        acts = self.ua_acceptance_ids.filtered(
            lambda a: a.state == "done" and a.date <= date).sorted(lambda a: (a.date, a.id))
        return [[act.date, line.qty_accepted] for act in acts for line in act.line_ids
                if line.product_id == product and line.qty_accepted > 0]

    def ua_penalty_rows(self, date=None):
        """Рядки розрахунку: одна частина рядка графіка, поставлена (чи ні) з простроченням."""
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        currency = self.currency_id
        rows = []
        for product in self.ua_schedule_ids.product_id:
            deliveries = self._ua_deliveries(product, date)
            lines = self.ua_schedule_ids.filtered(lambda s, p=product: s.product_id == p) \
                .sorted(lambda s: (s.date, s.id))
            for line in lines:
                need, parts = line.quantity, []
                while need > 0 and deliveries:
                    take = min(need, deliveries[0][1])
                    parts.append((deliveries[0][0], take))
                    need -= take
                    deliveries[0][1] -= take
                    if deliveries[0][1] <= 0:
                        deliveries.pop(0)
                if need > 0:
                    parts.append((False, need))
                for delivered, qty in parts:
                    days = ((delivered or date) - line.date).days
                    if days <= 0:
                        continue
                    value = currency.round(qty * line.price_unit)
                    rows.append({
                        "schedule_id": line.id, "product": product.display_name,
                        "due": line.date, "delivered": delivered, "qty": qty,
                        "price": line.price_unit, "value": value, "days": days,
                        "penalty": currency.round(value * self.ua_penalty_rate / 100.0 * days),
                        "fine": currency.round(value * self.ua_fine_rate / 100.0)
                        if days > self.ua_fine_days else 0.0,
                        "no_price": not line.price_unit,
                    })
        return rows

    def ua_penalty_totals(self, date=None):
        rows = self.ua_penalty_rows(date)
        return {"penalty": sum(r["penalty"] for r in rows), "fine": sum(r["fine"] for r in rows),
                "no_price": any(r["no_price"] for r in rows), "rows": rows}

    def _ua_penalty_date(self):
        """Дата розрахунку для друку: з контексту (ua_penalty_date) або сьогодні."""
        return fields.Date.to_date(self.env.context.get("ua_penalty_date")) \
            or fields.Date.context_today(self)

    @api.model
    def _ua_money(self, amount):
        """1 240,50 - сума для друку."""
        return "{:,.2f}".format(amount or 0.0).replace(",", " ").replace(".", ",")

    def action_print_penalty(self):
        self.ensure_one()
        if not self.ua_defense:
            raise UserError(_("Розрахунок санкцій - для оборонного контракту з графіком поставки."))
        return self.env.ref("l10n_ua_defense.action_report_ua_defense_penalty").report_action(self)


class UaDefenseSchedule(models.Model):
    _inherit = "ua.defense.schedule"

    currency_id = fields.Many2one(related="contract_id.currency_id")
    price_unit = fields.Monetary(
        "Ціна за од. з ПДВ", help="Ціна виробу за контрактом: від неї рахуються пеня і штраф.")
