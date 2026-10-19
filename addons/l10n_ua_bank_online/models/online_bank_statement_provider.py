# -*- coding: utf-8 -*-
"""Постачальники виписок для України: ПриватБанк (Автоклієнт) і Monobank.

Рушій - OCA `account_statement_import_online`: модель `online.bank.statement.provider`
викликає `_obtain_statement_data(date_since, date_until)` і сама створює виписки.
Тут лише дві речі: запит до банку і переклад відповіді в рядки виписки.

ПриватБанк, Автоклієнт (v3): GET {api_base}/statements/transactions
  заголовки: id (ідентифікатор клієнта), token (токен Автоклієнта)
  параметри: acc (рахунок), startDate і endDate у форматі dd-mm-yyyy, limit, followId (наступна сторінка)
  відповідь: {"status": "SUCCESS", "exist_next_page": true, "next_page_id": "...", "transactions": [...]}
  суми: поле SUM, напрям - TRANTYPE ("D" - списання, "C" - зарахування)

Monobank: GET {api_base}/personal/statement/{рахунок}/{від}/{до}
  заголовок: X-Token
  межі часу - секунди Unix, одне вікно не більше 31 дня, не частіше ніж раз на 60 секунд
  суми в копійках зі знаком; рахунок "0" - типова гривнева картка

Час банку - київський, тому позначки часу локалізуємо часовим поясом постачальника
(рушій вважає час без пояса за UTC).

Демо-режим (`ua_demo`) віддає ті самі структури з вбудованого зразка. Він потрібен, щоб
екран і звірку можна було перевірити без токенів банку.
"""
import json
import logging
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PRIVAT_BASE = "https://acp.privatbank.ua/api"
MONO_BASE = "https://api.monobank.ua"
TIMEOUT = 60
USER_AGENT = "Odoo l10n_ua_bank_online"
# Токен банку йде лише сюди. Поле «Адреса API» лишається для іншого шляху на тому
# самому хості (нова версія API), а не для іншого сервера.
ALLOWED_HOSTS = frozenset(urlsplit(base).hostname for base in (PRIVAT_BASE, MONO_BASE))


class _NoRedirect(HTTPRedirectHandler):
    """Переадресацію не виконуємо: заголовки з токеном пішли б на чужу адресу."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ua_bank_url_ok(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except ValueError:
        return False

# Зразок для демо-режиму: (зсув у днях, шаблон призначення, сума, контрагент, рахунок контрагента).
# У шаблоні {m} - назва місяця вікна, {y} - рік: тексти збігаються з тим, як їх пише банк,
# тому правила звірки і «Зведення» знаходять ці рядки так само, як справжні.
MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
DEMO_ROWS = [
    (0, "Оплата за меблі згідно з рахунком СФ-1042", 180000.00, "ТОВ «Дім і сад»", "UA213052990000026007233566001"),
    (4, "Оплата за меблі згідно з рахунком СФ-1051", 96500.00, "ФОП Кравченко І. П.", "UA733052990000026005011122334"),
    (5, "Заробітна плата за {m} {y}, остаточний розрахунок", -171233.44, "Зарплатний проєкт", ""),
    (5, "ПДФО за {m} {y}", -37581.00, "ГУ ДПС у м. Києві", "UA908999980313080000000010101"),
    (5, "Військовий збір за {m} {y}", -10439.00, "ГУ ДПС у м. Києві", "UA908999980313080000000011011"),
    (5, "Аліменти за {m} {y}", -4820.00, "Ткачук Олена Петрівна", ""),
    (14, "Аванс за {m} {y}", -138420.00, "Зарплатний проєкт", ""),
    (14, "ПДФО з авансу за {m} {y}", -30412.00, "ГУ ДПС у м. Києві", "UA908999980313080000000010101"),
    (14, "Військовий збір з авансу за {m} {y}", -8447.00, "ГУ ДПС у м. Києві", "UA908999980313080000000011011"),
    (19, "Єдиний внесок (ЄСВ) за {m} {y}", -45932.00, "ГУ ДПС у м. Києві", "UA908999980313080000000012121"),
]

# Другий зразок - рахунок для еквайрингу: надходження від карток, комісія, переказ на основний рахунок.
DEMO_ROWS_MONO = [
    (1, "Еквайринг за {m} {y}, партія 1", 24870.00, "Monobank еквайринг", ""),
    (2, "Комісія за еквайринг", -348.18, "Monobank", ""),
    (8, "Еквайринг за {m} {y}, партія 2", 31240.00, "Monobank еквайринг", ""),
    (9, "Комісія за еквайринг", -437.36, "Monobank", ""),
    (12, "Переказ на поточний рахунок", -50000.00, "ТОВ «Ясен Меблі»", "UA213052990000026007233566001"),
    (16, "Еквайринг за {m} {y}, партія 3", 18990.00, "Monobank еквайринг", ""),
    (17, "Комісія за еквайринг", -265.86, "Monobank", ""),
]

class OnlineBankStatementProvider(models.Model):
    _inherit = "online.bank.statement.provider"

    ua_account = fields.Char(
        string="Рахунок у банку",
        help="ПриватБанк: рахунок IBAN у форматі UA... Monobank: ідентифікатор рахунку з /personal/client-info "
             "(«0» - типова гривнева картка). Якщо порожньо, береться рахунок журналу.",
    )
    ua_demo = fields.Boolean(
        string="Демо-дані замість банку",
        help="Віддає вбудований зразок виписки. Потрібно, щоб перевірити екран і звірку без токенів банку.",
    )

    # ------------------------------------------------------------------ рушій
    def _pull(self, date_since, date_until):
        """Завантажити виписку і одразу звести свіжі рядки з проведеними платежами.

        Зарплату платять відомістю до того, як приходить виписка. Якщо не звести рядок з
        платежем тут, наступний прогін правил закодує його на 661 - і та сама сума ляже
        двічі. Правила за текстом лишаються ручною дією бухгалтера («Застосувати
        правила»), а зведення з платежем робимо самі: воно не вгадує, а знаходить."""
        Line = self.env["account.bank.statement.line"]
        last = Line.search([], order="id desc", limit=1).id or 0
        result = super()._pull(date_since, date_until)
        fresh = Line.search([("id", ">", last), ("journal_id", "in", self.journal_id.ids),
                             ("is_reconciled", "=", False)], order="date, id")
        if fresh:
            fresh._ua_match_payment()
        return result

    @api.model
    def _get_available_services(self):
        # мітка вибору з коду, не з бази: англійська - для англійського інтерфейсу
        privat = "ПриватБанк (Автоклієнт)" if (self.env.lang or "").startswith("uk") else "PrivatBank (Autoclient)"
        return super()._get_available_services() + [
            ("ua_privat", privat),
            ("ua_mono", "Monobank"),
        ]

    def _obtain_statement_data(self, date_since, date_until):
        self.ensure_one()
        if self.service not in ("ua_privat", "ua_mono"):
            return super()._obtain_statement_data(date_since, date_until)
        if self.ua_demo:
            return self._ua_demo_data(date_since, date_until), {}
        if self.service == "ua_privat":
            return self._ua_privat_data(date_since, date_until), {}
        return self._ua_mono_data(date_since, date_until), {}

    # ------------------------------------------------------------------ запит
    def _ua_fetch(self, url, headers):
        """Один вихід у мережу. Помилку банку показуємо текстом, а не трасуванням."""
        if not _ua_bank_url_ok(url):
            raise UserError(_("Адреса API має бути https-адресою банку: %s.")
                            % ", ".join(sorted(ALLOWED_HOSTS)))
        headers = dict(headers or {}, **{"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with build_opener(_NoRedirect).open(Request(url, headers=headers), timeout=TIMEOUT) as response:
                payload = response.read()
        except HTTPError as error:
            body = ""
            try:
                body = error.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 - тіло помилки не обов'язкове
                pass
            if error.code == 429:
                raise UserError(_("Банк обмежує частоту запитів. Спробуйте через хвилину.")) from error
            if error.code in (401, 403):
                raise UserError(_("Банк не прийняв токен (код %s). Перевірте токен і рахунок.\n%s")
                                % (error.code, body)) from error
            raise UserError(_("Банк відповів помилкою %s.\n%s") % (error.code, body)) from error
        except URLError as error:
            raise UserError(_("Немає зв'язку з банком: %s") % error.reason) from error
        try:
            return json.loads(payload.decode("utf-8"))
        except ValueError as error:
            # Відповідь лишається в журналі сервера: на екран чужі байти не віддаємо.
            _logger.warning("Банк повернув не JSON (%s): %r", urlsplit(url).hostname, payload[:300])
            raise UserError(_("Банк повернув відповідь не у форматі JSON.")) from error

    def _ua_tz(self):
        return pytz.timezone(self.tz or "Europe/Kyiv")

    def _ua_localize(self, moment):
        """Київський час банку -> час із поясом (рушій приводить його до UTC)."""
        return self._ua_tz().localize(moment) if moment.tzinfo is None else moment

    def _ua_account_number(self):
        return (self.ua_account or self.journal_id.bank_account_id.acc_number or "").strip()

    # ------------------------------------------------------------------ ПриватБанк
    def _ua_privat_data(self, date_since, date_until):
        token = (self.password or "").strip()
        if not token:
            raise UserError(_("Немає токена Автоклієнта. Впишіть його в полі «Токен»."))
        account = self._ua_account_number()
        if not account:
            raise UserError(_("Немає рахунку. Впишіть IBAN у полі «Рахунок у банку»."))
        base = (self.api_base or PRIVAT_BASE).rstrip("/")
        headers = {"id": (self.username or "").strip(), "token": token, "Content-Type": "application/json;charset=utf8"}
        params = {
            "acc": account,
            "startDate": date_since.strftime("%d-%m-%Y"),
            "endDate": (date_until - timedelta(days=1)).strftime("%d-%m-%Y"),
            "limit": "100",
        }
        lines = []
        follow_id = None
        for _page in range(100):
            query = dict(params)
            if follow_id:
                query["followId"] = follow_id
            data = self._ua_fetch("%s/statements/transactions?%s" % (base, urlencode(query)), headers)
            status = str(data.get("status") or "").upper()
            if status not in ("SUCCESS", "OK", ""):
                raise UserError(_("ПриватБанк відповів «%s»: %s") % (status, data.get("error_description") or data))
            for transaction in data.get("transactions") or []:
                line = self._ua_privat_line(transaction)
                if line:
                    lines.append(line)
            if not data.get("exist_next_page"):
                break
            follow_id = data.get("next_page_id")
            if not follow_id:
                break
        return lines

    def _ua_privat_line(self, transaction):
        currency = (transaction.get("CCY") or "").strip()
        journal_currency = (self.currency_id or self.journal_id.company_id.currency_id).name
        if currency and journal_currency and currency != journal_currency:
            return None
        amount = float(str(transaction.get("SUM") or "0").replace(",", ".").replace(" ", ""))
        amount = -abs(amount) if str(transaction.get("TRANTYPE") or "").upper() == "D" else abs(amount)
        moment = None
        for value, pattern in (
            (transaction.get("DATE_TIME_DAT_OD_TIM_P"), "%d.%m.%Y %H:%M:%S"),
            (transaction.get("DAT_OD"), "%d.%m.%Y"),
            (transaction.get("DAT_KL"), "%d.%m.%Y"),
        ):
            if not value:
                continue
            try:
                moment = datetime.strptime(str(value).strip(), pattern)
                break
            except ValueError:
                continue
        if moment is None:
            return None
        identifier = transaction.get("ID") or transaction.get("TECHNICAL_TRANSACTION_ID") or transaction.get("REF")
        return {
            "payment_ref": (transaction.get("OSND") or _("Платіж"))[:2000],
            "amount": amount,
            "date": self._ua_localize(moment),
            "unique_import_id": str(identifier or "")[:120],
            "partner_name": (transaction.get("AUT_CNTR_NAM") or "").strip(),
            "account_number": (transaction.get("AUT_CNTR_ACC") or "").strip(),
            "ref": (transaction.get("NUM_DOC") or "").strip(),
        }

    # ------------------------------------------------------------------ Monobank
    def _ua_mono_data(self, date_since, date_until):
        token = (self.password or "").strip()
        if not token:
            raise UserError(_("Немає токена Monobank. Візьміть його на api.monobank.ua і впишіть у полі «Токен»."))
        base = (self.api_base or MONO_BASE).rstrip("/")
        account = self._ua_account_number() or "0"
        headers = {"X-Token": token}
        lines = []
        window_start = date_since
        while window_start < date_until:
            window_end = min(window_start + timedelta(days=30), date_until)
            url = "%s/personal/statement/%s/%s/%s" % (
                base, account,
                int(self._ua_localize(window_start).timestamp()),
                int(self._ua_localize(window_end).timestamp()) - 1,
            )
            for transaction in self._ua_fetch(url, headers) or []:
                line = self._ua_mono_line(transaction)
                if line:
                    lines.append(line)
            window_start = window_end
        return lines

    def _ua_mono_line(self, transaction):
        amount = float(transaction.get("amount") or 0) / 100.0
        moment = datetime.fromtimestamp(int(transaction.get("time") or 0), self._ua_tz())
        description = (transaction.get("description") or "").strip()
        comment = (transaction.get("comment") or "").strip()
        return {
            "payment_ref": (": ".join(part for part in (description, comment) if part) or _("Платіж"))[:2000],
            "amount": amount,
            "date": moment,
            "unique_import_id": str(transaction.get("id") or "")[:120],
            "partner_name": (transaction.get("counterName") or description).strip(),
            "account_number": (transaction.get("counterIban") or "").strip(),
        }

    # ------------------------------------------------------------------ демо
    def _ua_demo_data(self, date_since, date_until):
        month_name = MONTHS_UA[date_since.month]
        rows = DEMO_ROWS_MONO if self.service == "ua_mono" else DEMO_ROWS
        lines = []
        for offset, template, amount, partner, account in rows:
            moment = date_since + timedelta(days=offset, hours=11)
            if moment >= date_until:
                continue
            reference = template.format(m=month_name, y=date_since.year)
            lines.append({
                "payment_ref": reference,
                "amount": amount,
                "date": self._ua_localize(moment),
                "unique_import_id": "demo-%s-%s" % (moment.strftime("%Y%m%d"), abs(int(amount * 100))),
                "partner_name": partner,
                "account_number": account,
            })
        return lines

    # ------------------------------------------------------------------ перевірка зв'язку
    def action_ua_test(self):
        """Легкий запит до банку, щоб побачити, чи приймають токен."""
        self.ensure_one()
        if self.ua_demo:
            message = _("Демо-режим: банк не опитується, дані беруться зі зразка.")
        elif self.service == "ua_privat":
            base = (self.api_base or PRIVAT_BASE).rstrip("/")
            query = urlencode({
                "acc": self._ua_account_number(),
                "startDate": (fields.Date.context_today(self) - timedelta(days=1)).strftime("%d-%m-%Y"),
                "limit": "1",
            })
            data = self._ua_fetch("%s/statements/balance?%s" % (base, query), {
                "id": (self.username or "").strip(), "token": (self.password or "").strip(),
            })
            balances = data.get("balances") or []
            message = _("ПриватБанк відповідає. Рахунків у відповіді: %s.") % len(balances)
        elif self.service == "ua_mono":
            base = (self.api_base or MONO_BASE).rstrip("/")
            data = self._ua_fetch("%s/personal/client-info" % base, {"X-Token": (self.password or "").strip()})
            accounts = data.get("accounts") or []
            message = _("Monobank відповідає: %s, рахунків %s.") % (data.get("name") or "", len(accounts))
        else:
            raise UserError(_("Перевірка зв'язку працює для ПриватБанку і Monobank."))
        self.message_post(body=message)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Зв'язок з банком"), "message": message, "type": "success", "sticky": False},
        }
