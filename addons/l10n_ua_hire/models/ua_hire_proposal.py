# -*- coding: utf-8 -*-
"""Пропозиція значення поля з документа. Людина приймає або відхиляє; слід рішення лишається."""
import re
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

CONFIDENCE = [("high", "висока"), ("medium", "середня"), ("low", "низька")]
STATES = [("pending", "чекає"), ("accepted", "прийнято"), ("rejected", "відхилено")]


class UaHireProposal(models.Model):
    _name = "ua.hire.proposal"
    _description = "Пропозиція значення з документа"
    _order = "id"

    case_id = fields.Many2one("ua.hire.case", "Справа", required=True, ondelete="cascade", index=True)
    field_name = fields.Char("Поле", required=True)
    value = fields.Char("Значення", required=True)
    file_id = fields.Many2one("ua.hire.file", "Файл", ondelete="set null")
    quote = fields.Char("Фрагмент документа")
    confidence = fields.Selection(CONFIDENCE, "Впевненість", default="medium")
    model = fields.Char("Модель")
    state = fields.Selection(STATES, "Стан", default="pending", required=True)
    decided_by = fields.Many2one("res.users", "Рішення прийняв", readonly=True)
    decided_at = fields.Datetime("Коли", readonly=True)

    def _normalize(self, fld, raw):
        """Привести відповідь моделі до формату поля. Повертає рядок або None, якщо значення не підходить."""
        if raw is None or raw is False:
            return None
        text = str(raw).strip()
        if not text:
            return None
        if fld.type == "date":
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
                try:
                    return datetime.strptime(text, fmt).date().isoformat()
                except ValueError:
                    continue
            return None
        if fld.type == "selection":
            options = dict(fld._description_selection(self.env))
            if text in options:
                return text
            by_label = {v.lower(): k for k, v in options.items()}
            return by_label.get(text.lower())
        if fld.type == "boolean":
            return "1" if text.lower() in ("1", "true", "так", "yes") else None
        if fld.type == "integer":
            m = re.search(r"\d+", text)
            return m.group() if m else None
        if fld.type in ("monetary", "float"):
            return None
        return text

    def _display_value(self):
        self.ensure_one()
        fld = self.case_id._fields[self.field_name]
        if fld.type == "selection":
            return dict(fld._description_selection(self.env)).get(self.value, self.value)
        if fld.type == "date":
            try:
                return datetime.strptime(self.value, "%Y-%m-%d").strftime("%d.%m.%Y")
            except ValueError:
                return self.value
        if fld.type == "boolean":
            return _("так")
        return self.value

    def _decide(self, state):
        self.write({"state": state, "decided_by": self.env.uid, "decided_at": fields.Datetime.now()})

    def action_accept(self):
        for p in self:
            if p.state != "pending":
                raise UserError(_("Цю пропозицію вже розглянуто."))
            case = p.case_id
            value = p.value
            if case._fields[p.field_name].type == "boolean":
                value = True
            case.set_value(p.field_name, value)
            p._decide("accepted")
            others = case.proposal_ids.filtered(lambda o: o.field_name == p.field_name and o.state == "pending" and o != p)
            others._decide("rejected")
        return True

    def action_reject(self):
        for p in self.filtered(lambda p: p.state == "pending"):
            p._decide("rejected")
        return True
