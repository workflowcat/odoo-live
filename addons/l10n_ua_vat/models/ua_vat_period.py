# -*- coding: utf-8 -*-
"""Зведення ПДВ за період: скільки нарахували, скільки в кредиті, скільки до
сплати, і що в періоді не доробили.

Запис на період, а не разовий розрахунок: зведення за серпень має лишатися таким,
яким його бачив бухгалтер, коли подавав декларацію. Тому це звичайна модель зі своїм
списком по місяцях; «Порахувати» перезаписує числа з книг на поточний момент.

Це рахунок, а не екран: усі числа - поля моделі, і будь-який звіт чи тест бере
їх напряму. Проблеми періоду складаємо простим списком рядків, без розмітки.

Податкове зобов'язання періоду складається з трьох частин:

1. ПДВ проведених вихідних рахунків мінус ПДВ повернень (коригування за
   ст.192 ПКУ, рядок 7 декларації);
2. чистий рух перших подій - нарахований ПДВ з авансів мінус закритий;
3. компенсуючі ПЗ періоду (п.198.5 і ст.199) плюс різниця річного
   перерахунку ЧВ, якщо вона проведена в цьому періоді.

Податковий кредит - ПДВ вхідних рахунків мінус повернення постачальнику плюс
митний ПДВ з імпорту.

Номери рядків декларації (1.1, 4.1, 9, 10.1, 17, 18, 19) наведені як орієнтир
для бухгалтера; сам файл декларації цей модуль поки не формує.
"""
import calendar
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class UaVatPeriod(models.Model):
    _name = "ua.vat.period"
    _description = "Зведення ПДВ за період"
    _order = "date_from desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)

    def _default_date_from(self):
        return fields.Date.context_today(self).replace(day=1)

    def _default_date_to(self):
        today = fields.Date.context_today(self)
        return today.replace(day=calendar.monthrange(today.year, today.month)[1])

    date_from = fields.Date(
        string="Період з", required=True, default=_default_date_from)
    date_to = fields.Date(
        string="Період по", required=True, default=_default_date_to)
    company_id = fields.Many2one(
        "res.company", string="Компанія",
        default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id")

    pz_total = fields.Monetary(
        string="ПЗ (податкові зобов'язання)", currency_field="currency_id",
        readonly=True)
    pk_total = fields.Monetary(
        string="ПК (податковий кредит)", currency_field="currency_id",
        readonly=True)
    due_total = fields.Monetary(
        string="До сплати", currency_field="currency_id", readonly=True)
    problems = fields.Text(string="Що не доробили в періоді", readonly=True)

    # Розділ I декларації, податкові зобов'язання.
    ua_r1_base = fields.Float(string="р.1.1 база 20 %", readonly=True)
    ua_r1_vat = fields.Float(string="р.1.1 ПДВ 20 %", readonly=True)
    ua_r2_base = fields.Float(string="р.1.2 база 14 %", readonly=True)
    ua_r2_vat = fields.Float(string="р.1.2 ПДВ 14 %", readonly=True)
    ua_r3_base = fields.Float(string="р.1.3 база 7 %", readonly=True)
    ua_r3_vat = fields.Float(string="р.1.3 ПДВ 7 %", readonly=True)
    ua_r0_base = fields.Float(
        string="Нульові обсяги разом", readonly=True,
        help="Обсяги за ставкою 0 % і звільнені разом. Дорівнює сумі рядків "
             "2.1 і 5: це контрольне число.")
    ua_r_export_base = fields.Float(string="р.2.1 база 0 % (експорт)", readonly=True)
    ua_r_exempt_base = fields.Float(string="р.5 база звільнені", readonly=True)
    ua_fe_vat = fields.Float(
        string="У тому числі аванси (перша подія)", readonly=True)
    ua_r41_base = fields.Float(string="р.4.1 база (компенсуючі)", readonly=True)
    ua_r41_vat = fields.Float(string="р.4.1 ПДВ (компенсуючі)", readonly=True)
    ua_r411_vat = fields.Float(
        string="р.4.1.1 ПДВ (річний перерахунок ЧВ)", readonly=True)
    ua_r7_base = fields.Float(string="р.7 коригування ПЗ (обсяг)", readonly=True)
    ua_r7_vat = fields.Float(string="р.7 коригування ПЗ (ПДВ)", readonly=True)
    ua_pz_total = fields.Float(string="р.9 усього ПЗ", readonly=True)

    # Розділ II, податковий кредит.
    ua_pk1_base = fields.Float(string="р.10.1 база 20 %", readonly=True)
    ua_pk1_vat = fields.Float(string="р.10.1 ПДВ 20 %", readonly=True)
    ua_pk2_base = fields.Float(string="р.10.2 база 14 %", readonly=True)
    ua_pk2_vat = fields.Float(string="р.10.2 ПДВ 14 %", readonly=True)
    ua_pk3_base = fields.Float(string="р.10.3 база 7 %", readonly=True)
    ua_pk3_vat = fields.Float(string="р.10.3 ПДВ 7 %", readonly=True)
    ua_customs_vat = fields.Float(string="ПК з імпорту (митний ПДВ)", readonly=True)
    ua_r14_base = fields.Float(string="р.14 коригування ПК (обсяг)", readonly=True)
    ua_r14_vat = fields.Float(string="р.14 коригування ПК (ПДВ)", readonly=True)
    ua_pk_total = fields.Float(string="р.17 усього ПК", readonly=True)

    # Розділ III.
    ua_r18 = fields.Float(string="р.18 до сплати", readonly=True)
    ua_r19 = fields.Float(string="р.19 від'ємне значення", readonly=True)

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for period in self:
            if period.date_from and period.date_to \
                    and period.date_from.year == period.date_to.year \
                    and period.date_from.month == period.date_to.month:
                period.name = "ПДВ %02d.%s" % (period.date_from.month, period.date_from.year)
            else:
                period.name = "ПДВ %s - %s" % (
                    period.date_from.strftime("%d.%m.%Y") if period.date_from else "",
                    period.date_to.strftime("%d.%m.%Y") if period.date_to else "")

    @api.model
    def ua_compose(self, company, year=None, month=None, **params):
        """Нове зведення ПДВ за місяць, одразу пораховане."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        today = fields.Date.context_today(self)
        year, month = int(year or today.year), int(month or today.month)
        last = calendar.monthrange(year, month)[1]
        period = self.create({
            "company_id": company.id,
            "date_from": fields.Date.to_date("%04d-%02d-01" % (year, month)),
            "date_to": fields.Date.to_date("%04d-%02d-%02d" % (year, month, last)),
        })
        period.action_compute()
        return period

    def action_compose_month(self):
        """Кнопка списку «Створити за місяць»: зведення поточного місяця."""
        today = fields.Date.context_today(self)
        period = self.ua_compose(self.env.company, today.year, today.month)
        return {"type": "ir.actions.act_window", "name": period.name, "res_model": "ua.vat.period",
                "view_mode": "form", "res_id": period.id, "target": "current"}

    @api.onchange("date_from", "date_to")
    def _onchange_period(self):
        if self.date_from and self.date_to and self.date_to < self.date_from:
            self.date_to = self.date_from

    # --- Допоміжні -----------------------------------------------------------

    def _rate_sums(self, move_types):
        """{ставка: [база, ПДВ]} з рядків проведених рахунків періоду.

        Ставка рядка - перший відсотковий податок (нуль, якщо податків немає),
        база - price_subtotal, ПДВ - різниця price_total і price_subtotal.
        """
        moves = self.env["account.move"].search([
            ("move_type", "in", move_types),
            ("state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
        ])
        sums = {}
        for move in moves:
            for line in move.invoice_line_ids:
                if line.display_type not in (False, "product"):
                    continue
                rate = 0.0
                for tax in line.tax_ids:
                    if tax.amount_type == "percent":
                        rate = tax.amount
                        break
                bucket = sums.setdefault(rate, [0.0, 0.0])
                bucket[0] += line.price_subtotal
                bucket[1] += line.price_total - line.price_subtotal
        return sums

    def _zero_split(self):
        """Розділити нульові обсяги продажу на звільнені і 0 % експорт."""
        moves = self.env["account.move"].search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
        ])
        exempt = export = 0.0
        for move in moves:
            for line in move.invoice_line_ids:
                if line.display_type not in (False, "product"):
                    continue
                rate = 0.0
                for tax in line.tax_ids:
                    if tax.amount_type == "percent":
                        rate = tax.amount
                        break
                if rate:
                    continue
                if line._ua_vat_zero_class() == "exempt":
                    exempt += line.price_subtotal
                else:
                    export += line.price_subtotal
        return round(exempt, 2), round(export, 2)

    def _fe_lines_sum(self, fe_kind, side):
        """Сума дебетів або кредитів рядків рахунку 6431 у службових проводках
        першої події за період. Фільтр за позначкою, не за текстом."""
        account = self.company_id._ua_vat_account("pz_advance")
        if not account:
            return 0.0
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("account_id", "=", account.id),
            ("move_id.ua_fe_kind", "=", fe_kind),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ])
        return sum(lines.mapped(side))

    def _customs_vat_sum(self):
        """Митний ПДВ періоду - дебети рахунку ПДВ у проводках митних декларацій."""
        account = self.company_id._ua_vat_account("vat")
        if not account:
            return 0.0
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("account_id", "=", account.id),
            ("move_id.ua_customs_entry", "=", True),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ])
        return round(sum(lines.mapped("debit")), 2)

    # --- Розрахунок ----------------------------------------------------------

    def action_compute(self):
        """Кнопка «Порахувати»: перерахувати зведення за період."""
        self.ensure_one()
        self.write(self._ua_period_vals())
        return True

    def _ua_period_vals(self):
        """Зведення ПДВ за період як словник значень.

        Кожен блок окремо в try: збій однієї перевірки не валить решту чисел.
        """
        self.ensure_one()
        company = self.company_id
        Move = self.env["account.move"]
        problems = []

        pz = self._rate_sums(["out_invoice"])
        pk = self._rate_sums(["in_invoice"])
        refund_pz = self._rate_sums(["out_refund"])
        refund_pk = self._rate_sums(["in_refund"])

        def at(sums, rate, idx):
            return round(sums.get(rate, [0.0, 0.0])[idx], 2)

        # Повернення зменшують: у декларації це рядки 7 і 14, зі знаком мінус.
        r7_base = -round(sum(v[0] for v in refund_pz.values()), 2)
        r7_vat = -round(sum(v[1] for v in refund_pz.values()), 2)
        r14_base = -round(sum(v[0] for v in refund_pk.values()), 2)
        r14_vat = -round(sum(v[1] for v in refund_pk.values()), 2)

        fe_vat = 0.0
        try:
            fe_vat = round(self._fe_lines_sum("open", "debit")
                           - self._fe_lines_sum("close", "credit"), 2)
        except Exception:
            _logger.warning("l10n_ua_vat: збій підрахунку перших подій",
                            exc_info=True)

        comp_base = comp_vat = 0.0
        try:
            comps = self.env["ua.vat.compensation"].search([
                ("company_id", "=", company.id),
                ("state", "=", "posted"),
                ("date_period", ">=", self.date_from),
                ("date_period", "<=", self.date_to),
            ])
            comp_base = round(sum(comps.mapped("comp_base_total")), 2)
            comp_vat = round(sum(comps.mapped("comp_vat_total")), 2)
        except Exception:
            _logger.warning("l10n_ua_vat: збій підрахунку компенсуючих ПЗ",
                            exc_info=True)

        recalc_vat = 0.0
        try:
            comps_annual = self.env["ua.vat.compensation"].search([
                ("company_id", "=", company.id),
                ("ua_annual_move_id", "!=", False),
            ])
            for comp in comps_annual:
                move = comp.ua_annual_move_id
                if move.state == "posted" and \
                        self.date_from <= move.date <= self.date_to:
                    recalc_vat += comp.ua_annual_delta
            recalc_vat = round(recalc_vat, 2)
        except Exception:
            _logger.warning("l10n_ua_vat: збій підрахунку річного перерахунку",
                            exc_info=True)

        customs_vat = 0.0
        try:
            customs_vat = self._customs_vat_sum()
        except Exception:
            _logger.warning("l10n_ua_vat: збій підрахунку митного ПДВ",
                            exc_info=True)

        exempt_base, export_base = 0.0, 0.0
        try:
            exempt_base, export_base = self._zero_split()
        except Exception:
            _logger.warning("l10n_ua_vat: збій розділення нульових обсягів",
                            exc_info=True)

        pz_total = round(sum(v[1] for v in pz.values()) + r7_vat + fe_vat
                         + comp_vat + recalc_vat, 2)
        pk_total = round(sum(v[1] for v in pk.values()) + r14_vat
                         + customs_vat, 2)
        due_total = round(pz_total - pk_total, 2)

        # --- Що не доробили --------------------------------------------------
        try:
            out_invoices = Move.search([
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("company_id", "=", company.id),
                ("invoice_date", ">=", self.date_from),
                ("invoice_date", "<=", self.date_to),
            ])
            missing = out_invoices.filtered(lambda m: m.ua_tax_invoice_needed)
            if missing:
                problems.append(
                    "Рахунки без податкової накладної (%d): %s"
                    % (len(missing), _shorten(missing.mapped("name"))))
        except Exception:
            problems.append("Не вдалося перевірити рахунки без накладної")

        try:
            open_fe = self.env["account.payment"].search([
                ("company_id", "=", company.id),
                ("ua_fe_move_id", "!=", False),
                ("ua_fe_reversed", "=", False),
                ("date", ">=", self.date_from),
                ("date", "<=", self.date_to),
            ])
            if open_fe:
                problems.append(
                    "Незакриті перші події (%d): %s"
                    % (len(open_fe), _shorten(open_fe.mapped("name"))))
        except Exception:
            problems.append("Не вдалося перевірити перші події")

        try:
            risky = Move.search([
                ("move_type", "=", "in_invoice"),
                ("state", "=", "posted"),
                ("company_id", "=", company.id),
                ("invoice_date", ">=", self.date_from),
                ("invoice_date", "<=", self.date_to),
                ("ua_in_pn_registered", "=", False),
            ]).filtered(lambda m: m.amount_tax
                        and m.partner_id.ua_vat_payer_status == "payer")
            if risky:
                problems.append(
                    "Податковий кредит без підтвердженої ПН постачальника "
                    "(%d): %s" % (len(risky), _shorten(risky.mapped("name"))))
        except Exception:
            problems.append("Не вдалося перевірити податковий кредит")

        try:
            if exempt_base > 0.01 and comp_vat <= 0.01:
                problems.append(
                    "Є звільнені продажі (%.2f), а компенсуючі ПЗ за період не "
                    "проведені (п.198.5 ПКУ)" % exempt_base)
        except Exception:
            pass

        return {
            "pz_total": pz_total,
            "pk_total": pk_total,
            "due_total": due_total,
            "problems": "\n".join("- %s" % p for p in problems)
                        or "Проблем не знайдено.",
            "ua_r1_base": at(pz, 20.0, 0), "ua_r1_vat": at(pz, 20.0, 1),
            "ua_r2_base": at(pz, 14.0, 0), "ua_r2_vat": at(pz, 14.0, 1),
            "ua_r3_base": at(pz, 7.0, 0), "ua_r3_vat": at(pz, 7.0, 1),
            "ua_r0_base": at(pz, 0.0, 0),
            "ua_r_exempt_base": exempt_base,
            "ua_r_export_base": export_base,
            "ua_fe_vat": fe_vat,
            "ua_r41_base": comp_base, "ua_r41_vat": comp_vat,
            "ua_r411_vat": recalc_vat,
            "ua_r7_base": r7_base, "ua_r7_vat": r7_vat,
            "ua_pz_total": pz_total,
            "ua_pk1_base": at(pk, 20.0, 0), "ua_pk1_vat": at(pk, 20.0, 1),
            "ua_pk2_base": at(pk, 14.0, 0), "ua_pk2_vat": at(pk, 14.0, 1),
            "ua_pk3_base": at(pk, 7.0, 0), "ua_pk3_vat": at(pk, 7.0, 1),
            "ua_customs_vat": customs_vat,
            "ua_r14_base": r14_base, "ua_r14_vat": r14_vat,
            "ua_pk_total": pk_total,
            "ua_r18": due_total if due_total > 0 else 0.0,
            "ua_r19": -due_total if due_total < 0 else 0.0,
        }


def _shorten(names, limit=10):
    """Список номерів: до десяти штук, далі «та ще N»."""
    names = [n for n in names if n]
    if len(names) <= limit:
        return ", ".join(names)
    return "%s та ще %d" % (", ".join(names[:limit]), len(names) - limit)
