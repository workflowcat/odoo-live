"""Інструменти контролю на операції і у відповіді ВТК.

Операція маршруту називає засоби вимірювання, якими перевіряють її пункти. Відповідь
«так» не приймається, поки хоч один з них непридатний на сьогодні: прострочений,
визнаний непридатним або законсервований. Відповідь «ні» приймається завжди -
брак, знайдений будь-чим, лишається браком.

У відповідь записуємо, якими засобами міряли, і текстом - знімок з номером і строком
повірки: якщо засіб потім переповірять, у паспорті лишиться те, чим міряли тоді.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class MrpRoutingWorkcenter(models.Model):
    _inherit = "mrp.routing.workcenter"

    ua_instrument_ids = fields.Many2many(
        "maintenance.equipment", "ua_routing_instrument_rel", "operation_id", "equipment_id",
        "Засоби вимірювання", domain="[('ua_measuring', '=', True)]",
        help="Чим перевіряють пункти ВТК цієї операції.")


class UaWorkorderCheck(models.Model):
    _inherit = "ua.workorder.check"

    ua_instrument_ids = fields.Many2many(
        "maintenance.equipment", "ua_check_instrument_rel", "check_id", "equipment_id",
        "Засоби вимірювання", readonly=True)
    ua_instruments_text = fields.Char("Чим міряли", readonly=True)


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def ua_answer_check(self, index, result, note=None):
        """Як у l10n_ua_mrp, але «так» - лише придатними засобами вимірювання операції."""
        self.ensure_one()
        instruments = self.operation_id.ua_instrument_ids
        if result == "ok":
            problems = [
                "%s: %s" % (instrument.ua_label(), reason)
                for instrument in instruments
                for reason in [instrument.ua_unfit_reason()] if reason
            ]
            if problems:
                raise UserError(_(
                    "Відповідь «так» на пункт %(index)s операції «%(operation)s» не приймається: "
                    "засоби вимірювання непридатні.\n%(problems)s\n\nМіряйте придатним засобом "
                    "(змініть перелік в операції) або спершу повірте цей.",
                    index=index, operation=self.operation_id.name or self.name,
                    problems="\n".join(problems)))
        super().ua_answer_check(index, result, note=note)
        answer = self.ua_check_ids.filtered(lambda check: check.sequence == int(index))
        answer.sudo().write({
            "ua_instrument_ids": [(6, 0, instruments.ids)],
            "ua_instruments_text": "; ".join(instruments.mapped(lambda i: i.ua_label())) or False,
        })
        return self.ua_check_rows()

    def ua_check_rows(self):
        rows = super().ua_check_rows()
        answers = {check.sequence: check for check in self.ua_check_ids}
        for row in rows:
            answer = answers.get(row["index"])
            row["instruments"] = (answer.ua_instruments_text or "") if answer else ""
        return rows
