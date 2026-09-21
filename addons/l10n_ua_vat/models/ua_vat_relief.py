# -*- coding: utf-8 -*-
"""Довідник підстав звільнення від ПДВ (предметна пільга за УКТ ЗЕД).

Одна підстава - це норма ПКУ плюс перелік початків кодів УКТ ЗЕД, плюс умови
і строк дії. За цим довідником товар сам стає звільненим
(product.template.ua_vat_treatment), а в податковій накладній звільнений рядок
отримує код ставки 903 і код пільги з довідника ДПС.
"""
from odoo import api, fields, models


class UaVatRelief(models.Model):
    _name = "ua.vat.relief"
    _description = "Підстава звільнення від ПДВ (пільга за УКТ ЗЕД)"
    _order = "sequence, id"

    name = fields.Char(
        string="Підстава (коротко)",
        required=True,
        help="Коротка назва пільги, напр. «БПЛА (безпілотні системи)».",
    )
    sequence = fields.Integer(string="Порядок", default=10)
    active = fields.Boolean(string="Активна", default=True)
    basis = fields.Char(
        string="Норма",
        required=True,
        help="Нормативна підстава: пункт ПКУ плюс постанова КМУ. "
             "Друкується в податковій накладній для пільгових рядків.",
    )
    uktzed_prefixes = fields.Text(
        string="Префікси УКТ ЗЕД",
        required=True,
        help="Початки кодів УКТ ЗЕД через кому або пробіл (напр. «8806, 8807»). "
             "Товар звільнений, якщо його код починається з будь-якого префікса.",
    )
    conditions = fields.Text(
        string="Умови застосування",
        help="Кінцеве призначення, отримувач, період дії.",
    )
    date_from = fields.Date(
        string="Діє з", help="Порожньо - без обмеження знизу.")
    date_to = fields.Date(
        string="Діє до", help="Порожньо - безстроково.")
    dps_benefit_code = fields.Char(
        string="Код пільги (довідник ДПС)",
        size=8,
        help="8-значний код з чинного Довідника податкових пільг ДПС. "
             "Зазначається у графі 9 податкової накладної для звільнених рядків.",
    )
    # п.32 підрозд.2 розд.XX ПКУ (пільга БПЛА): положення п.198.5 і ст.199 до
    # неї не застосовуються, право на податковий кредит збережено. Механізм
    # універсальний - інші пільги можна позначити так само.
    no_compensation = fields.Boolean(
        string="Без компенсації (п.198.5 і ст.199 не застосовуються)",
        default=False,
        help="Норма пільги прямо виключає нарахування компенсуючих ПЗ. "
             "Такі обсяги не беруть участі і в розрахунку ЧВ.",
    )

    def _prefixes(self):
        """Нормалізований список префіксів (без пробілів і крапок)."""
        self.ensure_one()
        raw = (self.uktzed_prefixes or "").replace(";", ",").replace(" ", ",")
        return [p for p in (
            chunk.strip().replace(" ", "").replace(".", "")
            for chunk in raw.split(",")) if p]

    @staticmethod
    def _norm_code(uktzed):
        """Код УКТ ЗЕД без пробілів і крапок - для порівняння префіксів."""
        return (uktzed or "").replace(" ", "").replace(".", "").strip()

    @api.model
    def _match(self, uktzed, on_date=None):
        """Чинна на дату активна підстава для коду УКТ ЗЕД.

        Повертає перший збіг за порядком (sequence) або порожній рекордсет.
        """
        code = self._norm_code(uktzed)
        if not code:
            return self.browse()
        on_date = on_date or fields.Date.context_today(self)
        for relief in self.search([("active", "=", True)]):
            if relief.date_from and on_date < relief.date_from:
                continue
            if relief.date_to and on_date > relief.date_to:
                continue
            for prefix in relief._prefixes():
                if code.startswith(prefix):
                    return relief
        return self.browse()
