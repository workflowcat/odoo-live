# -*- coding: utf-8 -*-
"""Сторінка «Період»: місяць зарплати як смуга з дев'яти кроків і один відкритий крок.

Кожен крок знає свій стан (`mark`) і короткий факт (`subtitle`). Відкритий крок показує
своє тіло на всю ширину: документи, проблеми і записи - одним переліком `rows`, кожен
рядок із рівнем, текстом і ціллю. Перемикання кроку клієнтське (`current` лише підказує
дефолт при завантаженні) - усі дев'ять тіл уже в першій відповіді, нового запиту не треба
(docs/payroll/spec-period-v2.md).

Дані беруться з уже наявних моделей: накази, табель, аванс, листки, проводки, відомості
на перерахування, рядки виписки, журнал змін, прогони звітності, заяви ПФУ. Своїх даних
модуль не тримає.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

ACCOUNT_CODES = ["23", "91", "92", "93", "661", "6411", "6415", "651", "6851", "471", "311", "378"]


class UaPeriodBoard(models.AbstractModel):
    _name = "ua.period.board"
    _inherit = ["ua.screen"]
    _description = "Дані сторінки «Період»"

    # ------------------------------------------------------------------ хелпери
    # _r2 / _money / _bounds / _company / _plural / MONTHS_UA / open_target - у ua.screen
    @staticmethod
    def _step(key, name, state, subtitle, action=None, rows=None, button=None):
        return {"key": key, "name": name, "state": state, "subtitle": subtitle,
                "action": action or {}, "rows": rows or [], "button": button or ""}

    def _detail_row(self, names, model, ids, noun, level="warn", count=None, domain=None):
        """Один рядок кроку, що підсумовує кілька проблемних записів разом:
        «5 листків у чернетках: Гнатюк, Ковальчук, Литвин, ще 2» замість п'яти
        окремих рядків. Ціль (`domain`) веде на весь перелік, не лише на показані імена."""
        if not ids:
            return None
        n = count if count is not None else len(ids)
        shown = [x for x in names[:3] if x]
        extra = max(n - len(shown), 0)
        tail = _(", ще %s") % extra if extra else ""
        return {"level": level, "text": "%s %s: %s%s" % (n, noun, ", ".join(shown), tail),
                "target": {"model": model, "domain": domain if domain is not None else [("id", "in", list(ids))]},
                "action": _("показати")}

    DOC_STATE_LEVEL = {"немає": "idle", "чернетка": "warn", "сформовано": "warn",
                       "створено": "ok", "подано": "ok"}

    def _doc_row(self, doc):
        """Документ кроку як рядок тіла: рівень - зі стану документа, ціль - на запис,
        де його ведуть (список за доменом, якщо запис не один)."""
        level = self.DOC_STATE_LEVEL.get(doc.get("state") or "", "idle")
        text = doc["name"]
        if doc.get("deadline"):
            text = "%s · до %s" % (text, doc["deadline"])
        target = doc.get("target") or {}
        if not target and doc.get("ids") and doc.get("model"):
            target = {"model": doc["model"], "domain": [("id", "in", doc["ids"])]}
        action = _("відкрити") if (target.get("model") or target.get("xmlid")) else ""
        return {"level": level, "text": text, "target": target, "action": action}

    @staticmethod
    def _join_ua(items):
        """«4, 5 і 8»: кома між усіма, крім останнього - там «і» (норма мови, не Oxford comma)."""
        items = [str(i) for i in items]
        if len(items) <= 1:
            return "".join(items)
        return "%s і %s" % (", ".join(items[:-1]), items[-1])

    # ------------------------------------------------------------------ кроки
    def _step_orders(self, company, first, last):
        Order = self.env["ua.hr.order"]
        domain = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last)]
        posted = Order.search_count(domain + [("state", "in", ("posted", "acknowledged"))])
        drafts = Order.search(domain + [("state", "=", "draft")])
        state = "warn" if drafts else ("done" if posted else "todo")
        fact = "%s проведено, %s чернеток" % (posted, len(drafts))
        row = self._detail_row([o.name or "без номера" for o in drafts], "ua.hr.order",
                               drafts.ids, "наказів у чернетках")
        return self._step("orders", "Кадрові накази", state, fact,
                          {"xmlid": "l10n_ua_hr_orders.action_ua_hr_order"}, [row] if row else [])

    def _step_timesheet(self, company, year, month):
        """Табель формується сам: якщо його ще немає, ua.timesheet.sheet._ua_ensure_for
        створює чернетку і заповнює нормою/фактом, тому кроку завжди є що показати."""
        sheet = self.env["ua.timesheet.sheet"]._ua_ensure_for(company, year, month)
        fact_days = sum(sheet.line_ids.mapped("days_worked"))
        norm_days = sum(sheet.line_ids.mapped("norm_days"))
        summary = sheet._checks_summary()
        state = "done" if (sheet.state == "confirmed" and summary["level"] != "error") else "warn"
        fact = "%s працівників · норма %s днів · факт %s днів" % (
            len(sheet.line_ids), self._money(norm_days).replace(",00", ""),
            self._money(fact_days).replace(",00", ""))
        rows = []
        if sheet.state != "confirmed":
            rows.append({"level": "warn", "text": _("Табель не затверджено"),
                        "target": {"model": "ua.timesheet.sheet", "res_id": sheet.id},
                        "action": _("відкрити")})
        dev_lines = sheet.line_ids.filtered(lambda l: abs(l.diff_days) > 0.01)
        row = self._detail_row([line.employee_id.name for line in dev_lines], "ua.timesheet.line",
                               dev_lines.ids, "відхилень у табелі")
        if row:
            rows.append(row)
        return self._step("timesheet", "Табель", state, fact,
                          {"model": "ua.timesheet.sheet", "res_id": sheet.id}, rows)

    def _step_advance(self, company, year, month):
        sheet = self.env["ua.advance.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ], limit=1)
        if not sheet or not sheet.line_ids:
            return self._step("advance", "Аванс", "todo", "не розраховано",
                              {"xmlid": "l10n_ua_payroll_rules.action_ua_advance_wizard"})
        state = "done" if sheet.state == "confirmed" else "warn"
        fact = "%s · %s осіб" % (self._money(sheet.total), len(sheet.line_ids))
        return self._step("advance", "Аванс", state, fact,
                          {"model": "ua.advance.sheet", "res_id": sheet.id})

    def _step_payslips(self, company, first, last):
        Payslip = self.env["hr.payslip"]
        domain = [("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last)]
        slips = Payslip.search(domain + [("state", "!=", "cancel")])
        done = slips.filtered(lambda s: s.state == "done")
        open_slips = slips - done
        gross = sum(done.mapped("line_ids").filtered(lambda l: l.code == "GROSS").mapped("total"))
        if not slips:
            return self._step("payslips", "Розрахунок листків", "todo", "листків немає",
                              {"xmlid": "payroll.action_hr_payslip_run_tree"})
        state = "done" if not open_slips else "warn"
        fact = "%s проведено · %s" % (len(done), self._money(gross))
        row = self._detail_row([s.employee_id.name for s in open_slips], "hr.payslip",
                               open_slips.ids, "листків у чернетках")
        return self._step("payslips", "Розрахунок листків", state, fact,
                          {"xmlid": "payroll.action_hr_payslip_run_tree"}, [row] if row else [])

    def _step_moves(self, company, first, last):
        Move = self.env["account.move"]
        domain = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last)]
        drafts = Move.search(domain + [("state", "=", "draft")])
        self.env.cr.execute(
            """SELECT COALESCE(SUM(aml.debit), 0), COALESCE(SUM(aml.credit), 0)
               FROM account_move_line aml JOIN account_move am ON am.id = aml.move_id
               WHERE am.company_id = %s AND am.state = 'posted' AND aml.date BETWEEN %s AND %s""",
            (company.id, first, last))
        debit, credit = self.env.cr.fetchone()
        balanced = abs(self._r2(debit) - self._r2(credit)) < 0.01
        state = "done" if (balanced and not drafts) else "warn"
        fact = "%s, чернеток %s" % ("дебет = кредит" if balanced else "дебет ≠ кредит", len(drafts))
        row = self._detail_row([m.name or m.ref or "-" for m in drafts], "account.move",
                               drafts.ids, "чернеток проводок")
        return self._step("moves", "Проводки", state, fact,
                          {"xmlid": "account.action_move_journal_line"}, [row] if row else [])

    def _step_payment(self, company, year, month):
        batches = self.env["ua.payment.batch"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
        ])
        if not batches:
            return self._step("payment", "Виплата", "todo", "відомості немає",
                              {"xmlid": "l10n_ua_payments.action_ua_payment_batch"})
        total = sum(batches.mapped("total"))
        paid = batches.filtered(lambda b: b.state == "paid")
        state = "done" if paid else "warn"
        fact = "%s · %s" % (self._money(total), "оплачено" if paid else "не позначено оплаченою")
        return self._step("payment", "Виплата", state, fact,
                          {"model": "ua.payment.batch", "res_id": batches[0].id})

    def _step_bank(self, company, first, last):
        lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("is_reconciled", "=", False),
            ("date", ">=", first), ("date", "<=", last),
        ])
        amount = sum(abs(line.amount) for line in lines)
        state = "done" if not lines else "warn"
        fact = "звірено все" if not lines else "%s рядків · %s" % (len(lines), self._money(amount))
        row = self._detail_row([(line.payment_ref or "")[:40] for line in lines],
                               "account.bank.statement.line", lines.ids, "рядків виписки не звірено")
        return self._step("bank", "Звірка банку", state, fact,
                          {"xmlid": "l10n_ua_bank_ui.action_ua_bank_board"}, [row] if row else [],
                          button="Звірити" if lines else "")

    # заявка ПФУ, за станом: те саме, що раніше показувала черга «Увага» (тепер розкладена
    # по кроках, docs/payroll/spec-period-v2.md, п.1) - тут, бо документ заявки вже стоїть
    # серед паперів цього ж кроку в _documents().
    PFU_STAGE = {
        "draft": "заяву не подано", "confirmed": "заяву не подано",
        "submitted": "ПФУ ще не прийняв заяву",
        "rejected": "ПФУ відмовив",
        "accepted": "кошти від ПФУ не надійшли",
        "funded_partial": "профінансовано частково",
        "funded": "допомогу не виплачено працівникам",
        "paid": "повідомлення не подано",
        "notified": "заяву не завершено",
    }

    def _step_reporting(self, company, year, month):
        """Податковий розрахунок подається щомісяця: 20 днів після закінчення місяця."""
        run = self.env["ua.report.run"].search([
            ("company_id", "=", company.id), ("report_code", "=", "j05"),
            ("year", "=", year), ("month", "=", month), ("doc_kind", "=", "HZ"),
        ], limit=1)
        deadline = self._bounds(year, month)[1] + timedelta(days=20)
        if run and run.state == "submitted":
            state, fact = "done", "подано %s" % (run.submitted_date.strftime("%d.%m.%Y") if run.submitted_date else "")
        elif run and run.state == "generated":
            state, fact = "warn", "сформовано, не подано · строк %s" % deadline.strftime("%d.%m.%Y")
        else:
            state, fact = "todo", "строк %s" % deadline.strftime("%d.%m.%Y")
        rows = []
        first, last = self._bounds(year, month)
        claim = self.env["ua.pfu.claim"].search([
            ("company_id", "=", company.id),
            ("payslip_run_id.date_start", ">=", first), ("payslip_run_id.date_start", "<=", last),
        ], limit=1)
        if claim and claim.state != "done":
            rows.append({"level": "crit" if claim.state == "rejected" else "warn",
                        "text": "Фінансування ПФУ: %s" % self.PFU_STAGE.get(claim.state, claim.state),
                        "target": {"model": "ua.pfu.claim", "res_id": claim.id}, "action": _("відкрити")})
        return self._step("reporting", "Податковий розрахунок за місяць", state, fact,
                          {"xmlid": "l10n_ua_reporting_ui.action_ua_reporting"}, rows)

    def _step_changes(self, company, year, month, first, last):
        """Скільки змін місяця ще не переглянув бухгалтер.

        Розбивка за видом («5 прийнято», «2 відпустки» - раніше окремий блок «Зміни
        місяця») тепер теж тут: рядками, разом із новими неприйнятими (spec-period-v2.md,
        п.1 - «Зміни місяця» належать цьому кроку)."""
        Log = self.env["ua.change.log"]
        total = Log.search_count([("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)])
        new = Log.count_new(company, year, month)
        action = {"xmlid": "l10n_ua_changes.action_ua_change_log",
                  "domain": [("year", "=", year), ("month", "=", month)],
                  "context": {"search_default_f_new": 1, "search_default_g_area": 1}}
        rows = []
        if new:
            new_recs = Log.search([("company_id", "=", company.id), ("year", "=", year),
                                   ("month", "=", month), ("state", "=", "new")], limit=20)
            names = ["%s · %s" % (r.res_name, r.what or dict(r._fields["operation"].selection).get(r.operation, ""))
                     for r in new_recs]
            row = self._detail_row(names, "ua.change.log", new_recs.ids, "нових змін", count=new,
                                   domain=[("company_id", "=", company.id), ("year", "=", year),
                                          ("month", "=", month), ("state", "=", "new")])
            if row:
                rows.append(row)
        for item in self._changes(company, first, last):
            rows.append({"level": "idle", "text": "%s %s" % (item["count"], item["label"]),
                        "target": {"model": item["model"], "domain": item["domain"]}, "action": _("показати")})
        if not total:
            state, fact = "done", "змін немає"
        elif new:
            state, fact = "warn", "%s нових з %s" % (new, total)
        else:
            state, fact = "done", "%s змін прийнято" % total
        return self._step("changes", "Перевірка змін", state, fact, action, rows)

    def _steps(self, company, year, month, first, last):
        """Кроки місяця в порядку роботи."""
        return [
            self._step_orders(company, first, last),
            self._step_timesheet(company, year, month),
            self._step_advance(company, year, month),
            self._step_payslips(company, first, last),
            self._step_moves(company, first, last),
            self._step_payment(company, year, month),
            self._step_bank(company, first, last),
            self._step_changes(company, year, month, first, last),
            self._step_reporting(company, year, month),
        ]

    # Порядок і номер кроку, що відповідає ua.period.close.blockers(): яка з чотирьох умов
    # на якому кроці. blockers() лишається єдиним джерелом істини «чи можна закрити» -
    # тут той самий порядок умов лише дзеркалиться, щоб рядок під кроком знав свій номер
    # (так само дзеркалить action_close_month_plan нижче, для діалогу плану).
    BLOCKER_STEPS = {"changes": 8, "moves": 5, "payslips": 4, "timesheet": 2}

    def _blocker_rows(self, company, year, month):
        """Причини, що заважають закрити місяць, кожна зі своїм кроком.

        Самі причини знає ua.period.close.blocker_rows() - тут лише додається номер
        кроку, на якому причину знімають."""
        return [{"key": row["key"], "n": self.BLOCKER_STEPS[row["key"]], "text": row["short"]}
                for row in self.env["ua.period.close"].blocker_rows(company, year, month)]

    def _blockers_summary(self, blocker_rows):
        """Рядок унизу кроку: «Заважає закрити місяць: N причин» + деталь, звідки саме -
        те саме на всіх дев'яти кроках (spec-period-v2.md, п.3: єдине місце про перешкоди)."""
        if not blocker_rows:
            return {"count": 0, "word": "", "text": "", "target": {}}
        nums = sorted({row["n"] for row in blocker_rows})
        count = len(blocker_rows)
        detail = (_("Крок %s.") % nums[0] if len(nums) == 1
                  else _("Усі - на кроках %s.") % self._join_ua(nums))
        first_key = min(blocker_rows, key=lambda r: r["n"])["key"]
        return {"count": count, "word": self._plural(count, "причина", "причини", "причин"),
                "text": detail, "target": {"step": first_key}}

    # ------------------------------------------------------------------ робоче місце місяця
    def _slip_domain(self, company, first, last):
        """Домен листків місяця: те, що стоїть за числами зверху екрана."""
        return [
            ("company_id", "=", company.id),
            ("date_from", ">=", str(first)), ("date_from", "<=", str(last)),
            ("state", "!=", "cancel"),
        ]

    def _slips(self, company, first, last):
        return self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel"),
        ])

    def _totals(self, company, first, last):
        """Три числа місяця: нараховано, до виплати, ЄСВ підприємства. У шапці, не в
        кроці - вони про місяць у цілому (spec-period-v2.md, п.4)."""
        slips = self._slips(company, first, last)
        lines = slips.mapped("line_ids")

        def total(codes):
            return self._r2(sum(lines.filtered(lambda l: l.code in codes).mapped("total")))

        gross = self._r2(total(("GROSS",)) + total(("MAT",)) + total(("DAILY", "AID_FREE", "GIFT_FREE"))
                         + total(("AID_TAX", "GIFT_TAX", "SEVERANCE", "COMP_TOOL")))
        return {
            "gross": self._money(gross),
            "net": self._money(total(("NET",))),
            "esv": self._money(total(("ESV",))),
            "people": len(slips),
            "draft": len(slips.filtered(lambda s: s.state != "done")),
            "model": "hr.payslip",
            "domain": self._slip_domain(company, first, last),
            "draft_domain": self._slip_domain(company, first, last) + [("state", "!=", "done")],
        }

    def _changes(self, company, first, last):
        """Події працівників у місяці: що змінилося проти попереднього місяця."""
        Order = self.env["ua.hr.order"]
        posted = [("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
                  ("state", "in", ("posted", "acknowledged"))]
        rows = []
        kinds = [("hire", "прийнято"), ("wage", "зміна окладу"), ("transfer", "переведення"),
                 ("dismissal", "звільнення")]
        for code, label in kinds:
            count = Order.search_count(posted + [("order_type", "=", code)])
            if count:
                rows.append({"label": label, "count": count, "model": "ua.hr.order",
                             "domain": [("company_id", "=", company.id), ("date", ">=", str(first)),
                                        ("date", "<=", str(last)), ("order_type", "=", code)]})
        Leave = self.env["hr.leave"]
        leave_domain = [("employee_id.company_id", "=", company.id), ("state", "=", "validate"),
                        ("request_date_from", "<=", last), ("request_date_to", ">=", first)]
        groups = [(("SICK", "SICK_CARE"), "лікарняні"), (("VAC", "STUDY", "CHILD_VAC"), "відпустки"),
                  (("MAT",), "декрет"), (("TRIP",), "відрядження")]
        for codes, label in groups:
            count = Leave.search_count(leave_domain + [("holiday_status_id.work_entry_type_id.code", "in", list(codes))])
            if count:
                rows.append({"label": label, "count": count, "model": "hr.leave",
                             "domain": [("employee_id.company_id", "=", company.id), ("state", "=", "validate"),
                                        ("request_date_from", "<=", str(last)), ("request_date_to", ">=", str(first)),
                                        ("holiday_status_id.work_entry_type_id.code", "in", list(codes))]})
        return rows

    def _headline(self, company, steps, close, blockers, totals):
        """Одна головна дія, яка змінюється зі станом місяця.

        Черга «Увага» більше не існує окремо (spec-period-v2.md, п.1): ПФУ-виняток
        переїхав рядком у крок «reporting», тому власної гілки тут більше нема -
        реальні проблеми і так зупиняють один із кроків нижче по каскаду."""
        by_key = {step["key"]: step for step in steps}
        if close.get("state") == "closed":
            return {"title": "Місяць закрито", "detail": close.get("closed_date") or "",
                    "action": "", "label": "", "tone": "ok"}
        if not totals["people"]:
            return {"title": "Місяць не підготовлено", "detail": "листків ще немає",
                    "action": "prepare", "label": "Підготувати місяць", "tone": "todo"}
        if totals["draft"]:
            return {"title": "Розрахунок попередній", "detail": "%s листків не проведено" % totals["draft"],
                    "action": "payslips", "label": "Затвердити розрахунок", "tone": "warn"}
        if by_key.get("payment", {}).get("state") != "done":
            return {"title": "Виплата не підготовлена", "detail": by_key.get("payment", {}).get("subtitle", ""),
                    "action": "payment", "label": "Підготувати виплати", "tone": "todo"}
        if by_key.get("reporting", {}).get("state") != "done":
            return {"title": "Звітність не подана", "detail": by_key.get("reporting", {}).get("subtitle", ""),
                    "action": "reporting", "label": "Переглянути звітність", "tone": "todo"}
        if blockers:
            return {"title": "Місяць майже готовий", "detail": "; ".join(blockers),
                    "action": "", "label": "", "tone": "warn"}
        return {"title": "Місяць готовий до закриття", "detail": "усі кроки виконані",
                "action": "close", "label": "Закрити місяць", "tone": "ok"}


    # ------------------------------------------------------------------ люди і суми
    CATEGORY_ORDER = ("BASIC", "ALW", "AVG", "MAT", "NOTAX", "NOESV", "GROSS", "DED", "NET", "COMP")
    SLIP_STATE = {"draft": "чернетка", "verify": "перевірено", "done": "проведено", "cancel": "скасовано"}

    def _payment_state(self, company, first, last):
        """Стан виплати за працівником: у якій відомості і чи позначена оплаченою."""
        batches = self.env["ua.payment.batch"].search([
            ("company_id", "=", company.id), ("year", "=", first.year), ("month", "=", first.month),
        ])
        out = {}
        for batch in batches:
            for line in batch.line_ids.filtered("employee_id"):
                current = out.get(line.employee_id.id)
                if current and current["paid"]:
                    continue
                out[line.employee_id.id] = {"batch": batch.name, "batch_id": batch.id,
                                            "paid": batch.state == "paid",
                                            "amount": self._money(line.amount)}
        return out

    @api.model
    def get_people(self, year=None, month=None):
        """Рядок на працівника: час, нараховано, до виплати, ЄСВ, стан листка і виплати."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        payments = self._payment_state(company, first, last)
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)], limit=1)
        by_employee = {line.employee_id.id: line for line in sheet.line_ids} if sheet else {}
        rows = []
        for slip in self._slips(company, first, last).sorted(lambda s: s.employee_id.name or ""):
            employee = slip.employee_id
            lines = {line.code: line.total for line in slip.line_ids}
            time_line = by_employee.get(employee.id)
            flags = []
            if not employee.sudo()._ua_payment_account():
                flags.append("немає рахунку")
            if time_line and abs(time_line.diff_days) > 0.01:
                flags.append("відхилення в табелі %s дн" % self._money(time_line.diff_days).replace(",00", ""))
            payment = payments.get(employee.id)
            rows.append({
                "employee_id": employee.id,
                "name": employee.name,
                "job": employee.job_title or "",
                "department": employee.department_id.name or "",
                "days": self._money(time_line.days_worked).replace(",00", "") if time_line else "",
                "gross": self._money(lines.get("GROSS", 0.0)),
                "net": self._money(lines.get("NET", 0.0)),
                "esv": self._money(lines.get("ESV", 0.0)),
                "state": self.SLIP_STATE.get(slip.state, slip.state),
                "done": slip.state == "done",
                "payment": (payment["batch"] if payment else ""),
                "paid": bool(payment and payment["paid"]),
                "flags": flags,
            })
        return rows

    @api.model
    def get_person(self, employee_id, year=None, month=None):
        """Картка працівника за місяць: рядки розрахунку, події, виплата."""
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        employee = self.env["hr.employee"].browse(int(employee_id))
        slip = self._slips(company, first, last).filtered(lambda s: s.employee_id == employee)[:1]
        lines = []
        if slip:
            order = {code: index for index, code in enumerate(self.CATEGORY_ORDER)}
            for line in slip.line_ids.sorted(lambda l: (order.get(l.category_id.code, 99), l.sequence)):
                if not line.total:
                    continue
                lines.append({"code": line.code, "name": line.name,
                              "category": line.category_id.name or "",
                              "amount": self._money(line.total)})
        events = []
        for order_doc in self.env["ua.hr.order"].search([
                ("employee_id", "=", employee.id), ("date", ">=", first), ("date", "<=", last)]):
            events.append({"title": order_doc.name or order_doc.display_name,
                           "detail": dict(order_doc._fields["order_type"].selection).get(order_doc.order_type, ""),
                           "model": "ua.hr.order", "id": order_doc.id})
        for leave in self.env["hr.leave"].search([
                ("employee_id", "=", employee.id), ("state", "=", "validate"),
                ("request_date_from", "<=", last), ("request_date_to", ">=", first)]):
            events.append({"title": leave.holiday_status_id.name or "",
                           "detail": "%s - %s" % (leave.request_date_from.strftime("%d.%m"),
                                                  leave.request_date_to.strftime("%d.%m")),
                           "model": "hr.leave", "id": leave.id})
        payment = self._payment_state(company, first, last).get(employee.id)
        return {
            "employee_id": employee.id,
            "name": employee.name,
            "job": employee.job_title or "",
            "department": employee.department_id.name or "",
            "slip_id": slip.id if slip else False,
            "state": self.SLIP_STATE.get(slip.state, slip.state) if slip else "листка немає",
            "lines": lines,
            "events": events,
            "payment": payment or {},
        }

    @api.model
    def action_open_person(self, employee_id, slip_id=None):
        if slip_id:
            return {"type": "ir.actions.act_window", "res_model": "hr.payslip", "res_id": int(slip_id),
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "res_model": "hr.employee", "res_id": int(employee_id),
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    # ------------------------------------------------------------------ обороти
    def _turnover(self, company, first, last):
        """Обороти за групами рахунків: беремо всі субрахунки за префіксом (311 і 311001 разом)."""
        rows = []
        Account = self.env["account.account"]
        for code in ACCOUNT_CODES:
            accounts = Account.search([("code", "=like", "%s%%" % code), ("company_ids", "in", company.id)], order="code")
            accounts = accounts.filtered(lambda a: (a.code or "").startswith(code))
            if not accounts:
                continue
            self.env.cr.execute(
                """SELECT COALESCE(SUM(aml.debit), 0), COALESCE(SUM(aml.credit), 0)
                   FROM account_move_line aml JOIN account_move am ON am.id = aml.move_id
                   WHERE aml.account_id IN %s AND am.state = 'posted' AND aml.date BETWEEN %s AND %s""",
                (tuple(accounts.ids), first, last))
            debit, credit = self.env.cr.fetchone()
            if not debit and not credit:
                continue
            balance = self._r2(debit) - self._r2(credit)
            rows.append({"code": code, "name": accounts[0].name,
                         "debit": self._money(debit), "credit": self._money(credit),
                         "saldo_debit": self._money(balance) if balance > 0 else "",
                         "saldo_credit": self._money(-balance) if balance < 0 else "",
                         "model": "account.move.line",
                         "domain": [("account_id", "in", accounts.ids),
                                    ("move_id.state", "=", "posted"),
                                    ("date", ">=", str(first)), ("date", "<=", str(last))]})
        return rows

    # ------------------------------------------------------------------ довідка
    # Пояснення кроків місяця для режиму підказок. Що це, коли готово, що далі.
    STEP_HELP = {
        "orders": {
            "what": "Накази місяця: прийняття, звільнення, зміна окладу, відпустки.",
            "done": "Готово, коли чернеток немає.",
            "next": "Проведений наказ сам змінює договір працівника і рядки його листка.",
        },
        "timesheet": {
            "what": "Дні і години кожного працівника. Норма береться з графіка, факт правите вручну.",
            "done": "Готово, коли табель затверджено.",
            "next": "«Перерахувати листки» в табелі переносить факт у листки.",
        },
        "advance": {
            "what": "Виплата за першу половину місяця за відсотком окладу.",
            "done": "Готово, коли авансову відомість затверджено.",
            "next": "Сума авансу віднімається в листку при остаточному розрахунку.",
        },
        "payslips": {
            "what": "Листок на кожного працівника: нарахування, ПДФО 18 %, військовий збір 5 %, ЄСВ 22 %.",
            "done": "Готово, коли всі листки затверджено.",
            "next": "Затвердження створює проводки і рядки для відомості на виплату.",
        },
        "moves": {
            "what": "Проводки з листків на рахунки 661, 641, 651.",
            "done": "Готово, коли дебет дорівнює кредиту і чернеток немає.",
            "next": "Обороти видно на екрані «Зведення».",
        },
        "payment": {
            "what": "Відомість на перерахування і файл для банку.",
            "done": "Готово, коли відомість позначено оплаченою.",
            "next": "Оплату підтверджує рядок виписки на кроці «Звірка банку».",
        },
        "bank": {
            "what": "Рядки виписки за місяць зіставляються з виплатами і податками.",
            "done": "Готово, коли незвірених рядків за місяць немає.",
            "next": "Звірений рядок закриває платіж на смузі строків.",
        },
        "changes": {
            "what": "Журнал кожної зміни суми, часу або стану після розрахунку: було, стало, хто.",
            "done": "Готово, коли всі зміни прийнято.",
            "next": "Без цього кроку місяць не закривається.",
        },
        "reporting": {
            "what": "Податковий розрахунок J0500111 з додатками Д1, 4ДФ і Д5.",
            "done": "Готово, коли розрахунок позначено поданим.",
            "next": "Строк подання - 20 днів після кінця місяця.",
        },
    }

    # ------------------------------------------------------------------ документи кроків
    def _doc(self, kind, name, report=None, records=None, deadline=None, target=None, state=None):
        """Документ біля кроку місяця, перетворюється на рядок кроку через _doc_row().

        kind: print - друкується; filing - подається в держорган; file - машинний файл.
        `model` - модель records, щоб _doc_row() міг побудувати ціль-список, коли явної
        `target` немає (документ на кілька записів, а не на один). Перегляд на папері і
        кошик друку сюди більше не належать - для цього є «Папери» (l10n_ua_papers).
        """
        ids = records.ids if records else []
        return {"kind": kind, "name": name, "report": report or "", "ids": ids,
                "model": records._name if records else "",
                "deadline": deadline.strftime("%d.%m.%Y") if deadline else "",
                "target": target or {}, "state": state or ""}

    @staticmethod
    def _doc_state(records):
        states = set(records.mapped("state")) if records and "state" in records._fields else set()
        if not records:
            return "немає"
        if states <= {"draft", "verify"}:
            return "чернетка"
        return "створено"

    def _documents(self, company, year, month, first, last):
        """Документи, які породжує кожен крок місяця. Ключ - ключ кроку."""
        out = {}
        Order = self.env["ua.hr.order"]
        orders = Order.search([("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
                               ("state", "!=", "cancel")])
        docs = []
        if orders:
            docs.append(self._doc("print", "Накази · %s" % len(orders), "l10n_ua_hr_orders.report_ua_hr_order", orders,
                                  state=self._doc_state(orders)))
        if "ua.military.notice" in self.env:
            notices = self.env["ua.military.notice"].search([("company_id", "=", company.id),
                                                            ("date_from", "<=", last), ("date_to", ">=", first)])
            for notice in notices:
                docs.append(self._doc("filing", "Повідомлення ТЦК", "l10n_ua_military.report_ua_military_notice", notice,
                                      deadline=notice.date_to + timedelta(days=7),
                                      target={"model": "ua.military.notice", "res_id": notice.id},
                                      state=self._doc_state(notice)))
        out["orders"] = docs

        sheet = self.env["ua.timesheet.sheet"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month), ("department_id", "=", False)], limit=1)
        out["timesheet"] = [self._doc("print", "Табель П-5", "l10n_ua_hr_docs.report_ua_timesheet", sheet,
                                      target={"model": "ua.timesheet.sheet", "res_id": sheet.id},
                                      state=self._doc_state(sheet))] if sheet else []

        advance = self.env["ua.advance.sheet"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month)], limit=1)
        out["advance"] = [self._doc("print", "Авансова відомість", "l10n_ua_payroll_reports.report_ua_advance_sheet",
                                    advance, target={"model": "ua.advance.sheet", "res_id": advance.id},
                                    state=self._doc_state(advance))] if advance else []

        slips = self.env["hr.payslip"].search([("company_id", "=", company.id), ("date_from", ">=", first),
                                               ("date_from", "<=", last), ("state", "!=", "cancel")])
        run = self.env["hr.payslip.run"].search([("company_id", "=", company.id), ("date_start", ">=", first),
                                                 ("date_start", "<=", last)], limit=1)
        docs = []
        if slips:
            docs.append(self._doc("print", "Розрахункові листки · %s" % len(slips),
                                  "l10n_ua_payroll_reports.report_ua_payslip", slips, state=self._doc_state(slips)))
        if run:
            docs.append(self._doc("print", "Розрахунково-платіжна відомість",
                                  "l10n_ua_payroll_reports.report_ua_payroll_sheet", run,
                                  target={"model": "hr.payslip.run", "res_id": run.id},
                                  state=self._doc_state(slips)))
        out["payslips"] = docs

        batches = self.env["ua.payment.batch"].search([("company_id", "=", company.id), ("year", "=", year),
                                                       ("month", "=", month)])
        docs = []
        for batch in batches:
            docs.append(self._doc("print", batch.name, "l10n_ua_payments.report_ua_payment_batch", batch,
                                  target={"model": "ua.payment.batch", "res_id": batch.id},
                                  state=self._doc_state(batch)))
            docs.append(self._doc("file", "Файл для банку · %s" % batch.name,
                                  target={"model": "ua.payment.batch", "res_id": batch.id}))
        out["payment"] = docs

        deadline = last + timedelta(days=20)
        docs = []
        run_j05 = self.env["ua.report.run"].search([("company_id", "=", company.id), ("report_code", "=", "j05"),
                                                    ("year", "=", year), ("month", "=", month)], limit=1)
        docs.append(self._doc("filing", "J0500111 · Д1, 4ДФ, Д5", deadline=deadline,
                              target={"xmlid": "l10n_ua_reporting_ui.action_ua_reporting"},
                              state={"submitted": "подано", "generated": "сформовано"}.get(run_j05.state, "чернетка")
                              if run_j05 else "немає"))
        claims = self.env["ua.pfu.claim"].search([("company_id", "=", company.id),
                                                  ("payslip_run_id.date_start", ">=", first),
                                                  ("payslip_run_id.date_start", "<=", last)])
        for claim in claims:
            docs.append(self._doc("filing", "Заява-розрахунок ПФУ", "l10n_ua_hr_docs.report_ua_pfu_claim", claim,
                                  deadline=deadline, target={"model": "ua.pfu.claim", "res_id": claim.id},
                                  state=self._doc_state(claim)))
        out["reporting"] = docs
        return out

    def _deadlines(self, company, year, month):
        """Смуга строків: платежі і подання навколо місяця, за датою."""
        state_map = {"ok": "ok", "warn": "warn", "todo": "crit", "plan": "todo"}
        rows = []
        import re
        for row in self.env["ua.payments.plan"].month_rows(company, year, month):
            # квартальний рядок - залишок старої схеми; розрахунок подається щомісяця
            if not row.get("date") or "квартал" in row["label"]:
                continue
            label = re.sub(r",\s*\S+\s+\d{4}", "", row["label"]).replace(" (остаточний розрахунок)", "")
            rows.append({"date": row["date"], "label": label, "state": state_map.get(row.get("state_class"), "todo")})
        first, last = self._bounds(year, month)
        rows.append({"date": (last + timedelta(days=20)).strftime("%d.%m.%Y"),
                     "label": "Податковий розрахунок", "state": "todo"})

        def key(r):
            d, m, y = r["date"].split(".")
            return (y, m, d)
        rows.sort(key=key)
        # однакові дати зливаються в одну позначку
        merged = []
        for r in rows:
            if merged and merged[-1]["date"] == r["date"]:
                merged[-1]["label"] += " · " + r["label"]
                if r["state"] in ("crit", "warn") and merged[-1]["state"] not in ("crit",):
                    merged[-1]["state"] = r["state"]
            else:
                merged.append(dict(r))
        today = fields.Date.context_today(self).strftime("%Y%m%d")
        for r in merged:
            d, m, y = r["date"].split(".")
            r["past"] = y + m + d < today
        return merged

    # позначка кроку зі стану: done/warn/todo (внутрішній розрахунок кожного _step_*) ->
    # ok/warn/crit/idle (спека, ті самі слова, що й у рядків кроку). "crit" - не свій
    # стан кроку, а надбудова: крок, який справді заважає закрити місяць, тепер червоний.
    MARK_MAP = {"done": "ok", "warn": "warn", "todo": "idle"}

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, year=None, month=None):
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)
        steps = self._steps(company, year, month, first, last)
        done = sum(1 for s in steps if s["state"] == "done")
        blockers = self.env["ua.period.close"].blockers(company, year, month)
        close = self.env["ua.period.close"].state_of(company, year, month)
        totals = self._totals(company, first, last)
        headline = self._headline(company, steps, close, blockers, totals)

        documents = self._documents(company, year, month, first, last)
        blocker_rows = self._blocker_rows(company, year, month)
        blocking_keys = {row["key"] for row in blocker_rows}
        blockers_summary = self._blockers_summary(blocker_rows)
        for index, step in enumerate(steps):
            step["n"] = index + 1
            mark = self.MARK_MAP.get(step.pop("state"), "idle")
            if mark == "warn" and step["key"] in blocking_keys:
                mark = "crit"
            step["mark"] = mark
            step["rows"] = [self._doc_row(doc) for doc in documents.get(step["key"], [])] + step["rows"]
            step["blockers"] = blockers_summary
        current_key = (next((s["key"] for s in steps if s["mark"] == "crit"), None)
                      or next((s["key"] for s in steps if s["mark"] == "warn"), None)
                      or steps[0]["key"])
        for step in steps:
            step["current"] = step["key"] == current_key

        return {
            "company": company.name,
            "period": self._period_block(year, month, closed=close.get("state") == "closed"),
            "steps": steps,
            "done": done,
            "total": len(steps),
            "turnover": self._turnover(company, first, last),
            "blockers": blockers,
            "close": close,
            "new_changes": self.env["ua.change.log"].count_new(company, year, month),
            "totals": totals,
            "help": self.STEP_HELP,
            "deadlines": self._deadlines(company, year, month),
            "headline": headline,
            "quarter": self._quarter_info(company, year, month),
            "year_close": self._year_info(company, year, month),
        }

    def _quarter_info(self, company, year, month):
        """Закриття кварталу показуємо в останньому місяці кварталу."""
        quarter = (month - 1) // 3 + 1
        if month != quarter * 3:
            return {}
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", company.id), ("year", "=", year),
                            ("month", "=", month), ("kind", "=", "quarter")], limit=1)
        return {"quarter": quarter, "label": "%s квартал %s" % (quarter, year),
                "closed": rec.state == "closed" if rec else False,
                "blockers": Close.quarter_blockers(company, year, quarter)}

    def _year_info(self, company, year, month):
        """Закриття року показуємо в грудні."""
        if month != 12:
            return {}
        Close = self.env["ua.period.close"]
        rec = Close.search([("company_id", "=", company.id), ("year", "=", year),
                            ("kind", "=", "year")], limit=1)
        return {"label": "%s рік" % year, "closed": rec.state == "closed" if rec else False,
                "blockers": Close.year_blockers(company, year)}

    # ------------------------------------------------------------------ дії
    # Відкриття цілі - ua.screen.open_target: xmlid, запис або перелік за доменом.
    # Колишні action_open / action_open_record / action_open_exception були трьома
    # говірками того самого і нічого понад open_target не робили.

    @staticmethod
    def _decode_period(ids, year, month):
        """Рік і місяць: прямий виклик (odoo shell, action_headline) дає їх окремо.

        Кнопки, підключені через ua_act (l10n_ua_shell), звуть план-метод без жодних
        kwargs (сервіс так влаштований: docs/payroll/action-model.md, «Як
        користуватися»), тому клієнт (period.js) пакує рік і місяць в один-єдиний
        параметр id, який RPC доносить сюди як список з одним числом - рік*100+місяць.
        Виклик із kwargs (є рік і місяць) завжди має перевагу над запакованим ids.
        """
        if year is not None and month is not None:
            return int(year), int(month)
        code = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        return divmod(int(code), 100)

    @api.model
    def action_accept_changes(self, ids=False, year=None, month=None):
        """Прийняти всі нові зміни місяця.

        Клас «узгодження» (action-model.md): без плану, зі скасуванням 20 с -
        action_undo_accept_changes нижче справді повертає щойно прийняті рядки
        назад у стан «нова», а не просто ховає повідомлення."""
        year, month = self._decode_period(ids, year, month)
        company = self._company()
        n = self.env["ua.change.log"].accept_period(year, month)
        text = _("Прийнято змін: %s.") % n if n else _("Приймати не було чого: нових змін немає.")
        return {"done": [{
            "text": text,
            "target": {"model": "ua.change.log",
                      "domain": [("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)]},
        }]}

    @api.model
    def action_undo_accept_changes(self, ids=False, year=None, month=None):
        """Скасування «Прийняти всі зміни»: чесний відкат тих самих рядків журналу назад
        у «нова», не приховування результату (action-model.md, «Вікно скасування»).

        ua_act кличе цей метод без жодних kwargs (лише ids), тому які рядки повертати
        назад визначаємо за вікном часу: прийняті цим користувачем за останні 25 с -
        з запасом над 20-секундною смугою скасування на екрані."""
        year, month = self._decode_period(ids, year, month)
        self.env["ua.change.log"].undo_accept_period(year, month)
        return True

    @api.model
    def action_close_month_plan(self, ids=False, year=None, month=None):
        """План перед закриттям місяця (action-model.md, клас «проведення»).

        Самі рядки складає ua.period.close.plan() - там же, де живуть перевірки
        close_period(); екран лише розпаковує період із id кнопки."""
        year, month = self._decode_period(ids, year, month)
        return self.env["ua.period.close"].plan(self._company(), year, month)

    @api.model
    def action_close_month(self, ids=False, year=None, month=None, hard=False):
        """Закрити місяць: перевірити блокери і поставити дату блокування.

        Перешкоди перевіряє ua.period.close.close_period() - і відмовляє (UserError),
        якщо вони є, навіть якщо діалог плану якось обійшли."""
        year, month = self._decode_period(ids, year, month)
        close_id = self.env["ua.period.close"].close_period(year, month, hard)
        rec = self.env["ua.period.close"].browse(close_id)
        return {"done": [{
            "text": _("Місяць %s закрито: дата блокування обліку %s.") % (
                rec.name, rec.lock_date.strftime("%d.%m.%Y") if rec.lock_date else ""),
            "target": {"model": "ua.period.close", "res_id": close_id},
        }]}

    @api.model
    def action_open_close_record(self, year, month):
        """Відкрити картку закриття періоду (там причина і кнопка «Відкрити знову»).

        Запис шукає і за потреби заводить ua.period.close.ensure_for()."""
        rec = self.env["ua.period.close"].ensure_for(self._company(), year, month)
        return self.open_target({"model": "ua.period.close", "res_id": rec.id})

    @api.model
    def action_close_quarter(self, year, quarter):
        return self.env["ua.period.close"].close_quarter(year, quarter)

    @api.model
    def action_close_year(self, year):
        return self.env["ua.period.close"].close_year(year)

    @api.model
    def action_prepare_month(self, year, month):
        """Підготувати місяць: процедура hr.payslip.run.ua_prepare_month().

        Саме відкриття місяця (табель, пакет, чернетки листків, перерахунок) живе
        там, де створюються його записи; екран лише натискає кнопку."""
        return self.env["hr.payslip.run"].ua_prepare_month(self._company(), year, month)

    @api.model
    def action_headline(self, year, month, action):
        """Головна дія робочого місця. Повертає повідомлення або дію Odoo."""
        year, month = int(year), int(month)
        if action == "prepare":
            return self.action_prepare_month(year, month)
        if action == "close":
            self.env["ua.period.close"].close_period(year, month)
            return {"message": _("Місяць закрито.")}
        company = self._company()
        first, last = self._bounds(year, month)
        steps = {step["key"]: step for step in self._steps(company, year, month, first, last)}
        step = steps.get(action)
        if step:
            return self.open_target(step["action"])
        raise UserError(_("Невідома дія."))
