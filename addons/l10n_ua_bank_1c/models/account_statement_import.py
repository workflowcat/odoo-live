"""Імпорт виписки у форматі 1CClientBankExchange через звичайний майстер імпорту виписки OCA."""
from odoo import _, models
from odoo.exceptions import UserError

from . import bank1c_format as fmt


class AccountStatementImport(models.TransientModel):
    _inherit = "account.statement.import"

    def _parse_file(self, data_file):
        if not fmt.is_bank1c(data_file):
            return super()._parse_file(data_file)
        try:
            parsed = fmt.parse(data_file)
            by_account = fmt.transactions(parsed)
        except fmt.Bank1CError as error:
            raise UserError(_("Файл клієнт-банку 1С: %s", error)) from None
        result = []
        for account, rows in by_account.items():
            balance = fmt.balances(parsed, account)
            if not rows and not balance:
                continue
            result.append(self._ua_bank1c_statement(parsed, account, rows, balance))
        if not result:
            raise UserError(_("У файлі клієнт-банку немає ні документів, ні залишків."))
        return result

    def _ua_bank1c_statement(self, parsed, account, rows, balance):
        journal = self.env["account.journal"].search([
            ("type", "=", "bank"),
            ("bank_account_id.sanitized_acc_number", "=", account),
            ("company_id", "in", self.env.companies.ids),
        ], limit=1)
        company = journal.company_id or self.env.company
        currency = (journal.currency_id or company.currency_id).name
        dates = [row["date"] for row in rows]
        date_from = (balance and balance[2]) or fmt.day(parsed["header"].get("ДатаНачала")) \
            or min(dates)
        date_to = (balance and balance[3]) or fmt.day(parsed["header"].get("ДатаКонца")) \
            or max(dates)
        statement = {
            "name": _("Клієнт-банк %(account)s, %(start)s - %(end)s", account=account[-8:],
                      start=date_from.strftime("%d.%m.%Y"), end=date_to.strftime("%d.%m.%Y")),
            "date": date_to,
            "transactions": [self._ua_bank1c_line(row) for row in rows],
        }
        if balance:
            statement["balance_start"] = balance[0]
            statement["balance_end_real"] = balance[1]
        return currency, account, [statement]

    def _ua_bank1c_line(self, row):
        partner = row["partner"]
        line = {
            "date": row["date"],
            "amount": row["amount"],
            "payment_ref": row["purpose"] or _("Документ № %s", row["number"]),
            "ref": row["number"],
            "partner_name": partner["name"] or False,
            "unique_import_id": "1c-%s-%s-%.2f-%s" % (
                row["number"], row["document_date"] or row["date"], row["amount"],
                partner["account"] or partner["code"]),
        }
        if partner["account"]:
            line["account_number"] = partner["account"]
        if partner["code"]:
            line["ua_partner_code"] = partner["code"]
        return line
