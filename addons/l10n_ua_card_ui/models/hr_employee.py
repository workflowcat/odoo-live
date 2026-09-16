"""Дані і дії картки працівника на OWL (див. docs/payroll/spec-owl-card.md).

get_card_data() збирає в один виклик усе, що картка малює: шапку, три колонки
(особа; оплата і відпустка; військовий облік і документи) і хроніку. Кожен рядок
"поле - значення" вже відформатований українською (дати ДД.ММ.РРРР, суми округлені,
порожні значення - словом "немає"), щоб OWL-шаблон лише малював рядки, не рахував нічого.

Кнопки картки викликають action_ua_card_* методи нижче; кожен повертає або словник дії
(act_window/report - JS відкриває його через action.doAction), або False/None (JS просто
перечитує картку - так для «Записати звірку ТЦК», де форма не потрібна).
"""
from datetime import date

import json
from urllib.parse import urlencode

from odoo import fields, models
from odoo.exceptions import UserError

PAYSLIP_STATE_LABELS = {"draft": "чернетка", "verify": "очікує", "done": "проведено", "cancel": "скасовано"}


def _fmt_date(d):
    return d.strftime("%d.%m.%Y") if d else None


def _fmt_money(v):
    if v is None:
        return None
    return "{:,.2f}".format(v or 0.0).replace(",", "\u00a0").replace(".", ",")


def _fmt_num(v, digits=1):
    """Число українською: 11,5 і 17 без зайвого нуля."""
    if v is None:
        return None
    text = ("{:,.%df}" % digits).format(v or 0.0).replace(",", "\u00a0").replace(".", ",")
    return text.rstrip("0").rstrip(",") if "," in text else text


def _sel_label(record, field_name):
    """Людська мітка для Selection-поля record[field_name] мовою поточного контексту."""
    val = record[field_name]
    if not val:
        return None
    selection = dict(record.fields_get([field_name])[field_name]["selection"])
    return selection.get(val, val)


def _order(value):
    """Значення ua_order_ref/ua_end_order_ref вже містить слово "Наказ" (конвенція поля,
    напр. "Наказ № 9-к від 17.08.2026") - тут лише підставляємо заглушку, коли пусто."""
    return value or "наказ не вказано"


def _row(label, value, numeric=False):
    empty = value in (None, "", False)
    return {"label": label, "value": value if not empty else "немає", "numeric": numeric, "empty": empty}


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ------------------------------------------------------------------
    # Дані картки
    # ------------------------------------------------------------------
    def get_card_data(self):
        self.ensure_one()
        # lang=uk_UA примусово: інакше Selection-мітки і назви країн з ядра Odoo (стать, сімейний
        # стан, громадянство) виходять мовою інтерфейсу викликача, а не українською, як вимагає спека.
        emp = self.with_context(lang="uk_UA").sudo()
        version = emp.current_version_id
        today = fields.Date.context_today(self)

        # Пігулки шапки: перша - головна (status pill), решта - додаткові прапорці поруч.
        # Критичні (coral) переважають над попереджувальними (warn), «усе гаразд» - mint.
        badges = []
        if not emp.active:
            badges.append({"label": "Звільнений(а)", "css": "o_ua_pill_crit"})
        if emp.ua_mil_needs_check:
            badges.append({"label": "Потребує звірки ТЦК", "css": "o_ua_pill_warn"})
        if emp.ua_docs_expiring:
            badges.append({"label": f"Документи спливають ({emp.ua_docs_expiring})", "css": "o_ua_pill_warn"})
        expired_docs = emp.ua_document_ids.filtered(lambda d: d.ua_doc_state == "expired")
        if expired_docs:
            badges.append({"label": f"Документи прострочені ({len(expired_docs)})", "css": "o_ua_pill_crit"})
        to_sign_docs = emp.ua_document_ids.filtered(lambda d: d.state == "to_sign")
        if to_sign_docs:
            badges.append({"label": f"Документи на підпис ({len(to_sign_docs)})", "css": "o_ua_pill_warn"})
        if not emp.ua_rnokpp:
            badges.append({"label": "Немає РНОКПП", "css": "o_ua_pill_crit"})
        if not badges:
            badges.append({"label": "Усе гаразд", "css": "o_ua_pill_ok"})

        name_parts = (emp.name or "").split()
        initials = "".join(p[0] for p in name_parts[:2]).upper() or "?"

        since = version.contract_date_start if version else None

        header = {
            "name": emp.name or "",
            "initials": initials,
            "avatar_url": f"/web/image/hr.employee/{emp.id}/avatar_128",
            "job_title": emp.job_title or "немає",
            "department": emp.department_id.name or "немає",
            "company": emp.company_id.name or "немає",
            "manager": emp.parent_id.name or "немає",
            "badge_number": emp.barcode or str(emp.id),
            "since": _fmt_date(since) or "немає",
            "active": emp.active,
            "badges": badges,
        }

        # -- Особа --------------------------------------------------------------------
        id_doc_parts = []
        if emp.ua_id_doc_type:
            id_doc_parts.append(_sel_label(emp, "ua_id_doc_type"))
        if emp.ua_id_doc_series:
            id_doc_parts.append(emp.ua_id_doc_series)
        if emp.ua_id_doc_number:
            id_doc_parts.append("№ " + emp.ua_id_doc_number)
        id_doc = " ".join(id_doc_parts) if id_doc_parts else None

        reg_address = ", ".join(x for x in (emp.private_street, emp.private_city, emp.private_zip) if x) or None

        benefits = []
        if emp.ua_disability_group and emp.ua_disability_group != "none":
            benefits.append("інвалідність, " + _sel_label(emp, "ua_disability_group"))
        if emp.ua_chernobyl_category and emp.ua_chernobyl_category != "none":
            benefits.append("ЧАЕС, категорія " + emp.ua_chernobyl_category)
        if emp.ua_veteran:
            benefits.append("УБД / ветеран")
        if emp.ua_large_family:
            benefits.append("багатодітна сім'я")
        if emp.ua_single_parent:
            benefits.append("одинокий батько/мати")

        children_str = "; ".join(
            c.name + (f" ({_fmt_date(c.birthday)})" if c.birthday else "") for c in emp.ua_child_ids
        ) or None

        person = [
            _row("РНОКПП", emp.ua_rnokpp),
            _row("Документ", id_doc),
            _row("УНЗР", emp.ua_id_doc_unzr),
            _row("Дата народження", _fmt_date(emp.birthday)),
            _row("Стать", _sel_label(emp, "sex")),
            _row("Громадянство", emp.country_id.name),
            _row("Адреса реєстрації", reg_address),
            _row("Фактична адреса", emp.ua_actual_address),
            _row("Телефон", emp.mobile_phone or emp.private_phone or emp.work_phone),
            _row("Email", emp.work_email),
            _row("Сімейний стан", _sel_label(emp, "marital")),
            _row("Діти", children_str),
            _row("Пільги і статус", "; ".join(benefits) or None),
        ]

        # -- Оплата ---------------------------------------------------------------------
        psp_label = _sel_label(emp, "ua_psp")
        if emp.ua_psp in ("child", "child150") and emp.ua_psp_children:
            psp_label = f"{psp_label}, дітей: {emp.ua_psp_children}"
        pay = [
            _row("Оклад (поточний)", _fmt_money(emp.ua_current_wage), numeric=True),
            _row("Вид відносин", _sel_label(emp, "ua_contract_kind")),
            _row("Основне місце роботи", "внутрішнє сумісництво" if version and version.ua_internal_parttime
                 else ("так" if emp.ua_main_job else "ні")),
            _row("Ставка", _sel_label(emp, "ua_fte")),
            _row("Категорія ЄСВ", _sel_label(emp, "ua_esv_category")),
            _row("ПСП", psp_label),
            _row("Група інвалідності", _sel_label(emp, "ua_disability_group") if emp.ua_disability_group != "none" else None),
            _row("Страховий стаж, років", _fmt_num(emp.ua_insurance_years, 1) if emp.ua_insurance_years else None, numeric=True),
            _row("Відсоток лікарняних", f"{emp.ua_sick_percent:.0f} %" if emp.ua_sick_percent else None, numeric=True),
        ]

        # -- Відпустка --------------------------------------------------------------------
        opening = None
        opening_date = emp.ua_vacation_opening_date or emp.company_id.ua_vacation_opening_date
        if opening_date:
            opening = "%s (на %s)" % (_fmt_num(emp.ua_vacation_opening_balance), _fmt_date(opening_date))
        vacation = [
            _row("Днів на рік", str(emp.ua_vacation_days_year) if emp.ua_vacation_days_year else None, numeric=True),
            _row("Накопичено", _fmt_num(emp.ua_vacation_accrued), numeric=True),
            _row("Використано", _fmt_num(emp.ua_vacation_used), numeric=True),
            _row("Залишок", _fmt_num(emp.ua_vacation_balance), numeric=True),
            _row("Залишок на дату впровадження", opening, numeric=True),
        ]

        # -- Військовий облік ---------------------------------------------------------------
        mil_doc_parts = []
        if emp.ua_mil_doc_type:
            mil_doc_parts.append(_sel_label(emp, "ua_mil_doc_type"))
        if emp.ua_mil_doc_series:
            mil_doc_parts.append(emp.ua_mil_doc_series)
        if emp.ua_mil_doc_number:
            mil_doc_parts.append("№ " + emp.ua_mil_doc_number)
        mil_doc = " ".join(mil_doc_parts) if mil_doc_parts else None

        reserve = None
        if emp.ua_mil_reserved:
            reserve = "заброньований" + (f" до {_fmt_date(emp.ua_mil_reserve_until)}" if emp.ua_mil_reserve_until else "")
            if emp.ua_mil_reserve_order:
                reserve += f", {emp.ua_mil_reserve_order}"
        deferment = None
        if emp.ua_mil_deferment:
            deferment = emp.ua_mil_deferment + (f" до {_fmt_date(emp.ua_mil_deferment_until)}" if emp.ua_mil_deferment_until else "")

        cat_group = " / ".join(x for x in (_sel_label(emp, "ua_mil_category"), _sel_label(emp, "ua_mil_group")) if x) or None
        rank_vos = ", ".join(x for x in (emp.ua_mil_rank, ("ВОС " + emp.ua_mil_vos) if emp.ua_mil_vos else None) if x) or None

        military = [
            _row("Стан обліку", _sel_label(emp, "ua_mil_status")),
            _row("Категорія / група", cat_group),
            _row("Звання, ВОС", rank_vos),
            _row("ТЦК та СП", emp.ua_mil_tcc),
            _row("Документ", mil_doc),
            _row("Придатність", _sel_label(emp, "ua_mil_fitness")),
            _row("Дата ВЛК", _fmt_date(emp.ua_mil_vlk_date)),
            _row("Бронювання", reserve),
            _row("Відстрочка", deferment),
            _row("Дата звірки", _fmt_date(emp.ua_mil_last_check)),
            _row("Потребує звірки", "так" if emp.ua_mil_needs_check else "ні"),
        ]

        # -- Документи --------------------------------------------------------------------
        state_css = {"ok": "text-success", "warning": "text-warning", "expired": "text-danger"}
        documents = [{
            "id": d.id,
            "type": _sel_label(d, "type") or "немає",
            "name": d.name or "немає",
            "number": d.number or "немає",
            "date": _fmt_date(d.date) or "немає",
            "valid_until": _fmt_date(d.valid_until) or "безстроково",
            "state": d.ua_doc_state,
            "css": state_css.get(d.ua_doc_state, ""),
        } for d in emp.ua_document_ids]

        # -- Хроніка ------------------------------------------------------------------------
        # Кожна зміна контракту (прийняття, зміна окладу, переведення) - окрема hr.version.
        # contract_date_start лишається датою ПЕРШОГО прийняття на всіх версіях, а фактичну дату
        # цієї конкретної зміни і її тип дає date_version + наказ, що цю версію провів - інакше
        # зміна окладу за 2026 рік показувалась би як «Прийняття» датою прийняття 2012 року.
        Order = emp.env["ua.hr.order"].sudo()
        timeline = []
        for v in emp.version_ids:
            order = Order.search([("version_id", "=", v.id), ("state", "!=", "draft")], limit=1)
            order_type = order.order_type if order else (
                "hire" if v.contract_date_start and v.contract_date_start == v.date_version else False)
            event_date = v.date_version or v.contract_date_start
            if order_type == "wage":
                timeline.append({
                    "date": event_date,
                    "kind": "wage",
                    "label": f"Зміна окладу: {_fmt_money(v.wage) or 'немає'}",
                    "detail": _order(v.ua_order_ref),
                    "res_model": "hr.version", "res_id": v.id,
                })
            elif order_type == "transfer":
                timeline.append({
                    "date": event_date,
                    "kind": "transfer",
                    "label": f"Переведення: {v.job_title or '-'} ({v.department_id.name or '-'})",
                    "detail": f"{_order(v.ua_order_ref)}; оклад {_fmt_money(v.wage) or 'немає'}",
                    "res_model": "hr.version", "res_id": v.id,
                })
            elif v.contract_date_start:
                timeline.append({
                    "date": v.contract_date_start,
                    "kind": "hire",
                    "label": f"Прийняття: {v.job_title or '-'} ({v.department_id.name or '-'})",
                    "detail": f"{_order(v.ua_order_ref)}; оклад {_fmt_money(v.wage) or 'немає'}",
                    "res_model": "hr.version", "res_id": v.id,
                })
            if v.contract_date_end:
                timeline.append({
                    "date": v.contract_date_end,
                    "kind": "dismiss",
                    "label": f"Звільнення: {v.ua_dismissal_basis or 'підстава не вказана'}",
                    "detail": _order(v.ua_end_order_ref),
                    "res_model": "hr.version", "res_id": v.id,
                })

        leaves = emp.env["hr.leave"].search([("employee_id", "=", emp.id), ("state", "=", "validate")])
        for lv in leaves:
            days = lv.number_of_days or 0.0
            detail = _order(lv.ua_order_ref)
            if lv.ua_sick_number:
                detail += f", лікарняний № {lv.ua_sick_number}"
            timeline.append({
                "date": lv.request_date_from,
                "kind": "leave",
                "label": f"Відпустка: {lv.holiday_status_id.name or '-'} ({days:g} дн.)",
                "detail": detail,
                "res_model": "hr.leave", "res_id": lv.id,
            })

        slips = emp.env["hr.payslip"].search([("employee_id", "=", emp.id)])
        for slip in slips:
            lines = slip.line_ids
            gross = sum(lines.filtered(lambda l: l.code == "GROSS").mapped("total"))
            net = sum(lines.filtered(lambda l: l.code == "NET").mapped("total"))
            timeline.append({
                "date": slip.date_to or slip.date_from,
                "kind": "payslip",
                "label": f"Листок за {_fmt_date(slip.date_from)} - {_fmt_date(slip.date_to)} ({PAYSLIP_STATE_LABELS.get(slip.state, slip.state)})",
                "detail": f"Нараховано {_fmt_money(gross)}, на руки {_fmt_money(net)}",
                "res_model": "hr.payslip", "res_id": slip.id,
            })

        for ev in emp.ua_mil_event_ids:
            timeline.append({
                "date": ev.date,
                "kind": "military",
                "label": f"Військовий облік: {_sel_label(ev, 'kind')}",
                "detail": ev.note or "",
                "res_model": "ua.military.event", "res_id": ev.id,
            })

        for d in emp.ua_document_ids:
            if d.date:
                timeline.append({
                    "date": d.date,
                    "kind": "document",
                    "label": f"Документ: {d.name}",
                    "detail": d.number or "",
                    "res_model": "ua.employee.document", "res_id": d.id,
                })

        timeline.sort(key=lambda e: e["date"] or date.min, reverse=True)
        for e in timeline:
            e["date"] = _fmt_date(e["date"])

        # -- Кнопки -------------------------------------------------------------------------
        can_manage = self.env.user.has_group("hr.group_hr_manager")
        actions = [
            {"key": "print_p2", "label": "Друк П-2", "method": "action_ua_card_print_p2", "group": "header"},
            {"key": "print_order", "label": "Наказ", "method": "action_ua_card_print_order", "group": "header"},
            {"key": "payslips", "label": "Листки", "method": "action_ua_card_open_payslips", "group": "header"},
        ]
        if can_manage:
            actions.append({"key": "change_wage", "label": "Змінити оклад", "method": "action_ua_card_new_version", "group": "footer"})
        actions.append({"key": "new_leave", "label": "Оформити відпустку", "method": "action_ua_card_new_leave", "group": "footer"})
        actions.append({"key": "new_document", "label": "Додати документ", "method": "action_ua_card_new_document", "group": "footer"})
        actions.append({"key": "mil_check", "label": "Записати звірку ТЦК", "method": "action_ua_card_register_mil_check", "group": "footer"})
        actions.append({"key": "income_certificate", "label": "Довідка про доходи", "method": "action_ua_card_income_certificate", "group": "footer"})
        actions.append({"key": "doc_pack", "label": "Пакет документів", "method": "action_ua_card_doc_pack", "group": "footer"})
        if can_manage:
            actions.append({"key": "dismiss", "label": "Звільнити", "method": "action_ua_card_dismiss", "group": "footer"})
        actions.append({"key": "standard_form", "label": "Стандартна форма", "method": "action_ua_card_open_standard_form", "group": "footer"})

        return {
            "header": header,
            "person": person,
            "pay": pay,
            "vacation": vacation,
            "military": military,
            "documents": documents,
            "timeline": timeline,
            "actions": actions,
        }

    # ------------------------------------------------------------------
    # Дії кнопок
    # ------------------------------------------------------------------
    def action_ua_card_print_p2(self):
        self.ensure_one()
        report = self.env.ref("l10n_ua_hr_card.action_report_ua_p2")
        return report.report_action(self)

    def action_ua_card_print_order(self):
        """Друк наказу останньої кадрової події картки: якщо є проведений ua.hr.order - друкує
        його (єдина система наказів); якщо працівника перенесено з історії (hr.version з
        ua_order_ref/ua_end_order_ref, але без запису ua.hr.order) - друкує застарілою формою
        l10n_ua_hr_docs як історичний резерв."""
        self.ensure_one()
        version = self.sudo().current_version_id
        if not version:
            raise UserError("У працівника немає жодної версії контракту.")
        is_dismissal = bool(version.contract_date_end and version.ua_end_order_ref)
        Order = self.env["ua.hr.order"].sudo()
        if is_dismissal:
            order = Order.search([
                ("employee_id", "=", self.id), ("order_type", "=", "dismissal"),
                ("state", "in", ("posted", "acknowledged")),
            ], limit=1, order="date desc")
        else:
            order = Order.search([
                ("employee_id", "=", self.id), ("order_type", "=", "hire"),
                ("state", "in", ("posted", "acknowledged")),
            ], limit=1, order="date desc")
        if order:
            report = self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_order")
            return report.report_action(order)
        if is_dismissal:
            xmlid = "l10n_ua_hr_docs.action_report_ua_order_dismiss"
        else:
            xmlid = "l10n_ua_hr_docs.action_report_ua_order_hire"
        report = self.env.ref(xmlid, raise_if_not_found=False)
        if not report:
            raise UserError("Модуль наказів (l10n_ua_hr_docs) не встановлено.")
        return report.report_action(version)

    def action_ua_card_open_payslips(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Листки: {self.name}",
            "res_model": "hr.payslip",
            "views": [(False, "list"), (False, "form")],
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def action_ua_card_new_version(self):
        self.ensure_one()
        emp = self.sudo()
        view = self.env.ref("l10n_ua_card_ui.view_hr_version_form_new")
        return {
            "type": "ir.actions.act_window",
            "name": f"Нова версія контракту: {self.name}",
            "res_model": "hr.version",
            "views": [(view.id, "form")],
            "target": "new",
            "context": {
                "default_employee_id": self.id,
                "default_contract_date_start": fields.Date.context_today(self),
                "default_job_id": emp.job_id.id,
                "default_department_id": emp.department_id.id,
                "default_wage": emp.ua_current_wage,
            },
        }

    def action_ua_card_dismiss(self):
        self.ensure_one()
        version = self.sudo().current_version_id
        if not version:
            raise UserError("У працівника немає активної версії контракту.")
        view = self.env.ref("l10n_ua_card_ui.view_hr_version_form_dismiss")
        return {
            "type": "ir.actions.act_window",
            "name": f"Звільнення: {self.name}",
            "res_model": "hr.version",
            "res_id": version.id,
            "views": [(view.id, "form")],
            "target": "new",
        }

    def action_ua_card_new_leave(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Відпустка: {self.name}",
            "res_model": "hr.leave",
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_employee_id": self.id},
        }

    def action_ua_card_doc_pack(self):
        """Пакет документів працівника: перегляд у вкладці браузера, друк звідти."""
        self.ensure_one()
        wizard = self.env["ua.hr.doc.pack.wizard"].create({"employee_ids": [(6, 0, self.ids)]})
        items = json.dumps([{"r": "l10n_ua_hr_orders.report_ua_hr_doc_pack", "ids": wizard.ids,
                             "t": "Пакет документів · %s" % self.name}], ensure_ascii=False)
        return {"type": "ir.actions.act_url", "target": "new",
                "url": "/ua/print?" + urlencode({"items": items})}

    def action_ua_card_income_certificate(self):
        """Майстер довідки про доходи з підставленим працівником."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "l10n_ua_payroll_reports.action_ua_income_certificate")
        action["context"] = {"default_employee_id": self.id}
        action["target"] = "new"
        return action

    def action_ua_card_new_document(self):
        self.ensure_one()
        view = self.env.ref("l10n_ua_card_ui.view_ua_employee_document_form_card")
        return {
            "type": "ir.actions.act_window",
            "name": f"Документ: {self.name}",
            "res_model": "ua.employee.document",
            "views": [(view.id, "form")],
            "target": "new",
            "context": {"default_employee_id": self.id},
        }

    def action_ua_card_register_mil_check(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        self.env["ua.military.event"].sudo().create({
            "employee_id": self.id,
            "date": today,
            "kind": "check",
            "note": "Звірка через картку працівника",
        })
        self.sudo().write({"ua_mil_last_check": today})
        return False

    def action_ua_card_open_standard_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "hr.employee",
            "res_id": self.id,
            "views": [(self.env.ref("hr.view_employee_form").id, "form")],
            "target": "current",
        }
