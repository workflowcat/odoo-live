"""Майстер завантаження галузевого пакета в компанію."""
from odoo import api, fields, models

ACTIONS = {
    "created": "створено",
    "matched": "підхоплено наявних",
    "kept": "уже були",
    "updated": "оновлено",
    "enabled": "увімкнено",
    "absent": "немає в системі",
}
SECTION_NAMES = {
    "groups": "Функції",
    "uoms": "Одиниці виміру",
    "categories": "Категорії",
    "workcenters": "Робочі центри",
    "products": "Товари і послуги",
    "boms": "Специфікації",
    "records": "Інші записи",
}


class UaCatalogLoad(models.TransientModel):
    _name = "ua.catalog.load"
    _description = "Завантаження галузевого каталогу"

    pack = fields.Selection(selection="_selection_pack", string="Пакет", required=True)
    company_id = fields.Many2one(
        "res.company", "Компанія", required=True, default=lambda self: self.env.company)
    mode = fields.Selection(
        [("missing", "Лише відсутнє"), ("update", "Оновити раніше завантажене")],
        string="Режим", required=True, default="missing",
        help="Лише відсутнє - наявне не чіпається. Оновити - назви, ціни і поля раніше "
             "завантажених записів знову беруться з пакета; склад специфікацій не "
             "перебудовується.")
    info = fields.Text("Що в пакеті", compute="_compute_info")
    result = fields.Text("Результат", readonly=True)
    state = fields.Selection([("draft", "Вибір"), ("done", "Завантажено")], default="draft")

    @api.model
    def _selection_pack(self):
        packs = self.env["ua.catalog"]._ua_packs()
        return sorted(((pid, p["name"]) for pid, p in packs.items()), key=lambda x: x[1])

    @api.depends("pack")
    def _compute_info(self):
        packs = self.env["ua.catalog"]._ua_packs()
        for wizard in self:
            pack = packs.get(wizard.pack)
            if not pack:
                wizard.info = False
                continue
            lines = [pack["summary"], ""]
            for section, count in pack["counts"].items():
                if count:
                    lines.append("%s: %d" % (SECTION_NAMES[section], count))
            if pack["missing"]:
                lines += ["", "Спершу встановіть модулі: " + ", ".join(pack["missing"])]
            for note in pack["notes"]:
                lines += ["", note]
            if pack["sources"]:
                lines += ["", "Джерела:"]
                lines += ["- %s %s" % (s.get("title", ""), s.get("url", ""))
                          for s in pack["sources"]]
            wizard.info = "\n".join(lines)

    def action_load(self):
        self.ensure_one()
        stats = self.env["ua.catalog"]._ua_load_pack(self.pack, self.company_id, self.mode)
        self.write({"result": self._ua_format(stats), "state": "done"})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    @staticmethod
    def _ua_format(stats):
        lines = []
        for section, label in SECTION_NAMES.items():
            if section in stats:
                parts = ["%s %d" % (ACTIONS.get(a, a), n) for a, n in stats[section].items()]
                lines.append("%s: %s" % (label, ", ".join(parts)))
        if stats.get("skipped_fields"):
            lines += ["", "Пропущено поля, яких немає в системі (потрібен модуль): "
                      + ", ".join(stats["skipped_fields"])]
        return "\n".join(lines) or "Нічого не змінено."
