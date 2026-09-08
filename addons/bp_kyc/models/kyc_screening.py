from odoo import fields, models

SOURCES = [("odb_registry", "ЄДР (OpenDataBot)"), ("odb_warning", "Ризик-маркер (OpenDataBot)"),
           ("odb_court", "Судові рішення (OpenDataBot)"), ("manual", "Ручна перевірка")]


class KycScreening(models.Model):
    _name = "kyc.screening"
    _description = "Перевірка KYC"
    _order = "severity desc, id"

    case_id = fields.Many2one("kyc.case", "Справа", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one(related="case_id.partner_id", store=True)
    source = fields.Selection(SOURCES, "Джерело", required=True, default="manual")
    key = fields.Char("Ключ")
    title = fields.Char("Що знайдено", required=True)
    detail = fields.Text("Деталі")
    severity = fields.Selection([("info", "Інфо"), ("warn", "Увага"), ("high", "Червоний")], "Вага", default="info", required=True)
    fetched_at = fields.Datetime("Отримано", default=fields.Datetime.now)
    payload = fields.Text("Сира відповідь (JSON)")
    pushed = fields.Boolean("Передано в реєстр", default=False)
