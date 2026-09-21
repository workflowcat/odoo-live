# -*- coding: utf-8 -*-
"""Провайдер курсів «НБУ» для OCA currency_rate_update.

OCA дає модель res.currency.rate.provider з двома точками розширення:

* _get_supported_currencies - перелік валют, які провайдер уміє;
* _obtain_rates(base, currencies, date_from, date_to) - словник
  {дата: {валюта: курс}}, де курс уже в конвенції Odoo.

Конвенція Odoo: res.currency.rate.rate = скільки одиниць валюти дають за
одну одиницю валюти компанії. НБУ публікує протилежне - скільки гривень
коштує одна одиниця валюти, а для дрібних валют (єна, форинт, драм) - за
10 або 100 одиниць. Тому:

    UAH за одиницю = rate / units   (НБУ віддає це готовим у rate_per_unit)
    курс Odoo      = 1 / (UAH за одиницю)

Якщо валюта компанії не гривня, курс рахуємо через гривню:

    курс Odoo(C) = (UAH за одиницю бази) / (UAH за одиницю C)

API: https://bank.gov.ua/NBU_Exchange/exchange_site - діапазон дат по одній
валюті. Вихідних у НБУ немає окремим кодом: за суботу й неділю сайт віддає
курс, порахований у пʼятницю. Якщо рядка за дату немає взагалі (свято,
валюта ще не котирувалася) - просто не пишемо курс за цей день.
"""
import logging

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)

NBU_URL = "https://bank.gov.ua/NBU_Exchange/exchange_site"
NBU_TIMEOUT = 15

# Валюти, які НБУ котирує щодня (довідник statdirectory/exchange).
# Список свідомо короткий: рідкісні валюти додаються сюди за потреби.
NBU_CURRENCIES = [
    "AUD", "AZN", "BDT", "BGN", "BRL", "BYN", "CAD", "CHF", "CNY", "CZK",
    "DKK", "DZD", "EGP", "EUR", "GBP", "GEL", "HKD", "HUF", "IDR", "ILS",
    "INR", "IQD", "IRR", "ISK", "JPY", "KGS", "KRW", "KWD", "KZT", "LBP",
    "LYD", "MDL", "MXN", "MYR", "NOK", "NZD", "PKR", "PLN", "RON", "RSD",
    "SAR", "SEK", "SGD", "THB", "TMT", "TND", "TRY", "TWD", "UAH", "USD",
    "UZS", "VND", "XAU", "ZAR",
]


class ResCurrencyRateProviderNBU(models.Model):
    _inherit = "res.currency.rate.provider"

    service = fields.Selection(
        selection_add=[("NBU", "НБУ (Національний банк України)")],
        ondelete={"NBU": "set default"},
    )

    def _get_supported_currencies(self):
        self.ensure_one()
        if self.service != "NBU":
            return super()._get_supported_currencies()
        return list(NBU_CURRENCIES)

    def _nbu_fetch(self, currency, date_from, date_to):
        """Рядки НБУ по одній валюті за діапазон дат. Винесено окремо, щоб
        тести підміняли лише мережевий виклик."""
        response = requests.get(
            NBU_URL,
            params={
                "start": fields.Date.to_date(date_from).strftime("%Y%m%d"),
                "end": fields.Date.to_date(date_to).strftime("%Y%m%d"),
                "valcode": currency.lower(),
                "sort": "exchangedate",
                "order": "asc",
                "json": "",
            },
            timeout=NBU_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    @staticmethod
    def _nbu_uah_per_unit(row):
        """Гривень за одну одиницю валюти. rate_per_unit НБУ вже враховує
        кратність; якщо його немає - ділимо rate на units."""
        value = row.get("rate_per_unit")
        if value:
            return float(value)
        units = float(row.get("units") or 1) or 1.0
        return float(row["rate"]) / units

    def _obtain_rates(self, base_currency, currencies, date_from, date_to):
        self.ensure_one()
        if self.service != "NBU":
            return super()._obtain_rates(base_currency, currencies, date_from, date_to)

        wanted = [c for c in currencies if c != "UAH"]
        # Базу (якщо вона не гривня) теж треба знати, щоб перерахувати курс.
        if base_currency != "UAH" and base_currency not in wanted:
            wanted.append(base_currency)

        # {дата: {валюта: гривень за одиницю}}
        uah_per_unit = {}
        for currency in wanted:
            if currency not in NBU_CURRENCIES:
                _logger.warning("НБУ не котирує валюту %s, пропускаємо", currency)
                continue
            for row in self._nbu_fetch(currency, date_from, date_to):
                if not row.get("rate"):
                    continue
                day = fields.Date.to_date(
                    "-".join(reversed(row["exchangedate"].split(".")))
                )
                uah_per_unit.setdefault(day.isoformat(), {})[currency] = (
                    self._nbu_uah_per_unit(row)
                )

        content = {}
        for day, per_unit in uah_per_unit.items():
            base_uah = 1.0 if base_currency == "UAH" else per_unit.get(base_currency)
            if not base_uah:
                # Курсу бази за цей день немає - решту перерахувати нічим.
                continue
            rates = {}
            for currency, value in per_unit.items():
                if currency == base_currency or not value:
                    continue
                rates[currency] = base_uah / value
            if rates:
                content[day] = rates
        return content
