import base64
import json
import logging
import re

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .ai import pdf_page_images
from .codes import digits, iban_normalize, iban_valid, name_key, parse_date, party_code_valid, to_float

_logger = logging.getLogger(__name__)

STATES = [("new", "Отримано"), ("review", "Потребує перевірки"), ("bill", "Чернетка рахунку"),
          ("duplicate", "Дублікат"), ("error", "Помилка")]
DOC_TYPES = [("invoice", "Рахунок на оплату"), ("act", "Акт"), ("waybill", "Видаткова накладна"),
             ("tax_invoice", "Податкова накладна"), ("other", "Інше")]
LEVELS = [("ok", "Так"), ("warn", "Увага"), ("error", "Помилка")]
READABLE = ("application/pdf", "image/jpeg", "image/png", "image/webp")


class PurchaseIntake(models.Model):
    _name = "bp.purchase.intake"
    _description = "Вхідний рахунок"
    _inherit = ["mail.thread.main.attachment", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char("Номер", default="Новий", readonly=True, copy=False)
    state = fields.Selection(STATES, "Стан", default="new", required=True, tracking=True, index=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    email_from = fields.Char("Від кого", readonly=True)
    email_subject = fields.Char("Тема листа", readonly=True)
    received_at = fields.Datetime("Отримано", default=fields.Datetime.now, readonly=True)
    attachment_id = fields.Many2one("ir.attachment", "Документ", ondelete="set null", copy=False)
    source_kind = fields.Selection([("text", "Текст PDF"), ("image", "Зображення")], "Як прочитано", readonly=True)

    doc_type = fields.Selection(DOC_TYPES, "Тип документа")
    number = fields.Char("Номер документа", index=True)
    date = fields.Date("Дата документа")
    due_date = fields.Date("Оплатити до")
    contract = fields.Char("Договір")
    currency_name = fields.Char("Валюта")
    supplier_name = fields.Char("Постачальник")
    supplier_code = fields.Char("ЄДРПОУ / РНОКПП", index=True)
    supplier_ipn = fields.Char("ІПН платника ПДВ")
    supplier_iban = fields.Char("IBAN")
    supplier_bank = fields.Char("Банк")
    supplier_address = fields.Char("Адреса")
    supplier_email = fields.Char("E-mail постачальника")
    buyer_name = fields.Char("Покупець")
    buyer_code = fields.Char("ЄДРПОУ покупця")
    prices_include_vat = fields.Boolean("Ціни з ПДВ")
    amount_untaxed = fields.Float("Без ПДВ", digits=(16, 2))
    vat_rate = fields.Float("Ставка ПДВ, %", digits=(5, 2))
    amount_tax = fields.Float("ПДВ", digits=(16, 2))
    amount_total = fields.Float("Всього", digits=(16, 2))
    line_ids = fields.One2many("bp.purchase.intake.line", "intake_id", "Позиції", copy=True)
    check_ids = fields.One2many("bp.purchase.intake.check", "intake_id", "Перевірки")
    error_count = fields.Integer("Помилок", compute="_compute_check_counts", store=True)
    warn_count = fields.Integer("Попереджень", compute="_compute_check_counts", store=True)

    partner_id = fields.Many2one("res.partner", "Картка постачальника", tracking=True, index="btree_not_null")
    partner_status = fields.Selection(related="partner_id.bp_supplier_status", string="Статус постачальника")
    move_id = fields.Many2one("account.move", "Рахунок постачальника", readonly=True, copy=False)
    move_state = fields.Selection(related="move_id.state", string="Стан рахунку")
    duplicate_of_id = fields.Many2one("bp.purchase.intake", "Дублікат запису", readonly=True, copy=False)

    markdown = fields.Text("Текст документа", readonly=True)
    raw_json = fields.Text("Відповідь моделі", readonly=True)
    ai_model = fields.Char("Модель", readonly=True)
    ai_neurons = fields.Float("Нейрони Workers AI", readonly=True, digits=(12, 2))
    error_message = fields.Text("Помилка розбору", readonly=True)

    @api.depends("check_ids.level")
    def _compute_check_counts(self):
        for r in self:
            r.error_count = len(r.check_ids.filtered(lambda c: c.level == "error"))
            r.warn_count = len(r.check_ids.filtered(lambda c: c.level == "warn"))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            vals["name"] = seq.next_by_code("bp.purchase.intake") or "Новий"
        return super().create(vals_list)

    # ---- incoming email ------------------------------------------------
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        values = dict(custom_values or {})
        values.update({
            "email_from": msg_dict.get("email_from") or "",
            "email_subject": msg_dict.get("subject") or "",
            "received_at": msg_dict.get("date") or fields.Datetime.now(),
        })
        return super().message_new(msg_dict, custom_values=values)

    def _message_post_after_hook(self, message, msg_values):
        res = super()._message_post_after_hook(message, msg_values)
        if msg_values.get("message_type") == "email" and len(self) == 1 and self.state == "new" and not self.attachment_id:
            docs = message.attachment_ids.filtered(lambda a: a.mimetype in READABLE or (a.name or "").lower().endswith(".pdf"))
            doc = docs.filtered(lambda a: a.mimetype == "application/pdf")[:1] or docs[:1]
            if doc:
                self.attachment_id = doc
                self._process_safely()
            else:
                self.write({"state": "error", "error_message": "У листі немає PDF або зображення документа."})
        return res

    # ---- processing ----------------------------------------------------
    def action_reprocess(self):
        for r in self:
            if r.move_id:
                raise UserError("Рахунок постачальника вже створено. Видаліть чернетку, щоб розібрати документ ще раз.")
            if not r.attachment_id:
                pdf = r.message_main_attachment_id
                if not pdf:
                    raise UserError("Немає документа для розбору.")
                r.attachment_id = pdf
        self._process_safely()
        return True

    def _process_safely(self):
        for r in self:
            try:
                with self.env.cr.savepoint():
                    r._process()
            except Exception as e:  # noqa: BLE001 - every failure becomes a visible state on the record
                _logger.exception("intake %s failed", r.name)
                r.write({"state": "error", "error_message": str(e)})
                r.message_post(body=f"Розбір не вдався: {e}")

    def _process(self):
        self.ensure_one()
        ai = self.env["bp.ai"]
        att = self.attachment_id
        content = base64.b64decode(att.datas or b"")
        mimetype = att.mimetype or "application/pdf"
        spec = ai.load_spec("extract_invoice")
        text, images = "", []
        if mimetype.startswith("image/"):
            images = [content]
        else:
            text, _tokens = ai.to_markdown(att.name, content, mimetype)
            if len(re.sub(r"\s", "", text)) < 40:
                images = pdf_page_images(content)
                if not images:
                    raise UserError("У PDF немає ні тексту, ні зображень сторінок.")
        if images:
            out, usage, model = ai.extract_json(spec, images=images)
            text = f"Документ прочитано як зображення: {len(images)} стор."
        else:
            out, usage, model = ai.extract_json(spec, text=text)
        self.write({"markdown": text, "raw_json": json.dumps(out, ensure_ascii=False, indent=1), "ai_model": model,
                    "source_kind": "image" if images else "text",
                    "ai_neurons": float(usage.get("neurons") or 0), "error_message": False})
        self._apply_extraction(out)
        self.check_ids.unlink()
        self._check_document()
        self._link_partner()
        self._check_registry()
        duplicate = self._check_duplicate()
        if duplicate:
            self.write({"state": "duplicate", "duplicate_of_id": duplicate.id if duplicate._name == self._name else False})
        elif self.error_count:
            self.state = "review"
        else:
            self._create_bill()
        self.message_post(body=self._summary())

    def _apply_extraction(self, out):
        s = out.get("supplier") or {}
        b = out.get("buyer") or {}
        doc_type = out.get("doc_type")
        self.write({
            "doc_type": doc_type if doc_type in dict(DOC_TYPES) else "other",
            "number": (out.get("number") or "").strip() or False,
            "date": parse_date(out.get("date")),
            "due_date": parse_date(out.get("due_date")),
            "contract": out.get("contract") or False,
            "currency_name": "UAH" if re.search(r"грн|uah|₴", str(out.get("currency") or "грн"), re.I) else (out.get("currency") or "").upper(),
            "supplier_name": (s.get("name") or "").strip() or False,
            "supplier_code": digits(s.get("code")) or False,
            "supplier_ipn": digits(s.get("ipn")) or False,
            "supplier_iban": iban_normalize(s.get("iban")) or False,
            "supplier_bank": s.get("bank") or False,
            "supplier_address": s.get("address") or False,
            "supplier_email": s.get("email") or False,
            "buyer_name": b.get("name") or False,
            "buyer_code": digits(b.get("code")) or False,
            "prices_include_vat": bool(out.get("prices_include_vat")),
            # with prices incl. ПДВ the base is derived from what the document states (total and ПДВ), never taken from the model
            "amount_untaxed": round(to_float(out.get("amount_total")) - to_float(out.get("amount_tax")), 2) if out.get("prices_include_vat")
                              else (to_float(out.get("amount_untaxed")) or max(to_float(out.get("amount_total")) - to_float(out.get("amount_tax")), 0.0)),
            "vat_rate": to_float(out.get("vat_rate")),
            "amount_tax": to_float(out.get("amount_tax")),
            "amount_total": to_float(out.get("amount_total")),
            "line_ids": [Command.clear()] + [Command.create({
                "sequence": i, "name": (ln.get("name") or "").strip() or "Позиція",
                "quantity": to_float(ln.get("quantity")) or 1.0, "uom_name": ln.get("uom") or False,
                "price_unit": to_float(ln.get("price_unit")), "amount": to_float(ln.get("amount")),
            }) for i, ln in enumerate(out.get("lines") or [], 1)],
        })

    def _add_check(self, key, name, level, detail=""):
        self.env["bp.purchase.intake.check"].create({"intake_id": self.id, "key": key, "name": name,
                                                     "level": level, "detail": detail})

    def _check_document(self):
        code = self.supplier_code or ""
        if not code:
            self._add_check("code", "Код постачальника", "error", "ЄДРПОУ або РНОКПП у документі не знайдено")
        elif party_code_valid(code):
            self._add_check("code", "Код постачальника", "ok", f"{code}: контрольна сума збігається")
        else:
            self._add_check("code", "Код постачальника", "error", f"{code}: контрольна сума не збігається")
        if not self.number:
            self._add_check("number", "Номер документа", "error", "номер не знайдено")
        if not self.date:
            self._add_check("date", "Дата документа", "warn", "дату не знайдено")
        if self.supplier_iban:
            ok = iban_valid(self.supplier_iban)
            self._add_check("iban", "IBAN", "ok" if ok else "error",
                            f"{self.supplier_iban}: {'контрольна сума збігається' if ok else 'контрольна сума не збігається'}")
        else:
            self._add_check("iban", "IBAN", "warn", "IBAN у документі не знайдено")
        if self.doc_type == "tax_invoice":
            self._add_check("doc_type", "Тип документа", "error",
                            "податкова накладна: це не документ до оплати, зіставте її з рахунком постачальника")
        lines_sum = round(sum(self.line_ids.mapped("amount")), 2)
        bad_lines = [l.sequence for l in self.line_ids if abs(l.quantity * l.price_unit - l.amount) > 0.011]
        base = self.amount_total if self.prices_include_vat else self.amount_untaxed
        base_label = "з ПДВ" if self.prices_include_vat else "без ПДВ"
        if not self.line_ids:
            self._add_check("lines", "Позиції", "error", "таблицю позицій не знайдено")
        elif abs(lines_sum - base) > 0.011:
            self._add_check("lines", "Сума позицій", "error", f"позиції {lines_sum:.2f}, у документі {base_label} {base:.2f}")
        else:
            self._add_check("lines", "Сума позицій", "ok", f"{lines_sum:.2f} {base_label}")
        if bad_lines:
            self._add_check("line_math", "Кількість × ціна", "warn", f"не збігається в рядках {bad_lines}")
        tax_calc = round(self.amount_untaxed * self.vat_rate / 100, 2)
        if abs(tax_calc - self.amount_tax) > 0.021:
            self._add_check("vat", "ПДВ", "error", f"{self.vat_rate:g}% від {self.amount_untaxed:.2f} = {tax_calc:.2f}, "
                                                    f"у документі {self.amount_tax:.2f}")
        else:
            self._add_check("vat", "ПДВ", "ok", f"{self.vat_rate:g}%: {self.amount_tax:.2f}")
        total_calc = round(self.amount_untaxed + self.amount_tax, 2)
        if abs(total_calc - self.amount_total) > 0.011:
            self._add_check("total", "Всього", "error", f"без ПДВ + ПДВ = {total_calc:.2f}, у документі {self.amount_total:.2f}")
        else:
            self._add_check("total", "Всього", "ok", f"{self.amount_total:.2f}")
        if self.vat_rate and len(self.supplier_ipn or "") != 12:
            self._add_check("ipn", "ІПН платника ПДВ", "warn", "рахунок з ПДВ, але ІПН постачальника не знайдено")
        own = digits(self.company_id.company_registry)
        if not self.buyer_code:
            self._add_check("buyer", "Покупець", "warn", "код покупця не знайдено")
        elif not own:
            self._add_check("buyer", "Покупець", "warn", "у картці компанії немає ЄДРПОУ, порівняти неможливо")
        elif self.buyer_code != own:
            self._add_check("buyer", "Покупець", "error", f"документ виставлено на {self.buyer_name} ({self.buyer_code}), "
                                                           f"не на {self.company_id.name} ({own})")
        else:
            self._add_check("buyer", "Покупець", "ok", f"{self.company_id.name}")

    def _link_partner(self):
        code = self.supplier_code or ""
        Partner = self.env["res.partner"].with_context(active_test=False)
        partner = Partner.browse()
        if code:
            partner = Partner.search([("company_registry", "=", code), ("parent_id", "=", False)], limit=1)
        if not partner and self.supplier_ipn:
            partner = Partner.search([("vat", "=", self.supplier_ipn), ("parent_id", "=", False)], limit=1)
        created = not partner
        if created:
            partner = Partner.create({
                "name": self.supplier_name or f"Постачальник {code}",
                "is_company": len(code) != 10,
                "company_registry": code or False,
                "vat": self.supplier_ipn or False,
                "email": self.supplier_email or False,
                "street": self.supplier_address or False,
                "country_id": self.env.ref("base.ua").id,
                "supplier_rank": 1,
                "bp_supplier_status": "unverified",
                "bp_intake_id": self.id,
            })
            partner.message_post(body=f"Створено з вхідного рахунку {self.name} ({self.email_from}). Постачальник не перевірений.")
        self.partner_id = partner
        status = dict(partner._fields["bp_supplier_status"].selection).get(partner.bp_supplier_status, "без статусу")
        self._add_check("partner", "Картка постачальника", "warn" if partner.bp_supplier_status == "unverified" else "ok",
                        f"{'створено' if created else 'знайдено'}: {partner.name}; статус: {status}")
        iban = self.supplier_iban
        if iban and iban_valid(iban):
            known = {iban_normalize(b.acc_number) for b in partner.bank_ids}
            if iban in known:
                self._add_check("iban_known", "IBAN у картці", "ok", "рахунок уже є в картці постачальника")
            elif known:
                self._add_check("iban_known", "IBAN у картці", "error",
                                "у картці постачальника інший рахунок: підтвердьте новий IBAN дзвінком постачальнику")
            else:
                self.env["res.partner.bank"].create({"partner_id": partner.id, "acc_number": iban})
                self._add_check("iban_known", "IBAN у картці", "warn", "додано до картки, виплати на нього не дозволено до перевірки")

    def _check_registry(self):
        partner = self.partner_id
        if not party_code_valid(self.supplier_code):
            self._add_check("registry", "ЄДР", "warn", "не запитано: код постачальника недійсний")
            return
        data, error = partner._bp_registry_update()
        if error:
            not_found = any(m in error.lower() for m in ("не знайшов", "not found", " 404"))
            self._add_check("registry", "ЄДР", "error" if not_found else "warn",
                            f"{'постачальника немає в реєстрі' if not_found else 'не отримано'}: {error}")
            return
        reg = data.get("registry") or {}
        status = reg.get("status") or ""
        self._add_check("registry", "Стан у ЄДР", "ok" if re.search(r"зареєстр", status, re.I) else "error", status or "невідомо")
        if name_key(reg.get("full_name")) and name_key(self.supplier_name) and \
                name_key(self.supplier_name) in (name_key(reg.get("full_name")), name_key(reg.get("short_name"))):
            self._add_check("registry_name", "Назва за ЄДР", "ok", reg.get("full_name"))
        else:
            self._add_check("registry_name", "Назва за ЄДР", "warn",
                            f"у документі «{self.supplier_name}», у ЄДР «{reg.get('full_name')}»")
        vat_code = digits(reg.get("vat_code"))
        if self.supplier_ipn:
            if vat_code and vat_code == self.supplier_ipn:
                self._add_check("registry_vat", "ІПН за ЄДР", "ok", f"{vat_code}, платник ПДВ: {reg.get('vat_status') or 'невідомо'}")
            else:
                self._add_check("registry_vat", "ІПН за ЄДР", "error",
                                f"у документі {self.supplier_ipn}, у реєстрі {vat_code or 'немає'}")
        for m in data.get("checks") or []:
            if m.get("present") and m.get("key") != "status" and m.get("severity") in ("warn", "high"):
                self._add_check(f"odb_{m.get('key')}", m.get("title") or m.get("key"),
                                "error" if m.get("severity") == "high" else "warn", m.get("detail") or "")

    def _check_duplicate(self):
        if not self.number:
            return False
        dup = self.search([("id", "!=", self.id), ("number", "=", self.number), ("supplier_code", "=", self.supplier_code),
                           ("state", "not in", ("duplicate", "error"))], order="id", limit=1)
        if not dup and self.partner_id:
            dup = self.env["account.move"].search([("move_type", "in", ("in_invoice", "in_refund")),
                                                   ("partner_id", "=", self.partner_id.id), ("ref", "=", self.number),
                                                   ("state", "!=", "cancel")], limit=1)
        if dup:
            label = dup.name if dup._name == self._name else f"рахунок {dup.name or dup.id}"
            self._add_check("duplicate", "Дублікат", "error", f"документ № {self.number} уже зареєстровано: {label}")
        return dup

    def _purchase_tax(self):
        if not self.vat_rate:
            return self.env["account.tax"]
        return self.env["account.tax"].search([("type_tax_use", "=", "purchase"), ("amount_type", "=", "percent"),
                                               ("amount", "=", self.vat_rate), ("price_include", "=", False),
                                               ("company_id", "=", self.company_id.id)], limit=1)

    def action_create_bill(self):
        for r in self:
            if r.move_id:
                raise UserError("Чернетку рахунку вже створено.")
            if r.state == "duplicate":
                raise UserError("Це дублікат. Рахунок не створюється.")
            if not r.partner_id:
                raise UserError("Немає картки постачальника.")
            r._create_bill()
        return self.action_open_bill() if len(self) == 1 else True

    def _create_bill(self):
        self.ensure_one()
        tax = self._purchase_tax()
        if self.vat_rate and not tax:
            self._add_check("tax", "Податок ПДВ у плані рахунків", "warn", f"податок закупівлі {self.vat_rate:g}% не знайдено")
        move = self.env["account.move"].with_company(self.company_id).create({
            "move_type": "in_invoice",
            "partner_id": self.partner_id.id,
            "ref": self.number,
            "invoice_date": self.date or False,
            "invoice_date_due": self.due_date or False,
            "bp_intake_id": self.id,
            "narration": f"Створено з вхідного листа {self.name}: {self.email_subject or ''}",
            "invoice_line_ids": [Command.create({
                "name": f"{l.name}{f' ({l.uom_name})' if l.uom_name else ''}",
                "quantity": l.quantity, "price_unit": self._price_without_vat(l),
                "tax_ids": [Command.set(tax.ids)],
            }) for l in self.line_ids.sorted("sequence")],
        })
        if self.attachment_id:
            copy = self.attachment_id.copy({"res_model": "account.move", "res_id": move.id})
            move.message_main_attachment_id = copy
        diff = round(move.amount_total - self.amount_total, 2)
        self._add_check("bill_total", "Сума рахунку в Odoo", "ok" if abs(diff) < 0.011 else "warn",
                        f"{move.amount_total:.2f}" + ("" if abs(diff) < 0.011 else f", різниця з документом {diff:+.2f}"))
        self.write({"move_id": move.id, "state": "bill"})
        return move

    def _price_without_vat(self, line):
        if not (self.prices_include_vat and self.vat_rate):
            return line.price_unit
        amount = line.amount or line.price_unit * line.quantity
        return round(amount / (1 + self.vat_rate / 100) / (line.quantity or 1.0), 2)

    def _summary(self):
        state = dict(STATES)[self.state]
        return (f"Розібрано ({self.ai_model}): {self.supplier_name or '?'}, № {self.number or '?'}, "
                f"всього {self.amount_total:.2f} {self.currency_name or ''}. Стан: {state}. "
                f"Помилок {self.error_count}, попереджень {self.warn_count}.")

    def action_open_bill(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": self.move_id.id, "view_mode": "form"}

    def action_open_partner(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "res.partner", "res_id": self.partner_id.id, "view_mode": "form"}

    def action_refresh_registry(self):
        for r in self.filtered("partner_id"):
            r.check_ids.filtered(lambda c: c.key.startswith("registry") or c.key.startswith("odb_")).unlink()
            r._check_registry()
        return True


class PurchaseIntakeLine(models.Model):
    _name = "bp.purchase.intake.line"
    _description = "Позиція вхідного рахунку"
    _order = "intake_id, sequence, id"

    intake_id = fields.Many2one("bp.purchase.intake", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer("№", default=1)
    name = fields.Char("Найменування", required=True)
    quantity = fields.Float("Кількість", digits=(16, 3), default=1.0)
    uom_name = fields.Char("Од.")
    price_unit = fields.Float("Ціна без ПДВ", digits=(16, 2))
    amount = fields.Float("Сума без ПДВ", digits=(16, 2))


class PurchaseIntakeCheck(models.Model):
    _name = "bp.purchase.intake.check"
    _description = "Перевірка вхідного рахунку"
    _order = "intake_id, id"

    intake_id = fields.Many2one("bp.purchase.intake", required=True, ondelete="cascade", index=True)
    key = fields.Char("Ключ", required=True)
    name = fields.Char("Перевірка", required=True)
    level = fields.Selection(LEVELS, "Результат", required=True)
    detail = fields.Char("Деталі")
