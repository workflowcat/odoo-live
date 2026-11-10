"""Еталонні сценарії нарахування як юніт-тести.

Джерело очікуваних чисел - golden/scenarios.json (той самий набір, що його рахував
scripts/payroll_check.py через JSON-RPC на живому стенді). Тут усе будується в
транзакції тесту через ORM: компанія, план рахунків, індекси цін, працівник, версія
контракту, історія заробітку, відпустки, листок.

Один сценарій - один метод тесту, тому в звіті падіння видно поіменно.
"""
import calendar
import json
import logging
import os
from collections import defaultdict

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)

MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(MODULE_DIR, "golden", "scenarios.json"), encoding="utf-8") as fh:
    GOLDEN = json.load(fh)
SCENARIOS = GOLDEN["scenarios"]

# Копійка: усі еталони заокруглені до двох знаків, тож поріг - пів копійки.
TOLERANCE = 0.005

# Робочі дні місяців для історії заробітку (середня за 12 місяців і за два місяці).
WORK_DAYS = {(2025, 8): 21, (2025, 9): 22, (2025, 10): 23, (2025, 11): 20, (2025, 12): 23,
             (2026, 1): 21, (2026, 2): 20, (2026, 3): 22, (2026, 4): 22, (2026, 5): 20,
             (2026, 6): 22, (2026, 7): 23, (2026, 8): 21}

# Тестові індекси споживчих цін 2026 року: лютий і березень дають наростаючий 103,1 %
# (поріг 103 % перевищено), серпень навмисно великий - індекс місяця листка не можна
# застосовувати до цього ж листка. Це не дані Держстату, а числа сценаріїв 17, 27, 28.
TEST_CPI = {2: 101.5, 3: 101.6, 8: 110.0}
TEST_CPI_YEAR = 2026
TEST_CPI_MONTHS = range(1, 9)

# Ці коди навмисно не проводяться: підсумки листка і аванс, уже проведений при виплаті.
NO_MOVE_CODES = {"GROSS", "NET", "ADV_PAID"}

DEFAULT_START = "2026-01-01"
REHIRE_FIRST_START = "2026-01-01"
REHIRE_FIRST_END = "2026-05-31"
REHIRE_SECOND_START = "2026-08-17"
# Резидент Дія Сіті з червня 2025: ставки Дія Сіті діють з липня 2025, тобто в місяці кожного сценарію.
DIIA_CITY_SINCE = "2025-06-10"


@tagged("post_install", "-at_install", "ua_golden")
class TestGoldenScenarios(TransactionCase):
    """Кожен сценарій будується з нуля; тести не залежать один від одного."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls._setup_company()
        cls._setup_cpi()
        cls.structure = cls.env["hr.payroll.structure"].search([("code", "=", "UA_SALARY")], limit=1)
        assert cls.structure, "немає структури UA_SALARY: модуль l10n_ua_payroll_rules не встановлений"
        cls.calendar = cls.company.resource_calendar_id
        assert cls.calendar, "у компанії немає графіка роботи"

    # ---- підготовка компанії --------------------------------------------------------
    @classmethod
    def _setup_company(cls):
        """Країна UA до плану рахунків, потім план ua_psbo і короткі коди (92, 661, 6411)."""
        ukraine = cls.env.ref("base.ua")
        if cls.company.country_id != ukraine:
            cls.company.country_id = ukraine
        if cls.company.chart_template != "ua_psbo":
            cls.env["account.chart.template"].try_loading("ua_psbo", cls.company, install_demo=False)
        cls.company.invalidate_recordset()
        # Odoo доповнює коди нулями (92 -> 920000); hooks модуля l10n_ua_chart повертає
        # короткі коди з шаблону - еталон проводок написаний саме в них.
        from odoo.addons.l10n_ua_chart.hooks import _short_codes
        _short_codes(cls.env)
        cls.env["account.account"].invalidate_model(["code"])

    @classmethod
    def _setup_cpi(cls):
        cpi = cls.env["ua.cpi.index"].sudo()
        for month in TEST_CPI_MONTHS:
            value = TEST_CPI.get(month, 100.0)
            row = cpi.search([("year", "=", TEST_CPI_YEAR), ("month", "=", month)], limit=1)
            if row:
                row.write({"value": value, "published_on": False})
            else:
                cpi.create({"year": TEST_CPI_YEAR, "month": month, "value": value})

    # ---- побудова сценарію ----------------------------------------------------------
    def _employee(self, scenario):
        setup = scenario["setup"]
        start = setup.get("start") or DEFAULT_START
        end = setup.get("end") or False
        index_base = setup.get("index_base")
        values = {
            "name": "Еталон %02d" % scenario["id"],
            "company_id": self.company.id,
            "ua_rnokpp": "30000000%02d" % scenario["id"],
            "ua_main_job": True,
            "ua_psp": "none",
            "ua_esv_category": "standard",
            "ua_contract_kind": "employment",
            "ua_fte": "1",
            "ua_insurance_years": setup.get("years", 0),
            "ua_index_off": not index_base,
            "ua_index_base": index_base or False,
            "ua_index_paid_month": False,
            "resource_calendar_id": self.calendar.id,
        }
        values.update(scenario["employee"])
        employee = self.env["hr.employee"].create(values)
        version = employee.version_id
        wage = scenario["wage"]
        if setup.get("rehire"):
            # Одна картка, дві версії: звільнення 31 травня і повторне прийняття 17 серпня.
            version.with_context(sync_contract_dates=True).write({
                "wage": wage, "contract_date_start": REHIRE_FIRST_START, "contract_date_end": REHIRE_FIRST_END,
                "struct_id": self.structure.id, "resource_calendar_id": self.calendar.id,
            })
            version = self.env["hr.version"].with_context(sync_contract_dates=True).create({
                "employee_id": employee.id, "date_version": REHIRE_SECOND_START,
                "contract_date_start": REHIRE_SECOND_START, "contract_date_end": False,
                "wage": wage, "struct_id": self.structure.id, "resource_calendar_id": self.calendar.id,
            })
        else:
            version.with_context(sync_contract_dates=True).write({
                "wage": wage, "date_version": start,
                "contract_date_start": start, "contract_date_end": end,
                "struct_id": self.structure.id, "resource_calendar_id": self.calendar.id,
            })
        if setup.get("history"):
            self._earnings_history(employee, setup["history"], setup.get("history_mil", 0))
        # нарахування днів відпустки мають існувати до заявки: рідна перевірка hr_holidays
        # не проводить відпустку без нарахування
        employee.sudo()._ua_ensure_leave_allocations()
        for code, date_from, date_to in setup.get("leaves", []):
            self._leave(employee, code, date_from, date_to)
        return employee, version

    def _earnings_history(self, employee, gross, on_service=0):
        """12 місяців до періоду листка: серпень 2025 - липень 2026.

        `on_service` останніх місяців людина була на військовій службі: заробітку немає,
        усі календарні дні виключено (п. 4 Порядку 100)."""
        history = self.env["ua.earnings.history"].sudo()
        for step in range(12):
            year, month = (2025, 8 + step) if 8 + step <= 12 else (2026, 8 + step - 12)
            serving = step >= 12 - on_service
            history.create({
                "employee_id": employee.id,
                "month": "%d-%02d-01" % (year, month),
                "gross": 0.0 if serving else gross,
                "work_days": 0.0 if serving else WORK_DAYS.get((year, month), 21),
                "excluded_days": calendar.monthrange(year, month)[1] if serving else 0,
            })

    def _leave(self, employee, code, date_from, date_to):
        leave_type = self.env["hr.leave.type"].search([("work_entry_type_id.code", "=", code)], limit=1)
        self.assertTrue(leave_type, "немає виду відсутності з кодом %s" % code)
        leave = self.env["hr.leave"].with_context(
            mail_notrack=True, mail_create_nolog=True, leave_skip_state_check=True,
        ).create({
            "employee_id": employee.id,
            "holiday_status_id": leave_type.id,
            "request_date_from": date_from,
            "request_date_to": date_to,
        })
        leave.sudo().action_approve()
        return leave

    def _payslip(self, scenario, employee, version):
        period = scenario["period"]
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id,
            "date_from": period[0],
            "date_to": period[1],
            "struct_id": self.structure.id,
            "name": employee.name,
            "company_id": self.company.id,
        })
        slip.onchange_employee()          # кнопка OCA: контракт, відпрацьовані дні, рядки входів
        for code, amount in scenario["inputs"].items():
            line = slip.input_line_ids.filtered(lambda r, c=code: r.code == c)
            if line:
                line.amount = amount
            else:
                self.env["hr.payslip.input"].create({
                    "payslip_id": slip.id, "code": code, "name": code,
                    "amount": amount, "contract_id": version.id,
                })
        slip.compute_sheet()
        return slip

    # ---- звірка ---------------------------------------------------------------------
    def _check_lines(self, scenario, slip):
        totals = {line.code: round(line.total, 2) for line in slip.line_ids}
        worked = [(w.code, w.number_of_days) for w in slip.worked_days_line_ids]
        wrong = []
        for code, expected in scenario["expect"].items():
            got = totals.get(code, 0.0 if expected == 0 else None)
            if got is None or abs(got - expected) >= TOLERANCE:
                wrong.append("%s = %s, очікували %s" % (code, got, expected))
        self.assertFalse(
            wrong,
            "сценарій %s «%s»: %s | рядки листка: %s | відпрацьовано: %s"
            % (scenario["id"], scenario["title"], "; ".join(wrong), totals, worked),
        )

    def _check_moves(self, scenario, slip):
        slip.action_payslip_done()
        move = slip.move_id
        self.assertTrue(move, "сценарій %s: листок підтверджено, але проводки немає" % scenario["id"])
        got = defaultdict(float)
        for line in move.line_ids:
            code = line.account_id.with_company(self.company).code or ""
            for expected in scenario["moves"]:
                prefix = expected["account"]
                # порівняння за префіксом: 92 == 920000, але 92 != 921
                if code.startswith(prefix) and (len(code) == len(prefix) or not code[len(prefix):].strip("0")):
                    got[(expected["side"], prefix)] += line.debit if expected["side"] == "Дт" else line.credit
        wrong = []
        for expected in scenario["moves"]:
            key = (expected["side"], expected["account"])
            amount = round(got.get(key, 0.0), 2)
            if abs(amount - expected["amount"]) >= TOLERANCE:
                wrong.append("%s%s = %s, очікували %s" % (key[0], key[1], amount, expected["amount"]))
        balance = round(sum(move.line_ids.mapped("debit")) - sum(move.line_ids.mapped("credit")), 2)
        if balance:
            wrong.append("проводка не збалансована: %s" % balance)
        self.assertFalse(
            wrong,
            "сценарій %s «%s», проводка: %s | рядки: %s"
            % (scenario["id"], scenario["title"], "; ".join(wrong),
               [(line.account_id.with_company(self.company).code, line.debit, line.credit) for line in move.line_ids]),
        )

    def _diia_city(self, scenario):
        """setup.diia_city: compliant - резидент, що відповідає вимогам; noncompliant - резидент,
        у місяці листка позначений «не відповідає вимогам»."""
        state = scenario["setup"].get("diia_city")
        if not state:
            return
        self.company.write({"ua_dc_resident": True, "ua_dc_since": DIIA_CITY_SINCE})
        if state == "noncompliant":
            self.env["ua.diia.city.month"].create({
                "company_id": self.company.id, "month": scenario["period"][0], "compliant": False})

    def _run_scenario(self, scenario):
        self._diia_city(scenario)
        employee, version = self._employee(scenario)
        slip = self._payslip(scenario, employee, version)
        self._check_lines(scenario, slip)
        if scenario["moves"]:
            self._check_moves(scenario, slip)

    # ---- карта проводок -------------------------------------------------------------
    def test_00_account_map_covers_rules(self):
        """Кожне правило з еталонною ненульовою сумою має рядок у карті проводок."""
        needed = set()
        for scenario in SCENARIOS:
            needed |= {code for code, amount in scenario["expect"].items() if abs(amount) > TOLERANCE}
        mapped = set(self.env["ua.payroll.account.map"].search([]).mapped("rule_code"))
        missing = sorted(needed - mapped - NO_MOVE_CODES)
        self.assertFalse(missing, "правила без проводки: %s" % missing)


def _make_test(scenario):
    def test(self):
        self._run_scenario(scenario)

    test.__doc__ = "Сценарій %s: %s" % (scenario["id"], scenario["title"])
    return test


for _scenario in SCENARIOS:
    setattr(TestGoldenScenarios, "test_%02d" % _scenario["id"], _make_test(_scenario))
