"""Де шукати постачальників: довідник публічних джерел і вікно з готовими посиланнями.

Джерело - шаблон посилання з {query} (назва товару) і {dk021} (код ДК 021). Для виду
комплектуючих чи товару вікно підставляє назву й код і показує:
- договори і тендери в Prozorro за кодом ДК 021 - хто вже постачав такий товар
  публічним замовникам і за якою ціною;
- пошук на маркетплейсах;
- перевірку контрагента в реєстрі;
- постачальників, які вже є в базі для цього виду, з кількістю позицій.
Список джерел - дані: компанія дописує свої (галузеві каталоги, дилерів).
"""
from html import escape
from urllib.parse import quote

from odoo import api, fields, models

KINDS = [("public", "Публічні закупівлі"), ("market", "Маркетплейс"),
         ("registry", "Перевірка контрагента"), ("seller", "Продавець"), ("other", "Інше")]


class UaSupplierSource(models.Model):
    _name = "ua.supplier.source"
    _description = "Джерело пошуку постачальників"
    _order = "sequence, id"

    name = fields.Char("Назва", required=True)
    kind = fields.Selection(KINDS, "Що це", required=True, default="other")
    url_template = fields.Char("Посилання", required=True,
                               help="{query} - назва товару, {dk021} - код ДК 021. Джерело з "
                                    "{dk021} показується лише коли код відомий.")
    note = fields.Text("Що там знайти")
    class_codes = fields.Char("Лише для видів",
                              help="Коди видів комплектуючих через кому (fastener, metal); "
                                   "вид-група охоплює всі свої підвиди. Порожньо - для всіх.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    def _ua_url(self, query, dk021):
        self.ensure_one()
        url = self.url_template or ""
        if "{dk021}" in url and not dk021:
            return False
        return url.replace("{query}", quote(query or "")).replace("{dk021}", dk021 or "")

    def _ua_applies(self, cls):
        self.ensure_one()
        codes = {c.strip() for c in (self.class_codes or "").split(",") if c.strip()}
        if not codes or not cls:
            return True
        return bool(codes & set(cls.search([("id", "parent_of", cls.id)]).mapped("code")))


class UaSupplierFind(models.TransientModel):
    _name = "ua.supplier.find"
    _description = "Де шукати постачальників"

    query = fields.Char("Що шукати", required=True)
    dk021_id = fields.Many2one("ua.dk021", "Код ДК 021")
    class_id = fields.Many2one("ua.component.class", "Вид комплектуючих")
    links_html = fields.Html("Джерела", compute="_compute_links", sanitize=False)
    known_html = fields.Html("Вже в базі", compute="_compute_links", sanitize=False)

    @api.model
    def _ua_open(self, query, dk021=False, cls=False):
        wizard = self.create({"query": query, "dk021_id": dk021.id if dk021 else False,
                              "class_id": cls.id if cls else False})
        return {"type": "ir.actions.act_window", "name": "Де шукати постачальників",
                "res_model": self._name, "res_id": wizard.id, "view_mode": "form",
                "target": "new"}

    @api.depends("query", "dk021_id", "class_id")
    def _compute_links(self):
        Source = self.env["ua.supplier.source"]
        kinds = dict(KINDS)
        for rec in self:
            items = []
            for source in Source.search([]):
                if not source._ua_applies(rec.class_id):
                    continue
                url = source._ua_url(rec.query, rec.dk021_id.code if rec.dk021_id else False)
                if not url:
                    continue
                items.append('<li><a href="%s" target="_blank" rel="noopener">%s</a> '
                             '<span class="text-muted">%s%s</span></li>' % (
                                 escape(url, quote=True), escape(source.name),
                                 escape(kinds.get(source.kind, "")),
                                 (". " + escape(source.note)) if source.note else ""))
            rec.links_html = "<ul>%s</ul>" % "".join(items) if items else False
            rec.known_html = rec._ua_known_html()

    def _ua_known_html(self):
        self.ensure_one()
        if not self.class_id:
            return False
        groups = self.env["product.supplierinfo"]._read_group(
            [("ua_component_class_id", "child_of", self.class_id.id)],
            ["partner_id"], ["__count"])
        if not groups:
            return "<p class='text-muted'>Для цього виду ще немає цін постачальників.</p>"
        rows = sorted(groups, key=lambda g: -g[1])
        return "<ul>%s</ul>" % "".join(
            "<li>%s - позицій: %d</li>" % (escape(partner.display_name), count)
            for partner, count in rows)
