# -*- coding: utf-8 -*-
"""Майстер на сторінці, а не в діалозі.

Пункт меню відкриває сторінку (docs/payroll/words.md). Звіти OCA і кілька майстрів ядра
оголошені як діалог: форма з кнопками в <footer>. На сторінці Odoo футер не малює, тож
кнопки пропадають, а в заголовку стоїть «модель,NewId». Домішка лагодить обидва місця,
не змінюючи жодного файлу OCA:
  - кнопки з футера переїжджають у шапку форми (<header>), «Скасувати» прибирається -
    на сторінці є навігація;
  - кнопка «Новий» прибирається: майстер нічого не зберігає;
  - заголовок сторінки - назва майстра з довідника моделей (перекладена).
"""
from lxml import etree

from odoo import api, fields, models


class UaPageWizardMixin(models.AbstractModel):
    _name = "ua.page.wizard.mixin"
    _description = "Майстер, що відкривається сторінкою"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type != "form":
            return arch, view
        footer = arch.find(".//footer")
        if footer is None:
            return arch, view
        header = arch.find("header")
        if header is None:
            header = etree.Element("header")
            arch.insert(0, header)
        for button in footer.iter("button"):
            if button.get("special") == "cancel":
                continue
            # умова видимості могла стояти на обгортці, а не на самій кнопці
            if not button.get("invisible"):
                parent = button.getparent()
                while parent is not None and parent is not footer:
                    if parent.get("invisible"):
                        button.set("invisible", parent.get("invisible"))
                        break
                    parent = parent.getparent()
            button.tail = None
            header.append(button)
        footer.getparent().remove(footer)
        arch.set("create", "0")
        arch.set("delete", "0")
        arch.set("duplicate", "0")
        return arch, view

    @api.model
    def default_get(self, fields_list):
        """Сторінка звіту відкривається з уже заповненим періодом: з початку року до
        сьогодні. Так «Перегляд» працює з першого кліку, а період лишається змінюваним."""
        values = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        for name, value in (("date_from", today.replace(month=1, day=1)), ("date_to", today),
                            ("date_at", today)):
            if name in fields_list and not values.get(name):
                values[name] = value
        return values

    def _compute_display_name(self):
        title = self.env["ir.model"]._get(self._name).name
        for record in self:
            record.display_name = title


def _page(model):
    return type(model.title().replace(".", ""), (models.TransientModel,), {
        "_name": model,
        "_inherit": [model, "ua.page.wizard.mixin"],
        "__module__": __name__,
    })


GeneralLedger = _page("general.ledger.report.wizard")
JournalLedger = _page("journal.ledger.report.wizard")
TrialBalance = _page("trial.balance.report.wizard")
OpenItems = _page("open.items.report.wizard")
AgedPartnerBalance = _page("aged.partner.balance.report.wizard")
VatReport = _page("vat.report.wizard")
AssetCompute = _page("account.asset.compute")
AssetReport = _page("wiz.account.asset.report")
StatementImport = _page("account.statement.import")
