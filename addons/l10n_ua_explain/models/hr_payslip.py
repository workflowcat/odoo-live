"""Слід розрахунку листка: знімається з живого коду, паралельної реалізації немає.

`get_payroll_dict` підміняє payroll.ua на RecordingBrowsable - кожне читання
атрибута дописується у спільний список. `_compute_payslip_line` забирає ці
читання по одному правилу за раз (довжина списку до/після super()) і складає
з них крок сліду. `_ua_explain` збирає з кроків і `_ua_payroll_sources` один
payload; `action_payslip_done` заморожує його в ua.explain.trace, коли
документ проводиться.

Де тримається слід під час розрахунку. Не в __dict__ recordset: get_lines_dict()
робить `for payslip in self`, а ітерація recordset дає щоразу НОВИЙ Python-об'єкт,
тож усе, покладене на self зовні, всередині не видно, і навпаки. Тому сховище
модульне, ключ - (курсор, id листка). Воно живе лише під час одного розрахунку:
get_payroll_dict заводить його наново, _ua_explain забирає і прибирає за собою."""

import re

from odoo import models

from .recording import RecordingBrowsable

_CODE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Сховище сліду на час одного розрахунку: {(id курсора, id листка): {"reads", "vals", "steps"}}.
# Обмежене згори, щоб довгий воркер не ріс без кінця: слід потрібен лише до найближчого
# _ua_explain, усе старше можна викидати.
_RUNS = {}
_RUNS_CAP = 200


def _run(env, payslip_id, reset=False):
    """Сховище одного розрахунку. reset=True - почати слід наново."""
    key = (id(env.cr), payslip_id)
    if reset or key not in _RUNS:
        if len(_RUNS) > _RUNS_CAP:
            _RUNS.clear()
        _RUNS[key] = {"reads": [], "vals": {}, "steps": []}
    return _RUNS[key]


def _run_pop(env, payslip_id):
    return _RUNS.pop((id(env.cr), payslip_id), None)


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # ------------------------------------------------------------------ знімання сліду

    def get_payroll_dict(self, contracts):
        self.ensure_one()
        res = super().get_payroll_dict(contracts)
        # Новий розрахунок цього листка - новий слід. Інакше повторний виклик
        # (перегляд після compute_sheet) дописав би кроки до попередніх.
        run = _run(self.env, self.id, reset=True)
        ua = res.get("ua")
        vals = ua.dict if ua is not None else {}
        # той самий словник, що піде в RecordingBrowsable, - не копія, щоб
        # _ua_explain пізніше бачив ті самі значення, які реально читали правила
        run["vals"] = vals
        res["ua"] = RecordingBrowsable(vals, run["reads"])
        return res

    def _ua_known_codes(self):
        """Коди всіх правил і категорій структури цього листка - для статичного
        пошуку посилань у тексті формули (BASIC, categories.ALW тощо). Межа
        методу, чесно: це не ті самі "reads", що йдуть від payroll.ua - їх бачимо
        лише за текстом, по межі слова, не за фактичним виконанням формули."""
        run = _run(self.env, self.id)
        if "codes" not in run:
            rules = self._get_salary_rules()
            codes = set(c for c in rules.mapped("code") if c)
            codes |= set(c for c in rules.mapped("category_id.code") if c)
            run["codes"] = codes
        return run["codes"]

    def _compute_payslip_line(self, rule, localdict, lines_dict):
        run = _run(self.env, self.id)
        reads = run["reads"]
        before = len(reads)
        localdict, lines_dict = super()._compute_payslip_line(rule, localdict, lines_dict)
        rule_reads = reads[before:]

        # унікальні ключі, порядок першої появи (дублі читань самого себе не цікаві)
        seen = []
        for k in rule_reads:
            if k not in seen:
                seen.append(k)
        ua_vals = run["vals"]
        values = {k: ua_vals.get(k) for k in seen}

        key = (rule.code or ("id" + str(rule.id))) + "-" + str(localdict["contract"].id)
        output = lines_dict.get(key, {}).get("total", 0.0)

        if rule.amount_select == "code":
            expression = rule.amount_python_compute or ""
        elif rule.amount_select == "percentage":
            expression = rule.amount_percentage_base or ""
        else:
            expression = str(rule.amount_fix)

        known_codes = self._ua_known_codes()
        own_code = rule.code or ""
        tokens = set(_CODE_RE.findall(expression))
        uses_rules = sorted(c for c in tokens if c in known_codes and c != own_code)

        step = {
            "code": rule.code or ("id" + str(rule.id)),
            "label": rule.name,
            "category": rule.category_id.code,
            "expression": expression,
            "note": rule.note or "",
            "reads": seen,
            "values": values,
            "output": output,
            "uses_rules": uses_rules,
        }
        run["steps"].append(step)
        return localdict, lines_dict

    # ------------------------------------------------------------------ API пояснення

    def _ua_explain(self, res_id, field=None):
        """Зібрати payload сліду для одного листка. `field` тут навмисно не
        звужує нічого - звуження на крок і його залежності робить диспетчер
        ua.explain.explain() однаково і для живого, і для замороженого payload,
        одним кодом, а не двома копіями цієї логіки.

        Preview нічого не пише в базу: get_lines_dict() - та сама функція, яку
        викликає compute_sheet(), - тільки рахує рядки й повертає словник. У ній
        немає жодного create чи write, лише SELECT (сум за кодами тощо). Це і є
        "in-memory виклик тих самих методів" з ТЗ: compute_sheet() поверх неї
        додає unlink(line_ids) + write(state=...), а ми ці два кроки не робимо -
        писати нема чому, тож і SAVEPOINT не потрібен."""
        payslip = self.browse(res_id)
        payslip.ensure_one()
        contracts = payslip._get_employee_contracts()

        lines_dict = payslip.get_lines_dict()

        # Слід щойно знятий самим get_lines_dict() і більше нікому не потрібен:
        # забираємо його разом із записом сховища.
        run = _run_pop(payslip.env, payslip.id) or {"steps": [], "vals": {}}
        steps = run["steps"]
        ua_vals = run["vals"]

        sources = payslip._ua_payroll_sources(contracts)
        inputs = {}
        for k, src in sources.items():
            entry = dict(src)
            if k in ua_vals:
                entry["value"] = ua_vals[k]
            inputs[k] = entry

        missing_keys = {k for k, e in inputs.items() if e.get("state") == "missing"}
        for step in steps:
            if missing_keys & set(step.get("reads") or []):
                step["has_missing"] = True

        def _line_total(code):
            for line in lines_dict.values():
                if line.get("code") == code:
                    return line.get("total", 0.0)
            return 0.0

        period = ""
        if payslip.date_to:
            period = "%04d-%02d" % (payslip.date_to.year, payslip.date_to.month)

        return {
            "version": "1",
            "subject": {
                "model": "hr.payslip",
                "res_id": payslip.id,
                "label": payslip.name or payslip.display_name,
                "employee": ({"id": payslip.employee_id.id, "name": payslip.employee_id.name}
                             if payslip.employee_id else None),
                "period": period,
            },
            "params": payslip._ua_explain_params(),
            "inputs": inputs,
            "steps": steps,
            "totals": {"gross": _line_total("GROSS"), "net": _line_total("NET")},
        }

    def _ua_explain_params(self):
        """Плаский список параметрів закону, діючих на дату листка - довідковий
        блок payload, окремо від inputs (той знає лише ключі, які реально
        використав цей листок)."""
        self.ensure_one()
        Param = self.env["ua.payroll.param"].sudo()
        date = self.date_to
        company = self.company_id
        out = {}
        for key in sorted(set(Param.search([]).mapped("key"))):
            domain = [("key", "=", key), ("valid_from", "<=", date)]
            if company:
                domain += ["|", ("company_id", "=", company.id), ("company_id", "=", False)]
            rec = Param.search(domain, order="company_id desc, valid_from desc", limit=1)
            if rec:
                out[key] = {
                    "value": rec.value,
                    "name": rec.name,
                    "valid_from": str(rec.valid_from),
                    "source": rec.source or "",
                }
        return out

    # ------------------------------------------------------------------ заморозка

    def action_payslip_done(self):
        res = super().action_payslip_done()
        Trace = self.env["ua.explain.trace"]
        for payslip in self:
            payload = self.env["hr.payslip"]._ua_explain(payslip.id)
            Trace.freeze(payslip, payload)
        return res
