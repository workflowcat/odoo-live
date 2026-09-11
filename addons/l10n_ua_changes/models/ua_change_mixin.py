# -*- coding: utf-8 -*-
"""Домішка, яка пише зміни в журнал.

Модель, що успадковує домішку, оголошує три речі:
    _ua_change_area    - ділянка журналу;
    _ua_change_fields  - {поле: назва} — тільки ці поля потрапляють у журнал;
    _ua_change_create / _ua_change_unlink - чи писати створення і видалення.

Старе значення читаємо до запису, нове — після. Так формат однаковий для всіх
типів полів, і не треба розбирати vals.
"""
from odoo import api, fields, models

SKIP_KEYS = ("ua_no_log", "install_mode")


class UaChangeMixin(models.AbstractModel):
    _name = "ua.change.mixin"
    _description = "Запис змін у журнал"

    _ua_change_area = "hr"
    _ua_change_fields = {}
    _ua_change_create = False
    _ua_change_unlink = True

    # ------------------------------------------------------------------ хелпери
    def _ua_log_off(self):
        ctx = self.env.context
        return any(ctx.get(key) for key in SKIP_KEYS) or not self.env.registry.ready

    def _ua_change_period(self):
        """Місяць, до якого належить зміна. Типово — поточний."""
        today = fields.Date.context_today(self)
        return today.year, today.month

    def _ua_change_label(self):
        return self.display_name or "%s %s" % (self._name, self.id)

    def _ua_change_company(self):
        company = self._fields.get("company_id") and self.company_id
        return company or self.env.company

    def _ua_fmt(self, fname):
        field = self._fields[fname]
        value = self[fname]
        if value is False or value is None:
            return ""
        if field.type == "many2one":
            return value.display_name or ""
        if field.type in ("one2many", "many2many"):
            return ", ".join(value.mapped("display_name"))
        if field.type == "selection":
            return dict(field._description_selection(self.env)).get(value, str(value))
        if field.type in ("float", "monetary"):
            return "%.2f" % value
        if field.type == "boolean":
            return "так" if value else "ні"
        return str(value)

    def _ua_raw(self, fname):
        field = self._fields[fname]
        value = self[fname]
        if field.type == "many2one":
            return value.id
        if field.type in ("one2many", "many2many"):
            return tuple(value.ids)
        return value

    def _ua_change_keep(self, fname, old, new):
        """Чи писати цю зміну в журнал. Моделі звужують перелік тут."""
        return True

    def _ua_change_loggable(self):
        """Чи писати створення цього запису. Порожні автоматичні рядки не пишемо."""
        return True

    def _ua_num(self, fname):
        field = self._fields[fname]
        if field.type in ("float", "monetary", "integer"):
            return float(self[fname] or 0.0)
        return None

    def _ua_write_log(self, rows):
        if rows:
            self.env["ua.change.log"].sudo().with_context(ua_no_log=True).create(rows)

    def _ua_row(self, operation, what="", old="", new="", amount=0.0):
        year, month = self._ua_change_period()
        return {
            "user_id": self.env.uid,
            "company_id": self._ua_change_company().id,
            "area": self._ua_change_area,
            "operation": operation,
            "model_name": self._name,
            "res_id": self.id,
            "res_name": (self._ua_change_label() or "")[:120],
            "what": what,
            "old_value": (old or "")[:120],
            "new_value": (new or "")[:120],
            "amount": amount,
            "year": year,
            "month": month,
        }

    # ------------------------------------------------------------------ ORM
    def write(self, vals):
        tracked = [f for f in self._ua_change_fields if f in vals]
        if self._ua_log_off() or not tracked:
            return super().write(vals)
        before = {rec.id: {f: (rec._ua_fmt(f), rec._ua_num(f), rec._ua_raw(f)) for f in tracked} for rec in self}
        res = super().write(vals)
        rows = []
        for rec in self:
            for fname in tracked:
                old_text, old_num, old_raw = before[rec.id][fname]
                new_text, new_num = rec._ua_fmt(fname), rec._ua_num(fname)
                if old_text == new_text:
                    continue
                if not rec._ua_change_keep(fname, old_raw, rec._ua_raw(fname)):
                    continue
                delta = (new_num - old_num) if (old_num is not None and new_num is not None) else 0.0
                rows.append(rec._ua_row("write", self._ua_change_fields[fname], old_text, new_text, delta))
        self._ua_write_log(rows)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self._ua_change_create and not self._ua_log_off():
            self._ua_write_log([rec._ua_row("create") for rec in records if rec._ua_change_loggable()])
        return records

    def unlink(self):
        if self._ua_change_unlink and not self._ua_log_off():
            self._ua_write_log([rec._ua_row("unlink") for rec in self if rec._ua_change_loggable()])
        return super().unlink()
