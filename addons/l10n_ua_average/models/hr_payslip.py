import calendar
from datetime import date, timedelta

from odoo import fields, models

from odoo.addons.l10n_ua_payroll_rules.models.hr_payslip import ua_round


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


_UA_MONTHS_GEN = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
                  7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}


def _ua_month_label(d):
    """Місяць і рік у родовому відмінку - "вересня 2026", для людських назв вікон розрахунку."""
    return "%s %d" % (_UA_MONTHS_GEN.get(d.month, str(d.month)), d.year)


def _entry(label, kind, state, source=None, note=None):
    """Один запис _ua_payroll_sources: label/kind/state завжди, source і/або note - за наявності."""
    out = {"label": label, "kind": kind, "state": state}
    if source is not None:
        out["source"] = source
    if note is not None:
        out["note"] = note
    return out


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    ua_vac_ahead = fields.Json(
        "Відпускні наперед", readonly=True, copy=False,
        help="Дні щорічної відпустки наступних місяців, оплачені цим листком, і сума за них: "
             "{\"2026-09\": {\"days\": 6, \"amount\": 3945.21}}. "
             "Записується під час проведення; листок наступного місяця ці дні вже не оплачує, "
             "а Д1 показує їх рядком КТН 10 у своєму місяці.")

    def _ua_average_window(self):
        """12 повних місяців перед місяцем листка."""
        first = self.date_from.replace(day=1)
        return _add_months(first, -12), first  # [start, end)

    def _ua_average_base(self):
        """Сума заробітку і календарні дні розрахункового періоду. Без історії - від окладу (п. 4 Постанови 100)."""
        start, end = self._ua_average_window()
        rows = self.env["ua.earnings.history"].search([("employee_id", "=", self.employee_id.id),
                                                       ("month", ">=", start), ("month", "<", end)])
        if not rows:
            wage = self.contract_id.wage or 0.0
            return wage * 12.0, 365.0
        holidays = self.env["ua.payroll.param"].get("holidays_per_year", self.date_to, self.company_id)
        total = sum(rows.mapped("gross"))
        days = sum(r.calendar_days or calendar.monthrange(r.month.year, r.month.month)[1] for r in rows)
        days -= sum(rows.mapped("excluded_days"))
        days -= holidays * len(rows) / 12.0
        if total <= 0 or days <= 0:
            # п. 4 Порядку 100: за весь розрахунковий період немає заробітку (військова служба,
            # відпустка без збереження зарплати) - середня від окладу
            wage = self.contract_id.wage or 0.0
            return wage * 12.0, 365.0
        return total, max(days, 1.0)

    def _ua_leave_calendar_days(self):
        """Календарні дні відпусток і лікарняних у періоді листка, з поділом лікарняних на роботодавця (1-5) і ПФУ (6+)."""
        out = {"vac_days": 0, "sick_emp_days": 0, "sick_pfu_days": 0, "unpaid_days": 0, "mat_days": 0, "mat_cover_days": 0,
               "study_days": 0, "child_vac_days": 0, "trip_days": 0, "trip_work_days": 0, "child3_days": 0, "sick_care_days": 0,
               "mil_days": 0, "vac_paid_days": 0, "vac_ahead_days": 0}
        leaves = self.env["hr.leave"].search([("employee_id", "=", self.employee_id.id), ("state", "=", "validate"),
                                              ("request_date_from", "<=", self.date_to), ("request_date_to", ">=", self.date_from)])
        for lv in leaves:
            code = lv.holiday_status_id.work_entry_type_id.code or ""
            start = max(lv.request_date_from, self.date_from)
            end = min(lv.request_date_to, self.date_to)
            if end < start:
                continue
            if code == "VAC":
                out["vac_days"] += (end - start).days + 1
            elif code == "UNPAID":
                out["unpaid_days"] += (end - start).days + 1
            elif code == "MAT":
                # допомога нараховується одразу за весь період листка непрацездатності (126 к.д.) у місяці його надання
                out["mat_cover_days"] += (end - start).days + 1   # дні декрету в цьому місяці: без доплати ЄСВ до мінімального
                if self.date_from <= lv.request_date_from <= self.date_to:
                    out["mat_days"] += (lv.request_date_to - lv.request_date_from).days + 1
            elif code == "STUDY":
                out["study_days"] += (end - start).days + 1
            elif code == "CHILD_VAC":
                out["child_vac_days"] += (end - start).days + 1
            elif code == "CHILD3":
                out["child3_days"] += (end - start).days + 1
            elif code == "MIL":
                # військова служба: трудові відносини тривають, зарплата не нараховується
                out["mil_days"] += (end - start).days + 1
            elif code == "SICK_CARE":
                # догляд за хворим оплачує ПФУ з першого дня, п'яти днів за рахунок роботодавця немає
                out["sick_care_days"] += (end - start).days + 1
            elif code == "TRIP":
                out["trip_days"] += (end - start).days + 1
                day = start
                while day <= end:
                    if day.weekday() < 5:          # робочі дні відрядження: за ними платять середню (ст. 121 КЗпП)
                        out["trip_work_days"] += 1
                    day = fields.Date.add(day, days=1)
            elif code == "SICK":
                d = start
                while d <= end:
                    idx = (d - lv.request_date_from).days + 1
                    out["sick_emp_days" if idx <= 5 else "sick_pfu_days"] += 1
                    d = fields.Date.add(d, days=1)
        ahead = self._ua_vac_ahead()
        out["vac_ahead_days"] = sum(days for _key, days in ahead)
        out["vac_paid_days"] = min(self._ua_vac_paid_ahead()[0], out["vac_days"])
        return out

    def _ua_vac_ahead(self):
        """Дні щорічної відпустки після кінця листка, якщо відпустка почалася в ньому.

        Ст. 21 ЗУ «Про відпустки»: відпускні виплачують до початку відпустки, тож листок
        місяця початку нараховує всю відпустку. ЄСВ і Д1 (КТН 10) рахують частку кожного
        наступного місяця окремо. Повертає [("2026-09", 6), ...]."""
        self.ensure_one()
        ahead = {}
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "validate"),
            ("holiday_status_id.work_entry_type_id.code", "=", "VAC"),
            ("request_date_from", ">=", self.date_from), ("request_date_from", "<=", self.date_to),
            ("request_date_to", ">", self.date_to),
        ])
        for leave in leaves:
            current = self.date_to + timedelta(days=1)
            while current <= leave.request_date_to:
                month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
                segment_end = min(month_end, leave.request_date_to)
                key = "%d-%02d" % (current.year, current.month)
                ahead[key] = ahead.get(key, 0) + (segment_end - current).days + 1
                current = segment_end + timedelta(days=1)
        return sorted(ahead.items())

    def _ua_vac_paid_ahead(self):
        """Дні відпустки цього місяця, які вже оплатив проведений листок попереднього місяця, і сума за них."""
        self.ensure_one()
        key = "%d-%02d" % (self.date_from.year, self.date_from.month)
        # відпустка не довша за кілька місяців: досить листків трьох попередніх місяців
        slips = self.sudo().search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "done"), ("credit_note", "=", False),
            ("date_to", "<", self.date_from), ("date_from", ">=", _add_months(self.date_from.replace(day=1), -3)),
        ])
        parts = [(slip.ua_vac_ahead or {}).get(key) or {} for slip in slips]
        return sum(int(part.get("days", 0)) for part in parts), sum(float(part.get("amount", 0.0)) for part in parts)

    def _ua_store_vac_ahead(self):
        """Записати відпускні наперед під час проведення: дні й суму за кожен наступний місяць."""
        for slip in self.filtered(lambda s: not s.credit_note):
            avg = slip._ua_average_day()
            ahead = {key: {"days": days, "amount": ua_round(days * avg)} for key, days in slip._ua_vac_ahead()}
            slip.ua_vac_ahead = ahead or False

    def _ua_vac_ahead_rows(self):
        """Відпускні наперед проведеного листка: [(перше число місяця, дні, сума), ...] для Д1."""
        self.ensure_one()
        rows = []
        for key, value in sorted((self.ua_vac_ahead or {}).items()):
            year, month = (int(part) for part in key.split("-"))
            rows.append((date(year, month, 1), int(value.get("days", 0)), float(value.get("amount", 0.0))))
        return rows

    def _ua_trip_window(self):
        """Два повні календарні місяці перед місяцем події (Постанова 100 у редакції 1213)."""
        first = self.date_from.replace(day=1)
        return _add_months(first, -2), first

    def _ua_average_trip(self):
        """Середня за робочий день для відрядження: заробіток двох місяців / відпрацьовані робочі дні.

        Календарні дні × 5/7 більше не застосовуються: Порядок 100 вимагає фактичні
        робочі дні розрахункового періоду. Якщо робочі дні невідомі, середньої немає,
        і правило бере денний заробіток за окладом."""
        start, end = self._ua_trip_window()
        rows = self.env["ua.earnings.history"].search([
            ("employee_id", "=", self.employee_id.id), ("month", ">=", start), ("month", "<", end),
        ])
        days = sum(rows.mapped("work_days"))
        if not rows or days <= 0:
            return 0.0, 0.0
        return sum(rows.mapped("gross")), days

    def _ua_average_day(self):
        """Середня за календарний день на дату листка."""
        total, days = self._ua_average_base()
        return total / days if days else 0.0

    def _ua_mat_shares(self):
        """Частки декретної допомоги за місяцями листка непрацездатності.

        ЄСВ перевіряється за кожним місяцем окремо, тому допомогу треба спершу розподілити
        пропорційно календарним дням (роз'яснення ДПС про мінімальний внесок після розподілу)."""
        self.ensure_one()
        leaves = self.env["hr.leave"].sudo().search([
            ("employee_id", "=", self.employee_id.id), ("state", "=", "validate"),
            ("holiday_status_id.work_entry_type_id.code", "=", "MAT"),
            ("request_date_from", ">=", self.date_from), ("request_date_from", "<=", self.date_to),
        ])
        # Рядків листка ще немає: значення рахуються до виконання правил. Тому суму
        # допомоги беремо тією самою формулою, що й правило MAT.
        leave_days = self._ua_leave_calendar_days()
        total_amount = ua_round(leave_days.get("mat_days", 0) * self._ua_average_day())
        if not leaves or not total_amount:
            return []
        shares = []
        for leave in leaves:
            days_total = (leave.request_date_to - leave.request_date_from).days + 1
            current = leave.request_date_from
            while current <= leave.request_date_to:
                month_end = date(current.year, current.month,
                                 calendar.monthrange(current.year, current.month)[1])
                segment_end = min(month_end, leave.request_date_to)
                days = (segment_end - current).days + 1
                shares.append(round(total_amount * days / days_total, 2))
                current = segment_end + timedelta(days=1)
        return shares

    def _ua_trip_day(self):
        total, days = self._ua_average_trip()
        return (total / days) if days else 0.0

    def _ua_comp_extra_days(self):
        """Дні компенсації понад ручний ввід COMP_DAYS: невикористана соціальна відпустка на
        дітей (усі роки, не згорає) і невикористані УБД / особливі умови праці поточного року -
        лише в місяці звільнення (дата закінчення контракту у вікні цього листка).

        Береться contract_id, якщо він уже записаний (форма листка проставляє його через
        onchange_employee); інакше - той самий _get_employee_contracts(), яким рахує сама
        get_lines_dict() - бо contract_id лишається порожнім, коли листок створено напряму
        через API/скрипт, без спрацювання onchange."""
        self.ensure_one()
        contract = self.contract_id or self._get_employee_contracts()[:1]
        if not (contract and contract.date_end and self.date_from <= contract.date_end <= self.date_to):
            return 0.0
        emp = self.employee_id.sudo()
        soc_child = max(emp.ua_soc_child_balance or 0.0, 0.0)
        vac_ubd = max(emp.ua_vac_ubd_balance or 0.0, 0.0)
        special = max(emp.ua_special_balance or 0.0, 0.0)
        return soc_child + vac_ubd + special

    def _ua_payroll_values(self, contracts):
        res = super()._ua_payroll_values(contracts)
        total, days = self._ua_average_base()
        avg = total / days if days else 0.0
        res.update({
            "avg100_day": avg,          # середня за Постановою 100, грн за календарний день
            "avg1266_day": avg,         # те саме вікно; виключення - через excluded_days
            "avg_trip_day": self._ua_trip_day(),
            "mat_shares": self._ua_mat_shares(),
            "vac_ahead_shares": [ua_round(days * avg) for _key, days in self._ua_vac_ahead()],
            "sick_percent": self.employee_id.sudo().ua_sick_percent or 50.0,
            "extra_comp_days": self._ua_comp_extra_days(),
            **self._ua_leave_calendar_days(),
        })
        return res

    def _ua_average_source(self, basis):
        """Джерело середньої за Постановою 100/1266: домен на ua.earnings.history вікна розрахунку.

        Той самий домен, що читає _ua_average_base() - тут лише перевіряємо, чи є рядки,
        не перераховуємо середню вдруге.

        Коли рядків історії немає, середня не порожня і не нульова: _ua_average_base()
        підставляє оклад за п. 4 Постанови 100. Це підстановка, а не факт, і саме так її
        треба показати - стан calculated і рядок про те, звідки взялося число. Назвати це
        "missing" було б неправдою: число є. Назвати "supplied" - теж, бо заробітку не було."""
        start, end = self._ua_average_window()
        domain = [("employee_id", "=", self.employee_id.id), ("month", ">=", start), ("month", "<", end)]
        has_rows = bool(self.env["ua.earnings.history"].search_count(domain))
        label = "заробіток за 12 місяців до %s" % _ua_month_label(end)
        if not has_rows:
            contract = self.contract_id or self._get_employee_contracts()[:1]
            source = {"model": "hr.version", "res_id": contract.id, "label": "оклад версії контракту",
                      "basis": basis} if contract else None
            return source, "calculated", (
                "Немає рядків ua.earnings.history за %s - середня порахована від окладу "
                "за п. 4 Постанови 100, а не від фактичного заробітку." % label)
        return {"model": "ua.earnings.history", "domain": domain, "label": label, "basis": basis}, "supplied", None

    def _ua_trip_source(self):
        """Джерело середньої для відрядження: вікно двох місяців, ua.earnings.history.work_days.

        Викликає _ua_average_trip() - те саме обчислення, яким рахується сам avg_trip_day -
        не дублює пошук рядків окремою формулою."""
        start, end = self._ua_trip_window()
        domain = [("employee_id", "=", self.employee_id.id), ("month", ">=", start), ("month", "<", end)]
        label = "заробіток за 2 місяці до %s" % _ua_month_label(end)
        total, days = self._ua_average_trip()
        if days <= 0:
            return None, ("Немає рядків ua.earnings.history з відпрацьованими робочими днями за %s - "
                          "avg_trip_day лишається 0, відрядження порахується за денним окладом." % label)
        return {"model": "ua.earnings.history", "domain": domain, "label": label,
                "basis": "Постанова КМУ № 100 (в редакції 1213)"}, None

    def _ua_payroll_sources(self, contracts):
        """Джерела входів, які додає цей модуль. Ключі ті самі, що в _ua_payroll_values."""
        res = super()._ua_payroll_sources(contracts)

        src100, state100, note100 = self._ua_average_source("Постанова КМУ № 100")
        res["avg100_day"] = _entry("Середня грн/календарний день (Постанова 100)", "money",
                                   state100, source=src100, note=note100)

        src1266, state1266, note1266 = self._ua_average_source("Постанова КМУ № 1266 (лікарняні)")
        res["avg1266_day"] = _entry("Середня грн/календарний день (Постанова 1266, лікарняні)", "money",
                                    state1266, source=src1266, note=note1266)

        src_trip, note_trip = self._ua_trip_source()
        res["avg_trip_day"] = _entry("Середня грн/робочий день для відрядження", "money",
                                     "supplied" if src_trip else "missing", source=src_trip, note=note_trip)

        leave_days = self._ua_leave_calendar_days()  # один виклик, використовуємо і для mat_shares, і для днів нижче
        if leave_days.get("mat_days"):
            res["mat_shares"] = _entry(
                "Частки декретної допомоги за місяцями", "money", "calculated",
                note="Пораховано як avg100_day x календарні дні декретної відпустки в кожному місяці "
                     "листка, розподілено пропорційно (роз'яснення ДПС про мінімальний внесок).")
        else:
            res["mat_shares"] = _entry(
                "Частки декретної допомоги за місяцями", "money", "not_applicable",
                note="У цьому листку немає декретної відпустки, що почалася в періоді (mat_days = 0).")

        if leave_days.get("vac_ahead_days"):
            res["vac_ahead_shares"] = _entry(
                "Відпускні за дні наступних місяців", "money", "calculated",
                note="avg100_day x дні відпустки в кожному наступному місяці. Відпускні платять до початку "
                     "відпустки (ст. 21 ЗУ «Про відпустки»); ЄСВ і Д1 (КТН 10) рахують кожен місяць окремо.")
        else:
            res["vac_ahead_shares"] = _entry(
                "Відпускні за дні наступних місяців", "money", "not_applicable",
                note="Відпустка, що почалася в цьому листку, не переходить на наступний місяць.")
        res["vac_paid_days"] = _entry(
            "Дні відпустки, оплачені наперед минулим листком", "days", "calculated",
            source={"model": "hr.payslip", "domain": [("employee_id", "=", self.employee_id.id), ("state", "=", "done"),
                                                       ("date_to", "<", self.date_from)],
                    "label": "проведені листки попередніх місяців (поле «Відпускні наперед»)",
                    "basis": "ст. 21 ЗУ «Про відпустки»"})

        res["sick_percent"] = _entry(
            "Відсоток оплати лікарняного (страховий стаж)", "rate", "supplied",
            source={"model": "hr.employee", "res_id": self.employee_id.id,
                    "label": self.employee_id.name or "Картка працівника",
                    "basis": "ЗУ «Про загальнообов'язкове державне соціальне страхування» (страховий стаж)"})

        res["extra_comp_days"] = _entry(
            "Дні компенсації понад ручний ввід (COMP_DAYS)", "days", "calculated",
            note="Сума залишків картки працівника: невикористана соціальна відпустка на дітей (усі роки) "
                 "+ УБД/особливі умови поточного року; застосовується лише в місяці звільнення, інакше 0.")

        leave_specs = [
            ("vac_days", "VAC", "Дні щорічної відпустки в періоді листка",
             "Заява на щорічну відпустку, затверджена HR"),
            ("vac_ahead_days", "VAC", "Дні відпустки наступних місяців, оплачені наперед (ст. 21 ЗУ «Про відпустки»)",
             "Заява на щорічну відпустку, затверджена HR"),
            ("unpaid_days", "UNPAID", "Дні відпустки без збереження зарплати",
             "Заява на відпустку без збереження зарплати, затверджена HR"),
            ("mat_days", "MAT", "Дні декретної відпустки, що почалася в цьому листку",
             "Листок непрацездатності у зв'язку з вагітністю та пологами, затверджений HR"),
            ("mat_cover_days", "MAT", "Календарні дні декретного покриття в місяці листка",
             "Листок непрацездатності у зв'язку з вагітністю та пологами, затверджений HR"),
            ("study_days", "STUDY", "Дні навчальної відпустки",
             "Довідка навчального закладу, відпустка затверджена HR"),
            ("child_vac_days", "CHILD_VAC", "Дні соціальної відпустки на дітей",
             "Заява на соціальну відпустку на дітей, затверджена HR"),
            ("child3_days", "CHILD3", "Дні відпустки для батьків трьох і більше дітей",
             "Заява на відпустку для батьків трьох і більше дітей, затверджена HR"),
            ("mil_days", "MIL", "Дні військової служби (місце роботи зберігається)",
             "Наказ про збереження місця роботи на час військової служби"),
            ("sick_care_days", "SICK_CARE", "Дні лікарняного по догляду за хворим",
             "Лікарняний листок по догляду за хворим, затверджений HR"),
            ("trip_days", "TRIP", "Календарні дні відрядження",
             "Наказ про відрядження, затверджений HR"),
            ("trip_work_days", "TRIP", "Робочі дні відрядження (оплата за середньою, ст. 121 КЗпП)",
             "Наказ про відрядження, затверджений HR"),
            ("sick_emp_days", "SICK", "Дні лікарняного за рахунок роботодавця (1-5)",
             "Лікарняний листок, затверджений HR"),
            ("sick_pfu_days", "SICK", "Дні лікарняного за рахунок ПФУ (6 і далі)",
             "Лікарняний листок, затверджений HR"),
        ]
        for key, code, label, basis in leave_specs:
            domain = [("employee_id", "=", self.employee_id.id), ("state", "=", "validate"),
                      ("request_date_from", "<=", self.date_to), ("request_date_to", ">=", self.date_from),
                      ("holiday_status_id.work_entry_type_id.code", "=", code)]
            res[key] = _entry(label, "days", "calculated",
                              source={"model": "hr.leave", "domain": domain,
                                      "label": "затверджені відсутності листка (%s)" % code, "basis": basis})
        return res

    def action_payslip_done(self):
        res = super().action_payslip_done()
        self._ua_store_vac_ahead()
        Hist = self.env["ua.earnings.history"]
        for slip in self:
            gross = sum(slip.line_ids.filtered(lambda l: l.category_id.code in ("BASIC", "ALW", "AVG")).mapped("total"))
            # відпускні - у заробіток місяців, на які припадають дні відпустки: частку наступних
            # місяців забираємо, частку цього місяця з минулого листка додаємо
            gross -= sum(amount for _month, _days, amount in slip._ua_vac_ahead_rows())
            gross += slip._ua_vac_paid_ahead()[1]
            month = slip.date_from.replace(day=1)
            row = Hist.search([("employee_id", "=", slip.employee_id.id), ("month", "=", month)], limit=1)
            worked = sum(line.number_of_days for line in slip.worked_days_line_ids if line.code == "WORK100")
            absent = sum(abs(line.number_of_days) for line in slip.worked_days_line_ids if line.code != "WORK100")
            vals = {"employee_id": slip.employee_id.id, "month": month, "gross": gross, "source": "payslip",
                    "payslip_id": slip.id, "work_days": max(worked - absent, 0.0),
                    "excluded_days": slip._ua_excluded_days()}
            row.write(vals) if row else Hist.create(vals)
        return res

    def _ua_excluded_days(self):
        """Календарні дні місяця без збереження заробітку: військова служба, відпустка без
        збереження зарплати. П. 4 Порядку 100 виключає їх із розрахункового періоду разом із
        сумами за них, тож рядок історії несе їх у `excluded_days`."""
        self.ensure_one()
        days = self._ua_leave_calendar_days()
        return int(days.get("mil_days", 0) + days.get("unpaid_days", 0))
