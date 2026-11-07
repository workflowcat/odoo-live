"""Надіслати в ЕДО: один чи багато записів (рахунки, акти звірки, договори) одним кроком.

Кожен запис - окремий документ ЕДО з друкованою формою в PDF. Записи, які вже мають
переданий чи підписаний документ того самого виду, пропускаються, щоб місячна розсилка
актів не пішла двічі. Документ, якому бракує реквізитів, не зупиняє решту: він лишається
зі станом «Не надіслано» і причиною.
"""
import base64
import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.ua_edo import KINDS

DONE_STATES = ("sent", "delivered", "signed")
DEFAULT_REPORTS = {
    "ua.reconciliation.act": "l10n_ua_contract.action_report_ua_reconciliation_act",
}


class UaEdoSendWizard(models.TransientModel):
    _name = "ua.edo.send.wizard"
    _description = "Надіслати в ЕДО"

    res_model = fields.Char(required=True, readonly=True)
    res_ids = fields.Char(required=True, readonly=True)
    record_count = fields.Integer("Записів", compute="_compute_counts")
    already_count = fields.Integer("Уже передано", compute="_compute_counts")
    report_id = fields.Many2one("ir.actions.report", "Друкована форма",
                                domain="[('model', '=', res_model)]")
    kind = fields.Selection(KINDS, "Вид документа", compute="_compute_kind", store=True,
                            readonly=False, required=True)
    file = fields.Binary("Свій файл", help="Замість друкованої форми - готовий файл "
                                           "(лише для одного запису).")
    file_name = fields.Char("Назва файла")
    note = fields.Text("Коментар для контрагента")
    send_now = fields.Boolean("Надіслати одразу", default=True,
                              help="Вимкніть, щоб лише підготувати чернетки й переглянути їх.")
    skip_sent = fields.Boolean("Пропустити вже передані", default=True)

    @api.model
    def action_open(self, records):
        if not records:
            raise UserError(_("Виберіть записи для відправки."))
        report = self._default_report(records)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "view_mode": "form",
            "target": "new", "name": _("Надіслати в ЕДО"),
            "context": {"default_res_model": records._name,
                        "default_res_ids": ",".join(str(i) for i in records.ids),
                        "default_report_id": report.id if report else False},
        }

    @api.model
    def _default_report(self, records):
        Report = self.env["ir.actions.report"]
        ref = DEFAULT_REPORTS.get(records._name)
        if records._name == "account.move":
            goods = records.invoice_line_ids.filtered(
                lambda l: l.display_type == "product" and l.product_id
                and l.product_id.type != "service")
            ref = "l10n_ua_docs.action_report_ua_delivery_note" if goods \
                else "l10n_ua_docs.action_report_ua_service_act"
        report = self.env.ref(ref, raise_if_not_found=False) if ref else Report
        return report or Report.search([("model", "=", records._name)], limit=1)

    def _records(self):
        self.ensure_one()
        ids = [int(i) for i in (self.res_ids or "").split(",") if i.strip().isdigit()]
        return self.env[self.res_model].browse(ids).exists()

    def _already(self, record):
        return self.env["ua.edo.document"].search_count([
            ("res_model", "=", record._name), ("res_id", "=", record.id),
            ("direction", "=", "out"), ("kind", "=", self.kind), ("state", "in", DONE_STATES)])

    @api.depends("res_model", "res_ids", "kind")
    def _compute_counts(self):
        for wizard in self:
            records = wizard._records() if wizard.res_model else []
            wizard.record_count = len(records)
            wizard.already_count = sum(1 for r in records if wizard._already(r)) \
                if wizard.kind else 0

    @api.depends("report_id", "res_model")
    def _compute_kind(self):
        Document = self.env["ua.edo.document"]
        for wizard in self:
            records = wizard._records() if wizard.res_model else []
            wizard.kind = Document._kind_for(records[:1], wizard.report_id) if records \
                else "other"

    def action_send(self):
        self.ensure_one()
        records = self._records()
        if not records:
            raise UserError(_("Записів для відправки немає."))
        if self.file and len(records) > 1:
            raise UserError(_("Свій файл - лише для одного запису."))
        if not self.file and not self.report_id:
            raise UserError(_("Виберіть друковану форму або прикладіть файл."))
        if records._name == "account.move":
            draft = records.filtered(lambda m: m.state != "posted")
            if draft:
                raise UserError(_("Спершу проведіть: %s.") % ", ".join(draft.mapped("display_name")))
        Document = self.env["ua.edo.document"]
        documents = Document
        for record in records:
            if self.skip_sent and self._already(record):
                continue
            values = Document._values_from(record, self.report_id, self.kind)
            values["note"] = self.note or False
            document = Document.create(values)
            if self.file:
                mimetype = mimetypes.guess_type(self.file_name or "")[0] or "application/pdf"
                document._attach(base64.b64decode(self.file), mimetype,
                                 self.file_name or "%s.pdf" % document.name)
            else:
                document._attach(*Document._render(self.report_id, record))
            documents |= document
        if self.send_now:
            for document in documents:
                problems = document._check_ready()
                if problems:
                    document.write({"state": "error", "error": "; ".join(problems)})
                else:
                    document._send()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "l10n_ua_edo.action_ua_edo_document")
        action["domain"] = [("id", "in", documents.ids)]
        action["context"] = {"create": False}
        if len(documents) == 1:
            action.update(view_mode="form", res_id=documents.id,
                          views=[(False, "form")])
        return action
