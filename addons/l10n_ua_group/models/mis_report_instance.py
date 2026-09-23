"""Читання порахованої матриці mis_builder по колонках.

l10n_ua_finrep уміє читати лише першу колонку звіту (`_ua_finrep_values`):
там колонка одна. У консолідації колонок багато - по одній на компанію,
«Разом до елімінації», «Елімінація ВГО» і «Консолідовано». Тому тут одна
додаткова точка: значення рядків форми за підписом колонки.

Другого розрахунку немає і тут: беремо ту саму матрицю
`mis.report.instance._compute_matrix()`, що її малює віджет.
"""

from odoo import fields, models

from odoo.addons.l10n_ua_finrep.models.mis_report import ROW_NAME_RE

from odoo.addons.mis_builder.models.accounting_none import AccountingNone


def _number(value):
    """Клітинка матриці як число: порожня (AccountingNone) - це нуль."""
    if value is AccountingNone or value is None or isinstance(value, str):
        return 0.0
    return float(value)


class MisReportInstance(models.Model):
    _inherit = "mis.report.instance"

    ua_group_consolidation = fields.Boolean(
        string="Консолідація групи",
        help="Звіт зібрано чарівником «Консолідація групи»: колонки - компанії, "
             "елімінація внутрішньогрупових оборотів і підсумок.",
    )

    def action_ua_group_consolidation(self):
        """Кнопка «Сформувати» в шапці списку: діалог параметрів консолідації.

        Діалог - разова дія з кнопки; сам звіт і далі відкривається сторінкою
        mis_builder, і список цієї сторінки веде пункт меню."""
        return {
            "type": "ir.actions.act_window",
            "name": "Консолідація групи",
            "res_model": "ua.group.consolidation",
            "view_mode": "form",
            "views": [(self.env.ref("l10n_ua_group.ua_group_consolidation_view_form").id, "form")],
            "target": "new",
        }

    def _ua_group_matrix(self):
        """{підпис колонки: {код рядка або ім'я контролю: сума}}."""
        self.ensure_one()
        matrix = self._compute_matrix()
        out = {}
        for subcol in matrix.iter_subcols():
            label = subcol.col.label
            values = out.setdefault(label, {})
            for row in matrix.iter_rows():
                if row.account_id:
                    continue  # рядки «деталі за рахунками» - не рядки форми
                name = row.kpi.name or ""
                cell = subcol.get_cell_for_row(row)
                value = _number(cell and cell.val)
                if name.startswith("ctl_"):
                    values[name] = value
                    continue
                match = ROW_NAME_RE.match(name)
                if match:
                    values[match.group(1)] = value
        return out

    def _ua_group_column(self, label):
        """{код рядка: сума} однієї колонки за її підписом."""
        self.ensure_one()
        return self._ua_group_matrix().get(label, {})
