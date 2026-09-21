# -*- coding: utf-8 -*-
"""Сторінка «Люди»: один екран замість чотирьох пунктів меню («Картки працівників»,
«Оргструктура», «Підрозділи», «Штатні розписи»), які показували той самий факт -
хто працює, в якому підрозділі, на якій посаді, на яку ставку і за який оклад -
кожен по-своєму.

Один набір даних (`_dataset`), чотири погляди на нього: «Перелік» - рядками,
«За підрозділами» - згруповано з підсумком, «Схема» - підпорядкування від
`parent_id`, «Штатний розпис» - той самий склад у формі документа. Кожен погляд
лише по-різному показує один і той самий перелік працівників (`_row` - одна форма
рядка на «Перелік» і на групування за підрозділами) - жодна гілка не рахує людей
по-своєму (спека, «Чотири погляди - це один набір даних»).

Модуль своїх даних не тримає (як l10n_ua_home і l10n_ua_papers): читає з hr.employee,
hr.version і hr.department, а для порівняння - з наявного ua.staff.list. Пише лише
run_action("create_staff_list") - справжній документ ua.staff.list, який після
цього живе в «Паперах», як решта паперів.

ЦПХ і ФОП (hr.employee.ua_contract_kind) у цей екран не входять - правило бухгалтера
Лани, 2026-09-16, те саме, що вже зашите в доменах карток/оргструктури/підрозділів
(l10n_ua_navigation/views/menus_areas.xml).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

EXCLUDED_KINDS = ("gph", "fop")
VIEWS = ("list", "departments", "chart", "staff")
MONTHS_OF = {
    1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня",
    7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня",
}


class UaPeople(models.AbstractModel):
    _name = "ua.people"
    _inherit = ["ua.screen"]
    _description = "Дані екрана «Люди»"

    # ------------------------------------------------------------------ хелпери
    # _company / _plural / open_target - у ua.screen
    @staticmethod
    def _fmt_num(v, digits=1):
        """Число українською без зайвого нуля: 11,5 і 17, не 11,50 і 17,0."""
        text = ("{:,.%df}" % digits).format(v or 0.0).replace(",", " ").replace(".", ",")
        return text.rstrip("0").rstrip(",") if "," in text else text

    @staticmethod
    def _fmt_date(d):
        if not d:
            return ""
        return "%s %s %s" % (d.day, MONTHS_OF.get(d.month, ""), d.year)

    @staticmethod
    def _t_record(record):
        """Ціль на конкретний запис - та сама форма, що приймає open_target."""
        if not record:
            return None
        return {"model": record._name, "res_id": record.id}

    @staticmethod
    def _job_of(emp):
        """Посада: професійна назва з чинної версії, тоді штатна назва версії, тоді
        поле картки - той самий ланцюжок, що й ua.staff.list.action_refill."""
        version = emp.version_id
        return (version and (version.ua_prof_name or version.job_title)) or emp.job_title or "-"

    @staticmethod
    def _fte_of(emp):
        return float(emp.ua_fte or "1")

    @staticmethod
    def _wage_of(emp):
        return emp.version_id.wage or 0.0

    # ------------------------------------------------------------------ один набір даних
    def _dataset(self, company, search, department):
        """Один запит, один перелік: активні працівники компанії за трудовим договором
        (без ЦПХ і ФОП), звужений пошуком і підрозділом, якщо задані. Кожен з чотирьох
        поглядів будує своє подання лише з цього переліку - жоден не рахує людей
        по-своєму (спека «Люди», «Чотири погляди - це один набір даних»)."""
        domain = [
            ("company_id", "=", company.id), ("active", "=", True),
            ("ua_contract_kind", "not in", list(EXCLUDED_KINDS)),
        ]
        if department:
            domain.append(("department_id", "=", int(department)))
        employees = self.env["hr.employee"].sudo().search(domain, order="name")
        if search:
            text = search.strip().lower()
            employees = employees.filtered(lambda e: (
                text in (e.name or "").lower()
                or text in (self._job_of(e) or "").lower()
                or text in (e.department_id.name or "").lower()
                or text in (e.ua_rnokpp or "").lower()
            ))
        return employees

    def _row(self, emp):
        """Один рядок працівника - та сама форма і в «Переліку», і в групуванні за
        підрозділами: жодних двох способів показати одну людину."""
        return {
            "id": emp.id, "name": emp.name, "job": self._job_of(emp),
            "department": emp.department_id.name or "-",
            "fte": self._fte_of(emp), "wage": self._wage_of(emp),
            "kind": emp.ua_contract_kind or "employment",
            "target": self._t_record(emp),
        }

    # ------------------------------------------------------------------ підсумок (завжди по всій компанії)
    def _summary(self, employees):
        """Шапка екрана: не залежить від пошуку чи вибраного погляду - орієнтир, скільки
        людей у компанії загалом, а не скільки зараз показано на екрані."""
        dept_ids = {e.department_id.id for e in employees if e.department_id}
        units = sum(self._fte_of(e) for e in employees)
        fund = sum(self._fte_of(e) * self._wage_of(e) for e in employees)
        return {"people": len(employees), "departments": len(dept_ids), "units": units, "fund": fund}

    # ------------------------------------------------------------------ погляд «Перелік»
    def _list_rows(self, employees):
        return [self._row(e) for e in employees]

    # ------------------------------------------------------------------ погляд «За підрозділами»
    def _departments(self, employees):
        """Групування «Переліку» за підрозділом: підсумок людей, ставок і фонду рахується
        з тих самих рядків _row, що й «Перелік» - не окремим запитом."""
        groups = {}
        order = []
        for emp in employees:
            dept = emp.department_id
            key = dept.id if dept else False
            if key not in groups:
                groups[key] = {"dept": dept, "rows": []}
                order.append(key)
            groups[key]["rows"].append(self._row(emp))

        out = []
        for key in order:
            g = groups[key]
            dept, rows = g["dept"], g["rows"]
            out.append({
                "id": dept.id if dept else False,
                "name": dept.name if dept else "без підрозділу",
                "people": len(rows),
                "units": sum(r["fte"] for r in rows),
                "fund": sum(r["fte"] * r["wage"] for r in rows),
                "rows": rows,
                "target": self._t_record(dept) if dept else None,
            })
        out.sort(key=lambda d: (d["id"] is False, d["name"]))
        return out

    # ------------------------------------------------------------------ погляд «Схема»
    def _chart(self, employees):
        """Підпорядкування від parent_id. manager_id веде лише на людину, яка теж є в цьому
        переліку (інакше клієнт не зміг би побудувати дерево з того, що йому повернули) -
        того, чийого керівника немає в переліку, показуємо коренем свого піддерева."""
        ids = set(employees.ids)
        rows = []
        for emp in employees:
            manager = emp.parent_id
            manager_id = manager.id if manager and manager.id in ids else False
            rows.append({
                "id": emp.id, "name": emp.name, "job": self._job_of(emp),
                "manager_id": manager_id, "target": self._t_record(emp),
            })
        return rows

    # ------------------------------------------------------------------ погляд «Штатний розпис»
    def _diff_text(self, diff):
        if abs(diff) < 0.01:
            return "не відрізняється"
        word = self._plural(abs(diff), "одиницю", "одиниці", "одиниць")
        return "відрізняється на %s %s" % (self._fmt_num(abs(diff)), word)

    def _staff(self, company, employees):
        """Поточний склад у формі документа: групування підрозділ+посада+код КП+оклад,
        той самий ланцюжок полів, що й ua.staff.list.action_refill (щоб рядок екрана і
        рядок майбутнього документа збігалися один в один). Порівняння - з чинним
        (затвердженим) ua.staff.list на цю дату, якщо він є."""
        today = fields.Date.context_today(self)
        rows = {}
        order = []
        for emp in employees:
            version = emp.version_id
            dept = emp.department_id
            job = self._job_of(emp)
            kp_code = (version and version.ua_kp_code) or ""
            wage = self._wage_of(emp)
            key = (dept.id if dept else False, job, kp_code, wage)
            if key not in rows:
                rows[key] = {"department": dept.name if dept else "без підрозділу",
                            "job": job, "kp_code": kp_code, "units": 0.0, "wage": wage, "fund": 0.0}
                order.append(key)
            r = rows[key]
            r["units"] += self._fte_of(emp)
            r["fund"] = r["units"] * r["wage"]

        lines = [rows[k] for k in order]
        lines.sort(key=lambda r: (r["department"], r["job"]))
        totals = {"units": sum(l["units"] for l in lines), "fund": sum(l["fund"] for l in lines)}

        current = None
        chinnyy = self.env["ua.staff.list"].sudo().search([
            ("company_id", "=", company.id), ("date", "<=", today), ("state", "=", "confirmed"),
        ], order="date desc, id desc", limit=1)
        if chinnyy:
            diff_units = totals["units"] - chinnyy.total_units
            current = {
                "name": "від %s" % self._fmt_date(chinnyy.date),
                "target": self._t_record(chinnyy),
                "diff_units": diff_units,
                "diff_text": self._diff_text(diff_units),
            }

        return {"as_of": self._fmt_date(today), "lines": lines, "totals": totals, "current": current}

    # ------------------------------------------------------------------ екран
    @api.model
    def get_screen_data(self, view="list", search="", department=None):
        """Дані екрана. Читання, нічого не пише: жодного create/write/unlink ні тут, ні
        в жодному методі вище - запис створює лише run_action("create_staff_list"),
        окремий виклик за кнопкою, а не побічно від відкриття екрана."""
        company = self._company()
        view = view if view in VIEWS else "list"
        search = search or ""
        department = int(department) if department else None

        full = self._dataset(company, "", None)
        scoped = self._dataset(company, search, department)

        data = {
            "summary": self._summary(full),
            "view": view,
            "search": search,
            "rows": None,
            "departments": None,
            "chart": None,
            "staff": None,
        }
        if view == "list":
            data["rows"] = self._list_rows(scoped)
        elif view == "departments":
            data["departments"] = self._departments(scoped)
        elif view == "chart":
            data["chart"] = self._chart(scoped)
        else:
            data["staff"] = self._staff(company, scoped)
        return data

    # ------------------------------------------------------------------ дії
    @api.model
    def run_action(self, action_key, params=None):
        if action_key != "create_staff_list":
            raise UserError(_("Невідома дія: %s") % action_key)
        company = self._company()
        today = fields.Date.context_today(self)
        doc = self.env["ua.staff.list"].create({"company_id": company.id, "date": today})
        doc.action_refill()
        return self.open_target(self._t_record(doc))
