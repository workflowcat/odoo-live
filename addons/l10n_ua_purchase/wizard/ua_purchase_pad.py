"""Пад швидкого замовлення: встав артикули - отримай запит на закупівлю.

Рядок на рядок, «АРТИКУЛ кількість». Роздільник - пробіл, кома або крапка з
комою; перед кількістю можна поставити множник «x» або «х». Без кількості -
одиниця. Невідомий артикул не мовчить: чарівник називає рядок і зупиняється.
"""
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

# Множники перед кількістю: латинська і кирилична «ікс», зірочка, знак множення.
MULTIPLIERS = ("x", "х", "*", "×")


class UaPurchasePad(models.TransientModel):
    _name = "ua.purchase.pad"
    _description = "Пад швидкого замовлення"

    raw_text = fields.Text(
        string="Артикули",
        help="Рядок на рядок: «АРТ-001 x 5», «АРТ-002;3», «АРТ-003 4» або "
             "просто «АРТ-004» (одна штука).",
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Підрозділ",
    )
    expense_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Рахунок витрат",
    )
    description = fields.Char(
        string="Для чого",
        help="Коротко: навіщо ця закупівля. Іде в опис запиту.",
    )

    # ------------------------------------------------------------------
    # Розбір тексту
    # ------------------------------------------------------------------
    @staticmethod
    def _ua_pad_parse_line(text):
        """Розібрати один рядок у пару (артикул, кількість).

        Повертає (код, кількість) або (код, None), якщо кількість не
        читається; для порожнього рядка - None.
        """
        text = (text or "").strip()
        if not text:
            return None
        parts = [part for part in re.split(r"[;,]|\s+", text) if part]
        code, rest = parts[0], parts[1:]
        if rest and rest[0].lower() in MULTIPLIERS:
            rest = rest[1:]
        elif rest and rest[0][:1].lower() in MULTIPLIERS and rest[0][1:]:
            rest = [rest[0][1:]] + rest[1:]
        if not rest:
            return code, 1.0
        if len(rest) > 1:
            return code, None
        try:
            qty = float(rest[0].replace(",", "."))
        except ValueError:
            return code, None
        if qty <= 0:
            return code, None
        return code, qty

    def _ua_pad_products(self):
        """Артикули активних товарів: {АРТИКУЛ У ВЕРХНЬОМУ РЕГІСТРІ: товар}."""
        products = self.env["product.product"].search(
            [("default_code", "!=", False), ("purchase_ok", "=", True)]
        )
        return {product.default_code.upper(): product for product in products}

    def _ua_pad_lines(self):
        """Розпізнані позиції: [(товар, кількість)]. Невідомий артикул або
        нечитана кількість зупиняє розбір зрозумілою помилкою."""
        self.ensure_one()
        known = self._ua_pad_products()
        found = {}
        order = []
        bad = []
        for raw in (self.raw_text or "").splitlines():
            parsed = self._ua_pad_parse_line(raw)
            if not parsed:
                continue
            code, qty = parsed
            if qty is None:
                bad.append(_("%(line)s - не зрозуміла кількість",
                             line=raw.strip()))
                continue
            product = known.get(code.upper())
            if not product:
                bad.append(_("%(line)s - артикулу «%(code)s» немає в товарах",
                             line=raw.strip(), code=code))
                continue
            if product in found:
                found[product] += qty
            else:
                found[product] = qty
                order.append(product)
        if bad:
            raise UserError(_(
                "Рядки, які не вдалося прочитати:\n%(rows)s\n\n"
                "Виправте артикул або кількість і повторіть.",
                rows="\n".join(bad),
            ))
        if not order:
            raise UserError(_(
                "Вставте артикули: рядок на рядок, «АРТИКУЛ кількість»."
            ))
        return [(product, found[product]) for product in order]

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_create_request(self):
        """Зробити запит на закупівлю з розпізнаних рядків."""
        self.ensure_one()
        lines = self._ua_pad_lines()
        today = fields.Date.context_today(self)
        request = self.env["purchase.request"].create({
            "description": self.description or _("Пад швидкого замовлення"),
            "ua_department_id": self.department_id.id,
            "ua_expense_account_id": self.expense_account_id.id,
            "line_ids": [(0, 0, {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_qty": qty,
                "name": product.display_name,
                "date_required": today,
                "estimated_cost": qty * (product.standard_price or 0.0),
            }) for product, qty in lines],
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Запит на закупівлю"),
            "res_model": "purchase.request",
            "res_id": request.id,
            "view_mode": "form",
        }
