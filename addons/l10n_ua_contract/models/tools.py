"""Рахунки розрахунків з контрагентами.

Акт звірки і сальдо договору беруть лише рахунки розрахунків: 36 (покупці), 37 (аванси
видані, інші дебітори), 63 (постачальники), 68 (аванси отримані, інші кредитори).
Податки (64), зарплата (66) і страхування (65) у звірку з контрагентом не входять,
хоч у плані ua_psbo вони теж мають тип «до сплати».

Якщо план рахунків не український (коди інші), беремо рахунки типу «до отримання» і
«до сплати» - так звіряє сам Odoo.
"""

SETTLEMENT_PREFIXES = ("36", "37", "63", "68")
NOT_SETTLEMENT_PREFIXES = ("64", "65", "66")
RECEIVABLE_PAYABLE = ("asset_receivable", "liability_payable")


def settlement_accounts(env, company):
    """Рахунки розрахунків компанії, з яких складається акт звірки."""
    accounts = env["account.account"].with_company(company).search([
        *env["account.account"]._check_company_domain(company),
        ("reconcile", "=", True),
    ])
    ukrainian = accounts.filtered(lambda a: (a.code or "").startswith(SETTLEMENT_PREFIXES))
    if ukrainian:
        return ukrainian
    return accounts.filtered(
        lambda a: a.account_type in RECEIVABLE_PAYABLE
        and not (a.code or "").startswith(NOT_SETTLEMENT_PREFIXES)
    )


def contract_kind_of_move(move_type):
    """Вид договору, який пасує документу: продаж - з покупцем, купівля - з постачальником."""
    if move_type in ("out_invoice", "out_refund", "out_receipt"):
        return "sale"
    if move_type in ("in_invoice", "in_refund", "in_receipt"):
        return "purchase"
    return False
