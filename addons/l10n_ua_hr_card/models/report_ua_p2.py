"""Право на друк особової картки П-2.

Шаблон читає картку через sudo(): у П-2 стоять поля, закриті навіть для кадровика
(оклад із договору), а форма має друкуватися цілою. Тому право перевіряємо тут, один
раз і до шаблона: П-2 друкує кадровик і лише для карток, які сам може прочитати.
Адреса /report/pdf/... цього шляху не обходить - Odoo бере значення звіту саме звідси."""
from odoo import api, models
from odoo.exceptions import AccessError


class ReportUaP2(models.AbstractModel):
    _name = "report.l10n_ua_hr_card.report_ua_p2"
    _description = "Особова картка П-2: право на друк"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["hr.employee"].browse(docids)
        if not self.env.su:
            if not self.env.user.has_group("hr.group_hr_user"):
                raise AccessError(self.env._("Особову картку П-2 друкує лише кадровик."))
            docs.check_access("read")
        return {"doc_ids": docids, "doc_model": "hr.employee", "docs": docs, "data": data}
