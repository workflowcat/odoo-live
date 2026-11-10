from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

from odoo import fields, models
from odoo.addons.payroll.models.base_browsable import BaseBrowsableObject


def ua_round(value, digits=2):
    """Округлення грошей: пів копійки вгору (ROUND_HALF_UP).

    Вбудований round() Python округлює до парного: round(0.125, 2) дає 0,12.
    Для грошей це неправильно. Тут значення переводиться в Decimal через рядок,
    тому двійкова похибка float не тягнеться далі, і половина завжди йде вгору."""
    if value is None:
        return 0.0
    quant = Decimal(1).scaleb(-int(digits))
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    ua_diia_city = fields.Boolean(
        "Ставки Дія Сіті", readonly=True, copy=False,
        help="Листок пораховано за ставками резидента Дія Сіті: ПДФО 5 % з винагороди і зарплати, "
             "ЄСВ - мінімальний страховий внесок за місяць. Ставиться під час розрахунку листка.")

    # ---- Дія Сіті --------------------------------------------------------------------
    def _ua_dc_month(self):
        """Запис «Дія Сіті: відповідність за місяць» для місяця листка, або порожньо."""
        self.ensure_one()
        Month = self.env["ua.diia.city.month"].sudo()
        if not self.date_from:
            return Month
        return Month.search([
            ("company_id", "=", self.company_id.id), ("month", "=", self.date_from.replace(day=1))], limit=1)

    def _ua_dc_applies(self):
        """Чи діють для листка ставки Дія Сіті.

        Так, коли компанія - резидент, місяць листка настав після місяця набуття статусу
        (ставка 5 % - з наступного місяця), статус ще чинний, у місяці немає позначки
        «не відповідає вимогам», а людина працює за трудовим договором або гіг-контрактом.
        ЦПХ і ФОП пільги не мають."""
        self.ensure_one()
        company = self.company_id.sudo()
        kind = self.employee_id.sudo().ua_contract_kind or "employment"
        if kind not in ("employment", "gig") or not self.date_from:
            return False
        if not company.ua_dc_resident or not company.ua_dc_since:
            return False
        first_month = company.ua_dc_since.replace(day=1) + relativedelta(months=1)
        if self.date_from.replace(day=1) < first_month:
            return False
        if company.ua_dc_until and self.date_from > company.ua_dc_until:
            return False
        month = self._ua_dc_month()
        return not month or bool(month.compliant)

    def _ua_dc_esv_paid(self):
        """ЄСВ Дія Сіті, уже нарахований цій людині іншими проведеними листками того самого місяця.

        Мінімальний внесок береться раз на місяць, а не з кожного листка."""
        self.ensure_one()
        if not self.employee_id or not self.date_from:
            return 0.0
        start = self.date_from.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        domain = [("slip_id.employee_id", "=", self.employee_id.id), ("slip_id.state", "=", "done"),
                  ("slip_id.ua_diia_city", "=", True), ("slip_id.date_from", ">=", start),
                  ("slip_id.date_from", "<=", end), ("code", "=", "ESV")]
        if self.id:
            domain.append(("slip_id", "!=", self.id))
        return ua_round(sum(self.env["hr.payslip.line"].sudo().search(domain).mapped("total")))

    def compute_sheet(self):
        for slip in self:
            applies = slip._ua_dc_applies()
            if slip.ua_diia_city != applies:
                slip.ua_diia_city = applies
        return super().compute_sheet()

    def _get_tools_dict(self):
        """Функції, доступні у формулах правил. r2 - округлення грошей."""
        tools = super()._get_tools_dict()
        tools["r2"] = ua_round
        return tools

    def _ua_month_workdays(self, contract):
        """Робочі дні періоду за графіком контракту. Святкові не віднімаються, поки holidays_per_year = 0 (воєнний стан)."""
        cal = contract.resource_calendar_id or self.employee_id.resource_calendar_id or self.company_id.resource_calendar_id
        if cal:
            data = cal.get_work_duration_data(datetime.combine(self.date_from, time.min),
                                              datetime.combine(self.date_to, time.max), compute_leaves=False)
            if data and data.get("days"):
                return data["days"]
        d, n = self.date_from, 0
        while d <= self.date_to:
            if d.weekday() < 5:
                n += 1
            d += timedelta(days=1)
        return n

    def _ua_payroll_values(self, contracts):
        """Значення для правил під префіксом payroll.ua. Інші модулі (середні, табель) доповнюють цей словник."""
        Param = self.env["ua.payroll.param"]
        emp = self.employee_id.sudo()
        p = Param.get_all(self.date_to, self.company_id)
        psp_mult = {"none": 0.0, "base": 1.0, "child": float(max(emp.ua_psp_children, 1)),
                    "child150": 1.5 * max(emp.ua_psp_children, 1), "s150": 1.5, "s200": 2.0}[emp.ua_psp or "none"]
        thr_mult = float(max(emp.ua_psp_children, 1)) if emp.ua_psp in ("child", "child150") else 1.0
        contract = contracts[:1]
        dc = self._ua_dc_applies()
        return {
            "min_wage": p["min_wage"], "living_wage": p["living_wage"],
            "pdfo_rate": p["pdfo_rate"], "vz_rate": p["vz_rate"], "night_rate": p["night_rate"],
            "esv_rate": p["esv_rate_disabled"] if emp.ua_esv_category == "disabled" else p["esv_rate"],
            "esv_max_base": p["min_wage"] * p["esv_max_multiplier"],
            "esv_min_applies": bool(emp.ua_main_job) and emp.ua_contract_kind == "employment",
            "psp_amount": p["psp_base"] * psp_mult,
            "psp_threshold": p["psp_threshold"] * thr_mult,
            "month_workdays": self._ua_month_workdays(contract) if contract else 0,
            "contract_kind": emp.ua_contract_kind or "employment",
            "holidays_per_year": p.get("holidays_per_year", 0.0),
            "fte": float(emp.ua_fte or "1"),
            "reserve_rate": p.get("reserve_rate", 0.0),
            "aid_charity_limit": p.get("aid_charity_limit", 0.0),
            "gift_limit_share": p.get("gift_limit_share", 0.0),
            "aid_used_year": self._ua_aid_used_year(),
            "mat_cover_days": 0,   # l10n_ua_average перевизначає
            "vac_ahead_shares": [],   # l10n_ua_average: відпускні за дні наступних місяців
            "time_ratio": -1.0,    # l10n_ua_hr_docs ставить частку часу із затвердженого табеля
            "dc_applies": dc,
            "dc_pdfo_rate": p.get("dc_pdfo_rate", p["pdfo_rate"]),
            "dc_esv_paid": self._ua_dc_esv_paid() if dc else 0.0,
        }

    def _ua_aid_used_year(self):
        """Скільки неоподатковуваної матеріальної допомоги працівник уже отримав цього року.

        Межа за пп. 170.7.3 ПКУ - річна, тому дивимось усі проведені листки року, крім цього."""
        if not self.employee_id or not self.date_from:
            return 0.0
        year_start = self.date_from.replace(month=1, day=1)
        lines = self.env["hr.payslip.line"].sudo().search([
            ("slip_id.employee_id", "=", self.employee_id.id),
            ("slip_id.state", "=", "done"),
            ("slip_id.date_from", ">=", year_start),
            ("slip_id.date_from", "<", self.date_from),
            ("code", "=", "AID_FREE"),
        ])
        return ua_round(sum(lines.mapped("total")))

    def _ua_worked_share(self, values):
        """Частка відпрацьованого часу за рядками відпрацьованих днів листка."""
        lines = self.worked_days_line_ids
        work = sum(line.number_of_days for line in lines if line.code == "WORK100")
        other = sum(abs(line.number_of_days) for line in lines if line.code != "WORK100")
        days = work - other
        total = values.get("month_workdays") or work or 1.0
        return max(min(days, total), 0.0) / (total or 1.0)

    def _ua_min_sal_target(self, values):
        """Мінімальна зарплата за ст. 3-1 ЗУ про оплату праці, пропорційно ставці і часу.

        Норму часу беремо із затвердженого табеля (time_ratio), інакше з рядків
        відпрацьованих днів. Для ЦПХ і ФОП доплата не застосовується."""
        if values.get("contract_kind") != "employment":
            return 0.0
        share = values.get("time_ratio", -1.0)
        if share is None or share < 0:
            share = self._ua_worked_share(values)
        share = max(min(share, 1.0), 0.0)
        return ua_round(values["min_wage"] * values.get("fte", 1.0) * share)

    def get_payroll_dict(self, contracts):
        res = super().get_payroll_dict(contracts)
        values = self._ua_payroll_values(contracts)
        values["min_sal_target"] = self._ua_min_sal_target(values)
        res["ua"] = BaseBrowsableObject(values)
        return res

    def _ua_param_source(self, key, date, company, label, kind="amount"):
        """Джерело одного параметра закону: діючий запис ua.payroll.param на дату
        (той самий запит, що й ua.payroll.param.get()). Не падає, коли параметра
        немає - "missing" з причиною, як і решта методу нижче."""
        Param = self.env["ua.payroll.param"]
        domain = [("key", "=", key), ("valid_from", "<=", date)]
        if company:
            domain += ["|", ("company_id", "=", company.id), ("company_id", "=", False)]
        # Значення компанії б'є загальне. Не сортуємо за company_id: у PostgreSQL порожні
        # значення при DESC ідуть першими, і загальний запис перемагав би.
        rec = Param.search(domain, order="valid_from desc, id desc")
        rec = rec.filtered("company_id")[:1] or rec[:1]
        if not rec:
            return {"label": label, "state": "missing", "kind": kind, "value": None,
                    "source": None, "note": "Немає запису параметра «%s» на %s." % (key, date)}
        return {"label": label, "state": "supplied", "kind": kind, "value": rec.value,
                "source": {"model": "ua.payroll.param", "res_id": rec.id, "label": rec.name,
                           "basis": rec.source or "", "valid_from": str(rec.valid_from)}}

    def _ua_payroll_sources(self, contracts):
        """Джерела всіх ключів, які цей модуль кладе у payroll.ua (_ua_payroll_values
        і min_sal_target з get_payroll_dict). Форма запису - docs/payroll/explain-model.md.
        Інші модулі, що доповнюють _ua_payroll_values (середні, індексація, табель),
        доповнюють і цей словник тим самим прийомом: super() + update()."""
        date = self.date_to
        company = self.company_id
        emp = self.employee_id.sudo()
        emp_source = {"model": "hr.employee", "res_id": emp.id, "label": emp.name} if emp else None
        out = {}

        out["min_wage"] = self._ua_param_source("min_wage", date, company, "Мінімальна зарплата")
        out["living_wage"] = self._ua_param_source("living_wage", date, company, "Прожитковий мінімум")
        out["pdfo_rate"] = self._ua_param_source("pdfo_rate", date, company, "Ставка ПДФО, %", kind="rate")
        out["vz_rate"] = self._ua_param_source("vz_rate", date, company, "Ставка військового збору, %", kind="rate")
        out["night_rate"] = self._ua_param_source("night_rate", date, company,
                                                   "Ставка доплати за нічні години, %", kind="rate")

        esv_key = "esv_rate_disabled" if emp.ua_esv_category == "disabled" else "esv_rate"
        esv_entry = self._ua_param_source(esv_key, date, company, "Ставка ЄСВ, %", kind="rate")
        esv_entry["note"] = ("Пільгова ставка: працівник з інвалідністю." if emp.ua_esv_category == "disabled"
                             else "Загальна ставка.")
        out["esv_rate"] = esv_entry

        multiplier = self._ua_param_source("esv_max_multiplier", date, company, "Множник максимальної бази ЄСВ")
        if multiplier["state"] == "supplied" and out["min_wage"]["state"] == "supplied":
            out["esv_max_base"] = {"label": "Максимальна база ЄСВ", "state": "calculated", "kind": "amount",
                                   "source": None,
                                   "note": "мінімальна зарплата × множник максимальної бази ЄСВ (%s × %s)" % (
                                       out["min_wage"]["value"], multiplier["value"])}
        else:
            out["esv_max_base"] = {"label": "Максимальна база ЄСВ", "state": "missing", "kind": "amount",
                                   "source": None, "note": "не порахувати: немає мінімальної зарплати або множника."}

        out["esv_min_applies"] = {
            "label": "Доплата ЄСВ до мінімального внеску застосовується", "state": "calculated", "kind": "flag",
            "source": None,
            "note": "основне місце роботи (%s) і трудовий договір (%s)" % (bool(emp.ua_main_job), emp.ua_contract_kind),
        }

        psp_base = self._ua_param_source("psp_base", date, company, "Базова податкова соціальна пільга")
        if psp_base["state"] == "supplied":
            out["psp_amount"] = {"label": "Податкова соціальна пільга", "state": "calculated", "kind": "amount",
                                 "source": None,
                                 "note": "базова пільга × коефіцієнт пільги «%s», дітей: %s" % (
                                     emp.ua_psp or "none", emp.ua_psp_children)}
        else:
            out["psp_amount"] = {"label": "Податкова соціальна пільга", "state": "missing", "kind": "amount",
                                 "source": None, "note": "немає запису «psp_base»."}

        psp_threshold = self._ua_param_source("psp_threshold", date, company, "Межа доходу для ПСП (база)")
        if psp_threshold["state"] == "supplied":
            out["psp_threshold"] = {"label": "Межа доходу для ПСП", "state": "calculated", "kind": "amount",
                                    "source": None,
                                    "note": "базова межа × коефіцієнт дітей, якщо пільга «на дітей»"}
        else:
            out["psp_threshold"] = {"label": "Межа доходу для ПСП", "state": "missing", "kind": "amount",
                                    "source": None, "note": "немає запису «psp_threshold»."}

        out["month_workdays"] = {"label": "Норма робочих днів місяця", "state": "calculated", "kind": "count",
                                 "source": None,
                                 "note": "графік контракту (або типовий п'ятиденний тиждень), період листка"}

        out["contract_kind"] = {"label": "Вид відносин", "state": "supplied", "kind": "text",
                                "value": emp.ua_contract_kind or "employment", "source": emp_source}

        holidays = self._ua_param_source("holidays_per_year", date, company, "Святкових днів на рік у нормі")
        if holidays["state"] != "supplied":
            holidays["note"] = "Немає запису - вважається 0 (воєнний стан, святкові не віднімаються)."
        out["holidays_per_year"] = holidays

        out["fte"] = {"label": "Ставка (частка)", "state": "supplied", "kind": "rate",
                      "value": float(emp.ua_fte or "1"), "source": emp_source}

        out["reserve_rate"] = self._ua_param_source("reserve_rate", date, company, "Ставка резерву відпусток, %", kind="rate")
        out["aid_charity_limit"] = self._ua_param_source("aid_charity_limit", date, company,
                                                          "Річна межа неоподатковуваної матдопомоги")
        out["gift_limit_share"] = self._ua_param_source("gift_limit_share", date, company,
                                                         "Межа неоподатковуваного подарунка, частка МЗП", kind="rate")

        out["aid_used_year"] = {"label": "Матдопомога, вже отримана цього року", "state": "calculated", "kind": "amount",
                                "source": None, "note": "сума рядків AID_FREE проведених листків з початку року"}

        # mat_cover_days і time_ratio: тут - заглушки get_payroll_dict (0 і -1.0 відповідно),
        # реальні джерела дає l10n_ua_average і l10n_ua_hr_docs, якщо модулі встановлено -
        # вони доповнюють цей словник через super(), так само як доповнюють _ua_payroll_values.
        out["mat_cover_days"] = {"label": "Днів декрету в цьому місяці", "state": "not_applicable", "kind": "count",
                                 "source": None, "note": "рахує l10n_ua_average, якщо модуль встановлено"}
        out["vac_ahead_shares"] = {"label": "Відпускні за дні наступних місяців", "state": "not_applicable", "kind": "amount",
                                   "source": None, "note": "рахує l10n_ua_average, якщо модуль встановлено"}
        out["time_ratio"] = {"label": "Частка відпрацьованого часу за табелем", "state": "not_applicable", "kind": "rate",
                             "source": None, "note": "-1 = табель не задіяно; рахує l10n_ua_hr_docs, якщо модуль встановлено"}

        dc = self._ua_dc_applies()
        out["dc_applies"] = {
            "label": "Ставки Дія Сіті", "state": "calculated", "kind": "flag", "source": None,
            "note": "компанія - резидент Дія Сіті (%s), вид відносин %s; ставка 5 %% - з місяця, наступного за набуттям "
                    "статусу, лише в місяцях без позначки «не відповідає вимогам»" % (
                        bool(self.company_id.sudo().ua_dc_resident), emp.ua_contract_kind)}
        if dc:
            out["dc_pdfo_rate"] = self._ua_param_source("dc_pdfo_rate", date, company, "Ставка ПДФО Дія Сіті, %", kind="rate")
            out["dc_esv_paid"] = {"label": "ЄСВ Дія Сіті, уже нарахований у місяці", "state": "calculated", "kind": "amount",
                                  "source": None, "note": "сума рядків ESV інших проведених листків цього місяця"}
        else:
            out["dc_pdfo_rate"] = {"label": "Ставка ПДФО Дія Сіті, %", "state": "not_applicable", "kind": "rate",
                                   "source": None, "note": "ставки Дія Сіті до листка не застосовуються"}
            out["dc_esv_paid"] = {"label": "ЄСВ Дія Сіті, уже нарахований у місяці", "state": "not_applicable",
                                  "kind": "amount", "source": None, "note": "ставки Дія Сіті до листка не застосовуються"}

        out["min_sal_target"] = {"label": "Цільова мінімальна зарплата за місяць", "state": "calculated", "kind": "amount",
                                 "source": None,
                                 "note": "мінімальна зарплата × ставка × частка часу (ст. 3-1 ЗУ про оплату праці)"}
        return out
