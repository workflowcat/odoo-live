"""Квартальний розрахунок ФОП 3 групи: ЄП, військовий збір, ЄСВ «за себе».

Нормативна рамка (числа лежать у ua.fop.param, тут - лише правила):

- ЄП 3 групи: 5 % доходу для неплатника ПДВ, 3 % для платника (п. 293.3 ПКУ).
  Звітний період - квартал, декларація складається наростаючим підсумком
  з початку року (п. 296.3 ПКУ). Тому сума кварталу рахується як різниця:
  податок наростаючим за цей квартал мінус податок наростаючим за попередній.
- Річний ліміт 3 групи - 1167 мінімальних зарплат, установлених на 1 січня
  звітного року (п. 291.4 ПКУ). З суми перевищення ЄП береться за ставкою
  15 % (п. 293.4 ПКУ), а з наступного кварталу підприємець зобов'язаний
  перейти на загальну систему (пп. 298.2.3 ПКУ) - це рішення людини, модуль
  лише показує стан ліміту.
- Військовий збір для ФОП 3 групи - 1 % доходу, з 1 січня 2025 року
  (п. 16-1 підрозд. 10 розд. XX ПКУ в редакції Закону № 4015-IX).
  Рахується з того самого касового доходу і в ті самі строки, що й ЄП.
- ЄСВ «за себе» - 22 % мінімальної зарплати за кожен місяць, незалежно від
  доходу (ст. 7 і ст. 8 Закону № 2464-VI). Звільнення на час воєнного стану
  для ФОП діяло по 31 грудня 2024 року.

Проводки нарахування модуль не робить: ФОП на єдиному податку не зобов'язаний
вести подвійний запис, і вигадувати йому рахунки 641/651 без потреби - зайве.
Якщо проводки колись знадобляться, це окремий модуль поверх цього.
"""
from datetime import date as _date, timedelta as _timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class UaFopQuarter(models.Model):
    _name = "ua.fop.quarter"
    _description = "ФОП 3 група: квартальний розрахунок"
    _order = "year desc, quarter desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", "ФОП", required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    year = fields.Integer(
        "Рік", required=True,
        default=lambda self: fields.Date.context_today(self).year,
    )
    quarter = fields.Selection(
        [("1", "I квартал"), ("2", "II квартал"),
         ("3", "III квартал"), ("4", "IV квартал")],
        "Квартал", required=True,
        default=lambda self: str((fields.Date.context_today(self).month - 1) // 3 + 1),
    )
    state = fields.Selection(
        [("draft", "Чернетка"), ("computed", "Розраховано")],
        "Стан", default="draft", copy=False,
    )

    ep_rate = fields.Float("Ставка ЄП, %", readonly=True)
    vz_rate = fields.Float("Ставка ВЗ, %", readonly=True)
    income_quarter = fields.Monetary("Дохід за квартал", currency_field="currency_id", readonly=True)
    income_ytd = fields.Monetary(
        "Дохід наростаючим", currency_field="currency_id", readonly=True,
        help="З 1 січня до кінця звітного кварталу (п. 296.3 ПКУ).",
    )
    ep_ytd = fields.Monetary("ЄП наростаючим", currency_field="currency_id", readonly=True)
    ep_quarter = fields.Monetary(
        "ЄП за квартал", currency_field="currency_id", readonly=True,
        help="Різниця: ЄП наростаючим за цей квартал мінус за попередній.",
    )
    vz_ytd = fields.Monetary("ВЗ наростаючим", currency_field="currency_id", readonly=True)
    vz_quarter = fields.Monetary("ВЗ за квартал", currency_field="currency_id", readonly=True)
    esv_quarter = fields.Monetary(
        "ЄСВ за квартал", currency_field="currency_id", readonly=True,
        help="22 % мінімальної зарплати за кожен з трьох місяців кварталу.",
    )
    total_due = fields.Monetary("Разом до сплати", currency_field="currency_id", readonly=True)

    limit_amount = fields.Monetary("Ліміт 3 групи на рік", currency_field="currency_id", readonly=True)
    limit_pct = fields.Float("Використано ліміту, %", digits=(6, 1), readonly=True)
    limit_state = fields.Selection(
        [("ok", "У межах"), ("warn", "Понад 80 %"), ("crit", "Перевищено")],
        "Стан ліміту", readonly=True,
    )
    excess_amount = fields.Monetary("Перевищення ліміту", currency_field="currency_id", readonly=True)
    excess_tax = fields.Monetary(
        "ЄП 15 % з перевищення", currency_field="currency_id", readonly=True,
        help="П. 293.4 ПКУ. Плюс обов'язковий перехід на загальну систему "
             "з наступного кварталу (пп. 298.2.3 ПКУ).",
    )

    _period_uniq = models.Constraint(
        "unique(company_id, year, quarter)",
        "Розрахунок за цей квартал для цього ФОП уже є.",
    )

    @api.depends("company_id", "year", "quarter")
    def _compute_name(self):
        for rec in self:
            rec.name = "ЄП %s - %s кв. %s" % (
                rec.company_id.name or "?", rec.quarter or "?", rec.year or "?")

    # ------------------------------------------------------------------
    # Періоди
    # ------------------------------------------------------------------
    @staticmethod
    def _bounds(year, quarter):
        """Перший і останній день кварталу."""
        quarter = int(quarter)
        start = _date(year, 3 * quarter - 2, 1)
        end = (_date(year, 12, 31) if quarter == 4
               else _date(year, 3 * quarter + 1, 1) - _timedelta(days=1))
        return start, end

    # ------------------------------------------------------------------
    # Розрахунок
    # ------------------------------------------------------------------
    def _tax_ytd(self, upto):
        """(дохід, ЄП, ВЗ) наростаючим з 1 січня по дату upto включно."""
        self.ensure_one()
        Param = self.env["ua.fop.param"]
        company = self.company_id
        jan_first = _date(self.year, 1, 1)
        income = self.env["ua.fop.income"]._income_total(company, jan_first, upto)
        rate = company._ua_fop_ep_rate(jan_first)
        vz_rate = Param.get("fop_vz_rate", jan_first, company)
        limit = self._limit_amount()
        excess = max(0.0, round(income - limit, 2))
        normal = income - excess
        excess_rate = Param.get("fop_excess_rate", jan_first, company)
        ep = round(normal * rate / 100.0, 2) + round(excess * excess_rate / 100.0, 2)
        vz = round(income * vz_rate / 100.0, 2)
        return round(income, 2), round(ep, 2), vz

    def _limit_amount(self):
        """Річний ліміт 3 групи: множник × МЗП на 1 січня звітного року."""
        self.ensure_one()
        Param = self.env["ua.fop.param"]
        jan_first = _date(self.year, 1, 1)
        mzp = Param.get("fop_mzp", jan_first, self.company_id)
        count = Param.get("fop_limit_mzp", jan_first, self.company_id)
        return round(mzp * count, 2)

    def _esv_quarter(self):
        """ЄСВ за три місяці кварталу: кожен місяць за своєю мінімальною зарплатою."""
        self.ensure_one()
        Param = self.env["ua.fop.param"]
        first_month = 3 * int(self.quarter) - 2
        total = 0.0
        for month in range(first_month, first_month + 3):
            on_date = _date(self.year, month, 1)
            mzp = Param.get("fop_mzp", on_date, self.company_id)
            rate = Param.get("fop_esv_rate", on_date, self.company_id)
            total += round(mzp * rate / 100.0, 2)
        return round(total, 2)

    def action_compute(self):
        for rec in self:
            if not rec.company_id.ua_fop:
                raise UserError(
                    "Компанія %s не позначена як ФОП на єдиному податку."
                    % rec.company_id.display_name)
            if rec.company_id.ua_fop_group != "3":
                raise UserError("Порахований лише розрахунок для 3 групи.")
            start, end = rec._bounds(rec.year, rec.quarter)
            income_ytd, ep_ytd, vz_ytd = rec._tax_ytd(end)
            if int(rec.quarter) == 1:
                prev = (0.0, 0.0, 0.0)
            else:
                _s, prev_end = rec._bounds(rec.year, int(rec.quarter) - 1)
                prev = rec._tax_ytd(prev_end)
            income_q = self.env["ua.fop.income"]._income_total(rec.company_id, start, end)
            limit = rec._limit_amount()
            pct = round(100.0 * income_ytd / limit, 1) if limit else 0.0
            excess = max(0.0, round(income_ytd - limit, 2))
            jan_first = _date(rec.year, 1, 1)
            excess_rate = self.env["ua.fop.param"].get("fop_excess_rate", jan_first, rec.company_id)
            ep_q = round(ep_ytd - prev[1], 2)
            vz_q = round(vz_ytd - prev[2], 2)
            esv_q = rec._esv_quarter()
            rec.write({
                "ep_rate": rec.company_id._ua_fop_ep_rate(jan_first),
                "vz_rate": self.env["ua.fop.param"].get("fop_vz_rate", jan_first, rec.company_id),
                "income_quarter": income_q,
                "income_ytd": income_ytd,
                "ep_ytd": ep_ytd,
                "ep_quarter": ep_q,
                "vz_ytd": vz_ytd,
                "vz_quarter": vz_q,
                "esv_quarter": esv_q,
                "total_due": round(ep_q + vz_q + esv_q, 2),
                "limit_amount": limit,
                "limit_pct": pct,
                "limit_state": "crit" if pct > 100.0 else "warn" if pct > 80.0 else "ok",
                "excess_amount": excess,
                "excess_tax": round(excess * excess_rate / 100.0, 2),
                "state": "computed",
            })
        return True

    # ------------------------------------------------------------------
    # Показники декларації платника ЄП
    # ------------------------------------------------------------------
    def declaration_rows(self):
        """Числа декларації платника ЄП за квартал - наростаючим підсумком.

        Офіційні номери рядків форми (наказ Мінфіну № 578) тут навмисно не
        проставлені: форму щороку правлять, а звіряти нумерацію має бухгалтер.
        Модуль відповідає за числа.
        """
        self.ensure_one()
        if self.state == "draft":
            self.action_compute()
        return [
            {"key": "income_quarter", "label": "Дохід за звітний квартал", "value": self.income_quarter},
            {"key": "income_ytd", "label": "Дохід наростаючим підсумком з початку року", "value": self.income_ytd},
            {"key": "income_excess", "label": "у т.ч. дохід понад ліміт групи", "value": self.excess_amount},
            {"key": "ep_ytd", "label": "Єдиний податок наростаючим підсумком", "value": self.ep_ytd},
            {"key": "ep_prev", "label": "Єдиний податок за попередній період", "value": round(self.ep_ytd - self.ep_quarter, 2)},
            {"key": "ep_quarter", "label": "Єдиний податок до сплати за квартал", "value": self.ep_quarter},
            {"key": "vz_ytd", "label": "Військовий збір наростаючим підсумком", "value": self.vz_ytd},
            {"key": "vz_quarter", "label": "Військовий збір до сплати за квартал", "value": self.vz_quarter},
            {"key": "esv_quarter", "label": "ЄСВ «за себе» за квартал", "value": self.esv_quarter},
            {"key": "total_due", "label": "Разом до сплати за квартал", "value": self.total_due},
        ]
