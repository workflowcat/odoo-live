"""Нарахування днів відпустки на рідних hr.leave.allocation.

Перевіряється правило, а не екран: скільки днів отримує працівник за Законом «Про відпустки»
і як рідний hr_holidays ці дні списує. Усі числа в коментарях пораховані вручну, щоб падіння
тесту було зрозумілим без запуску Odoo.

Дати в тестах фіксовані (прийняття 10.03.2025, розрахунок на 31.08.2026), тому результат не
залежить від дня прогону: генератор викликається з явною датою.
"""
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

HIRE = date(2025, 3, 10)
ON_DATE = date(2026, 8, 31)


@tagged("post_install", "-at_install", "ua_leaves")
class TestUaLeaveAllocations(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.company.resource_calendar_id
        assert cls.calendar, "у компанії немає графіка роботи"
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        cls.types = {}
        for code in ("VAC", "VAC_UBD", "SOC_CHILD", "VAC_SPECIAL", "UNPAID", "SICK"):
            leave_type = cls.env["hr.leave.type"].search(
                [("work_entry_type_id.code", "=", code)], limit=1)
            assert leave_type, "немає виду відсутності з кодом %s" % code
            cls.types[code] = leave_type
        # облік відпусток ведеться з дати прийняття: окремої дати впровадження немає
        cls.company.ua_vacation_opening_date = False

    # ---- будівельні блоки ------------------------------------------------------------------
    def _employee(self, name, start=HIRE, end=False, **values):
        employee = self.env["hr.employee"].create(dict({
            "name": name,
            "company_id": self.company.id,
            "ua_contract_kind": "employment",
            "resource_calendar_id": self.calendar.id,
        }, **values))
        employee.version_id.with_context(sync_contract_dates=True).write({
            "wage": 20000, "date_version": start, "contract_date_start": start,
            "contract_date_end": end, "resource_calendar_id": self.calendar.id,
            "struct_id": self.structure.id if self.structure else False,
        })
        employee._ua_ensure_leave_allocations(ON_DATE)
        return employee

    def _allocations(self, employee, code):
        return self.env["hr.leave.allocation"].search([
            ("employee_id", "=", employee.id),
            ("holiday_status_id", "=", self.types[code].id),
        ], order="date_from")

    def _days(self, employee, code):
        """Нараховано днів за видом - сума затверджених нарахувань."""
        allocations = self._allocations(employee, code)
        self.assertTrue(all(a.state == "validate" for a in allocations),
                        "генератор лишив незатверджене нарахування: %s" % allocations.mapped("state"))
        return round(sum(allocations.mapped("number_of_days")), 2)

    def _leave(self, employee, code, date_from, date_to):
        leave = self.env["hr.leave"].with_context(
            mail_notrack=True, mail_create_nolog=True, leave_skip_state_check=True,
        ).create({
            "employee_id": employee.id, "holiday_status_id": self.types[code].id,
            "request_date_from": date_from, "request_date_to": date_to,
        })
        leave.sudo().action_approve()
        return leave

    # ---- 1. щорічна основна за робочий рік --------------------------------------------------
    def test_01_work_year_proportional(self):
        """Прийнято 10.03.2025, рахуємо на 31.08.2026.

        Робочий рік перший: 10.03.2025 - 09.03.2026, відпрацьований повністю -> 24 к.д.
        Робочий рік другий: 10.03.2026 - 09.03.2027, відпрацьовано 10.03 - 31.08.2026.
          березень 22 + квітень 30 + травень 31 + червень 30 + липень 31 + серпень 31 = 175 днів
          24 x 175 / 365 = 11,5068... -> 11,51
        Разом 24 + 11,51 = 35,51 дня."""
        employee = self._employee("Відпустка: робочий рік")
        allocations = self._allocations(employee, "VAC")
        self.assertEqual(len(allocations), 2, "має бути по нарахуванню на кожен робочий рік")
        self.assertEqual(allocations[0].number_of_days, 24.0, "повний робочий рік дає норму цілком")
        self.assertAlmostEqual(allocations[1].number_of_days, 11.51, places=2)
        self.assertEqual(self._days(employee, "VAC"), 35.51)
        self.assertFalse(allocations[0].date_to, "невикористані дні щорічної відпустки не згорають")

    def test_02_work_year_starts_at_hire_not_january(self):
        """Робочий рік починається з дати прийняття, а не 1 січня (ст. 6 ЗУ «Про відпустки»)."""
        employee = self._employee("Відпустка: межі робочого року")
        allocations = self._allocations(employee, "VAC")
        self.assertEqual(allocations[0].ua_period_start, HIRE)
        self.assertEqual(allocations[1].ua_period_start, date(2026, 3, 10))

    def test_03_leave_counts_calendar_days(self):
        """Заявка на 14 к.д. списує 14 днів, а не 10 робочих: відпустка дається в календарних."""
        employee = self._employee("Відпустка: календарні дні")
        leave = self._leave(employee, "VAC", "2026-08-03", "2026-08-16")
        self.assertEqual(leave.number_of_days, 14.0)
        employee.invalidate_recordset()
        # 35,51 - 14 = 21,51
        self.assertAlmostEqual(employee.ua_vacation_balance, 21.5, places=1)

    def test_04_request_above_balance_is_refused(self):
        """Понад залишок рідна перевірка hr_holidays не пропускає."""
        employee = self._employee("Відпустка: понад залишок")
        with self.assertRaises(ValidationError):
            # 40 к.д. проти 35,51 нарахованих
            self._leave(employee, "VAC", "2026-07-01", "2026-08-09")

    # ---- 2. додаткова УБД: 14 днів на рік, без переносу ------------------------------------
    def test_05_ubd_fourteen_days_per_calendar_year(self):
        """УБД - 14 к.д. за календарний рік (ст. 16-2 ЗУ «Про відпустки»)."""
        employee = self._employee("УБД: 14 днів", ua_war_disability=True)
        allocations = self._allocations(employee, "VAC_UBD")
        self.assertEqual(set(allocations.mapped("number_of_days")), {14.0})
        self.assertEqual(employee.ua_vac_ubd_days_year, 14)
        self.assertEqual(employee.ua_vac_ubd_balance, 14.0)

    def test_06_ubd_does_not_carry_over(self):
        """Нарахування УБД обмежене 31 грудня: минулорічні дні в залишок не входять.

        Прийнято 10.03.2025 -> нарахування 2025 і 2026 років по 14 днів, разом 28.
        Залишок на 31.08.2026 - лише 14: рік 2025 уже закритий."""
        employee = self._employee("УБД: без переносу", ua_war_disability=True)
        self.assertEqual(self._days(employee, "VAC_UBD"), 28.0)
        for allocation in self._allocations(employee, "VAC_UBD"):
            self.assertEqual(allocation.date_to, date(allocation.ua_period_start.year, 12, 31))
        self.assertEqual(employee.ua_vac_ubd_balance, 14.0)

    # ---- 3. соціальна на дітей: 10 або 17 днів, переноситься --------------------------------
    def test_07_soc_child_ten_days_one_ground(self):
        """Одна підстава ст. 19 (дитина з інвалідністю) - 10 к.д. на рік."""
        employee = self._employee("Соцвідпустка: 10 днів", ua_soc_child_disabled_child=True)
        self.assertEqual(employee.ua_soc_child_days_year, 10)
        # роки 2025 і 2026 по 10 днів, переносяться без обмежень -> 20
        self.assertEqual(self._days(employee, "SOC_CHILD"), 20.0)
        self.assertEqual(employee.ua_soc_child_balance, 20.0)
        for allocation in self._allocations(employee, "SOC_CHILD"):
            self.assertFalse(allocation.date_to, "соціальна відпустка на дітей переноситься")

    def test_08_soc_child_seventeen_days_two_grounds(self):
        """Дві підстави (дитина з інвалідністю + одинока мати) - 17 к.д. на рік."""
        employee = self._employee("Соцвідпустка: 17 днів", ua_soc_child_disabled_child=True,
                                  ua_single_parent=True)
        self.assertEqual(employee.ua_soc_child_days_year, 17)
        self.assertEqual(self._days(employee, "SOC_CHILD"), 34.0)     # 17 x два роки
        self.assertEqual(employee.ua_soc_child_balance, 34.0)

    # ---- 4. початковий залишок і перенесення обліку -----------------------------------------
    def test_09_opening_balance_becomes_allocation(self):
        """Залишок на дату впровадження стає окремим нарахуванням, накопичення - з тієї ж дати.

        Дата впровадження 01.01.2026, залишок 9 днів. Відпрацьовано 01.01 - 31.08.2026 = 243 дні.
        Робочий рік 10.03.2025 - 09.03.2026: покрито 01.01 - 09.03.2026 = 68 днів -> 24 x 68/365 = 4,47
        Робочий рік 10.03.2026 - 09.03.2027: покрито 10.03 - 31.08.2026 = 175 днів -> 24 x 175/365 = 11,51
        Разом нараховано 15,98; залишок 9 + 15,98 = 24,98."""
        employee = self._employee("Відпустка: початковий залишок",
                                  ua_vacation_opening_date=date(2026, 1, 1),
                                  ua_vacation_opening_balance=9.0)
        employee._ua_ensure_leave_allocations(ON_DATE)
        opening = self._allocations(employee, "VAC").filtered(lambda a: a.ua_source == "opening")
        self.assertEqual(len(opening), 1)
        self.assertEqual(opening.number_of_days, 9.0)
        self.assertEqual(opening.date_from, date(2026, 1, 1))
        self.assertAlmostEqual(self._days(employee, "VAC"), 24.98, places=2)
        employee.invalidate_recordset()
        self.assertAlmostEqual(employee.ua_vacation_accrued, 16.0, places=1)
        self.assertAlmostEqual(employee.ua_vacation_balance, 25.0, places=1)

    def test_10_generator_is_idempotent(self):
        """Другий і третій виклики на ту саму дату нічого не додають."""
        employee = self._employee("Відпустка: ідемпотентність", ua_war_disability=True,
                                  ua_soc_child_disabled_child=True)
        before = {code: (len(self._allocations(employee, code)), self._days(employee, code))
                  for code in ("VAC", "VAC_UBD", "SOC_CHILD")}
        employee._ua_ensure_leave_allocations(ON_DATE)
        employee._ua_ensure_leave_allocations(ON_DATE)
        after = {code: (len(self._allocations(employee, code)), self._days(employee, code))
                 for code in ("VAC", "VAC_UBD", "SOC_CHILD")}
        self.assertEqual(before, after)

    # ---- 5. норма днів за станом здоров'я і віком --------------------------------------------
    def test_11_disability_group_three_gets_26_days(self):
        """III група інвалідності - 26 к.д. на рік (ст. 6 ЗУ «Про відпустки»).

        Повний робочий рік 26 + неповний 26 x 175/365 = 12,47 -> разом 38,47."""
        employee = self._employee("Відпустка: III група", ua_disability_group="3")
        self.assertEqual(employee.ua_vacation_days_year, 26)
        self.assertEqual(self._allocations(employee, "VAC")[0].number_of_days, 26.0)
        self.assertAlmostEqual(self._days(employee, "VAC"), 38.47, places=2)

    def test_12_disability_group_two_gets_30_days(self):
        """I і II група - 30 к.д. на рік."""
        employee = self._employee("Відпустка: II група", ua_disability_group="2")
        self.assertEqual(employee.ua_vacation_days_year, 30)
        self.assertEqual(self._allocations(employee, "VAC")[0].number_of_days, 30.0)

    def test_13_special_conditions_days(self):
        """Додаткова за особливий характер праці - скільки записано, але не більше 7 (ст. 8)."""
        employee = self._employee("Відпустка: особливі умови", ua_special_leave_days=4)
        self.assertEqual(employee.ua_special_allocated, 4)
        self.assertEqual(employee.ua_special_balance, 4.0)
        self.assertEqual(set(self._allocations(employee, "VAC_SPECIAL").mapped("number_of_days")), {4.0})

    # ---- 6. кому відпустка не належить -------------------------------------------------------
    def test_14_gph_contractor_gets_nothing(self):
        """Виконавець за договором ЦПХ - не працівник: нарахувань немає (ст. 2 ЗУ «Про відпустки»)."""
        employee = self._employee("ЦПХ: без відпустки", ua_contract_kind="gph",
                                  ua_war_disability=True, ua_soc_child_disabled_child=True)
        for code in ("VAC", "VAC_UBD", "SOC_CHILD", "VAC_SPECIAL"):
            self.assertFalse(self._allocations(employee, code), "ЦПХ отримав нарахування %s" % code)
        self.assertEqual(employee.ua_vacation_balance, 0.0)
        self.assertEqual(employee.ua_soc_child_balance, 0.0)

    def test_15_fop_contractor_gets_nothing(self):
        """ФОП-підрядник - так само без нарахувань."""
        employee = self._employee("ФОП: без відпустки", ua_contract_kind="fop")
        self.assertFalse(self._allocations(employee, "VAC"))
        self.assertEqual(employee.ua_vacation_balance, 0.0)

    def test_16_switching_to_contract_removes_allocations(self):
        """Переведення працівника на ЦПХ прибирає нарахування, і навпаки - повертає."""
        employee = self._employee("Відпустка: зміна виду відносин")
        self.assertTrue(self._allocations(employee, "VAC"))
        employee.write({"ua_contract_kind": "gph"})
        self.assertFalse(self._allocations(employee, "VAC"))
        employee.write({"ua_contract_kind": "employment"})
        self.assertTrue(self._allocations(employee, "VAC"))

    # ---- 7. види без нарахування -------------------------------------------------------------
    def test_17_unpaid_and_sick_need_no_allocation(self):
        """Лікарняний і відпустка без збереження нарахування не потребують."""
        self.assertFalse(self.types["SICK"].requires_allocation)
        self.assertFalse(self.types["UNPAID"].requires_allocation)
        employee = self._employee("Без нарахування: лікарняний")
        leave = self._leave(employee, "SICK", "2026-08-10", "2026-08-19")
        self.assertEqual(leave.state, "validate")
        self.assertFalse(self._allocations(employee, "SICK"))

    def test_18_ubd_leave_consumes_only_its_own_allocation(self):
        """Відпустка УБД списується з нарахування УБД і не чіпає щорічну."""
        employee = self._employee("УБД: списання", ua_war_disability=True)
        vacation_before = self._days(employee, "VAC")
        self._leave(employee, "VAC_UBD", "2026-08-03", "2026-08-12")      # 10 к.д.
        employee.invalidate_recordset()
        self.assertEqual(employee.ua_vac_ubd_used, 10.0)
        self.assertEqual(employee.ua_vac_ubd_balance, 4.0)
        self.assertEqual(self._days(employee, "VAC"), vacation_before)
