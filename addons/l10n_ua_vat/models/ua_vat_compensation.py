# -*- coding: utf-8 -*-
"""Компенсуючі податкові зобов'язання: п.198.5 і ст.199 ПКУ.

Якщо купили з податковим кредитом, а використали у звільнених операціях,
кредит треба погасити зустрічним зобов'язанням. Це і є компенсуючі ПЗ.

* п.198.5 «г» ПКУ: нараховуються компенсуючі ПЗ; база за п.189.1 - вартість
  придбання. Зведена податкова накладна складається не пізніше останнього дня
  звітного періоду, тип причини 09 (звільнені операції), реєструється протягом
  20 календарних днів після останнього дня місяця складання. Воєнні правила
  цей строк не подовжують.
* ст.199: придбання подвійного призначення компенсуються частково. ЧВ - частка
  використання в оподатковуваних операціях: оподатковувані обсяги поділити на
  загальні і помножити на 100. Компенсується частка (100 мінус ЧВ) відсотків.
  Річний перерахунок - п.199.4 і 199.5, у грудні.
* Для пільги БПЛА (п.32 підрозд.2 розд.XX ПКУ) з 26.12.2025 п.198.5 і ст.199
  не застосовуються, право на кредит збережено. Такі пільги позначені
  прапорцем «без компенсації» у довіднику, їхні обсяги виключаються і з ЧВ.

Проводки: нарахування Дт 6432 «ПЗ непідтверджені» / Кт 6412 «Розрахунки за
ПДВ», списання на витрати Дт 949 / Кт 6432. Рахунок 6431 тут не чіпаємо - він
зайнятий механізмом першої події.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Позначка проводки річного перерахунку, за якою шукаємо дублі.
UA_ANNUAL_REF = "Річний перерахунок ЧВ %d"


class UaVatCompensation(models.Model):
    """Місячний розрахунок компенсуючих ПЗ.

    «Розрахувати» дає ЧВ періоду і перегляд рядків (прямі на 100 %, подвійні
    на (100 мінус ЧВ) %). «Провести» робить бухгалтерську проводку і зведену
    податкову накладну. Ідемпотентно.
    """

    _name = "ua.vat.compensation"
    _description = "Компенсуючі ПЗ (п.198.5 / ст.199 ПКУ)"
    _order = "date_period desc, id desc"

    name = fields.Char(string="Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        "res.currency", string="Валюта", related="company_id.currency_id")
    date_period = fields.Date(
        string="Місяць періоду",
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help="Будь-яка дата місяця, за який рахуємо компенсуючі ПЗ.")
    state = fields.Selection(
        selection=[("draft", "Чернетка"), ("posted", "Проведено")],
        string="Стан", default="draft", copy=False)

    chv = fields.Float(
        string="ЧВ, %", digits=(5, 2), readonly=True,
        help="Частка використання в оподатковуваних операціях. Обсяги за "
             "пільгами без компенсації з розрахунку виключено.")
    taxable_base = fields.Monetary(
        string="Оподатковувані обсяги", currency_field="currency_id",
        readonly=True)
    denom_base = fields.Monetary(
        string="Загальні обсяги (для ЧВ)", currency_field="currency_id",
        readonly=True)
    nocomp_base = fields.Monetary(
        string="Виключено (пільги без компенсації)",
        currency_field="currency_id", readonly=True)

    line_ids = fields.One2many(
        "ua.vat.compensation.line", "comp_id", string="Рядки компенсації",
        readonly=True)
    direct_vat = fields.Monetary(
        string="ПЗ прямі (100 %)", currency_field="currency_id", readonly=True)
    dual_vat = fields.Monetary(
        string="ПЗ подвійні", currency_field="currency_id", readonly=True)
    comp_base_total = fields.Monetary(
        string="База компенсації", currency_field="currency_id", readonly=True)
    comp_vat_total = fields.Monetary(
        string="Компенсуючі ПЗ разом", currency_field="currency_id",
        readonly=True)
    move_id = fields.Many2one(
        "account.move", string="Проводка компенсації", readonly=True, copy=False)
    doc_id = fields.Many2one(
        "ua.vat.document", string="Зведена ПН", readonly=True, copy=False)

    x_annual_chv = fields.Float(
        string="Річна ЧВ, %", digits=(5, 2), readonly=True, copy=False,
        help="Частка використання за підсумками року (ст.199.4).")
    x_annual_delta = fields.Monetary(
        string="Різниця річного перерахунку", currency_field="currency_id",
        readonly=True, copy=False,
        help="Сума по всіх подвійних придбаннях року за річною ЧВ мінус "
             "проведені місячні компенсації. Додатна - донарахування ПЗ.")
    x_annual_move_id = fields.Many2one(
        "account.move", string="Проводка річного перерахунку", readonly=True,
        copy=False)
    x_annual_rk_ids = fields.Many2many(
        "ua.vat.document", "ua_vat_comp_annual_rk_rel", "comp_id", "doc_id",
        string="РК річного перерахунку", readonly=True, copy=False)

    @api.depends("date_period")
    def _compute_name(self):
        for rec in self:
            rec.name = "Компенсуючі ПЗ %s" % (
                rec.date_period.strftime("%Y-%m") if rec.date_period else "?")

    # --- Період --------------------------------------------------------------

    def _month_bounds(self):
        """(перший день місяця, перший день наступного)."""
        self.ensure_one()
        d = self.date_period or fields.Date.context_today(self)
        start = d.replace(day=1)
        end = (start.replace(year=start.year + 1, month=1)
               if start.month == 12 else start.replace(month=start.month + 1))
        return start, end

    def _ym(self):
        self.ensure_one()
        return (self.date_period
                or fields.Date.context_today(self)).strftime("%Y-%m")

    # --- Класифікація --------------------------------------------------------

    @staticmethod
    def _line_rate(line):
        """Ставка рядка - перший відсотковий податок."""
        for tax in line.tax_ids:
            if tax.amount_type == "percent":
                return tax.amount
        return 0.0

    @staticmethod
    def _relief_of(product):
        """Чинна підстава пільги товару або None."""
        if not product:
            return None
        try:
            return product.x_vat_relief_effective_id or None
        except Exception:
            return None

    def _sales_volumes(self, date_from, date_to):
        """Обсяги постачань періоду: (оподатковувані, знаменник, виключені).

        Оподатковувані - усі ставки більші за нуль плюс 0 % експорт. Звільнені
        компенсовні - лише у знаменнику. Звільнені за пільгами без компенсації
        виключені зовсім, за аналогією з п.199.6.

        Обсяг беремо у валюті компанії з balance рядка: дохідний рядок
        вихідного рахунку кредитовий, повернення дебетове, тому знак виходить
        сам, а курс - це курс проведення. Через price_subtotal валютні продажі
        спотворювали б ЧВ.
        """
        moves = self.env["account.move"].search([
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<", date_to),
        ])
        taxable, exempt_comp, nocomp = 0.0, 0.0, 0.0
        for move in moves:
            for line in move.invoice_line_ids:
                if line.display_type not in (False, "product"):
                    continue
                base = -(line.balance or 0.0)
                if self._line_rate(line) != 0.0:
                    taxable += base
                    continue
                if line._ua_vat_zero_class() == "export":
                    taxable += base
                    continue
                relief = self._relief_of(line.product_id)
                if relief and relief.no_compensation:
                    nocomp += base
                else:
                    exempt_comp += base
        return taxable, taxable + exempt_comp, nocomp

    def _classify_purchase_line(self, line):
        """«direct», «dual» або False для рядка вхідного рахунку.

        * товар є компонентом специфікації: дивимось на готові вироби. Лише
          звільнені компенсовні - прямий, тобто весь кредит компенсується;
          мікс звільнених і оподатковуваних - подвійний; лише оподатковувані
          або звільнені без компенсації - не компенсуємо;
        * сам товар звільнений з компенсовною пільгою (перепродаж) - прямий;
        * решта (послуги, оренда, комуналка, товари без мапінгу) - подвійний.
        """
        product = line.product_id
        if product and "mrp.bom.line" in self.env:
            try:
                bom_lines = self.env["mrp.bom.line"].search([
                    ("product_id", "=", product.id),
                    ("bom_id.company_id", "in", [False, self.company_id.id])])
                finished = bom_lines.bom_id.product_tmpl_id
            except Exception:
                finished = self.env["product.template"]
            if finished:
                comp_exempt = taxable_use = False
                for tmpl in finished:
                    if tmpl.x_vat_treatment == "exempt":
                        relief = self._relief_of(tmpl)
                        if relief and relief.no_compensation:
                            taxable_use = True  # кредит збережено
                        else:
                            comp_exempt = True
                    else:
                        taxable_use = True
                if comp_exempt and not taxable_use:
                    return "direct"
                if comp_exempt and taxable_use:
                    return "dual"
                return False
        if product and product.x_vat_treatment == "exempt":
            relief = self._relief_of(product)
            if relief and relief.no_compensation:
                return False
            return "direct"
        return "dual"

    # --- Розрахувати ---------------------------------------------------------

    def action_compute(self):
        """ЧВ періоду і перегляд рядків компенсації. Лише в чернетці."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(
                "Розрахунок уже проведено, перерахунок заборонено. Для змін "
                "створіть новий запис або зробіть річний перерахунок.")
        start, end = self._month_bounds()
        taxable, denom, nocomp = self._sales_volumes(start, end)
        chv = round(100.0 * taxable / denom, 2) if denom > 0.005 else 100.0
        chv = max(0.0, min(100.0, chv))
        dual_share = round((100.0 - chv) / 100.0, 4)

        self.line_ids.unlink()
        line_vals = []
        direct_vat = dual_vat = base_total = 0.0
        bills = self.env["account.move"].search([
            ("move_type", "=", "in_invoice"),
            ("state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
            ("invoice_date", ">=", start),
            ("invoice_date", "<", end),
        ])
        comp_cur = self.company_id.currency_id
        for bill in bills:
            for line in bill.invoice_line_ids:
                if line.display_type not in (False, "product"):
                    continue
                # База і ПДВ рядка у валюті компанії. База - balance (дебет
                # рядка вхідного рахунку курсом проведення); ПДВ валютного
                # рядка масштабуємо тим самим курсом, бо в balance його немає.
                vat_move = round(line.price_total - line.price_subtotal, 2)
                if (line.currency_id and line.currency_id != comp_cur
                        and abs(line.price_subtotal) > 0.005):
                    base_cc = line.balance or 0.0
                    vat_in = round(vat_move * base_cc / line.price_subtotal, 2)
                else:
                    base_cc = line.price_subtotal
                    vat_in = vat_move
                if vat_in <= 0.005:
                    continue  # без вхідного ПДВ компенсувати нічого
                kind = self._classify_purchase_line(line)
                if not kind:
                    continue
                share = 1.0 if kind == "direct" else dual_share
                comp_base = round(base_cc * share, 2)
                comp_vat = round(vat_in * share, 2)
                # Подвійні рядки зберігаємо навіть з нульовою компенсацією
                # (ЧВ = 100 %): інакше вони випадуть з бази річного
                # перерахунку і грудень занизить донарахування.
                if kind == "direct" and comp_vat <= 0.005:
                    continue
                line_vals.append({
                    "comp_id": self.id,
                    "source_line_id": line.id,
                    "name": "%s: %s" % (
                        bill.name or "?",
                        (line.name or line.product_id.display_name
                         or "рядок")[:64]),
                    "product_id": line.product_id.id or False,
                    "kind": kind,
                    "base": base_cc,
                    "vat_in": vat_in,
                    "share": round(share * 100.0, 2),
                    "comp_base": comp_base,
                    "comp_vat": comp_vat,
                })
                base_total += comp_base
                if kind == "direct":
                    direct_vat += comp_vat
                else:
                    dual_vat += comp_vat
        self.env["ua.vat.compensation.line"].create(line_vals)
        self.write({
            "chv": chv,
            "taxable_base": round(taxable, 2),
            "denom_base": round(denom, 2),
            "nocomp_base": round(nocomp, 2),
            "direct_vat": round(direct_vat, 2),
            "dual_vat": round(dual_vat, 2),
            "comp_base_total": round(base_total, 2),
            "comp_vat_total": round(direct_vat + dual_vat, 2),
        })
        return True

    # --- Провести ------------------------------------------------------------

    def _ua_accounts(self):
        """Три рахунки компенсації. Бракує хоча б одного - кажемо, якого."""
        self.ensure_one()
        company = self.company_id
        keys = {"pz_unconfirmed": "6432 (ПЗ непідтверджені)",
                "vat": "6412 (розрахунки за ПДВ)",
                "other_expense": "949 (інші витрати)"}
        found = {}
        for key, label in keys.items():
            account = company._ua_vat_account(key)
            if not account:
                raise UserError(
                    "У плані рахунків компанії немає рахунку %s - компенсуючі "
                    "ПЗ провести нікуди." % label)
            found[key] = account
        return found

    def action_post(self):
        """Провести компенсацію: бухгалтерська проводка плюс зведена ПН."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError("Компенсацію за %s уже проведено (%s)."
                            % (self._ym(), self.move_id.name or "?"))
        # Після проведеного річного перерахунку місячні компенсації того року
        # вже не проводяться: вони не потрапили б у зафіксовану річну дельту.
        year = (self.date_period or fields.Date.context_today(self)).year
        annual = self.env["account.move"].search([
            ("ref", "=", UA_ANNUAL_REF % year),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "posted")], limit=1)
        if annual:
            raise UserError(
                "Річний перерахунок ЧВ за %d уже проведено (%s), місячну "
                "компенсацію за %s проводити пізно: вона не врахована у річній "
                "різниці." % (year, annual.name, self._ym()))
        self.action_compute()
        if self.comp_vat_total < 0.01:
            raise UserError(
                "Немає що компенсувати за %s: компенсуючі ПЗ дорівнюють нулю."
                % self._ym())
        ym = self._ym()
        ref = "Компенсуючі ПЗ %s" % ym
        existing = self.env["account.move"].search([
            ("ref", "=", ref),
            ("company_id", "=", self.company_id.id)], limit=1)
        if existing:
            self.write({"move_id": existing.id, "state": "posted"})
            raise UserError("Компенсуючі ПЗ за %s уже проведені (%s)."
                            % (ym, existing.name))
        _start, end = self._month_bounds()
        last_day = end - timedelta(days=1)
        acc = self._ua_accounts()
        journal = self.company_id._ua_vat_journal()
        if not journal:
            raise UserError("Немає журналу інших операцій для проводки.")
        vat = round(self.comp_vat_total, 2)
        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": last_day,  # зведена ПН - останній день звітного періоду
            "ref": ref,
            "x_ua_vat_comp": True,
            "line_ids": [
                (0, 0, {"account_id": acc["pz_unconfirmed"].id,
                        "name": "Нарахування компенсуючих ПЗ (зведена ПН, 09)",
                        "debit": vat, "credit": 0.0}),
                (0, 0, {"account_id": acc["vat"].id,
                        "name": "Компенсуючі ПЗ за п.198.5 / ст.199 ПКУ",
                        "debit": 0.0, "credit": vat}),
                (0, 0, {"account_id": acc["other_expense"].id,
                        "name": "Списання компенсуючих ПЗ на витрати",
                        "debit": vat, "credit": 0.0}),
                (0, 0, {"account_id": acc["pz_unconfirmed"].id,
                        "name": "Списання компенсуючих ПЗ на витрати",
                        "debit": 0.0, "credit": vat}),
            ],
        })
        move.action_post()
        # Шукаємо за проводкою, а не за назвою: однойменна зведена ПН іншої
        # компанії не має сюди чіплятися.
        doc = self.env["ua.vat.document"].search([
            ("move_id", "=", move.id),
            ("doc_kind", "=", "tax_invoice")], limit=1)
        if not doc:
            doc = self.env["ua.vat.document"].create({
                "name": "Зведена ПН (компенсуюча) %s" % ym,
                "doc_kind": "tax_invoice",
                "move_id": move.id,
                "company_id": self.company_id.id,
                "x_pn_consolidated": True,
                "x_pn_reason_type": "09",
            })
        self.write({"move_id": move.id, "doc_id": doc.id, "state": "posted"})
        return True

    # --- Річний перерахунок (ст.199.4 і 199.5) --------------------------------

    def _annual_recalc_preview(self, year):
        """Перерахунок року без проведення: (річна ЧВ, розклад по місяцях).

        Річна ЧВ - за обсягами постачань за рік. По кожному подвійному
        придбанню року цільова компенсація - вхідний ПДВ помножений на
        (100 мінус річна ЧВ) відсотків, з порядковим округленням до копійки,
        як у місячному розрахунку.
        """
        self.ensure_one()
        d_from = fields.Date.to_date("%d-01-01" % year)
        d_to = fields.Date.to_date("%d-01-01" % (year + 1))
        taxable, denom, _nocomp = self._sales_volumes(d_from, d_to)
        chv_year = round(100.0 * taxable / denom, 2) if denom > 0.005 else 100.0
        chv_year = max(0.0, min(100.0, chv_year))
        dual_share = (100.0 - chv_year) / 100.0
        comps = self.search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "posted"),
            ("date_period", ">=", d_from),
            ("date_period", "<", d_to),
        ], order="date_period")
        breakdown = []
        for comp in comps:
            duals = comp.line_ids.filtered(lambda l: l.kind == "dual")
            posted = round(sum(duals.mapped("comp_vat")), 2)
            target = round(sum(round(l.vat_in * dual_share, 2) for l in duals), 2)
            breakdown.append({
                "comp": comp,
                "dual_vat_in": round(sum(duals.mapped("vat_in")), 2),
                "posted": posted,
                "target": target,
                "delta": round(target - posted, 2),
            })
        return chv_year, breakdown

    def action_annual_recalc(self):
        """Річний перерахунок ЧВ за ст.199.4 і 199.5 ПКУ.

        Різниця по кожному місяцю дає РК до відповідної зведеної ПН (умовний
        код причини 202), а сума різниць - коригуючу проводку грудня.
        Донарахування проводиться як звичайна компенсація, зменшення -
        дзеркально. Ідемпотентно за позначкою проводки.

        Свідомі спрощення: без окремого перерахунку необоротних активів
        (п.199.4 абз.2).
        """
        self.ensure_one()
        # Перерахунок - груднева операція: РК і проводка датуються груднем.
        if not self.date_period or self.date_period.month != 12:
            raise UserError(
                "Річний перерахунок ЧВ запускається із запису за грудень "
                "(ст.199.4 ПКУ: результат відображається у декларації грудня). "
                "Поточний запис - за %s." % self._ym())
        year = self.date_period.year
        ref = UA_ANNUAL_REF % year
        existing = self.env["account.move"].search([
            ("ref", "=", ref),
            ("company_id", "=", self.company_id.id)], limit=1)
        if existing:
            raise UserError("Річний перерахунок за %d уже проведено (%s)."
                            % (year, existing.name))
        chv_year, breakdown = self._annual_recalc_preview(year)
        delta = round(sum(b["delta"] for b in breakdown), 2)
        if abs(delta) < 0.01:
            raise UserError(
                "Річний перерахунок %d: різниці немає (річна ЧВ %.2f %%)."
                % (year, chv_year))
        acc = self._ua_accounts()
        journal = self.company_id._ua_vat_journal()
        if not journal:
            raise UserError("Немає журналу інших операцій для проводки.")
        amount = abs(delta)
        # Додатна різниця - донарахування, від'ємна - зменшення (дзеркально).
        legs = ("debit", "credit") if delta > 0 else ("credit", "debit")
        lines = [
            (0, 0, {"account_id": acc["pz_unconfirmed"].id,
                    "name": "Річний перерахунок ЧВ (РК до зведених ПН)",
                    legs[0]: amount, legs[1]: 0.0}),
            (0, 0, {"account_id": acc["vat"].id,
                    "name": "Річний перерахунок ЧВ (ст.199.4 ПКУ)",
                    legs[0]: 0.0, legs[1]: amount}),
            (0, 0, {"account_id": acc["other_expense"].id,
                    "name": "Річний перерахунок ЧВ: коригування витрат",
                    legs[0]: amount, legs[1]: 0.0}),
            (0, 0, {"account_id": acc["pz_unconfirmed"].id,
                    "name": "Річний перерахунок ЧВ: коригування витрат",
                    legs[0]: 0.0, legs[1]: amount}),
        ]
        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": fields.Date.to_date("%d-12-31" % year),
            "ref": ref,
            "x_ua_vat_comp": True,
            "line_ids": lines,
        })
        move.action_post()
        rk_docs = self.env["ua.vat.document"]
        for b in breakdown:
            if abs(b["delta"]) < 0.01:
                continue
            comp = b["comp"]
            rk_docs |= self.env["ua.vat.document"].create({
                "name": "РК до зведеної ПН %s (річний перерахунок %d)"
                        % (comp._ym(), year),
                "doc_kind": "adjustment",
                "move_id": move.id,
                "company_id": self.company_id.id,
                "x_pn_consolidated": True,
                "x_pn_reason_type": "09",
                "x_adj_reason_code": "202",
                "x_adj_pn_document_id": comp.doc_id.id or False,
            })
        self.write({
            "x_annual_chv": chv_year,
            "x_annual_delta": delta,
            "x_annual_move_id": move.id,
            "x_annual_rk_ids": [(6, 0, rk_docs.ids)],
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Річний перерахунок ЧВ",
                "message": "Річна ЧВ %.2f %%, різниця %.2f проведена (%s), "
                           "РК: %d." % (chv_year, delta, move.name,
                                        len(rk_docs)),
                "type": "success",
            },
        }

    @api.model
    def _compensable_exempt_base(self, company, date_from, date_to):
        """Обсяг звільнених компенсовних постачань періоду - для чек-листа."""
        probe = self.new({"company_id": company.id, "date_period": date_from})
        taxable, denom, _nocomp = probe._sales_volumes(
            date_from, date_to + timedelta(days=1))
        return round(denom - taxable, 2)


class UaVatCompensationLine(models.Model):
    """Рядок компенсації: джерело, вид, частка і суми."""

    _name = "ua.vat.compensation.line"
    _description = "Рядок компенсуючих ПЗ"
    _order = "kind, id"

    comp_id = fields.Many2one(
        "ua.vat.compensation", string="Розрахунок", required=True,
        ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="comp_id.currency_id")
    source_line_id = fields.Many2one(
        "account.move.line", string="Рядок рахунку", ondelete="set null")
    name = fields.Char(string="Джерело")
    product_id = fields.Many2one("product.product", string="Товар або послуга")
    kind = fields.Selection(
        selection=[("direct", "Прямий (100 %)"),
                   ("dual", "Подвійний")],
        string="Вид", required=True)
    base = fields.Monetary(
        string="База придбання", currency_field="currency_id")
    vat_in = fields.Monetary(
        string="Вхідний ПДВ", currency_field="currency_id")
    share = fields.Float(string="Частка, %", digits=(5, 2))
    comp_base = fields.Monetary(
        string="База компенсації", currency_field="currency_id")
    comp_vat = fields.Monetary(
        string="Компенсуючі ПЗ", currency_field="currency_id")
