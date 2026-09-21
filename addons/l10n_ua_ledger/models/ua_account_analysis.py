"""Аналіз рахунку: з якими рахунками і на які суми кореспондував обраний рахунок.

Такого регістру немає ні в Odoo, ні в OCA, тому запит тут повністю власний.

Задокументоване спрощення: багаторядкова проводка розкладається ПРОПОРЦІЙНО.
Дебет нашого рахунку в проводці ділиться між кредитовими рядками тієї самої
проводки пропорційно їхнім сумам, кредит - між дебетовими. Класика «один Дт і
кілька Кт» - точний окремий випадок цього ж правила. За побудовою сума
кореспонденцій дорівнює обороту рахунку; це перевіряється полем control_ok.
"""
from odoo import fields, models


class UaAccountAnalysis(models.TransientModel):
    _name = "ua.account.analysis"
    _inherit = "ua.ledger.base"
    _description = "Аналіз рахунку"

    account_id = fields.Many2one("account.account", "Рахунок", required=True)
    line_ids = fields.One2many(
        "ua.account.analysis.line", "analysis_id", "Кореспонденції", readonly=True
    )

    opening_balance = fields.Monetary("Сальдо на початок", currency_field="currency_id")
    total_debit = fields.Monetary("Оборот Дт", currency_field="currency_id")
    total_credit = fields.Monetary("Оборот Кт", currency_field="currency_id")
    closing_balance = fields.Monetary("Сальдо на кінець", currency_field="currency_id")
    control_ok = fields.Boolean("Сума кореспонденцій = оборот", readonly=True)

    def action_compute(self):
        for analysis in self:
            aml_model = analysis.env["account.move.line"]
            account = analysis.account_id
            opening = analysis._opening_balance([("account_id", "=", account.id)])
            our_lines = aml_model.search(analysis._aml_domain([
                ("account_id", "=", account.id),
                ("date", ">=", analysis.date_from),
                ("date", "<=", analysis.date_to),
            ]))
            by_move = {}
            for line in aml_model.search([("move_id", "in", our_lines.move_id.ids)]):
                by_move.setdefault(line.move_id.id, []).append(line)

            correspondence = {}
            total_debit = total_credit = 0.0
            our_ids = set(our_lines.ids)
            for move_lines in by_move.values():
                ours = [line for line in move_lines if line.id in our_ids]
                our_debit = sum(line.debit for line in ours)
                our_credit = sum(line.credit for line in ours)
                total_debit += our_debit
                total_credit += our_credit
                move_debit = sum(line.debit for line in move_lines)
                move_credit = sum(line.credit for line in move_lines)
                if our_debit and move_credit:
                    for line in move_lines:
                        if line.credit:
                            row = correspondence.setdefault(
                                line.account_id, {"debit": 0.0, "credit": 0.0}
                            )
                            row["debit"] += our_debit * line.credit / move_credit
                if our_credit and move_debit:
                    for line in move_lines:
                        if line.debit:
                            row = correspondence.setdefault(
                                line.account_id, {"debit": 0.0, "credit": 0.0}
                            )
                            row["credit"] += our_credit * line.debit / move_debit

            commands = [(5, 0, 0)]
            sum_debit = sum_credit = 0.0
            for sequence, corr_account in enumerate(
                sorted(correspondence, key=analysis._acc_code)
            ):
                values = correspondence[corr_account]
                sum_debit += values["debit"]
                sum_credit += values["credit"]
                commands.append((0, 0, {
                    "sequence": sequence,
                    "corr_account_id": corr_account.id,
                    "corr_code": analysis._acc_code(corr_account),
                    "corr_name": corr_account.name,
                    "debit": round(values["debit"], 2),
                    "credit": round(values["credit"], 2),
                }))

            total_debit = round(total_debit, 2)
            total_credit = round(total_credit, 2)
            analysis.write({
                "line_ids": commands,
                "opening_balance": opening,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "closing_balance": round(opening + total_debit - total_credit, 2),
                "control_ok": (
                    abs(sum_debit - total_debit) < 0.01
                    and abs(sum_credit - total_credit) < 0.01
                ),
            })
        return True

    def action_print_xlsx(self):
        self.ensure_one()
        self.action_compute()
        return self.env.ref(
            "l10n_ua_ledger.action_report_ua_account_analysis_xlsx"
        ).report_action(self)


class UaAccountAnalysisLine(models.TransientModel):
    _name = "ua.account.analysis.line"
    _description = "Рядок аналізу рахунку"
    _order = "sequence, id"

    analysis_id = fields.Many2one(
        "ua.account.analysis", "Аналіз", required=True, ondelete="cascade"
    )
    currency_id = fields.Many2one("res.currency", related="analysis_id.currency_id")
    sequence = fields.Integer("№")
    corr_account_id = fields.Many2one("account.account", "Кор. рахунок плану")
    corr_code = fields.Char("Кор. рахунок")
    corr_name = fields.Char("Назва")
    debit = fields.Monetary("Дт наш - Кт кор.", currency_field="currency_id")
    credit = fields.Monetary("Кт наш - Дт кор.", currency_field="currency_id")
