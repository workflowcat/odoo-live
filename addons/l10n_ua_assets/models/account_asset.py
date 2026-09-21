# -*- coding: utf-8 -*-
"""Українські правила поверх картки активу OCA.

Що вже вміє OCA і ми НЕ пишемо заново:

* прямолінійна амортизація помісячно - method_time «number», period «month»,
  method_number = строк у місяцях; перший рядок припадає на останній день
  місяця, останній рядок добирає залишок до копійки;
* 100 % МНМА у першому місяці - це той самий рушій зі строком 1 місяць;
* 50 / 50 - метод «прямолінійна до ліквідаційної вартості» з ліквідаційною
  50 %: рушій нарахує половину, а друга половина піде у витрати при
  списанні через майстер зняття з обліку;
* prorata, days_calc, знос з дня в день - все на місці.

Чого в OCA немає і що додано тут: амортизація починається з місяця,
НАСТУПНОГО за місяцем введення в експлуатацію (п. 29 П(С)БО 7,
п. 138.3.1 ПКУ). OCA починає з місяця введення. Виправляємо однією
перевизначеною точкою розширення - _get_depreciation_start_date.

Друге: попередження, коли обраний строк менший за мінімальний строк групи
за ПКУ. Саме попередження, не заборона: бухгалтерський строк може бути
коротшим, просто в податковому обліку його доведеться підтягнути.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class AccountAsset(models.Model):
    _inherit = "account.asset"

    ua_start_next_month = fields.Boolean(
        string="Амортизація з наступного місяця",
        compute="_compute_ua_start_next_month",
        readonly=False,
        store=True,
    )
    ua_life_months = fields.Integer(
        string="Строк, міс.",
        compute="_compute_ua_life_months",
    )
    ua_life_warning = fields.Char(
        string="Податкове попередження",
        compute="_compute_ua_life_warning",
    )
    ua_depreciation_start = fields.Date(
        string="Перший місяць амортизації",
        compute="_compute_ua_depreciation_start",
        help="Місяць, з якого нараховують амортизацію.",
    )
    # Реквізити друкованих форм ОЗ-1, ОЗ-3, ОЗ-6 (наказ Мінстату 352).
    ua_location = fields.Char(string="Місцезнаходження об'єкта")
    ua_responsible = fields.Char(string="Матеріально відповідальна особа")
    ua_factory_number = fields.Char(string="Заводський номер")
    ua_passport_number = fields.Char(string="Номер паспорта (документа)")
    ua_manufacturer = fields.Char(string="Виробник")
    ua_year_built = fields.Char(string="Рік випуску (побудови)")
    ua_commission = fields.Text(
        string="Склад комісії",
        help="Прізвища та посади членів комісії - по одному в рядку. "
             "Підставляється в ОЗ-1 і ОЗ-3.",
    )
    ua_disposal_reason = fields.Text(string="Причина списання")

    @api.depends("profile_id")
    def _compute_ua_start_next_month(self):
        for asset in self:
            asset.ua_start_next_month = asset.profile_id.ua_start_next_month

    @api.depends("method_number", "method_time", "method_period", "method_end",
                 "date_start")
    def _compute_ua_life_months(self):
        for asset in self:
            asset.ua_life_months = asset._ua_life_months()

    def _ua_life_months(self):
        """Строк корисного використання у місяцях, як його бачить рушій."""
        self.ensure_one()
        if self.method_number:
            if self.method_time == "year":
                return self.method_number * 12
            if self.method_period == "month":
                return self.method_number
            if self.method_period == "quarter":
                return self.method_number * 3
            return self.method_number * 12
        if self.method_end and self.date_start:
            months = (self.method_end.year - self.date_start.year) * 12
            months += self.method_end.month - self.date_start.month
            return months + 1
        return 0

    @api.depends("profile_id.ua_min_months", "ua_life_months")
    def _compute_ua_life_warning(self):
        for asset in self:
            minimum = asset.profile_id.ua_min_months
            months = asset.ua_life_months
            if minimum and months and months < minimum:
                asset.ua_life_warning = (
                    "Строк %s міс. менший за мінімальний строк групи за ПКУ "
                    "(%s міс.). У податковому обліку амортизацію рахують за "
                    "мінімальним строком." % (months, minimum)
                )
            else:
                asset.ua_life_warning = False

    @api.depends("date_start", "ua_start_next_month")
    def _compute_ua_depreciation_start(self):
        for asset in self:
            asset.ua_depreciation_start = asset._ua_first_depreciation_month()

    def _ua_first_depreciation_month(self):
        """Перше число місяця, з якого йде амортизація."""
        self.ensure_one()
        if not self.date_start:
            return False
        if self.ua_start_next_month:
            return self.date_start + relativedelta(months=1, day=1)
        return self.date_start

    # ------------------------------------------------------------------
    # Точка розширення OCA: з якої дати рушій починає будувати таблицю
    # ------------------------------------------------------------------

    def _get_depreciation_start_date(self, fy):
        date_start = super()._get_depreciation_start_date(fy)
        if not self.ua_start_next_month or not self.date_start:
            return date_start
        ua_start = self._ua_first_depreciation_month()
        return max(date_start, ua_start)
