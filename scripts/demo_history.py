"""Історія ТОВ «Ясен Меблі» місяць за місяцем: кадри і зарплата з січня 2025 року.

Це бібліотека для scripts/demo_company.py, сама вона не запускається. Склад людей лежить
у scripts/demo_world/people.json, календар подій - у scripts/demo_world/events.json;
опис світу - docs/base/demo-world.md.

Один місяць - це той самий шлях, яким іде бухгалтер у продукті:
  події місяця (накази про прийняття, оклад, відпустку; лікарняні; військовий облік)
  -> чернетки листків -> накази про звільнення (компенсація лягає в чернетку листка)
  -> табель -> авансова відомість -> розрахунок і проведення листків
  -> відомості на перерахування (аванс, зарплата, податки) і рядки виписки під них
  -> заява-розрахунок ПФУ -> об'єднана звітність -> журнал змін -> закриття місяця.

Закритий місяць - це історія: повторний прогін його пропускає і нічого в ньому не чіпає.
Усе пишеться кнопками і публічними методами модулів по JSON-RPC.
"""
import base64
import calendar
import json
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "demo_world")
FIRST_MONTH = (2025, 1)          # дата впровадження обліку в системі
LAST_CLOSED = (2026, 7)          # останній закритий місяць історії
PAID_MONTH = (2026, 8)           # проведено і виплачено, місяць ще відкритий
DRAFT_MONTH = (2026, 9)          # місяць у роботі: чернетки листків
MONTHS = {1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
          7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень"}
ORDER_LEAVES = {"VAC", "UNPAID", "MAT", "STUDY", "CHILD_VAC", "CHILD3", "SICK_CARE"}
PFU_CODES = ("SICK_PFU", "MAT", "SICK_CARE_PAY")
SCAN = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()   # заглушка скану, як у scripts/demo_hire.py


def load_people():
    return json.load(open(os.path.join(WORLD, "people.json"), encoding="utf-8"))


def load_events():
    return json.load(open(os.path.join(WORLD, "events.json"), encoding="utf-8"))


def workday(day, back=True):
    """Найближчий робочий день: назад (типово) або вперед."""
    step = timedelta(days=-1 if back else 1)
    while day.weekday() >= 5:
        day += step
    return day


def days_before(day, n):
    """Робочий день за n календарних днів до дати - дата наказу."""
    return workday(day - timedelta(days=n))


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def months_range(first, last):
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur = next_month(*cur)
    return out


class History:
    """Стан одного прогону: довідники, люди за ключем, події за місяцем."""

    def __init__(self, call, company, people, emp_ids, refs, say=print):
        self.call = call
        self.company = company
        self.people = {p["key"]: p for p in people}
        self.emp = emp_ids                      # ключ людини -> id картки
        self.refs = refs                        # depts, ct, leave_types, struct, struct_type, cal
        self.say = say
        self.events = load_events()
        self.stats = {}
        self.warnings = []
        self.bank_journal = call("account.journal", "search", [["type", "=", "bank"], ["company_id", "=", company]],
                                 order="sequence, id", limit=1)[0]
        self.misc_journal = call("account.journal", "search", [["type", "=", "general"], ["company_id", "=", company]], limit=1)[0]
        self.pay_setup = None

    # ------------------------------------------------------------------ дрібне
    def count(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def warn(self, text):
        self.warnings.append(text)
        self.say("  УВАГА: " + text)

    def month_events(self, year, month, types=None):
        prefix = "%04d-%02d" % (year, month)
        return [e for e in self.events if e["date"].startswith(prefix) and (not types or e["type"] in types)]

    def is_closed(self, year, month):
        return bool(self.call("ua.period.close", "search", [["company_id", "=", self.company], ["year", "=", year],
                                                             ["month", "=", month], ["kind", "=", "month"], ["state", "=", "closed"]]))

    def account(self, code):
        ids = self.call("account.account", "search", [["code", "=like", code + "%"], ["company_ids", "in", self.company]],
                        order="code", limit=1)
        if not ids:
            raise SystemExit("Немає рахунку %s у плані компанії" % code)
        return ids[0]

    def name_of(self, key):
        p = self.people[key]
        return "%s %s %s" % (p["last_name"], p["first_name"], p["middle_name"])

    # ------------------------------------------------------------------ події
    def ev_capital(self, e):
        ref = "%s (%s)" % (e["note"], e["date"])
        if self.call("account.move", "search_count", [["ref", "=", ref], ["company_id", "=", self.company]]):
            return
        bank_account = self.call("account.journal", "read", [self.bank_journal], ["default_account_id"])[0]["default_account_id"][0]
        move = self.call("account.move", "create", {
            "journal_id": self.misc_journal, "date": e["date"], "ref": ref, "company_id": self.company,
            "line_ids": [(0, 0, {"account_id": bank_account, "debit": e["amount"], "credit": 0.0, "name": e["note"]}),
                         (0, 0, {"account_id": self.account(e["account"]), "debit": 0.0, "credit": e["amount"], "name": e["note"]})]})
        self.call("account.move", "action_post", [move])
        self.count("внески і вхідний залишок")

    def ev_staff_list(self, e):
        ids = self.call("ua.staff.list", "search", [["company_id", "=", self.company], ["date", "=", e["date"]]])
        if ids:
            return
        day = date.fromisoformat(e["date"])
        sid = self.call("ua.staff.list", "create", {
            "company_id": self.company, "date": e["date"], "note": e.get("note") or False, "order_date": str(days_before(day, 5)),
            "order_ref": "Наказ директора про затвердження штатного розпису від %s" % days_before(day, 5).strftime("%d.%m.%Y")})
        self.call("ua.staff.list", "action_refill", [sid])
        if self.call("ua.staff.list", "read", [sid], ["line_ids"])[0]["line_ids"]:
            self.call("ua.staff.list", "action_confirm", [sid])
        self.count("штатні розписи")

    def _order(self, order_type, eid, domain, vals, acknowledge=True):
        """Наказ: знайти проведений за ключем або створити і провести. Повертає (id, чи новий)."""
        ids = self.call("ua.hr.order", "search", [["employee_id", "=", eid], ["order_type", "=", order_type],
                                                   ["state", "in", ["posted", "acknowledged"]]] + domain)
        if ids:
            return ids[0], False
        vals = dict(vals)
        if order_type in ("hire", "dismissal"):
            # скан підписаного наказу: порожній малюнок із позначкою, не документ
            vals.update({"signed_file": SCAN, "signed_filename": "nakaz_%s_%s.png" % (order_type, vals["date"])})
        oid = self.call("ua.hr.order", "create", dict(vals, order_type=order_type, employee_id=eid, company_id=self.company))
        self.call("ua.hr.order", "action_post", [oid])
        if acknowledge:
            self.call("ua.hr.order", "action_acknowledge", [oid])
            # ознайомили того ж дня, коли видали наказ, а не в день збирання демо
            self.call("ua.hr.order", "write", [oid], {"ack_date": vals["date"]})
        self.count("накази: " + order_type)
        return oid, True

    def ev_hire(self, e, rehire=False):
        p = self.people[e["who"]]
        eid = self.emp[e["who"]]
        day = date.fromisoformat(e["date"])
        extra = p.get("extra", {})
        if rehire:
            self.call("hr.employee", "write", [eid], {"active": True, "ua_dismissal_date": False}, context={"active_test": False})
        vals = {"date": str(days_before(day, 3)), "date_from": e["date"], "basis": "заява, трудовий договір",
                "department_id": self.refs["depts"][p["department"]], "wage": e.get("wage") or p.get("start_wage") or p["wage"],
                "job_title": p["job"], "prof_name": p["job"], "kp_code": extra.get("kp") or False, "fte": p["fte"],
                "contract_type_id": self.refs["ct"][extra.get("ct", "Permanent")],
                "trial_date_end": extra.get("trial") or False, "main_job": p["main_job"], "contract_kind": "employment"}
        oid, new = self._order("hire", eid, [["date_from", "=", e["date"]]], vals)
        if new:
            version = self.call("ua.hr.order", "read", [oid], ["version_id"])[0]["version_id"][0]
            # умови оплати, яких у наказі немає: вид оплати, тижнева норма, нічні зміни
            self.call("hr.version", "write", [version], {
                "structure_type_id": self.refs["struct_type"], "ua_internal_parttime": False,
                "ua_pay_type": extra.get("pay_type", "monthly"), "ua_hour_rate": extra.get("hour_rate", 0.0),
                "ua_weekly_hours": extra.get("weekly_hours", 40.0), "ua_night_shifts": extra.get("night_shifts", False),
            }, context={"sync_contract_dates": True})

    def ev_wage(self, e):
        eid = self.emp[e["who"]]
        day = date.fromisoformat(e["date"])
        self._order("wage", eid, [["date_from", "=", e["date"]]],
                    {"date": str(days_before(day, 5)), "date_from": e["date"], "wage": e["wage"], "basis": e.get("basis") or False})

    def _leave(self, eid, kind, d1, d2, order_ref=False, sick_number=False):
        lt = self.refs["leave_types"][kind]
        ids = self.call("hr.leave", "search", [["employee_id", "=", eid], ["holiday_status_id", "=", lt],
                                               ["request_date_from", "=", d1], ["state", "=", "validate"]])
        if ids:
            return ids[0], False
        lid = self.call("hr.leave", "create", {"employee_id": eid, "holiday_status_id": lt, "request_date_from": d1,
                                               "request_date_to": d2, "ua_order_ref": order_ref, "ua_sick_number": sick_number})
        self.call("hr.leave", "action_approve", [lid])
        return lid, True

    def sick_number(self, e):
        d = e["date"].replace("-", "")
        return "%s-%s-%06d" % (d[:4], d[4:], 100000 + (self.emp[e["who"]] * 7919 + int(d)) % 899999)

    def ev_leave(self, e):
        eid = self.emp[e["who"]]
        kind, d1, d2 = e["kind"], e["date"], e["to"]
        day = date.fromisoformat(d1)
        lt = self.refs["leave_types"][kind]
        if self.call("hr.leave", "search_count", [["employee_id", "=", eid], ["holiday_status_id", "=", lt],
                                                  ["request_date_from", "=", d1], ["state", "=", "validate"]]):
            return
        self.call("hr.employee", "ua_ensure_leave_allocations", [eid])
        number = self.sick_number(e) if kind in ("SICK", "MAT", "SICK_CARE") else False
        if kind in ORDER_LEAVES:
            vals = {"date": str(days_before(day, 3 if kind in ("MAT", "SICK_CARE") or e.get("mobilisation") else 10)),
                    "date_from": d1, "date_to": d2, "leave_type_id": lt, "sick_number": number,
                    "basis": "повістка ТЦК та СП, ст. 119 КЗпП" if e.get("mobilisation") else "заява", "note": e.get("note") or False}
            self._order("leave", eid, [["date_from", "=", d1]], vals)
        elif kind == "TRIP":
            order_day = days_before(day, 4)
            oid, _new = self._order("trip", eid, [["date_from", "=", d1]],
                                    {"date": str(order_day), "date_from": d1, "date_to": d2,
                                     "destination": e.get("destination") or "-", "purpose": e.get("purpose") or False})
            name = self.call("ua.hr.order", "read", [oid], ["name"])[0]["name"]
            self._leave(eid, kind, d1, d2, order_ref="Наказ № %s від %s" % (name, order_day.strftime("%d.%m.%Y")))
        else:   # лікарняний: наказу не потребує, лише номер е-ЛН
            self._leave(eid, kind, d1, d2, sick_number=number)
        self.count("відсутності: " + kind)

    def ev_mistake_leave(self, e):
        """Відпустку внесено з помилкою в датах: наказ проведено, відпустку скасовано (наказ лишається
        в журналі скасованим), того ж дня внесено правильний наказ."""
        eid = self.emp[e["who"]]
        lt = self.refs["leave_types"][e["kind"]]
        if self.call("ua.hr.order", "search_count", [["employee_id", "=", eid], ["order_type", "=", "leave"], ["date_from", "=", e["date"]]]):
            return
        day = date.fromisoformat(e["date"])
        self.call("hr.employee", "ua_ensure_leave_allocations", [eid])
        wrong = self.call("ua.hr.order", "create", {
            "order_type": "leave", "employee_id": eid, "company_id": self.company, "date": str(days_before(day, 12)),
            "date_from": e["date"], "date_to": e["to"], "leave_type_id": lt, "basis": "заява", "note": e.get("note") or False})
        self.call("ua.hr.order", "action_post", [wrong])
        leave = self.call("ua.hr.order", "read", [wrong], ["leave_id"])[0]["leave_id"][0]
        self.call("hr.leave", "action_refuse", [leave])
        self._order("leave", eid, [["date_from", "=", e["date"]], ["date_to", "=", e["right_to"]]],
                    {"date": e["fixed_on"], "date_from": e["date"], "date_to": e["right_to"], "leave_type_id": lt,
                     "basis": "заява; виправлення дат попереднього наказу", "note": e.get("note") or False})
        self.count("відсутності: " + e["kind"])
        self.count("підкладені помилки")

    def ev_military(self, e):
        eid = self.emp[e["who"]]
        if self.call("ua.military.event", "search_count", [["employee_id", "=", eid], ["kind", "=", e["kind"]], ["date", "=", e["date"]]]):
            return
        self.call("ua.military.event", "create", {"employee_id": eid, "date": e["date"], "kind": e["kind"], "note": e.get("note") or False})
        self.count("події військового обліку")

    def run_events(self, year, month):
        for e in self.month_events(year, month):
            t = e["type"]
            if t == "capital":
                self.ev_capital(e)
            elif t == "staff_list":
                pass   # після кадрових подій того ж дня, див. нижче
            elif t == "hire":
                self.ev_hire(e)
            elif t == "rehire":
                self.ev_hire(e, rehire=True)
            elif t == "wage":
                self.ev_wage(e)
            elif t == "leave":
                self.ev_leave(e)
            elif t == "mistake_leave":
                self.ev_mistake_leave(e)
            elif t == "military":
                self.ev_military(e)
        for e in self.month_events(year, month, ("staff_list",)):
            self.ev_staff_list(e)

    def run_dismissals(self, year, month, slips):
        for e in self.month_events(year, month, ("dismissal",)):
            eid = self.emp[e["who"]]
            day = date.fromisoformat(e["date"])
            _oid, new = self._order("dismissal", eid, [["date_to", "=", e["date"]]],
                                    {"date": str(days_before(day, 3)), "date_to": e["date"], "dismissal_basis": e["basis"],
                                     "comp_days": e.get("comp_days") or 0.0, "basis": "заява" if "36" in e["basis"] or "38" in e["basis"] else "наказ"})
            slip = slips.get(e["who"])
            if slip and e.get("severance"):
                self.set_input(slip, "SEVERANCE", e["severance"], "Вихідна допомога")
            if slip and e.get("comp_days") and not self.call("hr.payslip.input", "search_count",
                                                             [["payslip_id", "=", slip], ["code", "=", "COMP_DAYS"], ["amount", ">", 0]]):
                # наказ кладе дні компенсації в чернетку листка сам; це запас на випадок, коли листка
                # на мить проведення наказу ще не було (перерваний прогін)
                self.set_input(slip, "COMP_DAYS", e["comp_days"], "Компенсація невикористаної відпустки")

    # ------------------------------------------------------------------ листки
    def set_input(self, slip, code, amount, name=None, add=False):
        ids = self.call("hr.payslip.input", "search", [["payslip_id", "=", slip], ["code", "=", code]])
        if ids:
            if add:
                amount += self.call("hr.payslip.input", "read", ids[:1], ["amount"])[0]["amount"]
            self.call("hr.payslip.input", "write", ids[:1], {"amount": amount})
            return
        contract = self.call("hr.payslip", "read", [slip], ["contract_id"])[0]["contract_id"]
        self.call("hr.payslip.input", "create", {"payslip_id": slip, "code": code, "name": name or code, "amount": amount,
                                                 "contract_id": contract[0] if contract else False})

    def employed(self, d1, d2):
        """Ключі людей, у яких є договір у цьому місяці."""
        ids = list(self.emp.values())
        versions = self.call("hr.version", "search_read",
                             [["employee_id", "in", ids], ["contract_date_start", "<=", str(d2)],
                              "|", ["contract_date_end", "=", False], ["contract_date_end", ">=", str(d1)]],
                             fields=["employee_id"], context={"active_test": False})
        have = {v["employee_id"][0] for v in versions}
        out = []
        for key, eid in self.emp.items():
            mobilised = self.people[key].get("mobilised_from")
            if eid in have and not (mobilised and mobilised <= str(d1)):   # увільнений на весь місяць: листка немає
                out.append(key)
        return out

    def monthly_inputs(self, key, year, month, d1, d2):
        """Постійні входи листка людини: премія, ЦПХ, ФОП, аліменти."""
        extra = self.people[key].get("extra", {})
        out = {}
        for code in ("BONUS", "GPH", "FOP_PAY", "ALIM_PCT"):
            amount = extra.get(code)
            if not amount:
                continue
            if code == "BONUS" and month not in (3, 6, 8, 9, 12) and amount > 5000:
                amount = round(amount / 2)       # повна премія - наприкінці кварталу, решту місяців половина
            out[code] = amount
        return out

    def make_slips(self, year, month, run):
        d1, d2 = month_bounds(year, month)
        keys = self.employed(d1, d2)
        vals = [{"employee_id": self.emp[k], "date_from": str(d1), "date_to": str(d2), "struct_id": self.refs["struct"],
                 "payslip_run_id": run, "company_id": self.company} for k in keys]
        ids = self.call("hr.payslip", "create", vals, context={"active_test": False})
        slips = dict(zip(keys, ids))
        for key, slip in slips.items():
            self.call("hr.payslip", "onchange_employee", [slip])
            self.call("hr.payslip", "write", [slip], {"name": "Розрахунковий листок: %s, %s %s" % (self.name_of(key), MONTHS[month], year)})
            for code, amount in self.monthly_inputs(key, year, month, d1, d2).items():
                self.set_input(slip, code, amount)
        for e in self.month_events(year, month, ("input", "mistake_bonus")):
            slip = slips.get(e["who"])
            if not slip:
                continue
            if e["type"] == "mistake_bonus":
                self.set_input(slip, "BONUS", e["wrong"], "Премія")          # помилка: не та сума премії
            else:
                self.set_input(slip, e["code"], e["amount"], e.get("note"), add=e["code"] == "BONUS")
        for e in self.month_events(year, month, ("leave",)):
            if e.get("daily") and slips.get(e["who"]):
                self.set_input(slips[e["who"]], "DAILY", e["daily"], "Добові за відрядження")
        return slips

    def drop_slips(self, d1):
        """Прибрати листки місяця, який перераховуємо (лише відкриті місяці)."""
        old = self.call("hr.payslip", "search_read", [["employee_id", "in", list(self.emp.values())], ["date_from", "=", str(d1)]],
                        fields=["id", "state", "move_id"], context={"active_test": False})
        for sl in old:
            if sl["state"] == "done" and sl["move_id"]:
                self.call("account.move", "button_draft", [sl["move_id"][0]])
                self.call("account.move", "unlink", [sl["move_id"][0]])
            if sl["state"] != "cancel":
                self.call("hr.payslip", "write", [sl["id"]], {"state": "cancel"})
        if old:
            self.call("hr.payslip", "unlink", [sl["id"] for sl in old])

    def timesheet(self, year, month):
        ids = self.call("ua.timesheet.sheet", "search", [["company_id", "=", self.company], ["year", "=", year],
                                                          ["month", "=", month], ["department_id", "=", False]])
        sheet = ids[0] if ids else self.call("ua.timesheet.sheet", "create", {"company_id": self.company, "year": year, "month": month})
        if self.call("ua.timesheet.sheet", "read", [sheet], ["state"])[0]["state"] != "draft":
            self.call("ua.timesheet.sheet", "action_draft", [sheet])
        self.call("ua.timesheet.sheet", "action_refill", [sheet])
        lines = self.call("ua.timesheet.line", "search_read", [["sheet_id", "=", sheet]], fields=["employee_id", "days_worked"])
        by_emp = {l["employee_id"][0]: l for l in lines}
        for key, p in self.people.items():
            extra = p.get("extra", {})
            line = by_emp.get(self.emp.get(key))
            if not line:
                continue
            if extra.get("weekly_hours"):        # неповний тиждень: факт годин за нормою тижня, а не 8 годин на день
                self.call("ua.timesheet.line", "write", [line["id"]], {"hours": round(line["days_worked"] * extra["weekly_hours"] / 5.0, 2)})
            if extra.get("night_shifts") and line["days_worked"] >= 10:
                self.call("ua.timesheet.line", "write", [line["id"]], {"night_hours": 16.0})   # дві нічні зміни на місяць
        if lines:
            self.call("ua.timesheet.sheet", "action_confirm", [sheet])
            self.count("табелі")
        return sheet

    def advance_sheet(self, year, month):
        pay_date = str(workday(date(year, month, 20)))
        ids = self.call("ua.advance.sheet", "search", [["company_id", "=", self.company], ["year", "=", year], ["month", "=", month]], order="id")
        if ids:
            cur = self.call("ua.advance.sheet", "read", ids[:1], ["state"])[0]
            if cur["state"] == "confirmed":
                self.call("ua.advance.sheet", "action_draft", ids[:1])
            sheet = ids[0]
            self.call("ua.advance.sheet", "write", [sheet], {"percent": 50.0, "pay_date": pay_date})
        else:
            sheet = self.call("ua.advance.sheet", "create", {"company_id": self.company, "year": year, "month": month,
                                                              "percent": 50.0, "pay_date": pay_date})
        self.call("ua.advance.sheet", "action_refill", [sheet])
        for e in self.month_events(year, month, ("leave",)):
            if not e.get("advance_net"):
                continue
            # Людина йде посеред місяця одразу після авансу: аванс за відпрацьовані дні бухгалтер
            # зменшує на податки вручну, інакше листок місяця вийде з від'ємною сумою до виплати.
            line = self.call("ua.advance.line", "search_read", [["sheet_id", "=", sheet], ["employee_id", "=", self.emp[e["who"]]]], fields=["amount"])
            if line:
                rate = sum(self.call("ua.payroll.param", "get", key, pay_date) for key in ("pdfo_rate", "vz_rate"))
                self.call("ua.advance.line", "write", [line[0]["id"]], {
                    "amount": round(line[0]["amount"] * (1 - rate / 100.0), 2),
                    "note": "зменшено на ПДФО і військовий збір: останній робочий день %s" % (date.fromisoformat(e["date"]) - timedelta(days=1)).isoformat()})
        if self.call("ua.advance.sheet", "read", [sheet], ["line_ids"])[0]["line_ids"]:
            self.call("ua.advance.sheet", "action_confirm", [sheet])
            self.count("авансові відомості")
        return pay_date

    def slip_rows(self, slips):
        ids = list(slips.values())
        by_slip = {i: {} for i in ids}
        for l in self.call("hr.payslip.line", "search_read", [["slip_id", "in", ids]], fields=["slip_id", "code", "total"]):
            by_slip[l["slip_id"][0]][l["code"]] = round(by_slip[l["slip_id"][0]].get(l["code"], 0.0) + l["total"], 2)
        return {key: by_slip[slip] for key, slip in slips.items()}

    # ------------------------------------------------------------------ гроші
    def pay_order(self, kind, year, month, pay_date, statement=True):
        """Відомість на перерахування до «Проведено» і рядки виписки під її платежі."""
        if self.pay_setup is None:
            self.pay_setup = self.call("res.company", "ua_payment_setup", [self.company])
        ids = self.call("account.payment.order", "search", [["ua_kind", "=", kind], ["ua_year", "=", year], ["ua_month", "=", month]], order="id")
        order = ids[0] if ids else self.call("account.payment.order", "create", {
            "payment_mode_id": self.pay_setup["tax" if kind == "tax" else "salary"], "journal_id": self.pay_setup["journal"],
            "date_prefered": "now", "ua_kind": kind, "ua_year": year, "ua_month": month, "ua_pay_date": pay_date})
        state = self.call("account.payment.order", "read", [order], ["state"])[0]["state"]
        if state == "draft":
            self.call("account.payment.order", "action_fill", [order])
            if not self.call("account.payment.order", "read", [order], ["payment_line_ids"])[0]["payment_line_ids"]:
                return order
            self.call("account.payment.order", "action_confirm", [order])
            state = "open"
        if state in ("open", "generated"):
            self.call("account.payment.order", "action_paid", [order])
            self.count("відомості на перерахування")
        if statement:
            self.statement_lines(order)
        return order

    def statement_lines(self, order):
        payments = self.call("account.payment", "search_read", [["payment_order_id", "=", order]],
                             fields=["partner_id", "amount", "date", "memo", "is_matched"])
        vals = []
        for p in payments:
            if p["is_matched"]:
                continue
            ref = "%s; %s" % (p["memo"] or "Виплата", p["partner_id"][1] if p["partner_id"] else "")
            if self.call("account.bank.statement.line", "search_count", [["journal_id", "=", self.bank_journal], ["payment_ref", "=", ref],
                                                                         ["date", "=", p["date"]], ["amount", "=", -p["amount"]]]):
                continue
            vals.append({"journal_id": self.bank_journal, "company_id": self.company, "date": p["date"], "payment_ref": ref,
                         "amount": -round(p["amount"], 2), "partner_id": p["partner_id"][0] if p["partner_id"] else False})
        if vals:
            self.call("account.bank.statement.line", "create", vals)
            self.call("ua.bank.ops", "action_match_payments", journal_id=self.bank_journal)
            self.count("рядки виписки під зарплатні платежі", len(vals))

    # ------------------------------------------------------------------ документи після розрахунку
    def pfu_claim(self, run, year, month, rows):
        if not any(r.get(code) for r in rows.values() for code in PFU_CODES):
            return
        ids = self.call("ua.pfu.claim", "search", [["payslip_run_id", "=", run]])
        claim = ids[0] if ids else self.call("hr.payslip.run", "action_ua_pfu_claim", [run])["res_id"]
        for state, method in (("draft", "action_confirm"), ("confirmed", "action_submit"), ("submitted", "action_accept"),
                              ("accepted", "action_register_funding"), ("funded", "action_register_payment"),
                              ("paid", "action_notice_sent"), ("notified", "action_done")):
            if self.call("ua.pfu.claim", "read", [claim], ["state"])[0]["state"] == state:
                self.call("ua.pfu.claim", method, [claim])
        ny, nm = next_month(year, month)
        day = workday(date(ny, nm, 2), back=False)
        step = lambda n: str(workday(day + timedelta(days=n), back=False))
        # дії модуля ставлять «сьогодні»; заяву за місяць подавали на початку наступного
        self.call("ua.pfu.claim", "write", [claim], {"date": str(day), "submitted_date": str(day), "accepted_date": step(2),
                                                     "funded_date": step(7), "paid_date": step(8), "notice_date": step(9)})
        self.count("заяви-розрахунки ПФУ")

    def report_j05(self, year, month, kind="HZ"):
        """Об'єднана звітність за місяць: сформувати і позначити поданою."""
        quarter = (month - 1) // 3 + 1
        run = self.call("ua.report.run", "ensure_run", report_code="j05", year=year, quarter=quarter, month=month)
        state = self.call("ua.report.run", "read", [run], ["state"])[0]["state"]
        try:
            if state in ("draft", "checked"):
                self.call("ua.report.run", "action_generate", [run])
                state = "generated"
            if state == "generated":
                self.call("ua.report.run", "action_mark_submitted", [run])
                ny, nm = next_month(year, month)
                self.call("ua.report.run", "write", [run], {"submitted_date": str(workday(date(ny, nm, 18)))})
                self.count("об'єднана звітність (подано)")
        except SystemExit as exc:
            self.warn("об'єднана звітність за %02d.%s не сформована: %s" % (month, year, str(exc)[:300]))
        return run

    def close_quarter(self, year, month):
        """Квартал закривається лише після поданого розрахунку за його останній місяць."""
        if month % 3:
            return
        if self.call("ua.period.close", "search_count", [["company_id", "=", self.company], ["year", "=", year], ["month", "=", month],
                                                         ["kind", "=", "quarter"], ["state", "=", "closed"]]):
            return
        try:
            self.call("ua.period.close", "close_quarter", year, month // 3)
            self.count("закриті квартали")
        except SystemExit as exc:
            self.warn("квартал %s %s не закрито: %s" % (month // 3, year, str(exc)[:200]))

    def catch_up(self, year, month):
        """Закритий місяць не переписуємо, але звітність і квартал доводимо, якщо прогін обірвався."""
        submitted = self.call("ua.report.run", "search_count", [["company_id", "=", self.company], ["report_code", "=", "j05"], ["year", "=", year],
                                                                ["month", "=", month], ["doc_kind", "=", "HZ"], ["state", "=", "submitted"]])
        if not submitted:
            self.report_j05(year, month)
        self.close_quarter(year, month)

    def close_month(self, year, month, run):
        accepted = self.call("ua.change.log", "accept_period", year, month)
        if self.call("hr.payslip.run", "read", [run], ["state"])[0]["state"] != "close":
            self.call("hr.payslip.run", "close_payslip_run", [run])
        reasons = self.call("ua.period.close", "blockers", self.company, year, month)
        if reasons:
            raise SystemExit("Місяць %02d.%s не закривається: %s" % (month, year, "; ".join(reasons)))
        self.call("ua.period.close", "close_period", year, month, False)
        self.count("закриті місяці")
        return accepted

    # ------------------------------------------------------------------ підкладена помилка: перерахунок
    def fix_bonus(self, e):
        """Премію за закритий місяць внесено не тією сумою. Місяць відкривають з причиною,
        листок людини проводять заново, різницю доплачують окремою відомістю, місяць закривають
        знову і подають уточнюючий розрахунок. Викликається в місяці, коли помилку знайшли."""
        year, month = int(e["date"][:4]), int(e["date"][5:7])
        key, eid = e["who"], self.emp[e["who"]]
        d1, d2 = month_bounds(year, month)
        slip = self.call("hr.payslip", "search_read", [["employee_id", "=", eid], ["date_from", "=", str(d1)], ["state", "=", "done"]],
                         fields=["id", "move_id", "payslip_run_id"])
        if not slip:
            return
        bonus = self.call("hr.payslip.input", "search_read", [["payslip_id", "=", slip[0]["id"]], ["code", "=", "BONUS"]], fields=["amount"])
        if not bonus or abs(bonus[0]["amount"] - e["wrong"]) > 0.005:
            return   # уже виправлено
        reason = "Премію %s за %s %s внесено %s грн замість %s грн. Перерахунок листка, знайдено %s." % (
            self.name_of(key), MONTHS[month], year, e["wrong"], e["right"], e["found"])
        closes = self.call("ua.period.close", "search", [["company_id", "=", self.company], ["kind", "=", "month"], ["state", "=", "closed"],
                                                         ["lock_date", ">=", str(d2)]], order="lock_date desc")
        # відкриваємо всі місяці від останнього закритого до місяця помилки: дата блокування одна
        for cid in closes:
            self.call("ua.period.close", "write", [cid], {"reopen_reason": reason})
            self.call("ua.period.close", "action_reopen", [cid])
        saved = self.call("res.company", "read", [self.company], ["tax_lock_date"])[0]["tax_lock_date"]
        if saved and saved >= str(d1):
            self.call("res.company", "write", [self.company], {"tax_lock_date": False})
        run = slip[0]["payslip_run_id"][0]
        if self.call("hr.payslip.run", "read", [run], ["state"])[0]["state"] == "close":
            self.call("hr.payslip.run", "draft_payslip_run", [run])
        old_net = self.slip_rows({key: slip[0]["id"]})[key].get("NET", 0.0)
        if slip[0]["move_id"]:
            self.call("account.move", "button_draft", [slip[0]["move_id"][0]])
            self.call("account.move", "unlink", [slip[0]["move_id"][0]])
        self.call("hr.payslip", "write", [slip[0]["id"]], {"state": "draft"})
        self.set_input(slip[0]["id"], "BONUS", e["right"], "Премія")
        self.call("hr.payslip", "compute_sheet", [slip[0]["id"]])
        self.call("hr.payslip", "action_payslip_done", [slip[0]["id"]])
        new_net = self.slip_rows({key: slip[0]["id"]})[key].get("NET", 0.0)
        diff = round(new_net - old_net, 2)
        if diff > 0:
            self.extra_payment(year, month, eid, diff, e["found"], "Доплата за %s %s після перерахунку премії" % (MONTHS[month], year))
        # податки з різниці: відомість на податки місяця вже оплачена, тому доплата - окремими платежами
        self.tax_topup(year, month, e["found"])
        for cid in reversed(closes):
            c = self.call("ua.period.close", "read", [cid], ["year", "month"])[0]
            self.call("ua.change.log", "accept_period", c["year"], c["month"])
            crun = self.call("hr.payslip.run", "search", [["company_id", "=", self.company], ["date_start", "=", str(date(c["year"], c["month"], 1))]])
            if crun and self.call("hr.payslip.run", "read", crun[:1], ["state"])[0]["state"] != "close":
                self.call("hr.payslip.run", "close_payslip_run", crun[:1])
            self.call("ua.period.close", "close_period", c["year"], c["month"], False)
        if saved and saved >= str(d1):
            self.call("res.company", "write", [self.company], {"tax_lock_date": saved})
        base = self.call("ua.report.run", "search", [["company_id", "=", self.company], ["report_code", "=", "j05"], ["year", "=", year],
                                                     ["month", "=", month], ["doc_kind", "=", "HZ"]])
        if base:
            try:
                corr = self.call("ua.report.run", "create_correction", base[0], "HZU")["id"]
                self.call("ua.report.run", "action_generate", [corr])
                self.call("ua.report.run", "action_mark_submitted", [corr])
                self.call("ua.report.run", "write", [corr], {"submitted_date": e["found"], "note": reason})
                self.count("уточнюючі розрахунки")
            except SystemExit as exc:
                self.warn("уточнюючий розрахунок за %02d.%s не сформовано: %s" % (month, year, str(exc)[:300]))
        self.count("підкладені помилки")
        self.say("  помилка і виправлення: %s Доплачено %.2f." % (reason, diff))

    def extra_payment(self, year, month, eid, amount, pay_date, purpose):
        """Окрема відомість «Інша виплата» на одну людину: доплата після перерахунку."""
        if self.pay_setup is None:
            self.pay_setup = self.call("res.company", "ua_payment_setup", [self.company])
        if self.call("account.payment.order", "search_count", [["ua_kind", "=", "other"], ["ua_year", "=", year], ["ua_month", "=", month]]):
            return
        emp = self.call("hr.employee", "read", [eid], ["work_contact_id", "primary_bank_account_id"], context={"active_test": False})[0]
        order = self.call("account.payment.order", "create", {
            "payment_mode_id": self.pay_setup["salary"], "journal_id": self.pay_setup["journal"], "date_prefered": "now",
            "ua_kind": "other", "ua_year": year, "ua_month": month, "ua_pay_date": pay_date, "ua_note": purpose})
        currency = self.call("res.company", "read", [self.company], ["currency_id"])[0]["currency_id"][0]
        self.call("account.payment.line", "create", {
            "order_id": order, "partner_id": emp["work_contact_id"][0], "partner_bank_id": emp["primary_bank_account_id"][0],
            "amount_currency": amount, "currency_id": currency, "communication": purpose, "ua_employee_id": eid,
            "ua_account_id": self.account("661")})
        self.call("account.payment.order", "action_confirm", [order])
        self.call("account.payment.order", "action_paid", [order])
        self.statement_lines(order)
        self.count("відомості на перерахування")

    def tax_topup(self, year, month, pay_date):
        """Доплата ПДФО, військового збору і ЄСВ після перерахунку: залишки 6411, 6415, 651 за місяць."""
        d1, d2 = month_bounds(year, month)
        dps = self.call("res.partner", "search", [["name", "ilike", "ДПС"]], limit=1)
        for code, label in (("6411", "ПДФО"), ("6415", "Військовий збір"), ("651", "Єдиний внесок (ЄСВ)")):
            acc = self.account(code)
            # нарахування листків місяця мінус те, що вже сплачено відомістю на податки
            paid = self.call("account.payment", "search_read", [["payment_order_id.ua_kind", "=", "tax"], ["payment_order_id.ua_year", "=", year],
                                                                ["payment_order_id.ua_month", "=", month], ["destination_account_id", "=", acc]],
                             fields=["amount"])
            accrued = self.call("account.move.line", "read_group", [["account_id", "=", acc], ["parent_state", "=", "posted"],
                                                                    ["company_id", "=", self.company], ["credit", ">", 0],
                                                                    ["date", ">=", str(d1)], ["date", "<=", str(d2)]], ["credit:sum"], [])
            total = round((accrued[0].get("credit") or 0.0) if accrued else 0.0, 2)
            diff = round(total - sum(p["amount"] for p in paid), 2)
            if diff <= 0.005 or not dps:
                continue
            memo = "%s за %s %s, доплата після перерахунку" % (label, MONTHS[month], year)
            if self.call("account.payment", "search_count", [["memo", "=", memo]]):
                continue
            pid = self.call("account.payment", "create", {"payment_type": "outbound", "partner_type": "supplier", "partner_id": dps[0],
                                                          "amount": diff, "date": pay_date, "journal_id": self.bank_journal,
                                                          "company_id": self.company, "memo": memo, "destination_account_id": acc})
            self.call("account.payment", "action_post", [pid])
            line = self.call("account.bank.statement.line", "create", {"journal_id": self.bank_journal, "company_id": self.company,
                                                                       "date": pay_date, "payment_ref": memo, "amount": -diff, "partner_id": dps[0]})
            self.call("ua.bank.ops", "action_match_payments", line_id=line)

    # ------------------------------------------------------------------ місяць
    def run_month(self, year, month, mode):
        """mode: closed - увесь шлях до закриття; paid - проведено і виплачено, місяць відкритий;
        draft - чернетки листків. Повертає (id пакета, рядки листків за ключем людини)."""
        d1, d2 = month_bounds(year, month)
        name = "Зарплата за %s %s" % (MONTHS[month], year)
        run = self.call("hr.payslip.run", "search", [["company_id", "=", self.company], ["date_start", "=", str(d1)]])
        run = run[0] if run else self.call("hr.payslip.run", "create", {"name": name, "date_start": str(d1), "date_end": str(d2),
                                                                        "company_id": self.company})
        existing = self.call("hr.payslip", "search_read", [["payslip_run_id", "=", run], ["state", "!=", "cancel"]],
                             fields=["employee_id", "state"], context={"active_test": False})
        by_eid = {v: k for k, v in self.emp.items()}
        if mode != "draft" and existing and all(s["state"] == "done" for s in existing):
            # місяць уже пораховано і проведено: історію не переписуємо, лише читаємо
            slips = {by_eid[s["employee_id"][0]]: s["id"] for s in existing if s["employee_id"][0] in by_eid}
            self.say("%s: уже проведено, листків %s - пропущено" % (name, len(slips)))
            return run, self.slip_rows(slips)

        self.run_events(year, month)
        for e in self.events:
            if e["type"] == "mistake_bonus" and e["found"].startswith("%04d-%02d" % (year, month)):
                self.fix_bonus(e)
        self.drop_slips(d1)
        slips = self.make_slips(year, month, run)
        self.run_dismissals(year, month, slips)
        self.timesheet(year, month)
        pay_advance = None
        if mode != "draft":
            pay_advance = self.advance_sheet(year, month)
        ids = list(slips.values())
        for slip in ids:   # розрахунок і проведення - по одному листку: методи модулів чекають один запис
            self.call("hr.payslip", "compute_sheet", [slip])
        if mode == "draft":
            self.say("%s: чернетки, листків %s" % (name, len(ids)))
            return run, self.slip_rows(slips)
        for slip in ids:
            self.call("hr.payslip", "action_payslip_done", [slip])
        self.count("проведені листки %s" % year, len(ids))
        rows = self.slip_rows(slips)
        ny, nm = next_month(year, month)
        pay_salary = str(workday(date(ny, nm, 5)))
        statement = mode == "closed"
        self.pay_order("advance", year, month, pay_advance, statement=statement)
        self.pay_order("salary", year, month, pay_salary, statement=statement)
        gross = sum(r.get("GROSS", 0.0) for r in rows.values())
        net = sum(r.get("NET", 0.0) for r in rows.values())
        if mode == "closed":
            self.pay_order("tax", year, month, pay_salary)
            self.pfu_claim(run, year, month, rows)
            accepted = self.close_month(year, month, run)
            self.report_j05(year, month)
            self.close_quarter(year, month)
            self.say("%s: листків %s, нараховано %.2f, до виплати %.2f, прийнято змін %s - закрито" % (name, len(ids), gross, net, accepted))
        else:
            self.say("%s: листків %s, нараховано %.2f, до виплати %.2f - проведено і виплачено, місяць відкритий" % (name, len(ids), gross, net))
        return run, rows

    def summary(self):
        self.say("\nІсторія: що створено цим прогоном")
        for key in sorted(self.stats):
            self.say("  %-45s %s" % (key, self.stats[key]))
        for w in self.warnings:
            self.say("  УВАГА: " + w)
