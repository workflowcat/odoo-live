# -*- coding: utf-8 -*-
"""Спільний серверний договір екранів: одна ціль, одна смуга періоду, одні хелпери.

Дев'ять екранів системи («Домівка», «Папери», «Люди», «Період», «Банк», «Зведення»,
«Звітність», «Прийняття», «Налаштування») живляться моделями-постачальниками даних.
Кожна з них раніше тримала свою копію одного й того самого: назви місяців, межі місяця,
українську лічбу, форматування суми, округлення і - найгірше - свою говірку відкриття
цілі (`open_target`, `action_open`, `action_open_record`, `action_open_exception`).

Цей модуль заморожує один договір ДО того, як логіку відділять від інтерфейсу. Екран
підмішує міксин (`_inherit = ["ua.screen"]` поруч зі своїм `_name`) і копії видаляє.
Модуль навмисно порожній: жодних подань, ресурсів чи меню, залежність - лише `base`.

Ціль (`target`) - один із трьох видів, і більше жодного:
  {"xmlid": ..., "domain": ..., "context": ...}  - наявна дія Odoo, за потреби звужена;
  {"model": ..., "res_id": ...}                  - конкретний запис у формі;
  {"model": ..., "domain": ..., "name": ...}     - перелік записів за доменом.
Рядок виписки (account.bank.statement.line) відкривається у поданні звірки - це єдиний
особливий випадок, і він живе тут, а не в трьох копіях.

Смуга періоду (`_period_block`) має ОДНУ форму на всіх екранах:
  {"year", "month", "label", "closed", "periods": [{"year", "month", "label",
                                                     "current", "closed", ...}]}
Екран, якому треба інші слова в мітці (короткі місяці «Паперів»), перекриває
`_period_label` / `_period_item_label`; екран, якому треба додаткове поле в місяці
(«має прогін» у «Зведенні»), перекриває `_period_item_extra`.
"""
from datetime import date, timedelta

from odoo import _, api, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
# Рядок виписки має власне подання звірки: без нього відкривається гола форма
# рядка, де звіряти нічим. Раніше цей виняток стояв у трьох копіях open_target.
BANK_LINE_MODEL = "account.bank.statement.line"
BANK_LINE_VIEW = "account_reconcile_oca.bank_statement_line_form_reconcile_view"


class UaScreen(models.AbstractModel):
    _name = "ua.screen"
    _description = "Спільний договір екранів"

    MONTHS_UA = MONTHS_UA

    # «Зведення» показує суми без знака (ПДФО в листку мінусовий, на панелі - додатний)
    # і розділяє тисячі звичайним пробілом; решта екранів лишають знак і нерозривний
    # пробіл. Дві відмінності копій _money - дві позначки, а не друга копія методу.
    _money_absolute = False
    _money_thousands = "\xa0"

    # ------------------------------------------------------------------ хелпери
    def _company(self):
        return self.env.company

    @staticmethod
    def _bounds(year, month):
        """Перший і останній день місяця."""
        first = date(year, month, 1)
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        return first, last

    @staticmethod
    def _plural(n, *forms):
        """Українська форма іменника після числівника n: 1 - one, 2-4 - few, решта - many.

        Форми приймаються і трьома аргументами (`_plural(n, "рядок", "рядки", "рядків")`),
        і однією послідовністю (`_plural(n, forms)`) - виклики екранів історично різні."""
        if len(forms) == 1:
            forms = tuple(forms[0])
        one, few, many = forms
        n = abs(int(n))
        if n % 100 in (11, 12, 13, 14):
            return many
        r = n % 10
        if r == 1:
            return one
        if 2 <= r <= 4:
            return few
        return many

    @classmethod
    def _money(cls, value):
        """Українське форматування суми: 710 887,13."""
        value = value or 0.0
        if cls._money_absolute:
            value = abs(value)
        return "{:,.2f}".format(value).replace(",", cls._money_thousands).replace(".", ",")

    @staticmethod
    def _r2(value):
        return round(value or 0.0, 2)

    # ------------------------------------------------------------------ смуга періоду
    def _month_name(self, month):
        return self.MONTHS_UA.get(month, "")

    def _period_label(self, year, month):
        """Мітка поточного періоду в шапці екрана."""
        return "%s %s" % (self._month_name(month).capitalize(), year)

    def _period_item_label(self, year, month):
        """Мітка одного місяця у смузі. Типово - та сама, що й у шапці."""
        return self._period_label(year, month)

    def _period_item_extra(self, year, month):
        """Додаткові поля одного місяця смуги. Типово - жодного."""
        return {}

    def _period_closed(self, year, month):
        """Чи закрито місяць. Без модуля закриття періодів - завжди «ні»."""
        if "ua.period.close" not in self.env:
            return False
        return self.env["ua.period.close"].state_of(self._company(), year, month)["state"] == "closed"

    def _period_block(self, year, month, closed=None, span=6):
        """Смуга періоду однієї форми для всіх екранів.

        span місяців назад від обраного включно, від найстарішого до найновішого."""
        year, month = int(year), int(month)
        periods = []
        y, m = year, month
        for _i in range(span):
            item = {
                "year": y, "month": m,
                "label": self._period_item_label(y, m),
                "current": (y == year and m == month),
                "closed": self._period_closed(y, m),
            }
            item.update(self._period_item_extra(y, m))
            periods.append(item)
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        periods.reverse()
        current = next(p for p in periods if p["current"])
        return {
            "year": year, "month": month,
            "label": self._period_label(year, month),
            "closed": current["closed"] if closed is None else bool(closed),
            "periods": periods,
        }

    # ------------------------------------------------------------------ ціль
    @api.model
    def open_target(self, target):
        """Відкрити ціль будь-якого блоку будь-якого екрана.

        Один вхід замість чотирьох говірок (`open_target` «Домівки»/«Паперів»/«Людей»,
        `action_open` і `action_open_record` «Періоду»). Види цілі описані в шапці файлу."""
        target = target or {}
        if target.get("xmlid"):
            res = dict(self.env["ir.actions.actions"]._for_xml_id(target["xmlid"]))
            if target.get("domain"):
                res["domain"] = target["domain"]
            if target.get("context"):
                res["context"] = dict(target["context"])
            return res
        if target.get("model") and target.get("res_id"):
            model, res_id = target["model"], int(target["res_id"])
            res = {"type": "ir.actions.act_window", "res_model": model, "res_id": res_id,
                   "view_mode": "form", "views": [(False, "form")], "target": "current"}
            if model == BANK_LINE_MODEL:
                res["context"] = {"view_ref": BANK_LINE_VIEW}
            return res
        if target.get("model"):
            return {"type": "ir.actions.act_window", "res_model": target["model"],
                    "domain": target.get("domain") or [], "view_mode": "list,form",
                    "views": [(False, "list"), (False, "form")], "target": "current",
                    "name": target.get("name") or ""}
        raise UserError(_("Немає що відкривати."))
