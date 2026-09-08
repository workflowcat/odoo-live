from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    move_id = fields.Many2one("account.move", "Проводка", readonly=True, copy=False)

    def _ua_account(self, code):
        # план рахунків Odoo може доповнювати коди нулями (92 -> 920000): беремо найкоротший код із цим префіксом
        Acc = self.env["account.account"].with_company(self.company_id)
        acc = Acc.search([("code", "=", code), ("company_ids", "in", self.company_id.id)], limit=1) or \
              Acc.search([("code", "=like", f"{code}%"), ("company_ids", "in", self.company_id.id)], order="code", limit=1)
        if not acc:
            raise UserError(_("Немає рахунку %s у плані рахунків компанії %s.", code, self.company_id.name))
        return acc

    def _ua_expense_account(self):
        emp = self.employee_id.sudo()
        return emp.ua_expense_account_id or emp.department_id.ua_expense_account_id or self._ua_account("92")

    def _ua_journal(self):
        journal = self.env["account.journal"].search([("code", "=", "ЗП"), ("company_id", "=", self.company_id.id)], limit=1)
        if not journal:
            journal = self.env["account.journal"].create({"name": "Зарплата", "code": "ЗП", "type": "general", "company_id": self.company_id.id})
        return journal

    def _ua_move_lines(self):
        """Агрегує рядки листка за правилами карти проводок. Повертає список (дебет-рахунок, кредит-рахунок, сума, назва)."""
        self.ensure_one()
        maps = self.env["ua.payroll.account.map"].search([("company_id", "in", (False, self.company_id.id))])
        by_code = defaultdict(list)
        for m in maps:
            by_code[m.rule_code].append(m)
        expense = self._ua_expense_account()
        out = []
        for line in self.line_ids:
            amount = abs(round(line.total, 2))
            if not amount:
                continue
            for m in by_code.get(line.code, []):
                debit = expense if m.debit_side == "expense" else self._ua_account(m.debit_code)
                credit = expense if m.credit_side == "expense" else self._ua_account(m.credit_code)
                out.append((debit, credit, amount, f"{m.name}: {line.name}"))
        return out

    def _ua_partner_for(self, account):
        """Партнер на рядку проводки за рахунком: 66 - працівник, 641/642/651 - ДПС, 378 - ПФУ, 685 - отримувач аліментів, інші - без партнера.
        Так рядки 661/6411/651 закриваються звіркою банківської виписки за партнером."""
        code = account.code or ""
        emp = self.employee_id.sudo()
        company = self.company_id
        if code.startswith("66"):
            return emp.work_contact_id.id or False
        if code.startswith(("641", "642", "651", "652")):
            return company.sudo()._ua_partner("dps").id
        if code.startswith("378"):
            return company.sudo()._ua_partner("pfu").id
        if code.startswith("685"):
            return (emp.ua_alimony_partner_id or emp.work_contact_id).id or False
        return False

    def _ua_create_move(self):
        self.ensure_one()
        lines = self._ua_move_lines()
        if not lines:
            return False
        vals = []
        for debit, credit, amount, name in lines:
            base = {"name": f"{self.employee_id.name} · {name}"}
            vals.append((0, 0, {**base, "account_id": debit.id, "debit": amount, "credit": 0.0, "partner_id": self._ua_partner_for(debit)}))
            vals.append((0, 0, {**base, "account_id": credit.id, "debit": 0.0, "credit": amount, "partner_id": self._ua_partner_for(credit)}))
        move = self.env["account.move"].create({
            "journal_id": self._ua_journal().id, "date": self.date_to, "ref": self.number or self.name,
            "move_type": "entry", "line_ids": vals,
        })
        move.action_post()
        self.move_id = move
        return move

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for slip in self.filtered(lambda s: not s.move_id):
            slip._ua_create_move()
        return res

    def action_payslip_cancel(self):
        for slip in self.filtered("move_id"):
            move = slip.move_id
            slip.move_id = False
            if move.state == "posted":
                move.button_draft()
            move.unlink()
        return super().action_payslip_cancel()

    def action_open_move(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": self.move_id.id, "view_mode": "form"}
