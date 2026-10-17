import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Поля картки, від яких залежить право на відпустку. Зміна будь-якого з них перегенеровує
# нарахування тут же, а не чекає річного крона - інакше кадровик поставив би УБД і не побачив
# 14 днів у «Відсутностях». Частина полів живе в l10n_ua_hr_card, що залежить від цього
# модуля, тому перелік - імена, а не посилання на поля.
UA_LEAVE_FACT_FIELDS = {
    "ua_contract_kind", "ua_vacation_days_year", "ua_vacation_opening_balance", "ua_vacation_opening_date",
    "ua_disability_group", "birthday", "ua_war_disability", "ua_veteran", "ua_single_parent",
    "ua_special_leave_days", "ua_soc_child_disabled_child", "ua_child_ids", "company_id",
}

# Коди видів відсутності, за якими ведуться нарахування. Решта (SICK, UNPAID, MAT, STUDY,
# TRIP, CHILD_VAC, CHILD3, SICK_CARE) лишаються без нарахування: їх дає закон або лікар за
# фактом, а не з ліміту.
VAC = "VAC"
VAC_UBD = "VAC_UBD"
SOC_CHILD = "SOC_CHILD"
VAC_SPECIAL = "VAC_SPECIAL"
UA_ALLOC_CODES = (VAC, VAC_UBD, SOC_CHILD, VAC_SPECIAL)

TRANSITION_LABEL = "Коригування при переході"


def _age_on(birthday, on_date):
    if not birthday:
        return None
    return on_date.year - birthday.year - ((on_date.month, on_date.day) < (birthday.month, birthday.day))


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    ua_insurance_years = fields.Float("Страховий стаж, років", digits=(6, 2), groups="hr.group_hr_user",
                                      help="На дату початку хвороби. Визначає відсоток лікарняних (ст. 24 ЗУ 1105)")
    ua_sick_full = fields.Boolean("Лікарняні 100 % незалежно від стажу", groups="hr.group_hr_user",
                                  help="Пільгові категорії за ст. 24 ЗУ 1105")
    ua_sick_percent = fields.Float("Відсоток лікарняних", compute="_compute_ua_sick_percent", groups="hr.group_hr_user")

    @api.depends("ua_insurance_years", "ua_sick_full")
    def _compute_ua_sick_percent(self):
        for e in self:
            y = e.ua_insurance_years or 0.0
            e.ua_sick_percent = 100.0 if (e.ua_sick_full or y >= 8) else 70.0 if y >= 5 else 60.0 if y >= 3 else 50.0

    # -- Додаткові відпустки за Законом «Про відпустки» ---------------------------------------
    # ua_veteran (УБД) і ua_child_ids/ua_single_parent (сім'я) визначені в l10n_ua_hr_card, що
    # залежить від цього модуля (не навпаки) - формальної залежності тут немає, тож читаємо їх
    # через getattr. На практиці l10n_ua_card_ui встановлює обидва модулі разом.
    ua_war_disability = fields.Boolean("Особа з інвалідністю внаслідок війни", groups="hr.group_hr_user",
                                       help="Додаткова відпустка 14 днів за ст. 16-2 ЗУ «Про відпустки», як і для УБД")
    ua_special_leave_days = fields.Integer("Днів додаткової відпустки за особливий характер праці", default=0, groups="hr.group_hr_user",
                                           help="До 7 днів на рік: ненормований робочий день, робота за комп'ютером тощо (ст. 8 ЗУ «Про відпустки»)")
    ua_soc_child_disabled_child = fields.Boolean("Є дитина з інвалідністю", groups="hr.group_hr_user",
                                                 help="Підстава для соціальної відпустки за ст. 19 ЗУ «Про відпустки»")

    ua_soc_child_allocated = fields.Float("СОЦ_ДІТИ: нараховано (накопичено)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user",
                                          help="Сума нарахувань соціальної відпустки на дітей за всі роки; не згорає, переноситься без обмежень")
    ua_soc_child_last_year = fields.Integer("СОЦ_ДІТИ: рік останнього нарахування", compute="_compute_ua_soc_child_last_year", groups="hr.group_hr_user")

    @api.constrains("ua_special_leave_days")
    def _check_ua_special_leave_days(self):
        for e in self:
            if not (0 <= (e.ua_special_leave_days or 0) <= 7):
                raise ValidationError("Додаткова відпустка за особливий характер праці - від 0 до 7 днів на рік.")

    # -- норми на рік (живі, не зберігаються - завжди відображають поточне право) ---------------
    ua_vac_ubd_days_year = fields.Integer("УБД: днів на рік", compute="_compute_ua_vac_ubd_days_year", groups="hr.group_hr_user")
    ua_soc_child_days_year = fields.Integer("СОЦ_ДІТИ: днів на рік", compute="_compute_ua_soc_child_days_year", groups="hr.group_hr_user")
    ua_special_allocated = fields.Integer("ОСОБЛИВІ УМОВИ: днів на рік", compute="_compute_ua_special_allocated", groups="hr.group_hr_user")

    @api.depends("ua_war_disability")
    def _compute_ua_vac_ubd_days_year(self):
        for e in self:
            e.ua_vac_ubd_days_year = 14 if (getattr(e, "ua_veteran", False) or e.ua_war_disability) else 0

    def _ua_soc_child_grounds(self):
        """Кількість підстав ст. 19: двоє+ дітей до 15, дитина з інвалідністю, одинокий батько/мати."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        children = getattr(self, "ua_child_ids", [])
        young = sum(1 for c in children if c.birthday and _age_on(c.birthday, today) is not None and _age_on(c.birthday, today) < 15)
        grounds = 0
        if young >= 2:
            grounds += 1
        if self.ua_soc_child_disabled_child:
            grounds += 1
        if getattr(self, "ua_single_parent", False):
            grounds += 1
        return grounds

    @api.depends("ua_soc_child_disabled_child")
    def _compute_ua_soc_child_days_year(self):
        for e in self:
            grounds = e._ua_soc_child_grounds()
            e.ua_soc_child_days_year = 17 if grounds >= 2 else (10 if grounds == 1 else 0)

    @api.depends("ua_special_leave_days")
    def _compute_ua_special_allocated(self):
        for e in self:
            e.ua_special_allocated = max(0, min(e.ua_special_leave_days or 0, 7))

    # -- використано / залишок: читаються з рідних нарахувань -----------------------------------
    ua_vac_ubd_used = fields.Float("УБД: використано (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_vac_ubd_balance = fields.Float("УБД: залишок (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_soc_child_used = fields.Float("СОЦ_ДІТИ: використано (всі роки)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_soc_child_balance = fields.Float("СОЦ_ДІТИ: залишок (всі роки)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_special_used = fields.Float("ОСОБЛИВІ УМОВИ: використано (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")
    ua_special_balance = fields.Float("ОСОБЛИВІ УМОВИ: залишок (поточний рік)", compute="_compute_ua_leave_balances", digits=(6, 1), groups="hr.group_hr_user")

    # ===========================================================================================
    # Читання залишків із hr.leave.allocation
    # ===========================================================================================
    def _ua_leave_types(self):
        """{код виду роботи: hr.leave.type} для видів із нарахуванням. Один пошук на виклик."""
        types = self.env["hr.leave.type"].sudo().with_context(active_test=False).search(
            [("work_entry_type_id.code", "in", list(UA_ALLOC_CODES))])
        return {t.work_entry_type_id.code: t for t in types}

    def _ua_allocation_data(self, leave_type, on_date=None):
        """{employee: {'max': нараховано, 'taken': використано, 'left': залишок}} за один виклик.

        Рахує рідний hr.leave.type.get_allocation_data: він сам відкидає нарахування, чинність
        яких не покриває дату (УБД за минулий рік), і бере лише проведені відпустки - те саме,
        що робили старі обчислювані поля вручну.

        Для видів, що переносяться (соціальна на дітей), дата зсувається на найпізніше
        нарахування: якщо кадровик відкрив рік наперед, ці дні вже належать працівникові й
        мають бути в «нараховано»."""
        empty = {"max": 0.0, "taken": 0.0, "left": 0.0}
        out = {e: dict(empty) for e in self}
        # незбережена картка (форма створення) нарахувань ще не має - і не може мати
        saved = self.filtered(lambda e: bool(e._origin.id))
        if not leave_type or not saved:
            return out
        on_date = on_date or fields.Date.context_today(self)
        if leave_type.ua_alloc_basis == "year_carry":
            latest = self.env["hr.leave.allocation"].sudo().search(
                [("employee_id", "in", saved._origin.ids), ("holiday_status_id", "=", leave_type.id),
                 ("state", "=", "validate")], order="date_from desc", limit=1)
            if latest and latest.date_from > on_date:
                on_date = latest.date_from
        data = leave_type.sudo().get_allocation_data(saved._origin.sudo(), on_date)
        for employee in saved:
            rows = data.get(employee._origin.sudo(), [])
            info = rows[0][1] if rows else None
            out[employee] = {
                "max": info["max_leaves"] if info else 0.0,
                "taken": info["leaves_taken"] if info else 0.0,
                "left": info["remaining_leaves"] if info else 0.0,
            } if info else dict(empty)
        return out

    def _compute_ua_leave_balances(self):
        types = self._ua_leave_types()
        ubd = self._ua_allocation_data(types.get(VAC_UBD))
        soc = self._ua_allocation_data(types.get(SOC_CHILD))
        special = self._ua_allocation_data(types.get(VAC_SPECIAL))
        for e in self:
            e.ua_vac_ubd_used = round(ubd[e]["taken"], 1)
            e.ua_vac_ubd_balance = round(ubd[e]["left"], 1)
            e.ua_soc_child_allocated = round(soc[e]["max"], 1)
            e.ua_soc_child_used = round(soc[e]["taken"], 1)
            e.ua_soc_child_balance = round(soc[e]["left"], 1)
            e.ua_special_used = round(special[e]["taken"], 1)
            e.ua_special_balance = round(special[e]["left"], 1)

    def _compute_ua_vacation_balance(self):
        """Щорічна основна: залишок - це залишок рідних нарахувань, а не окрема арифметика.

        Поля оголошені в l10n_ua_payroll_rules (модуль без hr_holidays); щойно встановлено цей
        модуль, джерелом залишку стають hr.leave.allocation.

        «Накопичено» - усі нарахування, крім початкового залишку (тобто за правилом плюс
        коригування при переході), «використано» - проведені відпустки плюс дні, за які
        виплачено компенсацію при звільненні (вхід COMP_DAYS). Компенсація не зменшує саме
        нарахування: у рідному Odoo нарахування не буває від'ємним, а сам запис має лишитись
        читабельним - «за робочий рік 24 дні». Тому вона віднімається тут. Тотожність
        залишок = початковий + накопичено - використано тримається точно."""
        types = self._ua_leave_types()
        data = self._ua_allocation_data(types.get(VAC))
        today = fields.Date.context_today(self)
        opening = dict(self.env["hr.leave.allocation"].sudo()._read_group(
            [("employee_id", "in", self._origin.ids), ("holiday_status_id", "=", types[VAC].id),
             ("ua_source", "=", "opening"), ("state", "=", "validate")],
            groupby=["employee_id"], aggregates=["number_of_days:sum"])) if types.get(VAC) else {}
        for e in self:
            opening_days = opening.get(e._origin, 0.0)
            compensated = e._ua_vacation_compensated(today)
            e.ua_vacation_accrued = round(data[e]["max"] - opening_days, 1)
            e.ua_vacation_used = round(data[e]["taken"] + compensated, 1)
            e.ua_vacation_balance = round(data[e]["left"] - compensated, 1)

    def _compute_ua_soc_child_last_year(self):
        """Рік останнього нарахування СОЦ_ДІТИ = найпізніший рік серед нарахувань цього виду."""
        types = self._ua_leave_types()
        soc_type = types.get(SOC_CHILD)
        by_employee = {}
        if soc_type:
            groups = self.env["hr.leave.allocation"].sudo().with_context(active_test=False)._read_group(
                [("employee_id", "in", self._origin.ids), ("holiday_status_id", "=", soc_type.id),
                 ("state", "=", "validate")],
                groupby=["employee_id"], aggregates=["ua_period_start:max", "date_from:max"])
            for employee, period_max, date_max in groups:
                stamp = period_max or date_max
                by_employee[employee.id] = stamp.year if stamp else 0
        for e in self:
            e.ua_soc_child_last_year = by_employee.get(e._origin.id, 0)

    # ===========================================================================================
    # Правило нарахування: щорічна основна відпустка
    # ===========================================================================================
    def _ua_leave_opening_date(self):
        """Дата впровадження обліку відпусток: своя або компанії. До неї дні не нараховуються."""
        self.ensure_one()
        return self.ua_vacation_opening_date or self.sudo().company_id.ua_vacation_opening_date

    def _ua_employment_spans(self, on_date):
        """Відрізки роботи до on_date, дублікати версій із однаковими датами - один раз."""
        self.ensure_one()
        seen, spans = set(), []
        for v in self.sudo().version_ids:
            key = (v.contract_date_start, v.contract_date_end)
            if not v.contract_date_start or key in seen:
                continue
            seen.add(key)
            end = min(v.contract_date_end or on_date, on_date)
            if end >= v.contract_date_start:
                spans.append((v.contract_date_start, end))
        return sorted(spans)

    def _ua_work_years(self, on_date):
        """Робочі роки від дати прийняття: [start, end] по 365/366 днів (ст. 6 ЗУ «Про відпустки»).

        Робочий рік починається з дати прийняття, а не 1 січня. У разі повторного прийняття
        якір лишається на першому: відлік ведеться від найранішої версії контракту."""
        self.ensure_one()
        spans = self._ua_employment_spans(on_date)
        if not spans:
            return []
        hire, out, step = spans[0][0], [], 0
        while True:
            start = hire + relativedelta(years=step)
            if start > on_date:
                break
            out.append((start, hire + relativedelta(years=step + 1) - timedelta(days=1)))
            step += 1
        return out

    def _ua_vacation_accrual(self, on_date):
        """([(початок робочого року, нараховано)], разом) за щорічною основною відпусткою.

        Повністю відпрацьований і повністю відстежений робочий рік дає норму цілком (24 к.д.,
        26/30 при інвалідності, 31 неповнолітнім). Неповний - пропорційно: норма x календарні
        дні роботи / 365. Невикористане не згорає, тому кожен робочий рік лишається окремим
        нарахуванням без дати завершення чинності (ст. 10 ЗУ «Про відпустки»)."""
        self.ensure_one()
        spans = self._ua_employment_spans(on_date)
        if not spans:
            return [], 0.0
        opening = self._ua_leave_opening_date()
        norm = self.ua_vacation_days_year or 24
        raw, total = [], 0.0
        for year_start, year_end in self._ua_work_years(on_date):
            covered = 0
            for span_start, span_end in spans:
                start = max(span_start, year_start, opening) if opening else max(span_start, year_start)
                end = min(span_end, year_end)
                if end >= start:
                    covered += (end - start).days + 1
            if not covered:
                continue
            full = covered >= (year_end - year_start).days + 1
            days = float(norm) if full else norm * covered / 365.0
            raw.append([year_start, days, full])
            total += days
        if not raw:
            return [], 0.0
        # заокруглення до сотих робиться один раз, на підсумку: інакше поділ на робочі роки
        # сам собою з'їдав би по кілька сотих і залишок відрізнявся б від рахунку «однією
        # пропорцією за весь відпрацьований час»
        rows = [(year_start, round(days, 2)) for year_start, days, _full in raw]
        residual = round(round(total, 2) - sum(days for _y, days in rows), 2)
        if residual:
            for index in range(len(raw) - 1, -1, -1):
                if not raw[index][2]:
                    rows[index] = (rows[index][0], round(rows[index][1] + residual, 2))
                    break
        return rows, round(total, 2)

    def _ua_vacation_compensated(self, on_date):
        """Дні щорічної відпустки, за які вже виплачено компенсацію (вхід COMP_DAYS у проведених листках)."""
        self.ensure_one()
        if "hr.payslip.input" not in self.env:
            return 0.0
        opening = self._ua_leave_opening_date()
        domain = [("payslip_id.employee_id", "=", self.id), ("code", "=", "COMP_DAYS"),
                  ("payslip_id.state", "=", "done")]
        if opening:
            domain.append(("payslip_id.date_to", ">=", opening))
        return sum(self.env["hr.payslip.input"].sudo().search(domain).mapped("amount"))

    # ===========================================================================================
    # Генератор нарахувань
    # ===========================================================================================
    def _ua_alloc_domain(self, leave_type, source, period_start=None):
        domain = [("employee_id", "=", self.id), ("holiday_status_id", "=", leave_type.id),
                  ("ua_source", "=", source)]
        if period_start is not None:
            domain.append(("ua_period_start", "=", period_start))
        return domain

    def _ua_write_allocation(self, leave_type, source, period_start, days, date_from, date_to, label):
        """Створити або оновити одне нарахування. Ідемпотентно: ключ - (вид, джерело, період).

        Новий запис лишається в стані «На затвердження»: проводить їх генератор одним махом у
        кінці, бо кожне затвердження перераховує спожиті дні всього працівника."""
        self.ensure_one()
        Alloc = self.env["hr.leave.allocation"].sudo().with_context(
            active_test=False, mail_create_nolog=True, mail_notrack=True, tracking_disable=True)
        existing = Alloc.search(self._ua_alloc_domain(leave_type, source, period_start), limit=1)
        days = round(days, 2)
        if days <= 0:
            if existing:
                if existing.leaves_taken:
                    existing.write({"number_of_days": existing.leaves_taken})
                else:
                    existing.with_context(allocation_skip_state_check=True).unlink()
            return Alloc
        if not existing:
            return Alloc.create({
                "name": label, "employee_id": self.id, "holiday_status_id": leave_type.id,
                "number_of_days": days, "date_from": date_from, "date_to": date_to,
                "allocation_type": "regular", "ua_source": source, "ua_period_start": period_start,
            })
        changes = {}
        if abs(existing.number_of_days - days) >= 0.005:
            changes["number_of_days"] = days
        if existing.date_from != date_from:
            changes["date_from"] = date_from
        if existing.date_to != (date_to or False):
            changes["date_to"] = date_to or False
        if changes:
            existing.write(changes)
            # рідний _compute_description перезаписує назву після зміни днів - повертаємо свою
            existing.write({"name": label})
        elif existing.name != label:
            existing.write({"name": label})
        return existing if existing.state != "validate" else Alloc

    def _ua_drop_generated(self, leave_type, keep_keys):
        """Прибрати нарахування генератора, яких більше немає в плані (право зникло, рік відпав).

        Спершу звужуємо чинність до одного дня, і лише тоді видаляємо. Поки нарахування
        чинне, рідний розрахунок може тримати на ньому вже проведену відпустку, і тоді
        hr_holidays видалити його не дає. Знімати по одному не можна: після кожного видалення
        відпустка перечіплюється на наступне нарахування, і замість одного зайвого запису
        лишається їх кілька. Звужене нарахування відпустки вже не тримає - вона переходить на
        нарахування поточного плану, які покривають ті самі дати."""
        self.ensure_one()
        Alloc = self.env["hr.leave.allocation"].sudo().with_context(active_test=False)
        stale = Alloc.search([("employee_id", "=", self.id), ("holiday_status_id", "=", leave_type.id),
                              ("ua_source", "in", ["rule", "opening"])]).filtered(
            lambda a: (a.ua_source, a.ua_period_start) not in keep_keys)
        if not stale:
            return
        for alloc in stale:
            if alloc.date_to != alloc.date_from:
                alloc.write({"date_to": alloc.date_from})
        try:
            with self.env.cr.savepoint():
                stale.with_context(allocation_skip_state_check=True).unlink()
            return
        except (UserError, ValidationError):
            pass
        # нарахування все одно тримає проведену відпустку: лишаємо його рівно на використані
        # дні, щоб залишок від нього був нульовий, і пишемо про це в журнал
        for alloc in stale.exists():
            taken = alloc.leaves_taken
            if taken:
                alloc.write({"number_of_days": taken})
                _logger.info("Відпустки: нарахування %s (%s) лишено на %s використаних днів - "
                             "його не можна прибрати, поки на ньому висить проведена відпустка.",
                             alloc.id, self.name, taken)
            else:
                alloc.with_context(allocation_skip_state_check=True).unlink()

    def _ua_sync_vacation(self, leave_type, on_date):
        """Щорічна основна: залишок на дату впровадження + нарахування за кожен робочий рік.

        Дата завершення чинності у всіх порожня: невикористані дні не згорають (ст. 10 ЗУ
        «Про відпустки»). Дата початку - не раніше дати впровадження обліку: відпустка,
        оформлена до неї, вже врахована в початковому залишку і другий раз не списується."""
        self.ensure_one()
        if not leave_type:
            return self.env["hr.leave.allocation"]
        rows, _accrued = self._ua_vacation_accrual(on_date)
        opening_date = self._ua_leave_opening_date()
        spans = self._ua_employment_spans(on_date)
        first_day = opening_date or (spans[0][0] if spans else on_date)
        opening_balance = self.ua_vacation_opening_balance if opening_date else 0.0

        plan = []
        if opening_balance > 0:
            plan.append(("opening", first_day, first_day, opening_balance,
                         "Залишок відпустки на %s" % first_day.strftime("%d.%m.%Y")))
        for year_start, days in rows:
            date_from = max(year_start, opening_date) if opening_date else year_start
            plan.append(("rule", year_start, date_from, days,
                         "Щорічна відпустка за робочий рік з %s" % year_start.strftime("%d.%m.%Y")))

        keep, fresh = set(), self.env["hr.leave.allocation"]
        for source, period_start, date_from, days, label in plan:
            fresh |= self._ua_write_allocation(leave_type, source, period_start, days, date_from, False, label)
            if days > 0:
                keep.add((source, period_start))
        self._ua_drop_generated(leave_type, keep)
        return fresh

    def _ua_sync_year_allocations(self, leave_type, days_per_year, on_date, carry):
        """Відпустки за календарний рік: УБД і особливі умови (не переносяться), соціальна на дітей (переноситься).

        Ті, що не переносяться, обмежені 31 грудня: рідний розрахунок сам перестає їх рахувати
        наступного року (ст. 16-2 ЗУ «Про відпустки»). Соціальна на дітей лишається без дати
        завершення - вона переноситься без обмежень."""
        self.ensure_one()
        if not leave_type:
            return self.env["hr.leave.allocation"]
        spans = self._ua_employment_spans(on_date)
        if not spans:
            self._ua_drop_generated(leave_type, set())
            return self.env["hr.leave.allocation"]
        opening = self._ua_leave_opening_date()
        start_day = max(opening, spans[0][0]) if opening else spans[0][0]
        keep, fresh = set(), self.env["hr.leave.allocation"]
        for year in range(start_day.year, on_date.year + 1):
            period_start = date(year, 1, 1)
            date_from = max(period_start, start_day)
            date_to = False if carry else date(year, 12, 31)
            label = "%s за %d рік" % (leave_type.name, year)
            fresh |= self._ua_write_allocation(leave_type, "rule", period_start, days_per_year,
                                               date_from, date_to, label)
            if days_per_year > 0:
                keep.add(("rule", period_start))
        self._ua_drop_generated(leave_type, keep)
        return fresh

    def _ua_ensure_leave_allocations(self, on_date=None):
        """Привести hr.leave.allocation у відповідність до права працівника на відпустки.

        Ідемпотентний: другий виклик на ту саму дату нічого не змінює. Запускається річним
        кроном, зміною будь-якого поля-підстави (UA_LEAVE_FACT_FIELDS), зміною версії контракту
        і руками з картки.

        on_date у майбутньому дозволено для відпусток за календарний рік (крон у січні наперед
        відкриває рік). Щорічна основна нараховується не далі сьогодні: днів, які ще не
        відпрацьовані, у людини немає."""
        today = fields.Date.context_today(self)
        on_date = on_date or today
        types = self._ua_leave_types()
        fresh = self.env["hr.leave.allocation"].sudo()
        for employee in self.sudo():
            # ЦПХ і ФОП - не працівники за трудовим договором: відпустка їм не належить (ст. 2 ЗУ «Про відпустки»)
            if employee.ua_contract_kind != "employment":
                for code in UA_ALLOC_CODES:
                    if types.get(code):
                        employee._ua_drop_generated(types[code], set())
                continue
            fresh |= employee._ua_sync_vacation(types.get(VAC), min(on_date, today))
            fresh |= employee._ua_sync_year_allocations(types.get(VAC_UBD), employee.ua_vac_ubd_days_year, on_date, carry=False)
            fresh |= employee._ua_sync_year_allocations(types.get(SOC_CHILD), employee.ua_soc_child_days_year, on_date, carry=True)
            fresh |= employee._ua_sync_year_allocations(types.get(VAC_SPECIAL), employee.ua_special_allocated, on_date, carry=False)
        if fresh:
            fresh.filtered(lambda a: a.state != "validate").action_approve()
        self.invalidate_recordset()
        return True

    def _ua_write_transition_adjustment(self, leave_type, delta):
        """Дотягнути залишок до значення, яке було до переходу на рідні нарахування.

        Плюс - окреме нарахування «Коригування при переході»: видно в «Відсутностях», видно,
        що це не правило, а перенесення старого числа. Мінус - зменшення власних нарахувань
        з найновішого: від'ємних нарахувань у рідному Odoo не буває.
        Використані дні не чіпаються: нижче за них нарахування не опускається."""
        self.ensure_one()
        Alloc = self.env["hr.leave.allocation"].sudo().with_context(
            active_test=False, mail_create_nolog=True, mail_notrack=True, tracking_disable=True)
        if delta > 0:
            spans = self._ua_employment_spans(fields.Date.context_today(self))
            date_from = self._ua_leave_opening_date() or (spans[0][0] if spans else fields.Date.context_today(self))
            existing = Alloc.search(self._ua_alloc_domain(leave_type, "transition"), limit=1)
            days = round((existing.number_of_days if existing else 0.0) + delta, 2)
            period_start = existing.ua_period_start if existing else date_from
            alloc = self._ua_write_allocation(leave_type, "transition", period_start, days,
                                              existing.date_from if existing else date_from,
                                              False, TRANSITION_LABEL)
            if alloc:
                alloc.action_approve()
            return True
        left = round(-delta, 2)
        allocations = Alloc.search([("employee_id", "=", self.id), ("holiday_status_id", "=", leave_type.id),
                                    ("ua_source", "in", ["transition", "rule", "opening"])],
                                   order="date_from desc, id desc")
        for alloc in allocations:
            if left <= 0:
                break
            room = round(max(alloc.number_of_days - alloc.leaves_taken, 0.0), 2)
            cut = min(room, left)
            if cut <= 0:
                continue
            alloc.write({"number_of_days": round(alloc.number_of_days - cut, 2)})
            alloc.write({"notes": "%s: знято %.1f дн." % (TRANSITION_LABEL, cut)})
            left = round(left - cut, 2)
        if left > 0:
            _logger.warning("Перехід відпусток: %s, %s - не вдалося зняти %.1f дн., "
                            "вони вже використані відпустками.", self.name, leave_type.name, left)
        return True

    def _ua_check_allocation_rights(self):
        """Генератор пише нарахування через sudo(), тому право перевіряє публічна
        обгортка: перебудувати відпустки може кадровик (і крон, що йде від системи).
        Внутрішні виклики (зміна картки, договору, компанії) сюди не заходять."""
        if not (self.env.su or self.env.user.has_group("hr.group_hr_user")):
            raise AccessError(self.env._("Перебудувати нарахування відпусток може лише кадровик."))
        self.check_access("write")

    def ua_ensure_leave_allocations(self, on_date=None):
        """Публічна обгортка: Odoo не дає викликати методи з підкресленням через execute_kw."""
        self._ua_check_allocation_rights()
        if isinstance(on_date, str):
            on_date = fields.Date.to_date(on_date)
        return self._ua_ensure_leave_allocations(on_date=on_date)

    def _ua_ensure_allocations(self, year=None):
        """Стара назва: рік замість дати. Лишається для крона і скриптів перевірки."""
        on_date = date(year, 12, 31) if year else None
        return self._ua_ensure_leave_allocations(on_date=on_date)

    def ua_ensure_allocations(self, year=None):
        self._ua_check_allocation_rights()
        return self._ua_ensure_allocations(year=year)

    # ===========================================================================================
    # Перегенерація за зміною підстав
    # ===========================================================================================
    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("ua_skip_leave_allocations"):
            return res
        if UA_LEAVE_FACT_FIELDS & set(vals):
            self.filtered("active").with_context(ua_skip_leave_allocations=True)._ua_ensure_leave_allocations()
        return res

    def unlink(self):
        """Нарахування, виписані генератором, не мають тримати картку: вони похідні від неї.

        Рідний ondelete на hr.leave.allocation - restrict, тому без цього видалення картки
        падало б із «запис використовується». Нарахування, заведені руками, теж прибираємо:
        без працівника вони не мають сенсу, а рідний код не дає йому зникнути."""
        allocations = self.env["hr.leave.allocation"].sudo().with_context(
            active_test=False, allocation_skip_state_check=True).search([("employee_id", "in", self.ids)])
        if allocations:
            allocations.unlink()
        return super().unlink()
