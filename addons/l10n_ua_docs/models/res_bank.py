"""МФО - не BIC.

МФО (код банку за довідником НБУ) має шість цифр, BIC/SWIFT - вісім або одинадцять знаків.
Це різні коди різних реєстрів, і писати МФО в `res.bank.bic` не можна: OCA
`account_payment_order` перевіряє довжину BIC і не дає створити банк із шістьма знаками.
Тому МФО живе у власному полі.

Означення одне на обидві моделі: тут, на довіднику банків, воно вводиться, а на
`res.partner.bank` (res_partner_bank.py) обчислюється з IBAN і підхоплює це як запасний
варіант, коли номер рахунку не є українським IBAN.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

MFO_LABEL = "МФО"
MFO_HELP = ("Код банку за довідником НБУ, шість цифр. Це не BIC/SWIFT: "
            "у BIC вісім або одинадцять знаків, і це поле - окреме.")


class ResBank(models.Model):
    _inherit = "res.bank"

    ua_mfo = fields.Char(MFO_LABEL, size=6, index=True, help=MFO_HELP)

    @api.constrains("ua_mfo")
    def _check_ua_mfo(self):
        for bank in self:
            if bank.ua_mfo and not (len(bank.ua_mfo) == 6 and bank.ua_mfo.isdigit()):
                raise ValidationError("МФО має складатися рівно з шести цифр.")
