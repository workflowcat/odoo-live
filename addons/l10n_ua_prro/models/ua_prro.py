"""Програмний РРО: каса, зміна, фіскальний чек.

Odoo не підписує чеки сам: ключ касира і зв'язок з податковою тримає сервіс ПРРО (Checkbox,
Вчасно.Каса, фіскальний сервер ДПС через адаптер). Odoo складає чек і шле його в міст
інтеграцій (`bp.bridge`), міст передає сервісу і повертає фіскальний номер. Контракт маршрутів -
у docs/base/spec-prro.md.

Навчальний режим (`mode = 'test'`) працює без моста: номер «ТЕСТ-…», у податкову нічого не йде.
Так можна показати й перевірити весь шлях до підключення сервісу.

Повтор безпечний: кожен чек має свій uuid, сервіс за ним не фіскалізує той самий чек двічі.
"""
import json
import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

KINDS = [
    ("sale", "Продаж"),
    ("return", "Повернення"),
    ("service_in", "Службове внесення"),
    ("service_out", "Службова видача"),
]
PAYMENT_TYPES = [("cash", "Готівка"), ("card", "Картка"), ("cashless", "Безготівково")]
STATES = [("draft", "Чернетка"), ("done", "Фіскалізовано"), ("error", "Не надіслано"),
          ("cancel", "Скасовано")]
SHIFT_HOURS = 23


class UaPrroRegister(models.Model):
    _name = "ua.prro.register"
    _description = "Каса ПРРО"
    _inherit = ["mail.thread"]
    _order = "company_id, name"
    _check_company_auto = True

    name = fields.Char("Каса", required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    mode = fields.Selection(
        [("test", "Навчальний (без податкової)"), ("bridge", "Через міст до сервісу ПРРО")],
        "Режим", required=True, default="test", tracking=True)
    provider = fields.Char("Сервіс ПРРО", default="checkbox", tracking=True,
                           help="Назва адаптера в мосту: checkbox, vchasno тощо.")
    fiscal_number = fields.Char("Фіскальний номер ПРРО", tracking=True, copy=False)
    location = fields.Char("Господарська одиниця", help="Адреса або назва точки продажу.")
    journal_ids = fields.One2many("account.journal", "ua_prro_register_id", "Журнали оплат")
    auto_send = fields.Boolean("Чек на кожну оплату", default=True,
                               help="Оплата в журналі каси одразу створює і надсилає чек.")
    auto_close_shift = fields.Boolean(
        "Закривати зміну автоматично",
        help="Зміну, відкриту довше %s годин, закриває планувальник із Z-звітом." % SHIFT_HOURS)
    shift_ids = fields.One2many("ua.prro.shift", "register_id", "Зміни")
    current_shift_id = fields.Many2one("ua.prro.shift", "Поточна зміна",
                                       compute="_compute_current_shift")

    _fiscal_number_unique = models.Constraint(
        "UNIQUE (company_id, fiscal_number)", "Цей фіскальний номер уже має інша каса.")

    @api.depends("shift_ids.state")
    def _compute_current_shift(self):
        for register in self:
            register.current_shift_id = register.shift_ids.filtered(
                lambda s: s.state == "open")[:1]

    @api.constrains("mode", "fiscal_number")
    def _check_fiscal_number(self):
        for register in self:
            if register.mode == "bridge" and not register.fiscal_number:
                raise UserError(_("Для роботи через міст вкажіть фіскальний номер ПРРО."))

    def _shift(self):
        """Відкрита зміна або нова."""
        self.ensure_one()
        shift = self.current_shift_id
        if not shift:
            shift = self.env["ua.prro.shift"].create({"register_id": self.id})
            self.invalidate_recordset(["current_shift_id"])
        return shift

    def service_operation(self, kind, amount):
        """Службове внесення чи видача готівки: чек без товарів, лише сума."""
        self.ensure_one()
        if kind not in ("service_in", "service_out"):
            raise UserError(_("Службова операція - внесення або видача."))
        if self.currency_id.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("Сума службової операції має бути більшою за нуль."))
        receipt = self.env["ua.prro.receipt"].create({
            "register_id": self.id, "kind": kind, "payment_type": "cash",
            "service_amount": amount})
        receipt.action_send()
        return receipt

    def action_service_in(self):
        return self._service_form("service_in")

    def action_service_out(self):
        return self._service_form("service_out")

    def _service_form(self, kind):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "ua.prro.receipt",
                "view_mode": "form", "target": "new",
                "context": {"default_register_id": self.id, "default_kind": kind,
                            "default_payment_type": "cash"}}

    def action_close_shift(self):
        for register in self:
            if not register.current_shift_id:
                raise UserError(_("Каса %s: відкритої зміни немає.") % register.name)
            register.current_shift_id.action_close()
        return True

    def _bridge(self, path, payload):
        """Запит у міст. Повертає (успіх, дані) і ніколи не кидає помилку мережі."""
        self.ensure_one()
        try:
            status, data = self.env["bp.bridge"]._call("POST", path, payload)
        except UserError as error:
            return False, {"error": str(error)}
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else None
            return False, {"error": message or _("Сервіс ПРРО відповів %s.") % status}
        return True, data if isinstance(data, dict) else {}


class UaPrroShift(models.Model):
    _name = "ua.prro.shift"
    _description = "Зміна ПРРО"
    _inherit = ["mail.thread"]
    _order = "opened_at desc, id desc"
    _check_company_auto = True

    name = fields.Char("Зміна", readonly=True, copy=False, default="/")
    register_id = fields.Many2one("ua.prro.register", "Каса", required=True, index=True,
                                  ondelete="restrict")
    company_id = fields.Many2one(related="register_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="register_id.currency_id")
    state = fields.Selection([("open", "Відкрита"), ("closed", "Закрита")], "Стан",
                             default="open", required=True, tracking=True, index=True)
    opened_at = fields.Datetime("Відкрито", required=True, default=fields.Datetime.now)
    closed_at = fields.Datetime("Закрито", readonly=True)
    provider_shift_id = fields.Char("Зміна в сервісі", readonly=True, copy=False)
    receipt_ids = fields.One2many("ua.prro.receipt", "shift_id", "Чеки")
    receipt_count = fields.Integer("Чеків", compute="_compute_totals")
    sales_cash = fields.Monetary("Продаж готівкою", compute="_compute_totals")
    sales_card = fields.Monetary("Продаж карткою", compute="_compute_totals")
    returns_total = fields.Monetary("Повернення", compute="_compute_totals")
    service_in = fields.Monetary("Службове внесення", compute="_compute_totals")
    service_out = fields.Monetary("Службова видача", compute="_compute_totals")
    cash_balance = fields.Monetary(
        "Готівка в касі", compute="_compute_totals",
        help="Внесення + продаж готівкою - повернення готівкою - видача.")
    z_number = fields.Char("Z-звіт", readonly=True, copy=False)
    z_url = fields.Char("Z-звіт у сервісі", readonly=True, copy=False)
    z_totals = fields.Text("Підсумки сервісу", readonly=True, copy=False)
    z_mismatch = fields.Boolean("Розбіжність із сервісом", readonly=True, copy=False)

    _one_open = models.UniqueIndex("(register_id) WHERE state = 'open'",
                                   "У каси може бути лише одна відкрита зміна.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.prro.shift") or "/"
        return super().create(vals_list)

    @api.depends("receipt_ids.state", "receipt_ids.amount_total", "receipt_ids.kind",
                 "receipt_ids.payment_type")
    def _compute_totals(self):
        for shift in self:
            done = shift.receipt_ids.filtered(lambda r: r.state == "done")

            def total(kind, payment=None):
                return sum(done.filtered(lambda r: r.kind == kind and (
                    payment is None or r.payment_type == payment)).mapped("amount_total"))

            shift.receipt_count = len(done)
            shift.sales_cash = total("sale", "cash")
            shift.sales_card = total("sale") - shift.sales_cash
            shift.returns_total = total("return")
            shift.service_in = total("service_in")
            shift.service_out = total("service_out")
            shift.cash_balance = (shift.service_in + shift.sales_cash - total("return", "cash")
                                  - shift.service_out)

    def local_totals(self):
        """Підсумки зміни за чеками в обліку - те, з чим звіряється Z-звіт."""
        self.ensure_one()
        return {"receipts": self.receipt_count,
                "sales": round(self.sales_cash + self.sales_card, 2),
                "returns": round(self.returns_total, 2),
                "service_in": round(self.service_in, 2),
                "service_out": round(self.service_out, 2)}

    def action_close(self):
        for shift in self:
            if shift.state != "open":
                raise UserError(_("Зміну %s уже закрито.") % shift.name)
            pending = shift.receipt_ids.filtered(lambda r: r.state in ("draft", "error"))
            if pending:
                raise UserError(_("У зміні %(shift)s є ненадіслані чеки: %(names)s. Надішліть або "
                                  "скасуйте їх перед Z-звітом.", shift=shift.name,
                                  names=", ".join(pending.mapped("name"))))
            local = shift.local_totals()
            register = shift.register_id
            if register.mode == "test":
                values = {"z_number": "Z-ТЕСТ-%s" % shift.id, "z_totals": json.dumps(local)}
            else:
                ok, data = register._bridge("/api/prro/shifts/close", {
                    "register": register.fiscal_number, "provider": register.provider,
                    "shift": shift.provider_shift_id or None, "totals": local})
                if not ok:
                    raise UserError(_("Z-звіт не отримано: %s") % data["error"])
                remote = data.get("totals") or {}
                mismatch = [key for key in ("sales", "returns", "service_in", "service_out")
                            if key in remote and register.currency_id.compare_amounts(
                                float(remote[key]), local[key]) != 0]
                values = {"z_number": data.get("z_number"), "z_url": data.get("url"),
                          "z_totals": json.dumps(remote, ensure_ascii=False),
                          "z_mismatch": bool(mismatch)}
                if mismatch:
                    shift.message_post(body=_(
                        "Z-звіт сервісу не збігається з чеками в обліку: %(keys)s. Сервіс: "
                        "%(remote)s; облік: %(local)s.", keys=", ".join(mismatch),
                        remote=json.dumps(remote, ensure_ascii=False),
                        local=json.dumps(local, ensure_ascii=False)))
            values.update(state="closed", closed_at=fields.Datetime.now())
            shift.write(values)
        return True


class UaPrroReceipt(models.Model):
    _name = "ua.prro.receipt"
    _description = "Фіскальний чек"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    register_id = fields.Many2one("ua.prro.register", "Каса", required=True, index=True,
                                  check_company=True, ondelete="restrict")
    company_id = fields.Many2one(related="register_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="register_id.currency_id")
    shift_id = fields.Many2one("ua.prro.shift", "Зміна", readonly=True, index=True, copy=False)
    kind = fields.Selection(KINDS, "Вид", required=True, default="sale")
    payment_type = fields.Selection(PAYMENT_TYPES, "Форма оплати", required=True,
                                    default="cash")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, tracking=True,
                             copy=False, index=True)
    uuid = fields.Char("Ключ чека", readonly=True, copy=False, index=True,
                       default=lambda self: str(uuid.uuid4()),
                       help="Сервіс не фіскалізує чек з тим самим ключем двічі.")
    move_ids = fields.Many2many("account.move", "ua_prro_receipt_move_rel", "receipt_id",
                                "move_id", "Документи", readonly=True, copy=False)
    payment_id = fields.Many2one("account.payment", "Оплата", readonly=True, index=True,
                                 copy=False)
    related_id = fields.Many2one("ua.prro.receipt", "Чек продажу", readonly=True,
                                 help="Для повернення: чек, за яким повертають.")
    partner_id = fields.Many2one("res.partner", "Покупець", readonly=True)
    line_ids = fields.One2many("ua.prro.receipt.line", "receipt_id", "Рядки", readonly=True)
    service_amount = fields.Monetary("Сума операції")
    amount_total = fields.Monetary("Сума", compute="_compute_amount_total", store=True)
    fiscal_code = fields.Char("Фіскальний номер", readonly=True, copy=False, index=True)
    fiscal_date = fields.Datetime("Час фіскалізації", readonly=True, copy=False)
    receipt_url = fields.Char("Чек у сервісі", readonly=True, copy=False)
    offline = fields.Boolean("Офлайн", readonly=True, copy=False,
                             help="Сервіс видав номер в офлайн-режимі; податкова отримає чек пізніше.")
    error = fields.Text("Помилка", readonly=True, copy=False)
    attempts = fields.Integer("Спроб", readonly=True, copy=False)

    _uuid_unique = models.Constraint("UNIQUE (uuid)", "Ключ чека має бути унікальним.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ua.prro.receipt") or "/"
        return super().create(vals_list)

    @api.depends("kind", "line_ids.amount", "service_amount")
    def _compute_amount_total(self):
        for receipt in self:
            if receipt.kind in ("service_in", "service_out"):
                receipt.amount_total = receipt.service_amount
            else:
                receipt.amount_total = sum(receipt.line_ids.mapped("amount"))

    def unlink(self):
        if any(receipt.state not in ("draft", "cancel") or receipt.attempts
               for receipt in self):
            raise UserError(_("Чек, який надсилали в сервіс, не видаляють."))
        return super().unlink()

    # ------------------------------------------------------------ складання
    @api.model
    def _from_payment(self, payment, moves):
        """Чек на оплату покупця за документами `moves` або нічого.

        Сплачено рівно суму документів - чек по товарах. Інакше (частина, аванс, кілька
        оплат) - один рядок на кожну ставку ПДВ, сума ділиться пропорційно."""
        register = payment.journal_id.ua_prro_register_id
        moves = moves.filtered(lambda m: m.move_type in ("out_invoice", "out_receipt",
                                                          "out_refund") and m.state == "posted")
        if not register or not moves or payment.partner_type != "customer":
            return self.browse()
        if payment.currency_id != register.currency_id:
            payment.message_post(body=_("Фіскальний чек не створено: ПРРО приймає лише гривню."))
            return self.browse()
        refunds = moves.filtered(lambda m: m.move_type == "out_refund")
        kind = "return" if refunds else "sale"
        if refunds and refunds != moves:
            payment.message_post(body=_("Фіскальний чек не створено: одна оплата сплачує і "
                                        "продаж, і повернення. Складіть чеки окремо."))
            return self.browse()
        related = self.browse()
        if kind == "return":
            related = self.search([("move_ids", "in", refunds.reversed_entry_id.ids),
                                   ("kind", "=", "sale"), ("state", "=", "done")], limit=1)
        documents_total = sum(moves.mapped("amount_total"))
        if register.currency_id.compare_amounts(payment.amount, documents_total) == 0:
            lines = [values for move in moves for values in self._item_lines(move)]
        else:
            lines = self._share_lines(moves, payment.amount)
        return self.create({
            "register_id": register.id, "kind": kind,
            "payment_type": payment.journal_id.ua_prro_payment_type or "cash",
            "move_ids": [(6, 0, moves.ids)], "payment_id": payment.id,
            "partner_id": payment.partner_id.id, "related_id": related.id,
            "line_ids": [(0, 0, values) for values in lines],
        })

    @api.model
    def _tax_info(self, taxes):
        percent = taxes.filtered(lambda t: t.amount_type == "percent")
        letters = [t.ua_prro_letter for t in taxes if t.ua_prro_letter]
        return sum(percent.mapped("amount")), (letters[0] if letters else False)

    @api.model
    def _item_lines(self, move):
        rows = []
        for line in move.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            if not line.quantity:
                continue
            rate, letter = self._tax_info(line.tax_ids)
            full = move.currency_id.round(line.price_total / (1 - (line.discount or 0.0) / 100.0)) \
                if line.discount != 100 else 0.0
            rows.append({
                "product_id": line.product_id.id, "name": line.name or line.product_id.display_name,
                "quantity": line.quantity, "uom_name": line.product_uom_id.name or "",
                "price_unit": move.currency_id.round(full / line.quantity),
                "discount_amount": move.currency_id.round(full - line.price_total),
                "amount": line.price_total, "tax_rate": rate, "tax_letter": letter,
            })
        return rows

    @api.model
    def _share_lines(self, moves, amount):
        """Частина оплати: рядок на кожну ставку ПДВ пропорційно сумам документів."""
        currency = moves[:1].currency_id
        groups = {}
        for line in moves.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
            rate, letter = self._tax_info(line.tax_ids)
            key = (rate, letter)
            groups[key] = groups.get(key, 0.0) + line.price_total
        total = sum(groups.values())
        if not total:
            raise UserError(_("Документи без сум: чек не скласти."))
        names = ", ".join(moves.mapped("name"))
        rows, left = [], amount
        keys = sorted(groups, key=lambda k: groups[k])
        for index, key in enumerate(keys):
            share = left if index == len(keys) - 1 else currency.round(amount * groups[key] / total)
            left -= share
            rate, letter = key
            label = _("Оплата за %s") % names
            if len(keys) > 1:
                label += _(" (ПДВ %s%%)") % ("%g" % rate)
            rows.append({"name": label, "quantity": 1.0, "price_unit": share, "amount": share,
                         "discount_amount": 0.0, "tax_rate": rate, "tax_letter": letter})
        return rows

    # ------------------------------------------------------------ надсилання
    def _payload(self):
        self.ensure_one()
        register = self.register_id
        payload = {
            "id": self.uuid, "register": register.fiscal_number, "provider": register.provider,
            "kind": self.kind, "number": self.name, "total": round(self.amount_total, 2),
            "payments": [{"type": self.payment_type, "sum": round(self.amount_total, 2)}],
            "goods": [{
                "code": line.product_id.default_code or (str(line.product_id.id)
                                                          if line.product_id else None),
                "barcode": line.product_id.barcode or None,
                "name": line.name, "unit": line.uom_name or None,
                "quantity": line.quantity, "price": round(line.price_unit, 2),
                "discount": round(line.discount_amount, 2), "sum": round(line.amount, 2),
                "taxes": [{"rate": line.tax_rate, "letter": line.tax_letter or None}]
                if line.tax_rate or line.tax_letter else [],
            } for line in self.line_ids],
            "related": self.related_id.fiscal_code or None,
            "email": self.partner_id.email or None,
            "shift": self.shift_id.provider_shift_id or None,
        }
        if self.kind in ("service_in", "service_out"):
            payload.pop("goods")
        return payload

    def action_send(self):
        for receipt in self:
            if receipt.state not in ("draft", "error"):
                raise UserError(_("Чек %s уже надіслано або скасовано.") % receipt.name)
            if receipt.kind == "return" and not receipt.related_id.fiscal_code:
                receipt.write({"state": "error", "attempts": receipt.attempts + 1,
                               "error": _("Немає фіскального чека продажу, за яким повертають.")})
                continue
            if receipt.currency_id.compare_amounts(receipt.amount_total, 0.0) <= 0:
                raise UserError(_("Сума чека %s має бути більшою за нуль.") % receipt.name)
            shift = receipt.shift_id if receipt.shift_id.state == "open" else \
                receipt.register_id._shift()
            receipt.shift_id = shift
            receipt._send()
        return True

    def _send(self):
        self.ensure_one()
        register = self.register_id
        attempts = self.attempts + 1
        if register.mode == "test":
            self.write({"state": "done", "attempts": attempts, "error": False,
                        "fiscal_code": "ТЕСТ-%s" % self.name, "fiscal_date": fields.Datetime.now()})
            return
        ok, data = register._bridge("/api/prro/receipts", self._payload())
        if not ok or not data.get("fiscal_code"):
            self.write({"state": "error", "attempts": attempts,
                        "error": data.get("error") or _("Сервіс не повернув фіскальний номер.")})
            _logger.warning("prro receipt %s not sent: %s", self.name, self.error)
            return
        if data.get("shift") and not self.shift_id.provider_shift_id:
            self.shift_id.provider_shift_id = data["shift"]
        self.write({
            "state": "done", "attempts": attempts, "error": False,
            "fiscal_code": data["fiscal_code"],
            "fiscal_date": fields.Datetime.to_datetime(data.get("fiscal_date"))
            if data.get("fiscal_date") else fields.Datetime.now(),
            "receipt_url": data.get("url") or False, "offline": bool(data.get("offline")),
        })

    def action_cancel(self):
        for receipt in self:
            if receipt.state == "done":
                raise UserError(_("Фіскалізований чек не скасовують - робіть повернення."))
        self.write({"state": "cancel"})
        return True

    def action_open_url(self):
        self.ensure_one()
        if not self.receipt_url:
            raise UserError(_("Сервіс не дав посилання на чек."))
        return {"type": "ir.actions.act_url", "url": self.receipt_url, "target": "new"}

    @api.model
    def _cron_retry(self):
        """Повторити чеки, що не пішли (до 20 спроб), і закрити довгі зміни, якщо так налаштовано."""
        for receipt in self.search([("state", "=", "error"), ("attempts", "<", 20)], limit=200):
            try:
                with self.env.cr.savepoint():
                    receipt.action_send()
            except UserError as error:
                _logger.warning("prro retry %s: %s", receipt.name, error)
        limit = fields.Datetime.now() - timedelta(hours=SHIFT_HOURS)
        for shift in self.env["ua.prro.shift"].search([
                ("state", "=", "open"), ("opened_at", "<", limit),
                ("register_id.auto_close_shift", "=", True)]):
            try:
                with self.env.cr.savepoint():
                    shift.action_close()
            except UserError as error:
                _logger.warning("prro auto close %s: %s", shift.name, error)


class UaPrroReceiptLine(models.Model):
    _name = "ua.prro.receipt.line"
    _description = "Рядок фіскального чека"
    _order = "receipt_id, id"

    receipt_id = fields.Many2one("ua.prro.receipt", required=True, ondelete="cascade",
                                 index=True)
    currency_id = fields.Many2one(related="receipt_id.currency_id")
    product_id = fields.Many2one("product.product", "Товар")
    name = fields.Char("Назва", required=True)
    quantity = fields.Float("Кількість", digits=(16, 3), required=True, default=1.0)
    uom_name = fields.Char("Одиниця")
    price_unit = fields.Monetary("Ціна з ПДВ")
    discount_amount = fields.Monetary("Знижка")
    amount = fields.Monetary("Сума", required=True)
    tax_rate = fields.Float("Ставка ПДВ, %")
    tax_letter = fields.Char("Літера")
