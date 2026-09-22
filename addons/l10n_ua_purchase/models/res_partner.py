"""Паспорт постачальника: сигнали ризику, оцінка, історія закупівель.

Оцінка ризику тут - не друге KYC. Справа KYC, скринінг, санкції і бенефіціари
лишаються в `bp_kyc`; реквізити з реєстру - в `l10n_ua_partner_edr` і
`bp_purchase_intake`. Цей модуль бере з них готові висновки одним пулом
(`action_ua_supplier_sync`) у власні прапорці і додає те, чого там немає:
платіжну дисципліну і відхилення рахунків від замовлень. Сам рахунок балів
рахується лише з полів, які є в будь-якій базі, тому число однакове і в
окремій базі, і в повному складі модулів.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Бали ризику. Сума - 0..100+, поріг рівня нижче.
POINTS_NO_CODE = 10        # немає ЄДРПОУ / РНОКПП
POINTS_EDR_TERMINATED = 40  # стан у ЄДР: припинено
POINTS_VAT_NON_PAYER = 10  # неплатник ПДВ
POINTS_NO_BANK = 10        # немає банківського рахунку
POINTS_DELAY_SMALL = 10    # середнє запізнення оплат 6..30 днів
POINTS_DELAY_BIG = 20      # середнє запізнення оплат понад 30 днів
POINTS_OVERPRICE = 15      # є рахунки, дорожчі за замовлення
POINTS_KYC_BLOCK = 40      # KYC: рішення «відхилено»

LEVEL_HIGH = 40            # від стількох балів - високий
LEVEL_MEDIUM = 10          # від стількох балів - середній

DELAY_SMALL_DAYS = 5       # запізнення до стількох днів не штрафуємо
DELAY_BIG_DAYS = 30        # понад стільки днів - велике запізнення
OVERPRICE_RATIO = 1.10     # рахунок дорожчий за замовлення більш ніж на 10 %


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # Сигнали: підтягуються з сусідніх модулів, зберігаються в себе
    # ------------------------------------------------------------------
    ua_supplier_edr_terminated = fields.Boolean(
        string="У ЄДР припинено",
        help="Стан контрагента в ЄДР - припинено або в стані припинення. "
             "Підтягується з `l10n_ua_partner_edr` чи `bp_purchase_intake` "
             "кнопкою «Оновити сигнали»; без цих модулів ставиться вручну.",
    )
    ua_supplier_vat_non_payer = fields.Boolean(
        string="Неплатник ПДВ",
        help="Контрагент не платник ПДВ: податкового кредиту з його рахунків "
             "не буде. Підтягується з `l10n_ua_vat` кнопкою «Оновити сигнали».",
    )
    ua_supplier_kyc_block = fields.Boolean(
        string="KYC: відхилено",
        help="Рішення KYC по контрагенту - відхилено. Підтягується з `bp_kyc`; "
             "саме KYC тут не робиться.",
    )
    ua_supplier_signals_date = fields.Datetime(
        string="Сигнали оновлено",
        readonly=True,
        copy=False,
        help="Коли востаннє тягнули сигнали з ЄДР, ПДВ і KYC.",
    )

    # ------------------------------------------------------------------
    # Історія закупівель
    # ------------------------------------------------------------------
    ua_purchase_bill_ids = fields.One2many(
        comodel_name="account.move",
        inverse_name="partner_id",
        string="Рахунки постачальника",
        domain=[("move_type", "=", "in_invoice")],
    )
    ua_purchase_bill_count = fields.Integer(
        string="Рахунків",
        compute="_compute_ua_purchase_history",
        store=True,
        help="Кількість проведених вхідних рахунків контрагента.",
    )
    ua_purchase_bill_total = fields.Monetary(
        string="Сума рахунків",
        currency_field="currency_id",
        compute="_compute_ua_purchase_history",
        store=True,
        help="Сума проведених вхідних рахунків із податками.",
    )
    ua_purchase_paid_total = fields.Monetary(
        string="Сплачено",
        currency_field="currency_id",
        compute="_compute_ua_purchase_history",
        store=True,
    )
    ua_purchase_open_balance = fields.Monetary(
        string="Заборгованість",
        currency_field="currency_id",
        compute="_compute_ua_purchase_history",
        store=True,
    )
    ua_purchase_avg_delay_days = fields.Integer(
        string="Середнє запізнення оплат, днів",
        compute="_compute_ua_purchase_history",
        store=True,
        help="Середнє по сплачених рахунках: дата останньої оплати мінус "
             "строк оплати. Оплати вчасно і достроково рахуються як нуль.",
    )
    ua_purchase_overprice_count = fields.Integer(
        string="Рахунків дорожчих за замовлення",
        compute="_compute_ua_purchase_history",
        store=True,
        help="Проведені рахунки, сума яких перевищує суму свого замовлення "
             "більш ніж на 10 відсотків.",
    )

    # ------------------------------------------------------------------
    # Оцінка ризику
    # ------------------------------------------------------------------
    ua_supplier_risk_score = fields.Integer(
        string="Бали ризику",
        compute="_compute_ua_supplier_risk",
        store=True,
        help="Сума балів за правилами модуля: реквізити, стан у ЄДР, статус "
             "ПДВ, рішення KYC, платіжна дисципліна, відхилення рахунків.",
    )
    ua_supplier_risk_level = fields.Selection(
        selection=[
            ("low", "низький"),
            ("medium", "середній"),
            ("high", "високий"),
        ],
        string="Ризик постачальника",
        compute="_compute_ua_supplier_risk",
        store=True,
    )
    ua_supplier_risk_note = fields.Text(
        string="Через що бали",
        compute="_compute_ua_supplier_risk",
        store=True,
        help="Рядок на кожне спрацьоване правило з його балами.",
    )

    # ==================================================================
    # Обчислення
    # ==================================================================
    @api.depends(
        "ua_purchase_bill_ids.state",
        "ua_purchase_bill_ids.amount_total",
        "ua_purchase_bill_ids.amount_residual",
        "ua_purchase_bill_ids.payment_state",
        "ua_purchase_bill_ids.invoice_date_due",
    )
    def _compute_ua_purchase_history(self):
        for partner in self:
            bills = partner.ua_purchase_bill_ids.filtered(
                lambda move: move.state == "posted"
            )
            delays = []
            overprice = 0
            total = paid = balance = 0.0
            for bill in bills:
                total += bill.amount_total
                balance += bill.amount_residual
                paid += bill.amount_total - bill.amount_residual
                delay = partner._ua_bill_delay_days(bill)
                if delay is not None:
                    delays.append(delay)
                if partner._ua_bill_is_overpriced(bill):
                    overprice += 1
            partner.ua_purchase_bill_count = len(bills)
            partner.ua_purchase_bill_total = total
            partner.ua_purchase_paid_total = paid
            partner.ua_purchase_open_balance = balance
            partner.ua_purchase_avg_delay_days = (
                int(round(sum(delays) / len(delays))) if delays else 0
            )
            partner.ua_purchase_overprice_count = overprice

    def _ua_bill_payment_date(self, bill):
        """Дата останньої звіреної оплати рахунку або None."""
        try:
            dates = [pay.date for pay in bill._get_reconciled_payments() if pay.date]
        except Exception:  # чужий модуль зламав звірку - історія не мусить падати
            _logger.warning("l10n_ua_purchase: не читається оплата рахунку %s",
                            bill.id, exc_info=True)
            return None
        return max(dates) if dates else None

    def _ua_bill_delay_days(self, bill):
        """Запізнення оплати рахунку в днях (не менше нуля) або None,
        якщо рахунок ще не сплачений чи немає строку оплати."""
        if bill.payment_state not in ("paid", "in_payment"):
            return None
        due = bill.invoice_date_due or bill.invoice_date
        pay_date = self._ua_bill_payment_date(bill)
        if not due or not pay_date:
            return None
        return max((pay_date - due).days, 0)

    def _ua_bill_is_overpriced(self, bill):
        """Чи дорожчий рахунок за своє замовлення більш ніж на 10 %.
        Рахунок без замовлення відхиленням не вважаємо."""
        orders = bill.invoice_line_ids.purchase_line_id.order_id
        if not orders:
            return False
        ordered = sum(orders.mapped("amount_total"))
        if not ordered:
            return False
        return bill.amount_total > ordered * OVERPRICE_RATIO

    def _ua_supplier_risk_rules(self):
        """Спрацьовані правила ризику: список (назва, бали)."""
        self.ensure_one()
        rules = []
        if not (self.company_registry or self.vat):
            rules.append(("немає ЄДРПОУ / РНОКПП", POINTS_NO_CODE))
        if self.ua_supplier_edr_terminated:
            rules.append(("у ЄДР припинено", POINTS_EDR_TERMINATED))
        if self.ua_supplier_vat_non_payer:
            rules.append(("неплатник ПДВ", POINTS_VAT_NON_PAYER))
        if self.ua_supplier_kyc_block:
            rules.append(("KYC: відхилено", POINTS_KYC_BLOCK))
        if not self.bank_ids:
            rules.append(("немає банківського рахунку", POINTS_NO_BANK))
        delay = self.ua_purchase_avg_delay_days
        if delay > DELAY_BIG_DAYS:
            rules.append(("оплати запізнюються в середньому на %d днів" % delay,
                          POINTS_DELAY_BIG))
        elif delay > DELAY_SMALL_DAYS:
            rules.append(("оплати запізнюються в середньому на %d днів" % delay,
                          POINTS_DELAY_SMALL))
        if self.ua_purchase_overprice_count:
            rules.append(("рахунків дорожчих за замовлення: %d"
                          % self.ua_purchase_overprice_count, POINTS_OVERPRICE))
        return rules

    @api.depends(
        "company_registry", "vat", "bank_ids",
        "ua_supplier_edr_terminated", "ua_supplier_vat_non_payer",
        "ua_supplier_kyc_block",
        "ua_purchase_avg_delay_days", "ua_purchase_overprice_count",
    )
    def _compute_ua_supplier_risk(self):
        for partner in self:
            rules = partner._ua_supplier_risk_rules()
            score = sum(points for _name, points in rules)
            partner.ua_supplier_risk_score = score
            if score >= LEVEL_HIGH:
                partner.ua_supplier_risk_level = "high"
            elif score >= LEVEL_MEDIUM:
                partner.ua_supplier_risk_level = "medium"
            else:
                partner.ua_supplier_risk_level = "low"
            partner.ua_supplier_risk_note = "\n".join(
                "%s: %d" % (name, points) for name, points in rules
            ) or "зауважень немає"

    # ==================================================================
    # Дії
    # ==================================================================
    def _ua_supplier_pull_signals(self):
        """Прочитати висновки сусідніх модулів у власні прапорці.

        Звʼязок мʼякий: полів може не бути, тоді прапорець лишається таким,
        як його поставили руками.
        """
        self.ensure_one()
        vals = {}
        state = ""
        for name in ("ua_edr_status", "bp_registry_status"):
            if name in self._fields:
                state = "%s %s" % (state, self[name] or "")
        state = state.lower()
        if state.strip():
            vals["ua_supplier_edr_terminated"] = any(
                word in state for word in ("припин", "ліквід", "банкрут")
            )
        if "ua_vat_payer_status" in self._fields:
            vals["ua_supplier_vat_non_payer"] = (
                self.ua_vat_payer_status == "non_payer"
            )
        if "kyc_decision" in self._fields:
            vals["ua_supplier_kyc_block"] = self.kyc_decision == "rejected"
        vals["ua_supplier_signals_date"] = fields.Datetime.now()
        self.write(vals)
        return vals

    def action_ua_supplier_sync(self):
        """«Оновити сигнали»: перечитати ЄДР, ПДВ і KYC та перерахувати ризик."""
        for partner in self:
            partner._ua_supplier_pull_signals()
        return True

    def action_ua_supplier_bills(self):
        """Кнопка-лічильник: вхідні рахунки цього контрагента."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Рахунки постачальника",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id),
                       ("move_type", "=", "in_invoice")],
            "context": {"default_partner_id": self.id,
                        "default_move_type": "in_invoice"},
        }
