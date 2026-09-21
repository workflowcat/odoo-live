# -*- coding: utf-8 -*-
"""Аванс від покупця-платника ПДВ - це перша подія.

За п.187.1 ПКУ податкове зобов'язання виникає одразу при зарахуванні коштів,
навіть якщо нічого ще не відвантажено. Odoo такої проводки не робить, тому
робимо ми: Дт 6431 «Податкові зобов'язання» / Кт 6412 «Розрахунки за ПДВ» на
суму ПДВ авансу (сума помножена на ставку і поділена на 100 плюс ставка).

Ставку авансу беремо не з повітря: спершу з останньої підтвердженої угоди
партнера, потім з останнього проведеного рахунку продажу йому, і лише потім з
параметра ua.vat.advance_rate (типово 20).
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

UA_VAT_RATE_DEFAULT = 20.0


def _ua_advance_vat_rate(env):
    """Ставка ПДВ авансу з параметра ua.vat.advance_rate."""
    raw = env["ir.config_parameter"].sudo().get_param(
        "ua.vat.advance_rate", str(UA_VAT_RATE_DEFAULT))
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        rate = UA_VAT_RATE_DEFAULT
    return rate if 0 < rate <= 100 else UA_VAT_RATE_DEFAULT


def _ua_dominant_rate(lines, base_field):
    """Домінантна ставка рядків за сумою бази.

    Для кожного рядка беремо перший відсотковий податок (0 %, якщо податків
    немає) і сумуємо базу за ставками; повертаємо ставку з найбільшою сумою або
    None, якщо рядків немає. Нуль - валідна відповідь: пільга чи експорт
    означають, що ПДВ з авансу не буде.
    """
    by_rate = {}
    for line in lines:
        try:
            if getattr(line, "display_type", False):
                continue
            rate = 0.0
            for tax in line.tax_ids:
                if tax.amount_type == "percent":
                    rate = tax.amount
                    break
            by_rate[rate] = by_rate.get(rate, 0.0) + abs(
                getattr(line, base_field, 0.0) or 0.0)
        except Exception:
            continue
    if not by_rate:
        return None
    return max(by_rate.items(), key=lambda kv: kv[1])[0]


class AccountPayment(models.Model):
    _inherit = "account.payment"

    x_fe_move_id = fields.Many2one(
        "account.move",
        string="Проводка першої події",
        readonly=True,
        copy=False,
        help="Проводка Дт 6431 / Кт 6412 на суму ПДВ авансу, створена при "
             "проведенні авансової оплати від платника ПДВ.",
    )
    x_fe_reversed = fields.Boolean(
        string="Першу подію закрито",
        readonly=True,
        copy=False,
        help="Проводку першої події вже повністю закрито зворотними "
             "проводками. При частковій звірці авансу закривається пропорційна "
             "частка, і прапорець ще знято.",
    )
    x_fe_closed_amount = fields.Float(
        string="Закрито ПДВ першої події",
        digits=(16, 2),
        readonly=True,
        copy=False,
        help="Накопичена сума ПДВ першої події, вже закрита зворотними "
             "проводками пропорційно звіреній з рахунками частці авансу.",
    )

    def action_post(self):
        """Спершу стандартне проведення, потім спроба створити проводку першої
        події. Логіка ПДВ у try: оплата ніколи не падає через неї."""
        res = super().action_post()
        try:
            self._ua_create_first_event()
        except Exception:
            _logger.warning(
                "l10n_ua_vat: не вдалося створити проводку першої події для %s",
                self.ids, exc_info=True)
        return res

    def _ua_advance_rate(self):
        """Ставка ПДВ авансу: угода партнера, далі рахунок партнеру, далі
        параметр. Будь-який збій тихо веде до параметра."""
        self.ensure_one()
        partner = self.partner_id
        try:
            if partner and "sale.order" in self.env:
                order = self.env["sale.order"].search([
                    ("partner_id", "=", partner.id),
                    ("state", "in", ("sale", "done")),
                    ("company_id", "=", self.company_id.id),
                ], order="date_order desc, id desc", limit=1)
                if order:
                    rate = _ua_dominant_rate(order.order_line, "price_subtotal")
                    if rate is not None:
                        return rate
        except Exception:
            pass
        try:
            if partner:
                invoice = self.env["account.move"].search([
                    ("partner_id", "=", partner.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),
                    ("company_id", "=", self.company_id.id),
                ], order="invoice_date desc, id desc", limit=1)
                if invoice:
                    rate = _ua_dominant_rate(
                        invoice.invoice_line_ids, "price_subtotal")
                    if rate is not None:
                        return rate
        except Exception:
            pass
        return _ua_advance_vat_rate(self.env)

    def _ua_create_first_event(self):
        """Проводка ПДВ з авансу. Кожна оплата обробляється окремо: збій по
        одній не валить решту."""
        for payment in self:
            try:
                # Аванс платника ПДВ: вхідна оплата від покупця, контрагент -
                # платник ПДВ, оплата ще не звірена з жодним рахунком, і
                # проводки першої події ще немає.
                if payment.payment_type != "inbound":
                    continue
                if payment.partner_type != "customer":
                    continue
                if payment.partner_id.x_vat_status != "payer":
                    continue
                if payment.reconciled_invoice_ids:
                    continue
                if payment.x_fe_move_id:
                    continue
                rate = payment._ua_advance_rate()
                # Валютний аванс переводимо в гривню курсом на дату платежу:
                # проводка першої події завжди у валюті обліку.
                amount_uah = payment.amount
                comp_cur = payment.company_id.currency_id
                if payment.currency_id and payment.currency_id != comp_cur:
                    amount_uah = payment.currency_id._convert(
                        payment.amount, comp_cur, payment.company_id,
                        payment.date or fields.Date.context_today(payment))
                vat_amount = round(amount_uah * rate / (100.0 + rate), 2)
                if vat_amount <= 0:
                    continue
                company = payment.company_id
                acc_pz = company._ua_vat_account("pz_advance")
                acc_vat = company._ua_vat_account("vat")
                journal = company._ua_vat_journal()
                if not acc_pz or not acc_vat or not journal:
                    continue
                move = self.env["account.move"].create({
                    "journal_id": journal.id,
                    "company_id": company.id,
                    "date": payment.date,
                    "ref": "Перша подія (аванс): %s" % (payment.name or ""),
                    "x_ua_fe_kind": "open",
                    "line_ids": [
                        (0, 0, {"account_id": acc_pz.id,
                                "partner_id": payment.partner_id.id,
                                "name": "ПДВ з авансу (перша подія)",
                                "debit": vat_amount, "credit": 0.0}),
                        (0, 0, {"account_id": acc_vat.id,
                                "partner_id": payment.partner_id.id,
                                "name": "ПДВ з авансу (перша подія)",
                                "debit": 0.0, "credit": vat_amount}),
                    ],
                })
                move.action_post()
                payment.x_fe_move_id = move
            except Exception:
                _logger.warning(
                    "l10n_ua_vat: збій проводки першої події для оплати %s",
                    payment.id, exc_info=True)
                continue
