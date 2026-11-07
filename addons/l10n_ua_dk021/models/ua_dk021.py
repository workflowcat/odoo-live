"""Класифікатор ДК 021:2015 «Єдиний закупівельний словник» (CPV).

Код має вигляд 03111000-2: вісім цифр і контрольна. Перші дві - розділ, третя -
група, четверта - клас, п'ята - категорія, шоста-восьма - уточнення. Батька коду
шукаємо, відкидаючи останню значущу цифру, поки не знайдемо наявний код: у словнику
є пропуски рівнів, і прямого батька буває немає.

Класифікатор один на країну, тому модель спільна для всіх компаній. Завантаження
ідемпотентне: наявні коди лише оновлюють назву, нові додаються, зниклі
архівуються, а не видаляються - на них можуть посилатися товари.
"""
import json

from odoo import api, fields, models
from odoo.tools.misc import file_path

SOURCE = "l10n_ua_dk021/data/dk021_uk.json"


def _significant(code):
    """Значуща частина коду: без контрольної цифри і хвостових нулів, щонайменше 2."""
    digits = (code or "").split("-")[0]
    sig = digits.rstrip("0")
    return sig if len(sig) >= 2 else digits[:2]


class UaDk021(models.Model):
    _name = "ua.dk021"
    _description = "Код ДК 021:2015"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char("Код", required=True, index=True)
    name = fields.Char("Назва", required=True)
    parent_id = fields.Many2one("ua.dk021", "Вищий рівень", index=True, ondelete="restrict")
    child_ids = fields.One2many("ua.dk021", "parent_id", "Нижчі рівні")
    level = fields.Integer(
        "Рівень", help="1 - розділ, 2 - група, 3 - клас, 4 - категорія, 5-7 - уточнення.")
    is_service = fields.Boolean(
        "Послуга", compute="_compute_is_service", store=True,
        help="Розділи 45-98 - роботи і послуги, решта - товари.")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Такий код ДК 021 уже є.")

    @api.depends("code")
    def _compute_is_service(self):
        for rec in self:
            rec.is_service = (rec.code or "00")[:2] >= "45"

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s %s" % (rec.code or "", rec.name or "")

    @api.model
    def _name_search_prefix(self, text):
        """Пошук за початком коду без дефіса: «0311» знаходить 03110000-5 і нижче."""
        digits = (text or "").replace("-", "").strip()
        return digits.isdigit() and len(digits) >= 2

    @api.model
    def _search_display_name(self, operator, value):
        if operator == "ilike" and self._name_search_prefix(value):
            return [("code", "=like", value.replace("-", "").strip() + "%")]
        return super()._search_display_name(operator, value)

    def _ua_division(self):
        """Розділ (рівень 1) для звітів за напрямами."""
        self.ensure_one()
        rec = self
        while rec.parent_id:
            rec = rec.parent_id
        return rec

    @api.model
    def _ua_load(self, path=None):
        """Завантажує або оновлює класифікатор із JSON {код: назва}."""
        with open(path or file_path(SOURCE), encoding="utf-8") as fh:
            source = json.load(fh)
        Model = self.with_context(active_test=False).sudo()
        existing = {rec.code: rec for rec in Model.search([])}
        ordered = sorted(source, key=lambda c: (len(_significant(c)), c))
        to_create = []
        for code in ordered:
            name = source[code].strip()
            rec = existing.get(code)
            if rec:
                if rec.name != name or not rec.active:
                    rec.write({"name": name, "active": True})
            else:
                to_create.append({"code": code, "name": name,
                                  "level": max(len(_significant(code)) - 1, 1)})
        if to_create:
            for rec in Model.create(to_create):
                existing[rec.code] = rec
        by_digits = {code.split("-")[0]: rec for code, rec in existing.items()}
        parents = {}
        for code in ordered:
            sig = _significant(code)
            parent = False
            probe = sig[:-1]
            while len(probe) >= 2:
                parent = by_digits.get(probe.ljust(8, "0"))
                if parent:
                    break
                probe = probe[:-1]
            rec = existing[code]
            if parent and parent != rec and rec.parent_id != parent:
                parents.setdefault(parent.id, []).append(rec.id)
        for parent_id, child_ids in parents.items():
            Model.browse(child_ids).write({"parent_id": parent_id})
        gone = set(existing) - set(source)
        if gone:
            Model.search([("code", "in", list(gone)), ("active", "=", True)]).write(
                {"active": False})
        return len(source)
