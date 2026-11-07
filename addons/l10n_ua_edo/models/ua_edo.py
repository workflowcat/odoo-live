"""Електронний документообіг з контрагентами: вихідні й вхідні документи.

Odoo не тримає ключів сервісу ЕДО (Вчасно, M.E.Doc, Paperless тощо) і не підписує сам.
Вихідний документ: Odoo друкує форму (рахунок, акт, накладна, договір, акт звірки) у PDF,
складає реквізити і шле в міст (`bp.bridge`); міст передає файл сервісу, де його підписує
КЕП відповідальна особа і де він іде контрагенту. Стан документа в сервісі Odoo питає за
розкладом: доставлено, підписано контрагентом, відхилено з причиною. Підписаний файл (або
файл підпису) зберігається поруч із документом.

Вхідний документ: міст віддає нові документи контрагентів зі скриньки компанії, Odoo
заводить їх, шукає контрагента за ЄДРПОУ і рахунок постачальника за номером; підписати
чи відхилити можна з Odoo, сам підпис ставить сервіс.

Без моста працює тестовий режим (`ua_edo_mode = 'test'`): документ отримує номер
«ТЕСТ-…», нікуди не йде. Повтор після збою безпечний: кожен документ має свій uuid, і
сервіс за ним не створить дубль. Контракт маршрутів - docs/base/spec-edo.md.
"""
import base64
import logging
import re
import time
import uuid
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

KINDS = [
    ("invoice", "Рахунок на оплату"),
    ("act", "Акт виконаних робіт (наданих послуг)"),
    ("waybill", "Видаткова накладна"),
    ("contract", "Договір, додаткова угода"),
    ("reconciliation", "Акт звірки"),
    ("other", "Інший документ"),
]
STATES = [
    ("draft", "Чернетка"),
    ("sent", "Передано в сервіс"),
    ("delivered", "Доставлено контрагенту"),
    ("received", "Отримано, чекає рішення"),
    ("signed", "Підписано"),
    ("rejected", "Відхилено"),
    ("cancel", "Відкликано"),
    ("error", "Не надіслано"),
]
# Стан у сервісі -> наш стан. Невідомий стан сервісу нічого не змінює, лише пишеться в журнал.
PROVIDER_STATES = {
    "queued": "sent", "to_sign": "sent", "sent": "sent", "delivered": "delivered",
    "viewed": "delivered", "signed": "signed", "rejected": "rejected", "revoked": "cancel",
    "deleted": "cancel",
}
OPEN_OUT = ("sent", "delivered")
CODE = re.compile(r"\d{8}|\d{10}")
REFRESH_BATCH = 200
# Ознаки документа-джерела: перше поле, яке є в моделі.
DATE_FIELDS = ("invoice_date", "date_to", "date")
AMOUNT_FIELDS = ("amount_total", "closing_balance", "amount")
REPORT_KINDS = (("invoice_bill", "invoice"), ("service_act", "act"), ("delivery_note", "waybill"),
                ("reconciliation", "reconciliation"))


class ResCompany(models.Model):
    _inherit = "res.company"

    ua_edo_mode = fields.Selection(
        [("test", "Тестовий (без сервісу)"), ("bridge", "Через міст до сервісу ЕДО")],
        "Режим ЕДО", default="test", required=True)
    ua_edo_provider = fields.Char(
        "Сервіс ЕДО", default="vchasno",
        help="Назва адаптера в мосту: vchasno, medoc, paperless тощо.")


class UaEdoDocument(models.Model):
    _name = "ua.edo.document"
    _description = "Документ ЕДО"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    direction = fields.Selection([("out", "Вихідний"), ("in", "Вхідний")], "Напрям",
                                 required=True, default="out", index=True)
    kind = fields.Selection(KINDS, "Вид документа", required=True, default="other", tracking=True)
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True,
                             index=True, copy=False)
    partner_id = fields.Many2one("res.partner", "Контрагент", index=True, tracking=True,
                                 check_company=True)
    partner_code = fields.Char("ЄДРПОУ / РНОКПП контрагента",
                               help="Код, за яким сервіс знаходить контрагента.")
    partner_name = fields.Char("Назва контрагента в сервісі",
                               help="Для вхідного документа від невідомого контрагента.")
    doc_number = fields.Char("Номер документа", tracking=True)
    date = fields.Date("Дата документа", default=fields.Date.context_today)
    amount = fields.Monetary("Сума")
    currency_id = fields.Many2one("res.currency", "Валюта",
                                  default=lambda self: self.env.company.currency_id)
    note = fields.Text("Коментар для контрагента")
    res_model = fields.Char("Модель джерела", index=True, readonly=True)
    res_id = fields.Many2oneReference("Запис джерела", model_field="res_model", index=True,
                                      readonly=True)
    source_name = fields.Char("Документ в Odoo", compute="_compute_source_name")
    report_id = fields.Many2one("ir.actions.report", "Друкована форма", readonly=True)
    attachment_id = fields.Many2one("ir.attachment", "Файл документа", copy=False)
    signed_attachment_id = fields.Many2one(
        "ir.attachment", "Підписаний файл", copy=False,
        help="Файл із підписами сторін або окремий файл підпису з сервісу. Для паперового "
             "документа - скан із підписами.")
    uuid = fields.Char("Ключ документа", readonly=True, copy=False, index=True,
                       default=lambda self: str(uuid.uuid4()),
                       help="Сервіс за ним не створить дубль, якщо відправку повторили.")
    provider = fields.Char("Сервіс", readonly=True, copy=False)
    provider_id = fields.Char("Номер у сервісі", readonly=True, copy=False, index=True)
    provider_url = fields.Char("Посилання в сервісі", readonly=True, copy=False)
    provider_status = fields.Char("Стан у сервісі", readonly=True, copy=False)
    date_sent = fields.Datetime("Передано", readonly=True, copy=False)
    date_signed = fields.Datetime("Підписано", readonly=True, copy=False)
    date_refreshed = fields.Datetime("Стан перевірено", readonly=True, copy=False)
    signed_how = fields.Selection([("edo", "КЕП у сервісі"), ("paper", "На папері")],
                                  "Як підписано", readonly=True, copy=False)
    reject_reason = fields.Text("Причина відхилення", copy=False, tracking=True)
    error = fields.Text("Помилка", readonly=True, copy=False)
    attempts = fields.Integer("Спроб відправки", readonly=True, copy=False)

    _uuid_unique = models.Constraint("UNIQUE (uuid)", "Ключ документа має бути унікальним.")
    _provider_unique = models.UniqueIndex(
        "(company_id, provider_id) WHERE provider_id IS NOT NULL",
        "Цей документ сервісу вже заведено.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id
                ).next_by_code("ua.edo.document") or "/"
        documents = super().create(vals_list)
        for document in documents:
            if document.partner_id and not document.partner_code:
                document.partner_code = document.partner_id.commercial_partner_id.company_registry
        return documents

    @api.depends("res_model", "res_id")
    def _compute_source_name(self):
        for document in self:
            record = document._source()
            document.source_name = record.display_name if record else False

    @api.constrains("direction", "partner_id")
    def _check_partner(self):
        for document in self:
            if document.direction == "out" and not document.partner_id:
                raise ValidationError(_("Вихідний документ ЕДО має контрагента."))

    def unlink(self):
        if any(d.state not in ("draft", "error", "cancel") or d.provider_id for d in self):
            raise UserError(_("Документ, переданий у сервіс, не видаляють: його відкликають."))
        return super().unlink()

    # ------------------------------------------------------------------ джерело
    def _source(self):
        """Запис-джерело (рахунок, акт звірки, договір) або порожній запис."""
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return None
        record = self.env[self.res_model].browse(self.res_id).exists()
        return record or None

    @api.model
    def _kind_for(self, record, report):
        if record._name == "ua.contract":
            return "contract"
        name = report.report_name if report else ""
        for part, kind in REPORT_KINDS:
            if part in name:
                return kind
        return "other"

    @api.model
    def _values_from(self, record, report=None, kind=None):
        """Реквізити вихідного документа з запису-джерела."""
        date = next((record[f] for f in DATE_FIELDS if f in record._fields and record[f]), False)
        amount = next((record[f] for f in AMOUNT_FIELDS if f in record._fields), 0.0)
        currency = record.currency_id if "currency_id" in record._fields else False
        partner = record.partner_id.commercial_partner_id if "partner_id" in record._fields \
            else self.env["res.partner"]
        company = record.company_id if "company_id" in record._fields and record.company_id \
            else self.env.company
        return {
            "company_id": company.id, "direction": "out",
            "kind": kind or self._kind_for(record, report),
            "partner_id": partner.id or False,
            "partner_code": partner.company_registry or False,
            "doc_number": record.name if "name" in record._fields and record.name not in
            (False, "/") else record.display_name,
            "date": date or fields.Date.context_today(self),
            "amount": abs(amount or 0.0),
            "currency_id": (currency or company.currency_id).id,
            "res_model": record._name, "res_id": record.id,
            "report_id": report.id if report else False,
        }

    @api.model
    def _render(self, report, record):
        """(вміст, mimetype, назва файла) друкованої форми."""
        content, kind = report._render_qweb_pdf(report.report_name, record.ids)
        extension = "pdf" if kind == "pdf" else "html"  # у тестах Odoo друкує HTML
        title = False
        if report.print_report_name:
            try:
                title = safe_eval(report.print_report_name, {"object": record, "time": time})
            except Exception:  # noqa: BLE001 - назва файла не варта зупинки відправки
                title = False
        name = "%s.%s" % ((title or record.display_name or "document").replace("/", "-"),
                          extension)
        return content, "application/pdf" if extension == "pdf" else "text/html", name

    def _attach(self, content, mimetype, name, field="attachment_id"):
        self.ensure_one()
        attachment = self.env["ir.attachment"].create({
            "name": name, "raw": content, "mimetype": mimetype,
            "res_model": self._name, "res_id": self.id})
        self[field] = attachment
        return attachment

    # ---------------------------------------------------------------- відправка
    def _check_ready(self):
        self.ensure_one()
        problems = []
        if not self.attachment_id:
            problems.append(_("немає файла документа"))
        code = (self.partner_code or "").strip()
        if not CODE.fullmatch(code):
            problems.append(_("у контрагента немає ЄДРПОУ (8 цифр) чи РНОКПП (10 цифр)"))
        if self.company_id.ua_edo_mode == "bridge" and \
                not CODE.fullmatch((self.company_id.company_registry or "").strip()):
            problems.append(_("у компанії немає ЄДРПОУ"))
        return problems

    def _payload(self):
        self.ensure_one()
        company, partner = self.company_id, self.partner_id.commercial_partner_id
        return {
            "id": self.uuid, "provider": company.ua_edo_provider or None,
            "kind": self.kind, "number": self.doc_number or self.name,
            "date": fields.Date.to_string(self.date) if self.date else None,
            "amount": round(self.amount, 2), "currency": self.currency_id.name or None,
            "sender": {"code": company.company_registry or None, "name": company.name},
            "recipient": {"code": (self.partner_code or "").strip(), "name": partner.name,
                          "email": partner.email or None},
            "note": self.note or None,
            "file": {"name": self.attachment_id.name, "mimetype": self.attachment_id.mimetype,
                     "data": self.attachment_id.datas.decode() if self.attachment_id.datas
                     else None},
        }

    def _bridge(self, method, path, payload=None):
        """Запит у міст. Повертає (успіх, дані) і не кидає помилку мережі."""
        try:
            status, data = self.env["bp.bridge"]._call(method, path, payload)
        except UserError as error:
            return False, {"error": str(error)}
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else None
            return False, {"error": message or _("Сервіс ЕДО відповів %s.") % status}
        return True, data if isinstance(data, dict) else {}

    def _path(self, *parts):
        self.ensure_one()
        return "/api/edo/documents/%s" % "/".join(
            [quote(self.provider_id, safe="")] + list(parts))

    def action_send(self):
        for document in self:
            if document.direction != "out" or document.state not in ("draft", "error"):
                raise UserError(_("Документ %s уже передано або це вхідний документ.")
                                % document.name)
            problems = document._check_ready()
            if problems:
                raise UserError(_("Документ %s не можна надіслати: %s.")
                                % (document.name, "; ".join(problems)))
            document._send()
        return True

    def _send(self):
        self.ensure_one()
        company = self.company_id
        values = {"attempts": self.attempts + 1, "provider": company.ua_edo_provider or False}
        if company.ua_edo_mode == "test":
            values.update(state="sent", error=False, provider_id="ТЕСТ-%s" % self.name,
                          provider_status="test", date_sent=fields.Datetime.now())
            self.write(values)
            self._sync_source()
            return
        ok, data = self._bridge("POST", "/api/edo/documents", self._payload())
        if not ok or not data.get("id"):
            values.update(state="error",
                          error=data.get("error") or _("Сервіс не повернув номер документа."))
            self.write(values)
            _logger.warning("edo document %s not sent: %s", self.name, self.error)
            return
        status = data.get("status") or "sent"
        values.update(state=PROVIDER_STATES.get(status, "sent"), error=False,
                      provider_id=str(data["id"]), provider_url=data.get("url") or False,
                      provider_status=status, date_sent=fields.Datetime.now())
        self.write(values)
        self._sync_source()

    # ---------------------------------------------------------------- стан
    def action_refresh(self):
        for document in self:
            if document.company_id.ua_edo_mode != "bridge" or not document.provider_id:
                continue
            document._refresh()
        return True

    def _refresh(self):
        self.ensure_one()
        ok, data = self._bridge("GET", self._path())
        values = {"date_refreshed": fields.Datetime.now()}
        if not ok:
            values["error"] = data.get("error")
            self.write(values)
            return
        status = data.get("status")
        state = PROVIDER_STATES.get(status)
        values.update(provider_status=status or False, error=False)
        if data.get("url"):
            values["provider_url"] = data["url"]
        if not state:
            _logger.info("edo document %s: unknown status %r", self.name, status)
        elif state != self.state and not (self.direction == "in" and state in OPEN_OUT):
            values["state"] = state
            if state == "signed":
                values.update(signed_how="edo", date_signed=fields.Datetime.to_datetime(
                    data["signed_at"][:19].replace("T", " ")) if data.get("signed_at")
                    else fields.Datetime.now())
            if state == "rejected":
                values["reject_reason"] = data.get("reason") or _("Причину не вказано.")
        self.write(values)
        signed = data.get("signed_file")
        if state == "signed" and signed and signed.get("data") and not self.signed_attachment_id:
            self._attach(base64.b64decode(signed["data"]),
                         signed.get("mimetype") or "application/octet-stream",
                         signed.get("name") or "%s-signed" % self.name, "signed_attachment_id")
        if state in ("signed", "rejected") and "state" in values:
            self._sync_source()
            self._notify_result()

    def _sync_source(self):
        """Акт звірки йде за документом ЕДО: передано -> надіслано контрагенту, підписано
        контрагентом -> узгоджено з його сальдо, відхилено -> є розбіжності."""
        self.ensure_one()
        source = self._source()
        if self.direction != "out" or not source or source._name != "ua.reconciliation.act":
            return
        if self.state in OPEN_OUT:
            source.action_mark_sent()
        elif self.state == "signed" and source.state != "agreed":
            source.write({"their_filled": True, "their_closing_balance": source.closing_balance})
            source.action_mark_agreed()
        elif self.state == "rejected" and source.state != "disputed":
            source.action_mark_disputed()

    def _notify_result(self):
        """Подія в обговоренні документа-джерела: контрагент підписав чи відхилив."""
        self.ensure_one()
        source = self._source()
        if not source or not hasattr(source, "message_post"):
            return
        if self.state == "signed":
            body = _("ЕДО: %s підписано контрагентом.") % self.name
        else:
            body = _("ЕДО: %s відхилено контрагентом. Причина: %s") % (self.name,
                                                                        self.reject_reason)
        source.message_post(body=body)
        if self.state == "rejected":
            source_user = next((source[f] for f in ("invoice_user_id", "user_id")
                                if f in source._fields and source[f]), False)
            self.activity_schedule(
                "mail.mail_activity_data_todo", summary=_("Контрагент відхилив документ ЕДО"),
                note=self.reject_reason, user_id=(source_user or self.create_uid).id)

    @api.model
    def _cron_refresh(self):
        """Стан переданих документів і нові вхідні - для компаній, що працюють через міст."""
        companies = self.env["res.company"].search([("ua_edo_mode", "=", "bridge")])
        if not companies:
            return
        documents = self.search([("company_id", "in", companies.ids), ("direction", "=", "out"),
                                 ("state", "in", OPEN_OUT), ("provider_id", "!=", False)],
                                order="date_refreshed asc nulls first, id", limit=REFRESH_BATCH)
        for document in documents:
            document._refresh()
        for company in companies:
            self.with_company(company)._fetch_inbox(company)

    # ---------------------------------------------------------------- вхідні
    def _fetch_inbox(self, company):
        """Нові документи контрагентів зі скриньки компанії."""
        icp = self.env["ir.config_parameter"].sudo()
        key = "l10n_ua_edo.inbox_cursor.%s" % company.id
        params_path = "/api/edo/inbox"
        payload = {"company": company.company_registry or None,
                   "provider": company.ua_edo_provider or None,
                   "after": icp.get_param(key) or None}
        ok, data = self._bridge("POST", params_path, payload)
        if not ok:
            _logger.warning("edo inbox for %s: %s", company.name, data.get("error"))
            return self.browse()
        created = self.browse()
        for item in data.get("documents") or []:
            created |= self.with_company(company)._receive(company, item)
        if data.get("cursor"):
            icp.set_param(key, data["cursor"])
        return created

    def _receive(self, company, item):
        provider_id = str(item.get("id") or "")
        if not provider_id or self.search_count([("company_id", "=", company.id),
                                                 ("provider_id", "=", provider_id)]):
            return self.browse()
        sender = item.get("sender") or {}
        code = (sender.get("code") or "").strip()
        partner = self.env["res.partner"].search([
            ("company_registry", "=", code), ("parent_id", "=", False),
            ("company_id", "in", (company.id, False))], limit=1) if code else False
        kind = item.get("kind") if item.get("kind") in dict(KINDS) else "other"
        currency = self.env["res.currency"].search([("name", "=", item.get("currency"))],
                                                   limit=1) if item.get("currency") else False
        document = self.create({
            "company_id": company.id, "direction": "in", "kind": kind, "state": "received",
            "partner_id": partner.id if partner else False, "partner_code": code or False,
            "partner_name": sender.get("name") or False,
            "doc_number": item.get("number") or False,
            "date": fields.Date.to_date(item["date"][:10]) if item.get("date") else False,
            "amount": float(item.get("amount") or 0.0),
            "currency_id": (currency or company.currency_id).id,
            "provider": company.ua_edo_provider or False, "provider_id": provider_id,
            "provider_url": item.get("url") or False, "provider_status": item.get("status"),
            "note": item.get("note") or False,
        })
        file = item.get("file") or {}
        if file.get("data"):
            document._attach(base64.b64decode(file["data"]),
                             file.get("mimetype") or "application/pdf",
                             file.get("name") or "%s.pdf" % document.name)
        document._match_bill()
        if not partner:
            document.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Вхідний документ ЕДО від невідомого контрагента: %s")
                % (sender.get("name") or code or "?"))
        return document

    def _match_bill(self):
        """Вхідний документ -> рахунок постачальника з тим самим номером і контрагентом."""
        self.ensure_one()
        if self.res_model or not self.partner_id or not self.doc_number:
            return False
        bill = self.env["account.move"].search([
            ("company_id", "=", self.company_id.id),
            ("move_type", "in", ("in_invoice", "in_refund")),
            ("commercial_partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("ref", "=", self.doc_number)], limit=1)
        if bill:
            self.write({"res_model": "account.move", "res_id": bill.id})
        return bool(bill)

    def action_match_bill(self):
        for document in self:
            document._match_bill()
        return True

    def action_sign(self):
        """Погодити вхідний документ: сервіс ставить підпис відповідальної особи."""
        for document in self:
            if document.direction != "in" or document.state != "received":
                raise UserError(_("Підписати можна лише отриманий вхідний документ."))
            if document.company_id.ua_edo_mode == "bridge":
                ok, data = document._bridge("POST", document._path("sign"), {})
                if not ok:
                    raise UserError(_("Сервіс не прийняв підпис: %s") % data["error"])
            document.write({"state": "signed", "signed_how": "edo",
                            "date_signed": fields.Datetime.now(), "error": False})
            source = document._source()
            if source and hasattr(source, "message_post"):
                source.message_post(body=_("ЕДО: вхідний %s підписано.") % document.name)
        return True

    def action_reject(self):
        for document in self:
            if document.direction != "in" or document.state != "received":
                raise UserError(_("Відхилити можна лише отриманий вхідний документ."))
            if not (document.reject_reason or "").strip():
                raise UserError(_("Вкажіть причину відхилення: її побачить контрагент."))
            if document.company_id.ua_edo_mode == "bridge":
                ok, data = document._bridge("POST", document._path("reject"),
                                            {"reason": document.reject_reason})
                if not ok:
                    raise UserError(_("Сервіс не прийняв відхилення: %s") % data["error"])
            document.write({"state": "rejected", "error": False})
        return True

    # ------------------------------------------------------------- інші дії
    def action_revoke(self):
        """Відкликати вихідний документ, поки контрагент його не підписав."""
        for document in self:
            if document.direction != "out" or document.state not in OPEN_OUT:
                raise UserError(_("Відкликати можна лише переданий і ще не підписаний документ."))
            if document.company_id.ua_edo_mode == "bridge":
                ok, data = document._bridge("POST", document._path("revoke"), {})
                if not ok:
                    raise UserError(_("Сервіс не відкликав документ: %s") % data["error"])
            document.write({"state": "cancel"})
        return True

    def action_cancel(self):
        for document in self:
            if document.provider_id:
                raise UserError(_("Документ %s уже в сервісі: його відкликають.") % document.name)
        self.write({"state": "cancel"})
        return True

    def action_mark_signed(self):
        """Підписано поза ЕДО: контрагент підписав папір, скан прикладено."""
        for document in self:
            if document.direction != "out" or document.state not in ("draft", "error") + OPEN_OUT:
                raise UserError(_("Документ %s уже закрито.") % document.name)
            if not document.signed_attachment_id:
                raise UserError(_("Прикладіть скан документа з підписами сторін."))
            document.write({"state": "signed", "signed_how": "paper",
                            "date_signed": fields.Datetime.now()})
            document._sync_source()
        return True

    def action_open_source(self):
        self.ensure_one()
        source = self._source()
        if not source:
            raise UserError(_("Документ не пов'язаний із записом в Odoo."))
        return {"type": "ir.actions.act_window", "res_model": source._name, "res_id": source.id,
                "view_mode": "form"}

    def action_open_url(self):
        self.ensure_one()
        if not self.provider_url:
            raise UserError(_("Сервіс не дав посилання на документ."))
        return {"type": "ir.actions.act_url", "url": self.provider_url, "target": "new"}


class UaEdoSourceMixin(models.AbstractModel):
    """Лічильник і перехід до документів ЕДО з рахунку, договору чи акта звірки."""
    _name = "ua.edo.source.mixin"
    _description = "Документи ЕДО запису"

    ua_edo_count = fields.Integer("Документи ЕДО", compute="_compute_ua_edo_count")
    ua_edo_state = fields.Selection(STATES, "Стан ЕДО", compute="_compute_ua_edo_count",
                                    help="Стан останнього документа ЕДО цього запису.")

    def _compute_ua_edo_count(self):
        documents = self.env["ua.edo.document"].sudo().search(
            [("res_model", "=", self._name), ("res_id", "in", self.ids)], order="id")
        counts, states = {}, {}
        for document in documents:
            counts[document.res_id] = counts.get(document.res_id, 0) + 1
            if document.state != "cancel":
                states[document.res_id] = document.state
        for record in self:
            record.ua_edo_count = counts.get(record.id, 0)
            record.ua_edo_state = states.get(record.id, False)

    def action_ua_edo_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_edo.action_ua_edo_document")
        action["domain"] = [("res_model", "=", self._name), ("res_id", "=", self.id)]
        action["context"] = {"create": False}
        return action

    def action_ua_edo_send(self):
        return self.env["ua.edo.send.wizard"].action_open(self)


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "ua.edo.source.mixin"]


class UaContract(models.Model):
    _name = "ua.contract"
    _inherit = ["ua.contract", "ua.edo.source.mixin"]


class UaReconciliationAct(models.Model):
    _name = "ua.reconciliation.act"
    _inherit = ["ua.reconciliation.act", "ua.edo.source.mixin"]
