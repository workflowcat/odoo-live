"""Дія Сіті: чи відповідає резидент вимогам у місяці.

Пільгові ставки (ПДФО 5 % з винагороди і зарплати, ЄСВ - мінімальний внесок) діють лише в
місяцях, коли резидент відповідає вимогам закону (середня винагорода, кількість
спеціалістів). Документ рахує цифри з проведених листків, а рішення «відповідає / не
відповідає» ставить бухгалтер: винятки для нових резидентів і порядок перерахунку - на
ньому. Немає документа за місяць - листки рахуються за пільговими ставками, а сторінка
перевірок про це попереджає.
"""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

KINDS = ("employment", "gig")


class UaDiiaCityMonth(models.Model):
    _name = "ua.diia.city.month"
    _inherit = ["mail.thread", "ua.checks.mixin"]
    _description = "Дія Сіті: відповідність вимогам за місяць"
    _order = "month desc, id desc"

    name = fields.Char("Назва", compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, default=lambda s: s.env.company)
    month = fields.Date("Місяць", required=True, help="Перше число місяця")
    compliant = fields.Boolean(
        "Відповідає вимогам", default=True, tracking=True,
        help="Вимкніть, якщо в цьому місяці резидент не відповідає вимогам: листки місяця "
             "рахуються за загальними ставками (ПДФО 18 %, ЄСВ 22 % з нарахованого). "
             "Після зміни перерахуйте листки місяця.")
    headcount = fields.Integer("Працівників і гіг-спеціалістів", readonly=True)
    reward_total = fields.Float("Нараховано винагороди і зарплати, грн", digits=(16, 2), readonly=True)
    avg_reward = fields.Float("Середня винагорода, грн", digits=(16, 2), readonly=True)
    eur_rate = fields.Float("Курс євро", digits=(12, 4),
                            help="Курс для перевірки середньої винагороди. Типово - параметр «dc_eur_rate» "
                                 "(курс НБУ на 1 січня); змініть, якщо порядок вимагає іншої дати.")
    avg_reward_eur = fields.Float("Середня винагорода, євро", digits=(16, 2), compute="_compute_avg_eur", store=True)
    note = fields.Text("Примітка")

    _company_month_uniq = models.Constraint("unique(company_id, month)", "Один документ на місяць.")

    @api.depends("month")
    def _compute_name(self):
        for rec in self:
            rec.name = "Дія Сіті %s" % rec.month.strftime("%m.%Y") if rec.month else "Дія Сіті"

    @api.depends("avg_reward", "eur_rate")
    def _compute_avg_eur(self):
        for rec in self:
            rec.avg_reward_eur = round(rec.avg_reward / rec.eur_rate, 2) if rec.eur_rate else 0.0

    @api.constrains("month")
    def _check_month(self):
        for rec in self:
            if rec.month and rec.month.day != 1:
                raise ValidationError("Місяць документа Дія Сіті - перше число місяця.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("month"):
                vals["month"] = fields.Date.to_date(vals["month"]).replace(day=1)
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: not r.eur_rate):
            rec.eur_rate = rec._param("dc_eur_rate", 0.0)
        return records

    # ---- дані ---------------------------------------------------------------------
    def _param(self, key, default=0.0):
        self.ensure_one()
        Param = self.env["ua.payroll.param"]
        try:
            return Param.get(key, self.month, self.company_id)
        except Exception:
            return default

    def _period_end(self):
        return self.month + relativedelta(months=1, days=-1)

    def _slips(self, date_from, date_to):
        return self.env["hr.payslip"].sudo().search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date_from", ">=", date_from), ("date_from", "<=", date_to),
            ("employee_id.ua_contract_kind", "in", list(KINDS)),
        ])

    @staticmethod
    def _gross(slips):
        return sum(slips.mapped("line_ids").filtered(lambda line: line.code == "GROSS").mapped("total"))

    def action_fill(self):
        """Порахувати кількість людей і середню винагороду з проведених листків місяця."""
        for rec in self:
            slips = rec._slips(rec.month, rec._period_end())
            people = slips.mapped("employee_id")
            total = round(rec._gross(slips), 2)
            rec.write({
                "headcount": len(people),
                "reward_total": total,
                "avg_reward": round(total / len(people), 2) if people else 0.0,
                "eur_rate": rec.eur_rate or rec._param("dc_eur_rate", 0.0),
            })
        return True

    def _over_limit(self):
        """Люди, чий дохід від резидента з початку року перевищив річну межу (240 000 євро).

        Резидент далі утримує 5 %: різницю до 18 % людина сплачує сама в річній декларації.
        Документ лише показує, кого це стосується."""
        self.ensure_one()
        limit_eur = self._param("dc_income_limit_eur", 0.0)
        rate = self._param("dc_eur_rate", 0.0)
        if not limit_eur or not rate:
            return self.env["hr.employee"], 0.0
        limit = limit_eur * rate
        slips = self._slips(self.month.replace(month=1), self._period_end()).filtered("ua_diia_city")
        over = self.env["hr.employee"]
        for employee in slips.mapped("employee_id"):
            if self._gross(slips.filtered(lambda s, e=employee: s.employee_id == e)) > limit:
                over |= employee
        return over, limit

    # ---- перевірки ----------------------------------------------------------------
    def _checks(self):
        self.ensure_one()
        out = []
        company = self.company_id.sudo()
        if not company.ua_dc_resident:
            out.append(self._check_warn("Компанія не позначена резидентом Дія Сіті: ставки Дія Сіті не застосовуються.",
                                        target=self._target_record(company)))
        if not self.headcount:
            out.append(self._check_warn("Немає цифр за місяць: натисніть «Порахувати» після проведення листків."))
        else:
            min_avg = self._param("dc_min_avg_eur", 0.0)
            min_people = self._param("dc_min_headcount", 0.0)
            low_pay = bool(min_avg) and self.avg_reward_eur < min_avg
            few = bool(min_people) and self.headcount < min_people
            if low_pay:
                out.append(self._check_warn("Середня винагорода менша за вимогу закону.",
                                            "%.2f євро при вимозі %.0f" % (self.avg_reward_eur, min_avg)))
            if few:
                out.append(self._check_warn("Людей менше, ніж вимагає закон.",
                                            "%s при вимозі %.0f" % (self.headcount, min_people)))
            if (low_pay or few) and self.compliant:
                out.append(self._check_error(
                    "Цифри не відповідають вимогам, а місяць позначено «відповідає». Перевірте виняток "
                    "для нового резидента або зніміть позначку і перерахуйте листки."))
            if not (low_pay or few):
                out.append(self._check_ok("Середня винагорода і кількість людей відповідають вимогам.",
                                          "%.2f євро, %s осіб" % (self.avg_reward_eur, self.headcount)))
        over, limit = self._over_limit()
        if over:
            out.append(self._check_warn(
                "Дохід з початку року перевищив річну межу: з перевищення людина сама доплачує ПДФО в декларації.",
                "%s; межа %.2f грн" % (", ".join(over.mapped("name")), limit),
                self._target_records(over)))
        return out
