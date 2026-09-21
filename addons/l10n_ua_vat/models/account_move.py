# -*- coding: utf-8 -*-
"""Перша подія, строки реєстрації ПН, розрахунок коригування, митний ПДВ.

Головне правило - п.187.1 ПКУ: податкове зобов'язання виникає за датою події,
що сталася раніше, - зарахування коштів від покупця або відвантаження товарів
(для послуг - дата документа, що засвідчує постачання). Odoo такого поняття не
має: він знає суму податку в рахунку і нічого не знає про аванси.

Як це працює тут:

1. Аванс від покупця-платника ПДВ (оплата, ще не звірена з рахунком) дає
   проводку Дт 6431 «Податкові зобов'язання» / Кт 6412 «Розрахунки за ПДВ» на
   суму ПДВ авансу (див. account_payment.py).
2. Коли рахунок проводиться і звіряється з тим авансом, нативний рахунок уже
   нарахував свій ПДВ. Щоб податок не порахувався двічі, ми сторнуємо проводку
   першої події - Дт 6412 / Кт 6431 - на пропорційну частку: аванс 1200
   (ПДВ 200), звірений з рахунком на 600, закриває рівно 100.
3. Якщо рахунок був перший, ніякої службової проводки немає взагалі: ПДВ уже
   в самому рахунку.

Строки реєстрації - воєнні (п.89 підрозд.2 розд.XX ПКУ): складено 1-15 числа -
до 5 числа наступного місяця, 16-кінець місяця - до 18. Штраф за прострочення -
за шкалою п.90 підрозд.2 розд.XX для оподаткованих і 2 % обсягу з межею
1020 грн за п.120-1.1 для пільгових.
"""
import datetime
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)

# Межа штрафу за пільгову або нульову ПН, грн (п.120-1.1 ПКУ).
UA_PN_FINE_CAP_EXEMPT = 1020.0


def ua_pn_deadline(compose_date):
    """Граничний строк реєстрації ПН у ЄРПН за воєнними строками."""
    if not compose_date:
        return False
    day = 5 if compose_date.day <= 15 else 18
    year = compose_date.year + (1 if compose_date.month == 12 else 0)
    month = 1 if compose_date.month == 12 else compose_date.month + 1
    return datetime.date(year, month, day)


def ua_pn_fine_pct(overdue_days):
    """Відсоток штрафу від суми ПДВ за днями прострочення (п.90)."""
    if overdue_days <= 0:
        return 0.0
    if overdue_days <= 15:
        return 2.0
    if overdue_days <= 30:
        return 5.0
    if overdue_days <= 60:
        return 10.0
    if overdue_days <= 365:
        return 15.0
    return 25.0


class AccountMove(models.Model):
    _inherit = "account.move"

    ua_vat_document_ids = fields.One2many(
        "ua.vat.document", "move_id", string="Податкові документи")

    # --- Перша подія --------------------------------------------------------

    ua_first_event = fields.Selection(
        selection=[
            ("payment", "Оплата (аванс)"),
            ("shipment", "Відвантаження"),
            ("none", "Не було"),
        ],
        string="Перша подія",
        compute="_compute_x_first_event",
        help="Що сталося раніше: оплата чи відвантаження. За першою подією "
             "платнику ПДВ складається податкова накладна (п.187.1 ПКУ).",
    )
    ua_first_event_date = fields.Date(
        string="Дата першої події", compute="_compute_x_first_event")
    ua_fe_kind = fields.Selection(
        selection=[
            ("open", "Нарахування ПДВ з авансу"),
            ("close", "Закриття першої події"),
        ],
        string="Проводка першої події",
        copy=False,
        help="Позначка службових проводок ПДВ: нарахування - Дт 6431 / Кт 6412 "
             "з авансу, закриття - зворотна проводка після рахунку.",
    )
    ua_customs_entry = fields.Boolean(
        string="Позначка проводки митного ПДВ", copy=False,
        help="Позначка службової проводки податкового кредиту з імпорту.")
    ua_vat_comp = fields.Boolean(
        string="Проводка компенсуючих ПЗ", copy=False,
        help="Позначка службової проводки компенсуючих ПЗ. За нею строк "
             "зведеної ПН рахується як 20 календарних днів після останнього "
             "дня місяця складання.")

    ua_tax_invoice_needed = fields.Boolean(
        string="Потрібна податкова накладна",
        compute="_compute_x_tax_invoice_needed",
        help="Контрагент - платник ПДВ, перша подія вже сталася, а накладної "
             "в реєстрі ще немає.",
    )
    ua_rk_needed = fields.Boolean(
        string="Потрібен розрахунок коригування",
        compute="_compute_x_rk_needed",
        help="Проведене повернення платнику ПДВ: до накладної первинного "
             "рахунку треба скласти РК, а його ще немає.",
    )
    ua_fe_open = fields.Boolean(
        string="Є незакрита перша подія", compute="_compute_x_fe_open",
        help="Серед оплат рахунку є проводка першої події, яку ще не закрито.")
    ua_in_pn_registered = fields.Boolean(
        string="ПН постачальника зареєстрована",
        tracking=True,
        copy=False,
        help="Постав, коли постачальник зареєстрував накладну в ЄРПН. Доти "
             "податковий кредит із цього рахунку під ризиком.",
    )

    # --- Строк реєстрації і штраф -------------------------------------------

    ua_pn_deadline = fields.Date(
        string="Граничний строк реєстрації ПН",
        compute="_compute_x_pn_deadline",
        store=True,
        help="Воєнні строки (п.89 підрозд.2 розд.XX ПКУ): складено 1-15 - до "
             "5 числа наступного місяця, 16-кінець - до 18.",
    )
    ua_pn_overdue_days = fields.Integer(
        string="Прострочено реєстрацію, днів", compute="_compute_x_pn_risk")
    ua_pn_fine_est = fields.Monetary(
        string="Орієнтовний штраф за ПН",
        currency_field="company_currency_id",
        compute="_compute_x_pn_risk",
        help="За оподаткованими - 2, 5, 10, 15 або 25 %% суми ПДВ (п.90); за "
             "пільговими - 2 %% обсягу без ПДВ, але не більше 1020 грн "
             "(п.120-1.1).",
    )
    ua_pn_at_risk = fields.Boolean(
        string="ПН під ризиком штрафу", compute="_compute_x_pn_risk",
        help="Накладна потрібна, ще не зареєстрована, а строк настав або "
             "близько (3 дні).")

    # --- Імпорт: митний ПДВ --------------------------------------------------

    ua_is_import = fields.Boolean(
        string="Імпортний рахунок", compute="_compute_x_is_import",
        help="Вхідний рахунок у валюті, відмінній від валюти компанії: ПДВ "
             "сплачується на митниці за митною декларацією.")
    ua_customs_decl_number = fields.Char(
        string="Номер митної декларації", copy=False,
        help="Номер митної декларації (ІМ-40), за якою сплачено імпортний ПДВ.")
    ua_customs_vat = fields.Monetary(
        string="Митний ПДВ",
        currency_field="company_currency_id",
        copy=False,
        help="Сума ПДВ, сплачена на митниці, у гривні. Іде в податковий кредит "
             "проводкою Дт 6412 / Кт 3771.",
    )
    ua_customs_move_id = fields.Many2one(
        "account.move", string="Проводка митного ПДВ", readonly=True, copy=False)

    # --- Обчислення ---------------------------------------------------------

    @api.depends("move_type", "currency_id", "company_id.currency_id")
    def _compute_x_is_import(self):
        for move in self:
            try:
                move.ua_is_import = (
                    move.move_type == "in_invoice"
                    and move.currency_id != move.company_id.currency_id)
            except Exception:
                move.ua_is_import = False

    def _ua_vat_payments(self):
        """Оплати, звірені з цим рахунком."""
        self.ensure_one()
        try:
            return self._get_reconciled_payments()
        except Exception:
            return self.env["account.payment"]

    def _ua_vat_first_shipment_date(self):
        """Дата відвантаження - або None.

        Якщо в базі є склад і рахунок родом із замовлення продажу, беремо дату
        першого завершеного переміщення. Без складу відвантаження засвідчує сам
        проведений рахунок (видаткова накладна або акт), тому беремо його дату.
        """
        self.ensure_one()
        try:
            if "stock.picking" in self.env:
                pickings = (
                    self.invoice_line_ids.sale_line_ids.order_id.picking_ids
                ).filtered(lambda p: p.state == "done" and p.date_done)
                if pickings:
                    return fields.Date.to_date(min(pickings.mapped("date_done")))
        except Exception:
            pass
        if self.state == "posted" and self.move_type in (
                "out_invoice", "out_refund"):
            return self.invoice_date or self.date
        return None

    def _ua_vat_first_payment_date(self):
        """Дата першої звіреної оплати рахунку - або None."""
        self.ensure_one()
        payments = self._ua_vat_payments().filtered(lambda p: p.date)
        if not payments:
            return None
        return min(payments.mapped("date"))

    @api.depends("invoice_line_ids", "payment_state", "state", "invoice_date")
    def _compute_x_first_event(self):
        """Що сталося раніше - оплата чи відвантаження. Збій дає «не було»,
        щоб форма рахунку ніколи не падала через ПДВ."""
        for move in self:
            event, event_date = "none", False
            try:
                shipment_date = move._ua_vat_first_shipment_date()
                payment_date = move._ua_vat_first_payment_date()
                if payment_date and shipment_date:
                    if payment_date <= shipment_date:
                        event, event_date = "payment", payment_date
                    else:
                        event, event_date = "shipment", shipment_date
                elif payment_date:
                    event, event_date = "payment", payment_date
                elif shipment_date:
                    event, event_date = "shipment", shipment_date
            except Exception:
                event, event_date = "none", False
            move.ua_first_event = event
            move.ua_first_event_date = event_date

    @api.depends("move_type", "partner_id.ua_vat_payer_status", "ua_first_event_date",
                 "invoice_date", "ua_vat_comp", "date", "reversed_entry_id")
    def _compute_x_pn_deadline(self):
        """Строк реєстрації від дати складання.

        Зведена (компенсуюча) ПН - 20 календарних днів після останнього дня
        місяця складання; цей строк воєнними правилами не подовжений.
        Зменшуючий РК реєструє покупець: воєнний строк 18 календарних днів з
        дня отримання РК. Дати отримання в Odoo немає, тому рахуємо від дати
        складання - це спрощення.
        """
        for move in self:
            deadline = False
            try:
                if move.ua_vat_comp and move.date:
                    d = move.date
                    year = d.year + (1 if d.month == 12 else 0)
                    month = 1 if d.month == 12 else d.month + 1
                    month_end = d.replace(
                        year=year, month=month, day=1) - timedelta(days=1)
                    deadline = month_end + timedelta(days=20)
                elif (move.move_type == "out_invoice"
                        and move.partner_id.ua_vat_payer_status == "payer"):
                    compose = move.ua_first_event_date or move.invoice_date
                    deadline = ua_pn_deadline(compose)
                elif (move.move_type == "out_refund"
                        and move.partner_id.ua_vat_payer_status == "payer"
                        and move.reversed_entry_id and move.invoice_date):
                    deadline = move.invoice_date + timedelta(days=18)
            except Exception:
                deadline = False
            move.ua_pn_deadline = deadline

    def _ua_pn_registered(self):
        """(чи зареєстровано, найраніша дата реєстрації) для ПН цього рахунку."""
        self.ensure_one()
        docs = self.ua_vat_document_ids.filtered(
            lambda d: d.doc_kind == "tax_invoice" and d.ua_pn_registered_date)
        dates = docs.mapped("ua_pn_registered_date")
        return bool(docs), (min(dates) if dates else False)

    def _ua_pn_fine(self, days):
        """Оцінка штрафу за прострочення реєстрації на `days` днів."""
        self.ensure_one()
        if days <= 0:
            return 0.0
        vat = self.amount_tax or 0.0
        if vat > 0.005:
            return round(vat * ua_pn_fine_pct(days) / 100.0, 2)
        return round(min((self.amount_untaxed or 0.0) * 0.02,
                         UA_PN_FINE_CAP_EXEMPT), 2)

    def _compute_x_pn_risk(self):
        """Прострочення, штраф і прапорець ризику.

        Залежить від сьогоднішньої дати, тому не зберігається. Зареєстрована до
        строку ПН - нуль і без ризику. Зареєстрована із запізненням - днів
        стільки, скільки між строком і фактичною реєстрацією, штраф лишається
        історичним фактом, але під ризиком документ уже не рахується.
        """
        today = fields.Date.context_today(self)
        for move in self:
            days, fine, at_risk = 0, 0.0, False
            try:
                deadline = move.ua_pn_deadline
                registered, reg_date = move._ua_pn_registered()
                if deadline and registered:
                    if reg_date and reg_date > deadline:
                        days = (reg_date - deadline).days
                        fine = move._ua_pn_fine(days)
                elif deadline:
                    days = max(0, (today - deadline).days)
                    at_risk = today >= (deadline - timedelta(days=3))
                    fine = move._ua_pn_fine(days)
            except Exception:
                days, fine, at_risk = 0, 0.0, False
            move.ua_pn_overdue_days = days
            move.ua_pn_fine_est = fine
            move.ua_pn_at_risk = at_risk

    @api.depends("move_type", "partner_id.ua_vat_payer_status", "ua_first_event",
                 "ua_vat_document_ids.doc_kind")
    def _compute_x_tax_invoice_needed(self):
        for move in self:
            try:
                move.ua_tax_invoice_needed = (
                    move.move_type == "out_invoice"
                    and move.partner_id.ua_vat_payer_status == "payer"
                    and move.ua_first_event != "none"
                    and not move.ua_vat_document_ids.filtered(
                        lambda d: d.doc_kind == "tax_invoice"))
            except Exception:
                move.ua_tax_invoice_needed = False

    @api.depends("move_type", "state", "partner_id.ua_vat_payer_status",
                 "reversed_entry_id.ua_vat_document_ids.doc_kind",
                 "ua_vat_document_ids.doc_kind")
    def _compute_x_rk_needed(self):
        for move in self:
            try:
                origin = move.reversed_entry_id
                move.ua_rk_needed = (
                    move.move_type == "out_refund"
                    and move.state == "posted"
                    and move.partner_id.ua_vat_payer_status == "payer"
                    and bool(origin)
                    and bool(origin.ua_vat_document_ids.filtered(
                        lambda d: d.doc_kind == "tax_invoice"))
                    and not move.ua_vat_document_ids.filtered(
                        lambda d: d.doc_kind == "adjustment"))
            except Exception:
                move.ua_rk_needed = False

    @api.depends("move_type", "state", "payment_state")
    def _compute_x_fe_open(self):
        for move in self:
            try:
                move.ua_fe_open = bool(move._ua_vat_payments().filtered(
                    lambda p: p.ua_fe_move_id and not p.ua_fe_reversed))
            except Exception:
                move.ua_fe_open = False

    # --- Реєстр документів ---------------------------------------------------

    def _ua_vat_materialize(self, kind):
        """Створити (або знайти) податковий документ цього рахунку.

        Ідемпотентно: другий виклик повертає той самий запис.
        """
        self.ensure_one()
        existing = self.ua_vat_document_ids.filtered(
            lambda d: d.doc_kind == kind)[:1]
        if existing:
            return existing
        titles = {"tax_invoice": "Податкова накладна",
                  "adjustment": "Розрахунок коригування"}
        return self.env["ua.vat.document"].create({
            "name": "%s %s" % (titles[kind], self.name or ""),
            "doc_kind": kind,
            "move_id": self.id,
            "company_id": self.company_id.id,
        })

    def action_ua_create_tax_invoice(self):
        """Кнопка «Скласти податкову накладну»."""
        self.ensure_one()
        doc = self._ua_vat_materialize("tax_invoice")
        return {
            "type": "ir.actions.act_window",
            "res_model": "ua.vat.document",
            "res_id": doc.id,
            "view_mode": "form",
            "target": "current",
        }

    # --- Проведення ----------------------------------------------------------

    def _post(self, soft=True):
        """Після стандартного проведення закриваємо перші події і складаємо РК
        на повернення. Уся логіка ПДВ у try: проведення рахунку ніколи не падає
        через неї."""
        posted = super()._post(soft=soft)
        try:
            posted._ua_reverse_first_event()
        except Exception:
            _logger.warning(
                "l10n_ua_vat: не вдалося закрити перші події для %s",
                posted.ids, exc_info=True)
        try:
            posted._ua_auto_adjustment()
        except Exception:
            _logger.warning(
                "l10n_ua_vat: не вдалося скласти РК для %s",
                posted.ids, exc_info=True)
        return posted

    def _ua_auto_adjustment(self):
        """Проведене повернення платнику ПДВ, первинний рахунок якого має ПН,
        автоматично отримує розрахунок коригування.

        Причину вгадуємо: ціни рядків повернення збігаються з первинними -
        103 «Повернення товару», інакше 101 «Зміна ціни». Бухгалтер може
        змінити.
        """
        created = self.env["ua.vat.document"]
        for move in self:
            try:
                if not (move.move_type == "out_refund"
                        and move.state == "posted"
                        and move.partner_id.ua_vat_payer_status == "payer"):
                    continue
                origin = move.reversed_entry_id
                if not origin:
                    continue
                pn_doc = origin.ua_vat_document_ids.filtered(
                    lambda d: d.doc_kind == "tax_invoice")[:1]
                if not pn_doc:
                    continue  # коригувати нема чого: накладної ще немає
                if move.ua_vat_document_ids.filtered(
                        lambda d: d.doc_kind == "adjustment"):
                    continue
                doc = move._ua_vat_materialize("adjustment")
                orig_prices = {
                    line.product_id.id: line.price_unit
                    for line in origin.invoice_line_ids
                    if line.display_type in (False, "product")}
                same_price = all(
                    abs(line.price_unit
                        - orig_prices.get(line.product_id.id, -1)) < 0.005
                    for line in move.invoice_line_ids
                    if line.display_type in (False, "product"))
                vals = {}
                if not doc.ua_adj_reason_code:
                    vals["ua_adj_reason_code"] = "103" if same_price else "101"
                if not doc.ua_adj_pn_document_id:
                    vals["ua_adj_pn_document_id"] = pn_doc.id
                if vals:
                    doc.write(vals)
                created |= doc
            except Exception:
                _logger.warning(
                    "l10n_ua_vat: збій складання РК для повернення %s",
                    move.id, exc_info=True)
                continue
        return created

    def _ua_reverse_first_event(self):
        """Закрити першу подію пропорційно звіреній частці авансу.

        Для кожної авансової оплати з проводкою першої події, звіреної з цим
        рахунком і ще не закритої повністю, створюємо зворотну проводку
        Дт 6412 / Кт 6431 на частку ПДВ за часткою звіреного авансу. Аванс
        1200 (ПДВ 200), звірений з рахунком на 600, закриває 100, а не 200.

        Накопичене закриття тримаємо в payment.ua_fe_closed_amount. Остання
        звірка, що добиває аванс, закриває точний залишок, тому копійки не
        розповзаються. Повертає кількість створених проводок.
        """
        closed = 0
        for invoice in self:
            try:
                if invoice.move_type != "out_invoice":
                    continue
                if invoice.partner_id.ua_vat_payer_status != "payer":
                    continue
                payments = invoice._ua_vat_payments().filtered(
                    lambda p: p.ua_fe_move_id and not p.ua_fe_reversed)
                if not payments:
                    continue
                company = invoice.company_id
                acc_pz = company._ua_vat_account("pz_advance")
                acc_vat = company._ua_vat_account("vat")
                journal = company._ua_vat_journal()
                # Збій налаштувань однієї компанії не має обривати закриття
                # перших подій решти рахунків пакета - тому continue, не return.
                if not acc_pz or not acc_vat or not journal:
                    continue
                for payment in payments:
                    try:
                        closed += invoice._ua_close_one_payment(
                            payment, acc_pz, acc_vat, journal)
                    except Exception:
                        _logger.warning(
                            "l10n_ua_vat: збій закриття першої події оплати %s "
                            "рахунком %s", payment.id, invoice.id, exc_info=True)
                        continue
            except Exception:
                _logger.warning(
                    "l10n_ua_vat: збій закриття перших подій рахунку %s",
                    invoice.id, exc_info=True)
                continue
        return closed

    def _ua_close_one_payment(self, payment, acc_pz, acc_vat, journal):
        """Закрити частку першої події однієї оплати. Повертає 1 або 0."""
        self.ensure_one()
        # Увесь ПДВ першої події - сума дебетів рядків 6431 у проводці авансу.
        fe_vat = sum(payment.ua_fe_move_id.line_ids.filtered(
            lambda l: l.account_id == acc_pz).mapped("debit"))
        if fe_vat <= 0:
            return 0
        already = round(payment.ua_fe_closed_amount or 0.0, 2)
        # Частка звіреного авансу: сума часткових звірок дебіторських рядків
        # проводки оплати (накопичена за всіма рахунками, тому і третій рахунок
        # закриє свою частку) поділена на суму оплати.
        pay_lines = (payment.move_id.line_ids if payment.move_id
                     else self.env["account.move.line"])
        pay_recv = pay_lines.filtered(
            lambda l: l.account_id.account_type == "asset_receivable")
        partials = pay_recv.matched_debit_ids | pay_recv.matched_credit_ids
        reconciled_total = sum(partials.mapped("amount"))
        fraction = min(reconciled_total / payment.amount, 1.0) \
            if payment.amount else 0.0
        fully = bool(pay_recv) and all(l.reconciled for l in pay_recv)
        if fully:
            to_close = round(fe_vat - already, 2)
        else:
            to_close = round(min(fe_vat * fraction - already,
                                 fe_vat - already), 2)
        if to_close <= 0.005:
            return 0
        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": self.date or fields.Date.context_today(self),
            "ref": "Закриття першої події: %s" % (self.name or ""),
            "ua_fe_kind": "close",
            "line_ids": [
                (0, 0, {
                    "account_id": acc_vat.id,
                    "partner_id": self.partner_id.id,
                    "name": "Закриття ПДВ першої події",
                    "debit": to_close, "credit": 0.0,
                }),
                (0, 0, {
                    "account_id": acc_pz.id,
                    "partner_id": self.partner_id.id,
                    "name": "Закриття ПДВ першої події",
                    "debit": 0.0, "credit": to_close,
                }),
            ],
        })
        move.action_post()
        payment.ua_fe_closed_amount = round(already + to_close, 2)
        if payment.ua_fe_closed_amount >= fe_vat - 0.01:
            payment.ua_fe_reversed = True
        return 1

    def action_ua_close_first_events(self):
        """Кнопка «Закрити першу подію» - страховка, коли автоматика не
        спрацювала. Після натискання каже, що зробила."""
        closed = 0
        try:
            closed = self._ua_reverse_first_event() or 0
        except Exception:
            _logger.warning(
                "l10n_ua_vat: дія закриття перших подій не вдалася для %s",
                self.ids, exc_info=True)
        if closed:
            message = ("Створено проводок закриття першої події: %d "
                       "(Дт 6412 / Кт 6431, пропорційно звіреній частці "
                       "авансу)." % closed)
            notif = "success"
        else:
            message = ("Немає що закривати: незакритих проводок першої події "
                       "за оплатами цього рахунку не знайдено.")
            notif = "info"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "ПДВ: перша подія",
                       "message": message, "type": notif},
        }

    # --- Митний ПДВ ----------------------------------------------------------

    def action_ua_post_customs_vat(self):
        """«Взяти в кредит»: проводка Дт 6412 / Кт 3771 на суму ПДВ із митної
        декларації. Рахунок 3771 закриється банківською оплатою митниці.
        Повторне натискання нічого не дублює."""
        self.ensure_one()
        if self.ua_customs_move_id:
            message, notif = ("Митний ПДВ уже в кредиті: %s"
                              % self.ua_customs_move_id.name, "info")
        elif not self.ua_customs_vat or self.ua_customs_vat <= 0:
            message, notif = ("Вкажіть суму митного ПДВ із митної декларації "
                              "(у гривні).", "warning")
        else:
            company = self.company_id
            acc_vat = company._ua_vat_account("vat")
            acc_customs = company._ua_vat_account("customs")
            journal = company._ua_vat_journal()
            if not acc_vat or not acc_customs or not journal:
                message, notif = (
                    "Не знайдено рахунок ПДВ, рахунок розрахунків з митницею "
                    "або журнал операцій - перевірте план рахунків.", "danger")
            else:
                ref = "Митний ПДВ"
                if self.ua_customs_decl_number:
                    ref += " (МД %s)" % self.ua_customs_decl_number
                ref += ": %s" % (self.name or "")
                entry = self.env["account.move"].create({
                    "journal_id": journal.id,
                    "company_id": company.id,
                    "date": self.invoice_date or fields.Date.context_today(self),
                    "ref": ref,
                    "ua_customs_entry": True,
                    "line_ids": [
                        (0, 0, {"account_id": acc_vat.id,
                                "partner_id": self.partner_id.id,
                                "name": "Податковий кредит: митний ПДВ",
                                "debit": self.ua_customs_vat, "credit": 0.0}),
                        (0, 0, {"account_id": acc_customs.id,
                                "partner_id": self.partner_id.id,
                                "name": "Заборгованість перед митницею (ПДВ)",
                                "debit": 0.0, "credit": self.ua_customs_vat}),
                    ],
                })
                entry.action_post()
                self.ua_customs_move_id = entry
                message, notif = (
                    "Митний ПДВ %s узято в податковий кредит (%s)." % (
                        formatLang(self.env, self.ua_customs_vat,
                                   currency_obj=company.currency_id),
                        entry.name), "success")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": "Митний ПДВ", "message": message, "type": notif},
        }


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _ua_vat_zero_class(self):
        """Чим є нульовий рядок: «exempt» (пільга) чи «export» (0 %).

        Спершу дивимось на групу податка - нативні групи ПДВ 0 %, «Звільнено
        від ПДВ» і «Не є ПДВ» позначені маркером ua_vat_zero_kind. Якщо
        податок нейтральний, дивимось на покупця-нерезидента, далі на режим
        ПДВ товару.
        """
        self.ensure_one()
        for tax in self.tax_ids:
            kind = tax.tax_group_id.ua_vat_zero_kind
            if kind == "export":
                return "export"
            if kind in ("exempt", "not_object"):
                return "exempt"
        partner = self.move_id.partner_id
        if partner.country_id and partner.country_id.code != "UA":
            return "export"
        product = self.product_id
        if product and product.ua_vat_treatment == "exempt":
            return "exempt"
        return "export"

    @api.model_create_multi
    def create(self, vals_list):
        """Пільговий або експортний податок підставляється не лише з екрана.

        Рядки, створені з коду чи API без явних податків, інакше лишалися б зі
        стандартними 20 % товару. Податки, передані явно, поважаємо.
        """
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list):
            try:
                if "tax_ids" in vals or line.display_type != "product":
                    continue
                if line.move_id.state != "draft":
                    continue
                line._ua_onchange_vat_treatment()
            except Exception:
                continue
        return lines

    @api.onchange("product_id")
    def _ua_onchange_vat_treatment(self):
        """Нерезидент - податок 0 % експорт; звільнений товар - пільговий
        податок; решту не чіпаємо і лишаємо стандартний."""
        for line in self:
            try:
                move = line.move_id
                if not line.product_id or not move:
                    continue
                if move.move_type not in ("out_invoice", "out_refund"):
                    continue
                company = move.company_id or self.env.company
                partner = move.partner_id
                if partner.country_id and partner.country_id.code != "UA":
                    tax = company._ua_vat_export_tax()
                elif line.product_id.ua_vat_treatment == "exempt":
                    tax = company._ua_vat_exempt_tax()
                else:
                    continue
                if tax:
                    line.tax_ids = [(6, 0, tax.ids)]
            except Exception:
                continue


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        """Закриття першої події в момент звірки.

        Оплата часто звіряється з рахунком уже після його проведення, і хук
        _post цього не бачить. Ловимо саму звірку. Збій логіки ПДВ не валить
        звірку.
        """
        partials = super().create(vals_list)
        try:
            invoices = (
                partials.debit_move_id.move_id | partials.credit_move_id.move_id
            ).filtered(lambda m: m.move_type == "out_invoice"
                       and m.state == "posted")
            if invoices:
                invoices._ua_reverse_first_event()
                # Перша подія «оплата» з'явилась - перерахувати збережений
                # строк реєстрації: depends компʼюта звірок не бачить.
                invoices._compute_x_pn_deadline()
        except Exception:
            _logger.warning(
                "l10n_ua_vat: закриття першої події при звірці не вдалося (%s)",
                partials.ids, exc_info=True)
        return partials
