from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_sti_code = fields.Char("Код ДПІ (C_STI_ORIG)", size=4, help="Чотиризначний код податкової інспекції, куди подається звіт")
    ua_sti_name = fields.Char("Назва ДПІ", help="Найменування контролюючого органу, як у формі")
    ua_reg = fields.Char("Код області (C_REG)", size=2)
    ua_raj = fields.Char("Код району (C_RAJ)", size=2)
    ua_katottg = fields.Char("Код КАТОТТГ", size=19)
    ua_kved = fields.Char("Основний КВЕД", size=10)
    ua_director_name = fields.Char("Керівник (ПІБ)")
    ua_director_rnokpp = fields.Char("РНОКПП керівника", size=10)
    ua_accountant_name = fields.Char("Головний бухгалтер (ПІБ)")
    ua_accountant_rnokpp = fields.Char("РНОКПП головного бухгалтера", size=10)
