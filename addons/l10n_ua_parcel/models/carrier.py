"""Перевізник і те, як питати його про стан відправлень.

Способи (connector):
- novaposhta - API Нової пошти; ключ API не обов'язковий, з ключем і телефоном видно більше;
- ukrposhta - API відстеження Укрпошти, потрібен токен з додатка до договору;
- bridge - через міст інтеграцій (`bp_bridge`, маршрут /api/parcels/track) для Meest, DHL,
  сервісів-агрегаторів; мост повертає той самий спільний вигляд, що й parcel_core;
- demo - вбудований сценарій для демо-бази і тестів, без мережі;
- manual - стан змінюють люди.

Ключ береться спершу зі змінної середовища UA_PARCEL_<КОД>_KEY (наприклад,
UA_PARCEL_NOVAPOSHTA_KEY), далі з поля картки, яке бачить лише адміністратор.
"""
import json
import logging
import os
import zlib
from datetime import timedelta

import pytz
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import parcel_core as core

_logger = logging.getLogger(__name__)

NP_URL = "https://api.novaposhta.ua/v2.0/json/"
UP_URL = "https://www.ukrposhta.ua/status-tracking/0.0.1/statuses"
TIMEOUT = 30
NP_BATCH = 100
UP_BATCH = 50
try:
    KYIV = pytz.timezone("Europe/Kyiv")
except pytz.UnknownTimeZoneError:  # старі бази часових поясів
    KYIV = pytz.timezone("Europe/Kiev")


def to_utc(moment):
    """Час перевізника (київський, без пояса) -> UTC без пояса, як зберігає Odoo."""
    if not moment:
        return False
    return KYIV.localize(moment).astimezone(pytz.utc).replace(tzinfo=None)


def to_kyiv(moment):
    return pytz.utc.localize(moment).astimezone(KYIV).replace(tzinfo=None)

CONNECTORS = [
    ("novaposhta", "API Нової пошти"),
    ("ukrposhta", "API Укрпошти"),
    ("bridge", "Через міст інтеграцій"),
    ("demo", "Демо без мережі"),
    ("manual", "Вручну"),
]

# Демо: (година від створення, стан, текст). Номер, що закінчується на 7, не забирають і він
# повертається; міжнародний номер S10 проходить митницю.
DEMO_STEPS = [
    (0, "new", "Відправник створив накладну"),
    (6, "in_transit", "Прийнято у відділенні"),
    (20, "in_transit", "Прямує до міста одержувача"),
    (40, "at_pickup", "Прибуло у відділення"),
    (64, "delivered", "Отримано"),
]
DEMO_RETURN = DEMO_STEPS[:4] + [
    (160, "returning", "Повернення: збіг строк безкоштовного зберігання"),
    (200, "returned", "Вручено відправнику"),
]
DEMO_IMPORT = [
    (0, "in_transit", "Прийнято (міжнародне)"),
    (30, "in_transit", "Надійшло до місця міжнародного поштового обміну"),
    (50, "customs", "Пред'явлено митниці"),
    (80, "in_transit", "Випущено митницею"),
    (100, "at_pickup", "Надійшло у відділення доставки"),
    (130, "delivered", "Вручено"),
]


class UaParcelCarrier(models.Model):
    _name = "ua.parcel.carrier"
    _description = "Перевізник відправлень"
    _order = "sequence, name"

    name = fields.Char("Назва", required=True, translate=True)
    code = fields.Char("Код", required=True, help="Латиницею, без пробілів: novaposhta, ukrposhta, meest.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", "Компанія",
                                 help="Порожньо - перевізник спільний для всіх компаній бази.")
    connector = fields.Selection(CONNECTORS, "Як дізнаємося стан", required=True, default="manual")
    api_key = fields.Char("Ключ API", groups="base.group_system", copy=False,
                          help="Краще задати змінною середовища UA_PARCEL_<КОД>_KEY.")
    phone = fields.Char("Телефон компанії для перевірки",
                        help="Нова пошта показує повні дані відправлення, якщо в запиті телефон "
                             "відправника чи одержувача.")
    tracking_url = fields.Char("Сторінка відстеження", help="Адреса з {number} на місці номера.")
    number_pattern = fields.Char("Шаблон номера", help="Регулярний вираз для номерів цього перевізника.")
    check_hours = fields.Integer("Перевіряти кожні, год", default=3)
    stuck_days = fields.Integer("Без руху понад, днів", default=4,
                                help="Відправлення без нових подій довше за цей строк потрапляє в «Потребують уваги».")
    pickup_days = fields.Integer("Безкоштовне зберігання, днів", default=5,
                                 help="Якщо перевізник не назвав дату платного зберігання, рахуємо від прибуття.")
    note = fields.Text("Примітка")
    parcel_count = fields.Integer("Відправлень", compute="_compute_parcel_count")

    _code_uniq = models.Constraint("unique(code, company_id)", "Перевізник з таким кодом уже є.")

    def _compute_parcel_count(self):
        data = self.env["ua.parcel"]._read_group([("carrier_id", "in", self.ids)], ["carrier_id"], ["__count"])
        counts = {carrier.id: count for carrier, count in data}
        for carrier in self:
            carrier.parcel_count = counts.get(carrier.id, 0)

    def action_ua_parcels(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_parcel.action_ua_parcel")
        action["domain"] = [("carrier_id", "=", self.id)]
        action["context"] = {"default_carrier_id": self.id}
        return action

    # --------------------------------------------------------------- допоміжне
    @api.model
    def _ua_detect(self, number):
        """Перевізник для номера: спершу шаблони з довідника, далі вбудовані."""
        carriers = self.search([("company_id", "in", [False, self.env.company.id])])
        extra = [(c.code, c.number_pattern) for c in carriers if c.number_pattern]
        code = core.detect_carrier(number, extra)
        return carriers.filtered(lambda c: c.code == code)[:1] if code else self.browse()

    def _ua_key(self):
        self.ensure_one()
        env_key = os.environ.get("UA_PARCEL_%s_KEY" % (self.code or "").upper())
        return env_key or self.sudo().api_key or ""

    def _ua_link(self, number):
        self.ensure_one()
        return self.tracking_url.replace("{number}", number) if self.tracking_url else False

    def _ua_post(self, url, payload, headers=None):
        """Запит до перевізника. Окремий метод, щоб тести підставляли відповідь без мережі."""
        try:
            r = requests.post(url, data=json.dumps(payload), timeout=TIMEOUT, allow_redirects=False,
                              headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        except requests.RequestException as e:
            raise UserError(_("%(carrier)s недоступний: %(error)s", carrier=self.name, error=e)) from e
        if r.status_code in (401, 403):
            raise UserError(_("%s не прийняв ключ API. Перевірте ключ у картці перевізника "
                              "або змінну середовища.") % self.name)
        if r.status_code >= 400:
            raise UserError(_("%(carrier)s відповів помилкою %(code)s.", carrier=self.name, code=r.status_code))
        try:
            return r.json()
        except ValueError as e:
            raise UserError(_("%s повернув не JSON.") % self.name) from e

    # --------------------------------------------------------------- запит стану
    def _ua_fetch(self, parcels):
        """{номер: спільний вигляд з parcel_core} для відправлень цього перевізника."""
        self.ensure_one()
        method = getattr(self, "_ua_fetch_%s" % self.connector, None)
        return method(parcels) if method else {}

    def _ua_fetch_manual(self, parcels):
        return {}

    def _ua_fetch_novaposhta(self, parcels):
        out = {}
        key = self._ua_key()
        for start in range(0, len(parcels), NP_BATCH):
            chunk = parcels[start:start + NP_BATCH]
            payload = {
                "apiKey": key, "modelName": "TrackingDocument", "calledMethod": "getStatusDocuments",
                "methodProperties": {"Documents": [
                    {"DocumentNumber": p.name, "Phone": p._ua_phone()} for p in chunk]},
            }
            data = self._ua_post(NP_URL, payload)
            if not data.get("success"):
                raise UserError(_("Нова пошта: %s") % "; ".join(map(str, data.get("errors") or [])))
            for row in data.get("data") or []:
                result = core.np_result(row)
                out[result["number"]] = result
        return out

    def _ua_fetch_ukrposhta(self, parcels):
        key = self._ua_key()
        if not key:
            raise UserError(_("Для Укрпошти потрібен токен відстеження: змінна UA_PARCEL_UKRPOSHTA_KEY "
                              "або поле «Ключ API» в картці перевізника."))
        out = {}
        for start in range(0, len(parcels), UP_BATCH):
            chunk = parcels[start:start + UP_BATCH]
            rows = self._ua_post(UP_URL, chunk.mapped("name"), {"Authorization": "Bearer %s" % key})
            if isinstance(rows, dict):
                rows = rows.get("statuses") or rows.get("data") or []
            out.update(core.up_results(rows))
        return out

    def _ua_fetch_bridge(self, parcels):
        if "bp.bridge" not in self.env:
            raise UserError(_("Міст інтеграцій не встановлено (модуль bp_bridge)."))
        status, data = self.env["bp.bridge"]._call(
            "POST", "/api/parcels/track", {"carrier": self.code, "numbers": parcels.mapped("name")})
        if status >= 400:
            raise UserError(_("Міст не зміг перевірити відправлення: %s") % (data.get("error") or status))
        return core.generic_results(data.get("results") or [])

    def _ua_fetch_demo(self, parcels):
        now = fields.Datetime.now()
        rows = []
        for parcel in parcels:
            start = parcel.create_date or now
            if parcel.name[-1:] == "7":
                steps = DEMO_RETURN
            elif core.S10.fullmatch(parcel.name):
                steps = DEMO_IMPORT
            else:
                steps = DEMO_STEPS
            # Різні відправлення стартують з різним зсувом, щоб демо не рухалося строєм.
            shift = zlib.crc32(parcel.name.encode()) % 30
            events = []
            for hours, state, text in steps:
                when = start if not hours else start + timedelta(hours=hours + shift)
                if when <= now:
                    events.append({"state": state, "text": text, "code": state,
                                   "date": fields.Datetime.to_string(to_kyiv(when))})
            rows.append({"number": parcel.name, "events": events})
        return core.generic_results(rows)
