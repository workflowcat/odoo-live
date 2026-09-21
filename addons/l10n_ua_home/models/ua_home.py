# -*- coding: utf-8 -*-
"""Сторінка «Домівка»: карта п'яти розділів системи з потоком між ними і особиста панель
праворуч - що зробити зараз, що змінилося останнім часом і хто це зробив, чернетки користувача.

Працює для будь-якого місяця, не лише поточного. Дані беруться з уже наявних моделей (як і
в l10n_ua_period): накази, документи працівників, справи прийняття, військовий облік, табель,
аванс, листки, виписка банку, звітність, анкета компанії, журнал змін. Своїх даних модуль
не тримає.

Ціль (`target`) відкривається через `open_target` - спільний договір екранів
(l10n_ua_screen.ua.screen), той самий на всіх екранах: xmlid, конкретний запис або
список за доменом. Смуга місяців - `_period_block` звідти ж.
"""
from odoo import SUPERUSER_ID, api, fields, models

from odoo.addons.l10n_ua_screen.models.ua_screen import MONTHS_UA

SEVERITY = {"crit": 0, "warn": 1, "done": 2}
# area з ua.change.log -> ключ розділу «Домівки»: кадри/час - «люди», облік - разом із зарплатою.
AREA_MAP = {"hr": "people", "time": "people", "payroll": "payroll", "account": "payroll",
            "bank": "bank", "report": "reporting", "setup": "setup"}
# «Стан X» (значення what з ua.change.log, див. l10n_ua_changes/models/tracked.py) -> іменник
# у трьох формах лічби, для згортання однотипних сусідніх рядків «Свіжого» (див. _recent):
# "7 проводок", а не сім однакових рядків "Стан проводки". Чого нема в словнику - лишається
# під загальним "подія/події/подій", а не ламаною грамотикою.
WHAT_NOUN = {
    "Стан наказу": ("наказ", "накази", "наказів"),
    "Стан табеля": ("табель", "табелі", "табелів"),
    "Стан листка": ("листок", "листки", "листків"),
    "Стан відсутності": ("відсутність", "відсутності", "відсутностей"),
    "Стан проводки": ("проводка", "проводки", "проводок"),
    "Стан відомості": ("відомість", "відомості", "відомостей"),
    "Стан авансу": ("аванс", "аванси", "авансів"),
    "Стан звіту": ("звіт", "звіти", "звітів"),
}
# Логіни службових акаунтів цієї бази - не людей за клавіатурою, а інтеграцій (чат-помічник
# працівників, перегляд payroll-review). Odoo не має поля "бот чи людина": ні share, ні active,
# ні hr.employee, ні res.users.apikeys цих акаунтів від людських (admin/lana) не відрізняють -
# перевірено прямим запитом до бази. Сам бот ядра (OdooBot) розпізнається надійно через
# SUPERUSER_ID, тому в списку лишається тільки те, чого код сам не знає.
AUTOMATIC_LOGINS = {"assistant", "viewer_tmp"}


class UaHome(models.AbstractModel):
    _name = "ua.home"
    _inherit = ["ua.screen"]
    _description = "Дані екрана «Домівка»"

    # П'ять розділів у фіксованому порядку: ключ, позначка, назва, xmlid кореневого меню.
    REGIONS = [
        ("people", "ПР", "Працівники", "l10n_ua_navigation.menu_ua_people_root"),
        ("payroll", "ЗП", "Зарплата", "l10n_ua_period.menu_ua_period_root"),
        ("bank", "БН", "Банк", "l10n_ua_bank_ui.menu_ua_bank_board"),
        ("reporting", "ЗВ", "Звітність", "l10n_ua_reporting_ui.menu_ua_reporting_root"),
        ("setup", "НЛ", "Налаштування зарплати", "l10n_ua_navigation.menu_ua_setup_root"),
    ]

    # ------------------------------------------------------------------ хелпери
    # _company / _bounds / _plural / MONTHS_UA / open_target - у ua.screen
    @staticmethod
    def _is_automatic(user):
        """Чи належить запис журналу не людині, а автоматиці - див. AUTOMATIC_LOGINS вище."""
        return user.id == SUPERUSER_ID or user.login in AUTOMATIC_LOGINS

    @staticmethod
    def _feat(region, level, badge, target, todo=None, hint=None):
        """Один факт екрана: живить і бейдж розділу, і рядок «зробити», якщо todo задано.
        Факт зі станом "done" todo не має - вже зроблене нікуди йти не повинно."""
        return {"region": region, "level": level, "badge": badge, "target": target,
                "todo": todo, "hint": hint}

    # ------------------------------------------------------------------ меню як його бачить користувач
    def _visible_leaves(self, root):
        """Листові пункти меню під коренем, видимі поточному користувачу, у порядку меню (DFS).

        «Листок» - видимий пункт без видимих дітей: якщо всі діти папки невидимі (немає прав),
        сама папка теж не рахується екраном. Так count/items завжди відповідають тому, що
        людина реально бачить у навігації, а не структурі XML."""
        if not root:
            return []
        visible_ids = self.env["ir.ui.menu"]._visible_menu_ids()
        leaves = []

        def walk(menu):
            children = menu.child_id.filtered(lambda m: m.id in visible_ids)
            if children:
                for child in children:
                    walk(child)
            elif menu.id in visible_ids:
                leaves.append(menu)

        walk(root)
        return leaves

    def _menu_target(self, menu):
        """xmlid дії пункту меню - той самий xmlid, який `open_target` уміє розкрити."""
        if not menu or not menu.action:
            return None
        action = menu.action
        xmlid = action.get_external_id().get(action.id)
        return {"xmlid": xmlid} if xmlid else None

    # ------------------------------------------------------------------ факти: люди
    def _feat_documents(self, company):
        """Документи на підпис - стан не прив'язаний до місяця, це наскрізний перелік."""
        docs = self.env["ua.employee.document"].search([
            ("employee_id.company_id", "=", company.id), ("employee_id.active", "=", True),
            ("state", "=", "to_sign"),
        ])
        n = len(docs)
        if not n:
            return None
        target = {"model": "ua.employee.document",
                  "domain": [("employee_id.company_id", "=", company.id), ("state", "=", "to_sign")],
                  "name": "Документи на підпис"}
        word = self._plural(n, "папір", "папери", "паперів")
        return self._feat("people", "crit", "%s %s на підпис" % (n, word), target,
                          todo="Підписати %s %s" % (n, word),
                          hint="Кадрові документи, які потребують підпису працівника чи директора.")

    def _feat_hire(self, company):
        if "ua.hire.case" not in self.env:
            return None
        cases = self.env["ua.hire.case"].search([
            ("company_id", "=", company.id), ("stage", "in", ("candidate", "onboarding"))])
        n = len(cases)
        if not n:
            return None
        target = {"model": "ua.hire.case",
                  "domain": [("company_id", "=", company.id), ("stage", "in", ("candidate", "onboarding"))],
                  "name": "Справи прийняття"}
        return self._feat("people", "warn",
                          "%s %s прийняття" % (n, self._plural(n, "справа", "справи", "справ")), target,
                          todo="Завершити %s %s прийняття" % (n, self._plural(n, "справу", "справи", "справ")),
                          hint="Справа кандидата чи оформлення, яку ще не завершено.")

    def _feat_orders(self, company, first, last):
        orders = self.env["ua.hr.order"].search([
            ("company_id", "=", company.id), ("date", ">=", first), ("date", "<=", last),
            ("state", "=", "draft"),
        ])
        n = len(orders)
        if not n:
            return None
        target = {"model": "ua.hr.order",
                  "domain": [("company_id", "=", company.id), ("date", ">=", str(first)),
                             ("date", "<=", str(last)), ("state", "=", "draft")],
                  "name": "Накази в чернетці"}
        word = self._plural(n, "наказ", "накази", "наказів")
        return self._feat("people", "warn", "%s %s в чернетці" % (n, word), target,
                          todo="Провести %s %s" % (n, word),
                          hint="Кадровий наказ, який ще не проведено.")

    def _feat_leaves(self, company, first, last):
        leaves = self.env["hr.leave"].search([
            ("employee_id.company_id", "=", company.id), ("state", "in", ("confirm", "validate1")),
            ("request_date_from", "<=", last), ("request_date_to", ">=", first),
        ])
        n = len(leaves)
        if not n:
            return None
        target = {"model": "hr.leave",
                  "domain": [("employee_id.company_id", "=", company.id), ("state", "in", ("confirm", "validate1")),
                             ("request_date_from", "<=", str(last)), ("request_date_to", ">=", str(first))],
                  "name": "Заяви на погодженні"}
        return self._feat("people", "warn",
                          "%s %s на погодженні" % (n, self._plural(n, "заява", "заяви", "заяв")), target,
                          todo="Погодити %s %s" % (n, self._plural(n, "заяву", "заяви", "заяв")),
                          hint="Заява на відпустку чи лікарняний очікує погодження.")

    def _feat_military(self, company):
        if "ua_mil_needs_check" not in self.env["hr.employee"]._fields:
            return None
        employees = self.env["hr.employee"].search([
            ("company_id", "=", company.id), ("active", "=", True), ("ua_mil_needs_check", "=", True)])
        n = len(employees)
        if not n:
            return None
        target = {"model": "hr.employee",
                  "domain": [("company_id", "=", company.id), ("ua_mil_needs_check", "=", True)],
                  "name": "Звірка ТЦК"}
        return self._feat("people", "warn",
                          "%s %s без звірки ТЦК" % (n, self._plural(n, "працівник", "працівники", "працівників")),
                          target,
                          todo="Оновити звірку ТЦК для %s %s"
                               % (n, self._plural(n, "працівника", "працівників", "працівників")),
                          hint="Дані військового обліку не звірялися понад рік або відсутні.")

    # ------------------------------------------------------------------ факти: зарплата
    def _feat_payslips(self, company, first, last, month):
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", company.id), ("date_from", ">=", first), ("date_from", "<=", last),
            ("state", "!=", "cancel"),
        ])
        drafts = slips.filtered(lambda s: s.state == "draft")
        if drafts:
            n = len(drafts)
            target = {"model": "hr.payslip",
                      "domain": [("company_id", "=", company.id), ("date_from", ">=", str(first)),
                                 ("date_from", "<=", str(last)), ("state", "=", "draft")],
                      "name": "Листки в чернетці"}
            word = self._plural(n, "листок", "листки", "листків")
            return self._feat("payroll", "crit", "%s %s не підтверджено" % (n, word), target,
                              todo="Підтвердити %s %s за %s" % (n, word, MONTHS_UA[month]),
                              hint="Нарахування, утримання і внески за кожним працівником.")
        if slips and all(s.state == "done" for s in slips):
            n = len(slips)
            target = {"model": "hr.payslip",
                      "domain": [("company_id", "=", company.id), ("date_from", ">=", str(first)),
                                 ("date_from", "<=", str(last))],
                      "name": "Розрахункові листки"}
            return self._feat("payroll", "done",
                              "%s %s проведено" % (n, self._plural(n, "листок", "листки", "листків")), target)
        return None

    def _feat_timesheet(self, company, year, month):
        sheet = self.env["ua.timesheet.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month),
            ("department_id", "=", False),
        ], limit=1)
        if sheet and sheet.state == "confirmed":
            return self._feat("payroll", "done", "табель затверджено",
                              {"model": "ua.timesheet.sheet", "res_id": sheet.id})
        if sheet:
            return self._feat("payroll", "warn", "табель не затверджено",
                              {"model": "ua.timesheet.sheet", "res_id": sheet.id},
                              todo="Затвердити табель за %s" % MONTHS_UA[month],
                              hint="Дні і години кожного працівника за місяць.")
        return self._feat("payroll", "warn", "табеля немає",
                          {"xmlid": "l10n_ua_hr_docs.action_ua_timesheet_sheet"},
                          todo="Заповнити табель за %s" % MONTHS_UA[month],
                          hint="Дні і години кожного працівника за місяць.")

    def _feat_advance(self, company, year, month):
        sheet = self.env["ua.advance.sheet"].search([
            ("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)], limit=1)
        if sheet:
            return None
        return self._feat("payroll", "warn", "аванс не розраховано",
                          {"xmlid": "l10n_ua_payroll_rules.action_ua_advance_wizard"},
                          todo="Розрахувати аванс за %s" % MONTHS_UA[month],
                          hint="Виплата за першу половину місяця за відсотком окладу.")

    # ------------------------------------------------------------------ факти: банк
    def _feat_bank(self, company, first, last):
        lines = self.env["account.bank.statement.line"].search([
            ("company_id", "=", company.id), ("is_reconciled", "=", False),
            ("date", ">=", first), ("date", "<=", last),
        ])
        n = len(lines)
        if not n:
            return None
        target = {"model": "account.bank.statement.line",
                  "domain": [("company_id", "=", company.id), ("is_reconciled", "=", False),
                             ("date", ">=", str(first)), ("date", "<=", str(last))],
                  "name": "Незвірені рядки виписки"}
        word = self._plural(n, "рядок", "рядки", "рядків")
        return self._feat("bank", "warn", "%s %s не звірено" % (n, word), target,
                          todo="Звірити %s %s виписки" % (n, word),
                          hint="Рядок виписки ще не зіставлено з платежем чи податком.")

    # ------------------------------------------------------------------ факти: звітність
    def _feat_reporting_j05(self, company, year, month):
        run = self.env["ua.report.run"].search([
            ("company_id", "=", company.id), ("report_code", "=", "j05"),
            ("year", "=", year), ("month", "=", month), ("doc_kind", "=", "HZ"),
        ], limit=1)
        target = {"model": "ua.report.run", "res_id": run.id} if run \
            else {"xmlid": "l10n_ua_reporting_ui.action_ua_reporting"}
        if run and run.state == "submitted":
            return self._feat("reporting", "done", "J0500111 подано", target)
        if run and run.state == "generated":
            return self._feat("reporting", "warn", "J0500111 сформовано, не подано", target,
                              todo="Подати J0500111",
                              hint="Податковий розрахунок з додатками Д1, 4ДФ і Д5.")
        return self._feat("reporting", "warn", "J0500111 не сформовано", target,
                          todo="Сформувати J0500111",
                          hint="Податковий розрахунок з додатками Д1, 4ДФ і Д5.")

    def _feat_reporting_other(self, company, year, month):
        runs = self.env["ua.report.run"].search([
            ("company_id", "=", company.id), ("report_code", "!=", "j05"),
            ("year", "=", year), ("month", "=", month), ("state", "in", ("checked", "generated", "submitted")),
        ])
        n = len(runs)
        if not n:
            return None
        return self._feat("reporting", "done",
                          "%s %s перевірено чи краще" % (n, self._plural(n, "звіт", "звіти", "звітів")),
                          {"xmlid": "l10n_ua_reporting_ui.action_ua_reporting"})

    # ------------------------------------------------------------------ факти: налаштування
    def _feat_setup(self, company):
        if "ua.setup.profile" not in self.env:
            return None
        profile = self.env["ua.setup.profile"].search([("company_id", "=", company.id)], limit=1)
        if not profile or not profile.required_missing:
            return None
        return self._feat("setup", "warn",
                          "%s обов'язкових питань без відповіді" % profile.required_missing,
                          {"model": "ua.setup.profile", "res_id": profile.id},
                          todo="Заповнити анкету компанії",
                          hint="Обов'язкові питання анкети компанії лишаються без відповіді.")

    # ------------------------------------------------------------------ розділи, черга, бейджі
    def _regions(self, features):
        by_region = {}
        for f in features:
            by_region.setdefault(f["region"], []).append(f)
        out = []
        for key, mark, name, root_xmlid in self.REGIONS:
            root = self.env.ref(root_xmlid, raise_if_not_found=False)
            leaves = self._visible_leaves(root)
            action = self._menu_target(leaves[0]) if leaves else None
            region_feats = by_region.get(key, [])
            badges = sorted(region_feats, key=lambda f: SEVERITY.get(f["level"], 9))[:3]
            out.append({
                "key": key, "mark": mark, "name": name,
                "count": len(leaves),
                # Кожен пункт - своя ціль (той самий xmlid, що й у action вище), не просто текст:
                # список повний (усі листки меню), скільки з них показати картці - вирішує фронт.
                "items": [{"name": leaf.name, "target": self._menu_target(leaf)} for leaf in leaves],
                "action": action,
                "tasks": sum(1 for f in region_feats if f.get("todo")),
                "badges": [{"level": f["level"], "text": f["badge"], "target": f["target"]} for f in badges],
            })
        return out

    # Рівень із «Зведення» словами «Домівки»: danger - критично, решта - увага.
    ATTENTION_LEVEL = {"danger": "crit", "warning": "warn", "info": "warn"}

    def _todo(self, features, company=None):
        rows = sorted((f for f in features if f.get("todo")), key=lambda f: SEVERITY.get(f["level"], 9))
        out = [{"level": f["level"], "text": f["todo"], "hint": f["hint"], "target": f["target"]} for f in rows]
        return out + self._todo_attention(company, out)

    def _todo_attention(self, company, already):
        """Те, що не прив'язане до місяця: документи спливають, бракує індексу цін,
        закінчується строковий договір або випробування, немає РНОКПП.

        Раніше це стояло чергою «Увага» на екрані місяця. Місяць звівся до кроків
        (docs/payroll/spec-period-v2.md), і речі, які місяця не стосуються, переїхали
        сюди: «Домівка» і є тим місцем, де написано, що зробити. Рядки, які «Домівка»
        вже рахує сама (ТЦК, анкета, виписка), не дублюємо."""
        if not company:
            return []
        Dashboard = self.env["ua.dashboard"].sudo()
        if not hasattr(Dashboard, "_get_attention"):
            return []
        seen = {(row["text"] or "").lower() for row in already}
        out = []
        for row in Dashboard._get_attention(company):
            title = (row.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            target = row.get("target") or None
            out.append({"level": self.ATTENTION_LEVEL.get(row.get("level"), "warn"),
                        "text": title, "hint": row.get("detail") or "", "target": target})
            seen.add(title.lower())
        return out

    # ------------------------------------------------------------------ нещодавнє і чернетки
    def _recent(self, company, year, month):
        """До 30 рядків «Свіжого». Масова дія (провести десятки банківських проводок одним
        махом) пише десятки однакових рядків журналу підряд - сусідні рядки з однаковим what
        (що змінено), автором і днем згортаємо в один рядок з лічбою («7 проводок · OdooBot ·
        16.09»), а ціль лишаємо від найновішого запису групи, щоб рядок і далі відкривав щось
        реальне. Поодинокі рядки лишаються як є. Читаємо із запасом (300, не 30) - інакше згортання
        з'їло б хвіст і повернуло менше за 30 рядків там, де їх насправді вистачає."""
        Log = self.env["ua.change.log"]
        logs = Log.search([("company_id", "=", company.id), ("year", "=", year), ("month", "=", month)],
                          order="date desc, id desc", limit=300)
        operation_labels = dict(Log._fields["operation"].selection)
        area_labels = dict(Log._fields["area"].selection)
        raw = []
        for log in logs:
            what = log.what or operation_labels.get(log.operation) or area_labels.get(log.area, "")
            target = None
            if log.res_id and log.model_name in self.env:
                target = {"model": log.model_name, "res_id": log.res_id}
            raw.append({
                "what": what,
                "name": log.res_name,
                "who": log.user_id.name or "Система",
                "when": log.date.strftime("%d.%m") if log.date else "",
                "area": AREA_MAP.get(log.area, log.area),
                "target": target,
                "automatic": self._is_automatic(log.user_id),
            })

        groups = []
        for entry in raw:
            key = (entry["what"], entry["who"], entry["when"])
            if groups and groups[-1]["key"] == key:
                groups[-1]["count"] += 1
            else:
                groups.append({"key": key, "count": 1, "row": entry})

        rows = []
        for group in groups[:30]:
            n = group["count"]
            row = group["row"]
            if n == 1:
                rows.append(row)
                continue
            what, who, when = group["key"]
            one, few, many = WHAT_NOUN.get(what, ("подія", "події", "подій"))
            rows.append({
                "what": "%s %s" % (n, self._plural(n, one, few, many)),
                "name": "",
                "who": who,
                "when": when,
                "area": row["area"],
                "target": row["target"],
                "automatic": row["automatic"],
            })
        return rows

    def _drafts(self, company):
        user = self.env.user
        rows = []

        for order in self.env["ua.hr.order"].search([
                ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
            rows.append({"title": order.name or "Наказ без номера", "subtitle": order.employee_id.name or "",
                        "target": {"model": "ua.hr.order", "res_id": order.id}})

        for batch in self.env["ua.payment.batch"].search([
                ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
            rows.append({"title": batch.name or "Відомість без назви",
                        "subtitle": "%s %s" % (MONTHS_UA.get(batch.month, "").capitalize(), batch.year),
                        "target": {"model": "ua.payment.batch", "res_id": batch.id}})

        for sheet in self.env["ua.advance.sheet"].search([
                ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
            rows.append({"title": sheet.name or "Авансова відомість без назви",
                        "subtitle": "%s %s" % (MONTHS_UA.get(sheet.month, "").capitalize(), sheet.year),
                        "target": {"model": "ua.advance.sheet", "res_id": sheet.id}})

        for run in self.env["ua.report.run"].search([
                ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
            rows.append({"title": run.name or "Звіт без назви",
                        "subtitle": dict(run._fields["report_code"].selection).get(run.report_code, ""),
                        "target": {"model": "ua.report.run", "res_id": run.id}})

        if "ua.military.list" in self.env:
            for mlist in self.env["ua.military.list"].search([
                    ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
                rows.append({"title": mlist.name or "Список без назви", "subtitle": mlist.tcc or "",
                            "target": {"model": "ua.military.list", "res_id": mlist.id}})

        if "ua.military.notice" in self.env:
            for notice in self.env["ua.military.notice"].search([
                    ("company_id", "=", company.id), ("state", "=", "draft"), ("create_uid", "=", user.id)]):
                d1 = notice.date_from.strftime("%d.%m") if notice.date_from else ""
                d2 = notice.date_to.strftime("%d.%m") if notice.date_to else ""
                rows.append({"title": notice.name or "Повідомлення без назви", "subtitle": "%s - %s" % (d1, d2),
                            "target": {"model": "ua.military.notice", "res_id": notice.id}})

        if "ua.hire.case" in self.env:
            stage_labels = dict(self.env["ua.hire.case"]._fields["stage"].selection)
            for case in self.env["ua.hire.case"].search([
                    ("company_id", "=", company.id), ("stage", "in", ("candidate", "onboarding")),
                    ("create_uid", "=", user.id)]):
                rows.append({"title": case.name or "Кандидат без імені",
                            "subtitle": case.job_title or stage_labels.get(case.stage, ""),
                            "target": {"model": "ua.hire.case", "res_id": case.id}})

        return rows

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, year=None, month=None):
        company = self._company()
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        first, last = self._bounds(year, month)

        features = [f for f in (
            self._feat_documents(company),
            self._feat_hire(company),
            self._feat_orders(company, first, last),
            self._feat_leaves(company, first, last),
            self._feat_military(company),
            self._feat_payslips(company, first, last, month),
            self._feat_timesheet(company, year, month),
            self._feat_advance(company, year, month),
            self._feat_bank(company, first, last),
            self._feat_reporting_j05(company, year, month),
            self._feat_reporting_other(company, year, month),
            self._feat_setup(company),
        ) if f]

        employees = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True),
            ("ua_contract_kind", "not in", ("gph", "fop"))])
        gph = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id), ("active", "=", True), ("ua_contract_kind", "=", "gph")])

        return {
            "period": self._period_block(year, month),
            "company": {"name": company.name, "employees": employees, "gph": gph},
            "regions": self._regions(features),
            "flows": [["people", "payroll"], ["payroll", "bank"], ["payroll", "reporting"], ["setup", "payroll"]],
            "todo": self._todo(features, company),
            "recent": self._recent(company, year, month),
            "drafts": self._drafts(company),
            "unseen_changes": self.env["ua.change.log"].count_new(company, year, month),
        }
