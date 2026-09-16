"""Дані підпису для вкладки «Документи» картки працівника - окремий, невеликий метод.

get_card_data (у l10n_ua_card_ui/models/hr_employee.py) - великий метод, який малює всю картку
і належить іншому агенту в цій паралельній роботі; його не чіпаємо. Стан підпису, дату підпису
і кнопки «Підписано»/«Друк» картка бере окремим викликом цього методу."""
from odoo import models

STATE_LABELS = {"to_sign": "На підпис", "signed": "Підписано", "not_needed": "Не потрібен"}
STATE_CSS = {"to_sign": "text-warning", "signed": "text-success", "not_needed": "text-muted"}
DOC_STATE_CSS = {"ok": "text-success", "warning": "text-warning", "expired": "text-danger"}
# Пігулка картки «Документи»: одна пігулка на рядок, найважливіший стан виграє. На підпис і
# прострочено - однаково критичні (coral), спливає - жовта (warn), підписано - зелена (mint).
DOC_PILL_LABELS = {"warning": "Спливає", "expired": "Прострочено"}


def _sel_label(record, field):
    value = record[field]
    if not value:
        return None
    return dict(record._fields[field]._description_selection(record.env)).get(value)


class HrEmployeeCardDocuments(models.Model):
    _inherit = "hr.employee"

    def get_card_documents(self):
        self.ensure_one()
        rows = []
        for d in self.ua_document_ids:
            # Пігулка: підпис виграє, поки не підписано; далі виграє строк дії.
            if d.state == "to_sign":
                pill_label, pill_css = "На підпис", "o_ua_pill_crit"
            elif d.ua_doc_state == "expired":
                pill_label, pill_css = DOC_PILL_LABELS["expired"], "o_ua_pill_crit"
            elif d.ua_doc_state == "warning":
                pill_label, pill_css = DOC_PILL_LABELS["warning"], "o_ua_pill_warn"
            elif d.state == "signed":
                pill_label, pill_css = "Підписано", "o_ua_pill_ok"
            else:
                pill_label, pill_css = STATE_LABELS.get(d.state, d.state), "o_ua_pill"
            rows.append({
                "id": d.id,
                "type": _sel_label(d, "type") or "немає",
                "name": d.name or "немає",
                "valid_until": d.valid_until.strftime("%d.%m.%Y") if d.valid_until else "безстроково",
                "css": DOC_STATE_CSS.get(d.ua_doc_state, ""),
                "state": d.state,
                "state_label": STATE_LABELS.get(d.state, d.state),
                "state_css": STATE_CSS.get(d.state, ""),
                "pill_label": pill_label,
                "pill_css": pill_css,
                "signed_date": d.signed_date.strftime("%d.%m.%Y") if d.signed_date else None,
                "can_sign": d.state == "to_sign",
                "can_print": bool(d.report_xmlid and d.res_id),
            })
        return rows

    def action_ua_card_document_sign(self, document_id):
        self.ensure_one()
        doc = self.env["ua.employee.document"].sudo().browse(document_id)
        if not doc.exists() or doc.employee_id.id != self.id:
            return False
        doc.action_mark_signed()
        return True

    def action_ua_card_document_print(self, document_id):
        self.ensure_one()
        doc = self.env["ua.employee.document"].sudo().browse(document_id)
        if not doc.exists() or doc.employee_id.id != self.id:
            return False
        return doc.action_print()
