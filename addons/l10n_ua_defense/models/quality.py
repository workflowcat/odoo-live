"""ВТК на виробах за оборонним контрактом.

Пункти перевірки лежать текстом на операції маршруту (`ua_checks`), відповіді «так / ні» -
на нарядах (`ua.workorder.check`, l10n_ua_mrp). Тут три речі поверх цього:

- замовлення за контрактом з увімкненим «Випуск лише після ВТК» не закривається, поки є
  пункт без відповіді або з відповіддю «ні»;
- акт приймання за таким контрактом не приймає серійний номер, чий виріб не пройшов ВТК;
- паспорт виробу друкує, що саме перевіряли, з яким результатом, хто і коли.

Вироби без операцій чи без пунктів перевірки ВТК не зупиняє: перевіряти нічого.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

QUALITY_STATES = [
    ("none", "Без перевірки"),
    ("pending", "Не все перевірено"),
    ("failed", "Є «ні»"),
    ("passed", "Перевірку пройдено"),
]


def _state(rows):
    if not rows:
        return "none"
    if any(row["result"] == "fail" for row in rows):
        return "failed"
    if any(not row["result"] for row in rows):
        return "pending"
    return "passed"


class UaContract(models.Model):
    _inherit = "ua.contract"

    ua_quality_gate = fields.Boolean(
        "Випуск лише після ВТК", default=True,
        help="Замовлення на виробництво за контрактом не закривається, а акт приймання не "
             "приймає виріб, поки на всі пункти перевірки операцій немає відповіді «так».")


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ua_quality_state = fields.Selection(
        QUALITY_STATES, "ВТК", compute="_compute_ua_quality_state",
        help="Зведення відповідей на пункти перевірки операцій замовлення.")

    @api.depends("workorder_ids.ua_check_ids.result", "workorder_ids.operation_id.ua_checks")
    def _compute_ua_quality_state(self):
        for production in self:
            production.ua_quality_state = _state(production._ua_quality_rows())

    def _ua_quality_rows(self):
        """Пункти перевірки всіх нарядів замовлення з відповідями, в порядку операцій."""
        self.ensure_one()
        rows = []
        if not isinstance(self.id, int):
            return rows
        for workorder in self.workorder_ids.sorted(lambda w: (w.operation_id.sequence, w.id)):
            for row in workorder.ua_check_rows():
                rows.append(dict(row, operation=workorder.operation_id.name or workorder.name))
        return rows

    def _ua_quality_problems(self):
        problems = []
        for row in self._ua_quality_rows():
            if row["result"] == "fail":
                problems.append(_("%(operation)s, пункт %(index)s «%(text)s»: «ні»%(note)s",
                                  operation=row["operation"], index=row["index"], text=row["text"],
                                  note=(" - " + row["note"]) if row["note"] else ""))
            elif not row["result"]:
                problems.append(_("%(operation)s, пункт %(index)s «%(text)s»: немає відповіді",
                                  operation=row["operation"], index=row["index"], text=row["text"]))
        return problems

    def button_mark_done(self):
        for production in self.filtered(lambda p: p.ua_contract_id.ua_quality_gate):
            problems = production._ua_quality_problems()
            if problems:
                raise UserError(_(
                    "%(production)s за контрактом %(contract)s не пройшло ВТК:\n%(problems)s\n\n"
                    "Дайте відповіді на пункти перевірки в нарядах або вимкніть «Випуск лише "
                    "після ВТК» у контракті.",
                    production=production.name, contract=production.ua_contract_id.name,
                    problems="\n".join(problems)))
        return super().button_mark_done()


class StockLot(models.Model):
    _inherit = "stock.lot"

    ua_quality_state = fields.Selection(QUALITY_STATES, "ВТК", compute="_compute_ua_quality_state")

    def _compute_ua_quality_state(self):
        for lot in self:
            production = lot.ua_production_id
            lot.ua_quality_state = production.ua_quality_state if production else "none"

    def _ua_quality_rows(self):
        self.ensure_one()
        return self.ua_production_id._ua_quality_rows() if self.ua_production_id else []


class UaDefenseAcceptance(models.Model):
    _inherit = "ua.defense.acceptance"

    def action_done(self):
        for act in self.filtered(lambda a: a.contract_id.ua_quality_gate):
            lots = act.line_ids.filtered(lambda line: line.result == "accepted").lot_ids
            bad = lots.filtered(lambda lot: lot.ua_quality_state in ("pending", "failed"))
            if bad:
                raise UserError(_(
                    "Не пройшли ВТК: %(lots)s. Такі вироби в акті - «На доопрацювання», або "
                    "спершу закрийте перевірку в нарядах.",
                    lots=", ".join(bad.mapped("name"))))
        return super().action_done()
