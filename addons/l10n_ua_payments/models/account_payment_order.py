# -*- coding: utf-8 -*-
"""Відомість на перерахування = платіжне доручення пакетом OCA (`account.payment.order`).

Зарплату платять зарплатним проєктом: банк отримує список «рахунок - сума - призначення».
Раніше цей список був власною моделлю `ua.payment.batch`, яка нічого не проводила: рахунки
661, 6411, 6415, 651, 6851 закривалися потім правилом звірки виписки за текстом призначення.
Тепер список - це доручення OCA, а його затвердження створює справжні `account.payment`:
кожен платіж дебетує саме той рахунок, який закриває (661 працівникові, 6411/6415/651 ДПС),
і звірка закриває рядки листка за контрагентом і сумою, без регулярних виразів.

Що лишилося нашим:
  - вид виплати, рік і місяць (`ua_kind`, `ua_year`, `ua_month`) і збирання рядків із
    листків або авансової відомості;
  - текст призначення, той самий, що його шукають правила звірки виписки;
  - файл для банку - CSV у windows-1251 (Приват, Моно), формат живе на способі оплати;
  - друкована відомість і перевірки документа.

Стани беремо OCA і читаємо їх українською: чернетка (draft) - затверджено (open) -
файл сформовано (generated) - оплачено (uploaded, платежі проведені й звірені).
"""
import base64
import csv
import io
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MONTHS_UA = {
    1: "січень", 2: "лютий", 3: "березень", 4: "квітень", 5: "травень", 6: "червень",
    7: "липень", 8: "серпень", 9: "вересень", 10: "жовтень", 11: "листопад", 12: "грудень",
}
KINDS = [("advance", "Аванс"), ("salary", "Заробітна плата"), ("tax", "Податки і внески"),
         ("other", "Інша виплата")]
# Податки до бюджету: код правила листка -> (назва рядка, код рахунку, текст призначення).
# Текст збігається з правилами звірки виписки, тому платіж потім знаходиться сам.
TAXES = [
    ("PDFO", "ПДФО", "6411", "ПДФО за %s %s"),
    ("VZ", "Військовий збір", "6415", "Військовий збір за %s %s"),
    ("ESV", "Єдиний внесок (ЄСВ)", "651", "Єдиний внесок (ЄСВ) за %s %s"),
]
# Стан доручення OCA -> як його називає українська відомість.
STATE_LABELS = {"draft": "Чернетка", "open": "Затверджено", "generated": "Файл сформовано",
                "uploaded": "Оплачено", "cancel": "Скасовано"}
# Рахунки, на яких висить борг перед людиною: працівник і ЦПХ - 661, ФОП-підрядник - 6851
# (так само, як у карті проводок l10n_ua_payroll_account).
EMPLOYEE_ACCOUNT = "661"
CONTRACTOR_ACCOUNT = "6851"


class AccountPaymentOrder(models.Model):
    _name = "account.payment.order"
    _inherit = ["account.payment.order", "ua.checks.mixin"]

    # Ті самі стани OCA, названі українською: екрани «Період» і «Папери» показують їх людині.
    state = fields.Selection(
        selection=[(key, label) for key, label in STATE_LABELS.items()], string="Стан")
    ua_kind = fields.Selection(KINDS, "Вид виплати", tracking=True,
                               help="Порожньо - звичайне доручення OCA, не зарплатна відомість.")
    ua_year = fields.Integer("Рік", tracking=True)
    ua_month = fields.Integer("Місяць", tracking=True)
    ua_pay_date = fields.Date("Дата виплати", tracking=True,
                              help="Дата, якою проводяться платежі відомості.")
    ua_label = fields.Char("Назва", compute="_compute_ua_label", store=True)
    ua_note = fields.Text("Примітка")
    ua_legacy = fields.Boolean("Перенесена історія", readonly=True, copy=False,
                               help="Відомість, перенесена з ua.payment.batch; платежі за нею не проводились.")
    ua_line_count = fields.Integer("Рядків", compute="_compute_ua_totals")
    ua_without_account = fields.Integer("Без рахунку", compute="_compute_ua_totals")

    # ------------------------------------------------------------------ назва і підсумки
    @api.depends("ua_kind", "ua_year", "ua_month")
    def _compute_ua_label(self):
        labels = dict(KINDS)
        for order in self:
            if not order.ua_kind:
                order.ua_label = False
                continue
            order.ua_label = "%s %02d.%s" % (labels.get(order.ua_kind, ""),
                                             order.ua_month or 0, order.ua_year or "")

    @api.depends("ua_label", "name")
    def _compute_display_name(self):
        ua = self.filtered("ua_label")
        for order in ua:
            order.display_name = "%s · %s" % (order.ua_label, order.name or "")
        return super(AccountPaymentOrder, self - ua)._compute_display_name()

    @api.depends("payment_line_ids.amount_currency", "payment_line_ids.partner_bank_id")
    def _compute_ua_totals(self):
        for order in self:
            lines = order.payment_line_ids
            order.ua_line_count = len(lines)
            order.ua_without_account = len(lines.filtered(lambda line: not line.partner_bank_id))

    # ------------------------------------------------------------------ період і призначення
    def _ua_period(self):
        """Перший і останній день місяця відомості."""
        self.ensure_one()
        first = date(self.ua_year, self.ua_month, 1)
        next_first = date(self.ua_year + (self.ua_month == 12), self.ua_month % 12 + 1, 1)
        return first, next_first

    def _ua_purpose(self):
        """Текст призначення. Збігається з правилами звірки виписки."""
        self.ensure_one()
        month_name = MONTHS_UA.get(self.ua_month, "")
        if self.ua_kind == "advance":
            return "Аванс за %s %s" % (month_name, self.ua_year)
        if self.ua_kind == "salary":
            return "Заробітна плата за %s %s, остаточний розрахунок" % (month_name, self.ua_year)
        if self.ua_kind == "tax":
            return "Податки і внески за %s %s" % (month_name, self.ua_year)
        return "Виплата за %s %s" % (month_name, self.ua_year)

    def _ua_account(self, code):
        """Рахунок плану за коротким кодом (план Odoo може доповнювати коди нулями)."""
        self.ensure_one()
        company = self.company_id or self.env.company
        Acc = self.env["account.account"].with_company(company)
        acc = Acc.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1) or \
            Acc.search([("code", "=like", "%s%%" % code), ("company_ids", "in", company.id)],
                       order="code", limit=1)
        if not acc:
            raise UserError(_("Немає рахунку %(code)s у плані рахунків компанії %(company)s.",
                              code=code, company=company.name))
        return acc

    def _ua_employee_account(self, employee):
        """Рахунок, на якому висить борг перед цією людиною.

        Карта проводок кредитує 661 за трудовим договором і за ЦПХ, а оплату ФОП-підряднику
        - 6851 (правило FOP). Платіж має дебетувати той самий рахунок, інакше він нічого не
        закриє. Тому вид відносин питаємо в картки, а не вгадуємо за рахунком."""
        self.ensure_one()
        kind = employee.sudo().ua_contract_kind
        return self._ua_account(CONTRACTOR_ACCOUNT if kind == "fop" else EMPLOYEE_ACCOUNT)

    # ------------------------------------------------------------------ наповнення
    @api.model
    def ua_compose(self, company, year=None, month=None, kind=None, **params):
        """Нова відомість на перерахування за місяць, одразу заповнена.

        Що в неї входить - питання до самої відомості, не до екрана «Папери»."""
        if isinstance(company, int):
            company = self.env["res.company"].browse(company)
        company = company or self.env.company
        kind = kind or "salary"
        order = self.create({
            "payment_mode_id": company.sudo()._ua_payment_mode(kind).id,
            "journal_id": company.sudo()._ua_payment_journal().id,
            "date_prefered": "now",
            "ua_kind": kind, "ua_year": int(year), "ua_month": int(month),
            "ua_pay_date": fields.Date.context_today(self),
        })
        order.action_fill()
        return order

    def action_fill(self):
        for order in self:
            if not order.ua_kind:
                raise UserError(_("Заповнювати автоматично можна лише зарплатну відомість."))
            if order.state != "draft":
                raise UserError(_("Заповнити можна лише чернетку."))
            order.payment_line_ids.unlink()
            if order.ua_kind == "tax":
                order._ua_fill_taxes()
                continue
            order._ua_fill_people()
        return True

    def _ua_sources(self):
        """Пари (працівник, сума) для відомості на людей."""
        self.ensure_one()
        first, next_first = self._ua_period()
        if self.ua_kind == "advance":
            sheet = self.env["ua.advance.sheet"].search([
                ("company_id", "=", self.company_id.id), ("year", "=", self.ua_year),
                ("month", "=", self.ua_month)], limit=1)
            if not sheet:
                raise UserError(_("Немає авансової відомості за цей місяць."))
            return [(line.employee_id, round(line.amount, 2))
                    for line in sheet.line_ids.filtered(lambda l: l.amount > 0)]
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("state", "in", ("done", "verify")),
            ("date_from", ">=", first), ("date_from", "<", next_first),
        ])
        out = []
        for slip in slips:
            net = sum(slip.line_ids.filtered(lambda l: l.code == "NET").mapped("total"))
            if round(net, 2) > 0:
                out.append((slip.employee_id, round(net, 2)))
        return out

    def _ua_fill_people(self):
        """Рядки на працівників. Без IBAN або без контрагента відомість не збирається."""
        self.ensure_one()
        values = self._ua_sources()
        if not values:
            raise UserError(_("Немає сум до виплати за цей місяць."))
        values.sort(key=lambda item: item[0].name or "")
        no_partner, no_iban, vals_list = [], [], []
        purpose = self._ua_purpose()
        for employee, amount in values:
            partner = employee.sudo().work_contact_id
            bank = employee.sudo()._ua_payment_bank()
            account = self._ua_employee_account(employee)
            if not partner:
                no_partner.append(employee.name or "")
                continue
            if not bank:
                no_iban.append(employee.name or "")
                continue
            vals_list.append({
                "order_id": self.id, "partner_id": partner.id, "partner_bank_id": bank.id,
                "amount_currency": amount, "currency_id": self.company_currency_id.id,
                "communication": purpose, "ua_employee_id": employee.id,
                "ua_account_id": account.id,
            })
        if no_partner:
            raise UserError(_("Немає контрагента працівника: %s. Відкрийте картку і заповніть контакт.",
                              ", ".join(no_partner[:10])))
        if no_iban:
            raise UserError(_("Немає IBAN: %s. Впишіть банківський рахунок у картці працівника.",
                              ", ".join(no_iban[:10])))
        self.env["account.payment.line"].create(vals_list)

    def _ua_fill_taxes(self):
        """Рядки на сплату ПДФО, військового збору і ЄСВ. Суми - з проведених листків місяця."""
        self.ensure_one()
        first, next_first = self._ua_period()
        month_name = MONTHS_UA.get(self.ua_month, "")
        slips = self.env["hr.payslip"].search([
            ("company_id", "=", self.company_id.id), ("state", "=", "done"),
            ("date_from", ">=", first), ("date_from", "<", next_first),
        ])
        lines = slips.mapped("line_ids")
        partner = self.company_id.sudo()._ua_partner("dps")
        vals_list, no_iban = [], []
        for code, label, account_code, purpose in TAXES:
            amount = round(abs(sum(lines.filtered(lambda l: l.code == code).mapped("total"))), 2)
            if not amount:
                continue
            bank = self.company_id.sudo()._ua_tax_bank(code)
            if not bank:
                no_iban.append(label)
                continue
            vals_list.append({
                "order_id": self.id, "partner_id": partner.id, "partner_bank_id": bank.id,
                "amount_currency": amount, "currency_id": self.company_currency_id.id,
                "communication": purpose % (month_name, self.ua_year),
                "ua_label": label, "ua_account_id": self._ua_account(account_code).id,
            })
        if no_iban:
            raise UserError(_("Немає рахунку бюджету: %s. Впишіть рахунки в картці компанії.",
                              ", ".join(no_iban)))
        if not vals_list:
            raise UserError(_("За цей місяць немає проведених листків, тому немає що платити."))
        self.env["account.payment.line"].create(vals_list)
        return True

    # ------------------------------------------------------------------ рух документа
    def action_confirm(self):
        """Затвердити: OCA складає платежі (ще чернетки) з рядків відомості."""
        for order in self:
            if order.state != "draft":
                raise UserError(_("Затвердити можна лише чернетку."))
            if not order.payment_line_ids:
                raise UserError(_("Немає рядків. Натисніть «Заповнити»."))
            missing = order.payment_line_ids.filtered(lambda line: not line.partner_bank_id)
            if missing:
                raise UserError(_("Без рахунку: %s. Впишіть IBAN у картці працівника або в рядку.",
                                  ", ".join(missing.mapped("ua_payee_name")[:10])))
            # Лише відомості зарплати і податків: там рахунки з карток працівників і бюджету.
            # Звичайні відомості OCA (постачальникам) лишають рішення про надійність людині.
            if order.ua_kind:
                order._ua_trust_banks()
            order.draft2open()
        return True

    def _ua_trust_banks(self):
        """Зарплатний проєкт платить на рахунки, які бухгалтер уже вписав у картки.

        Odoo вимагає окремої позначки надійності рахунку одержувача (`allow_out_payment`),
        інакше платіж не проводиться. Позначаємо рахунки рядків і пишемо про це в стрічку -
        рішення видиме, а не мовчазне."""
        self.ensure_one()
        banks = self.payment_line_ids.mapped("partner_bank_id").filtered(
            lambda b: not b.allow_out_payment)
        if not banks:
            return
        banks.sudo().write({"allow_out_payment": True})
        self.message_post(body=_("Рахунки одержувачів позначено надійними для виплат: %s.",
                                 len(banks)))

    def action_cancel(self):
        """Скасувати відомість. Odoo 19 лишає платіж у стані «в обробці» (in_process), а
        OCA повертає в чернетку лише проведені: без цього скасована відомість залишала за
        собою проведені платежі і закриті ними рядки 661."""
        self.payment_ids.filtered(
            lambda p: p.state in ("posted", "in_process", "paid")).action_draft()
        return super().action_cancel()

    def action_draft(self):
        for order in self:
            if order.state == "draft":
                continue
            if order.state == "uploaded":
                raise UserError(_("Оплачену відомість повертають у чернетку лише скасуванням "
                                  "платежів: натисніть «Скасувати»."))
            order.action_cancel()
            order.cancel2draft()
        return True

    def action_paid(self):
        """Позначити оплаченою: платежі проводяться і закривають 661 / 6411 / 6415 / 651."""
        for order in self:
            if order.state not in ("open", "generated"):
                raise UserError(_("Позначити оплаченою можна лише затверджену відомість."))
            if order.state == "open":
                order.action_export()
            order.generated2uploaded()
        return True

    # ------------------------------------------------------------------ проведення і звірка
    def post_and_reconcile(self):
        """Провести платежі і закрити ними рядки листків за контрагентом.

        OCA звіряє платіж із тим рядком проводки, який стоїть у `move_line_id`. Зарплатна
        відомість такого рядка не має: сума до виплати - це залишок 661 працівника за
        місяць (нарахування мінус утримання), тобто кілька рядків одразу. Тому звіряємо
        платіж з усіма незакритими рядками того самого рахунку й контрагента за місяць
        відомості: разом вони дають нуль - рівно те, що бухгалтер чекає побачити на 661.
        """
        others = self.filtered(lambda order: not order.ua_kind)
        if others:
            super(AccountPaymentOrder, others).post_and_reconcile()
        for order in self - others:
            order.payment_ids.filtered(lambda p: p.state == "draft").action_post()
            order._ua_reconcile()
        return True

    def _ua_reconcile(self):
        self.ensure_one()
        first, next_first = self._ua_period()
        Line = self.env["account.move.line"]
        for payment in self.payment_ids:
            account = payment.destination_account_id
            if not account.reconcile or not payment.move_id:
                continue
            own = payment.move_id.line_ids.filtered(
                lambda line: line.account_id == account and not line.reconciled)
            if not own:
                continue
            open_lines = Line.search([
                ("account_id", "=", account.id),
                ("partner_id", "=", payment.partner_id.id),
                ("company_id", "=", self.company_id.id),
                ("parent_state", "=", "posted"),
                ("reconciled", "=", False),
                ("date", ">=", first), ("date", "<", next_first),
            ])
            batch = own | open_lines
            if len(batch) > 1:
                batch.reconcile()

    # ------------------------------------------------------------------ файл для банку
    def _ua_bank_file(self):
        """CSV для зарплатного проєкту: ПІБ, РНОКПП, рахунок, сума, призначення."""
        self.ensure_one()
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["ПІБ", "РНОКПП", "Рахунок", "Сума", "Призначення"])
        purpose = self._ua_purpose()
        for line in self.payment_line_ids:
            writer.writerow([
                line.ua_payee_name,
                line.ua_payee_code,
                line.ua_payee_iban,
                ("%.2f" % line.amount_currency).replace(".", ","),
                line.communication or purpose,
            ])
        return stream.getvalue().encode("windows-1251", "replace")

    def generate_payment_file(self):
        """Гак OCA: який файл віддає цей спосіб оплати."""
        self.ensure_one()
        if self.ua_kind and self.payment_mode_id.ua_file_format == "csv1251":
            return self._ua_bank_file(), "%s.csv" % (self.ua_label or self.name)
        return super().generate_payment_file()

    def action_export(self):
        """Кнопка «Файл для банку»: формує файл, чіпляє його до відомості і віддає посилання."""
        self.ensure_one()
        if self.state == "draft":
            raise UserError(_("Спершу затвердьте відомість."))
        content, filename = self.generate_payment_file()
        attachment = self.env["ir.attachment"].create({
            "name": filename, "type": "binary", "datas": base64.b64encode(content),
            "mimetype": "text/csv", "res_model": self._name, "res_id": self.id,
        })
        self.message_post(body=_("Сформовано файл для банку: %s", attachment.name),
                          attachment_ids=[attachment.id])
        if self.state == "open":
            self.write({"state": "generated", "date_generated": fields.Date.context_today(self),
                        "generated_user_id": self.env.uid})
        return {"type": "ir.actions.act_url", "url": "/web/content/%s?download=1" % attachment.id,
                "target": "self"}

    # ------------------------------------------------------------------ перевірки
    def _checks(self):
        self.ensure_one()
        if not self.ua_kind:
            return super()._checks()
        out = []
        if not self.payment_line_ids:
            out.append(self._check_error("Немає рядків відомості", target=self._target_record(self)))
            return out
        no_iban = self.payment_line_ids.filtered(lambda l: not l.partner_bank_id)
        if no_iban:
            out.append(self._check_error(
                "Рядки без IBAN", fact=len(no_iban),
                target=self._target_records(no_iban, "account.payment.line")))
        else:
            out.append(self._check_ok("Усі рядки мають IBAN"))

        first, next_first = self._ua_period()
        total = round(sum(self.payment_line_ids.mapped("amount_currency")), 2)
        if self.ua_kind == "salary":
            slips = self.env["hr.payslip"].search([
                ("company_id", "=", self.company_id.id), ("state", "in", ("done", "verify")),
                ("date_from", ">=", first), ("date_from", "<", next_first),
            ])
            net_total = round(sum(slips.line_ids.filtered(lambda l: l.code == "NET").mapped("total")), 2)
            if abs(net_total - total) > 0.01:
                out.append(self._check_error(
                    "Сума відомості не збігається з «до виплати» листків місяця",
                    fact="%.2f ≠ %.2f" % (total, net_total),
                    target=self._target_records(slips, "hr.payslip")))
            else:
                out.append(self._check_ok("Сума відомості збігається з листками місяця",
                                          fact="%.2f" % total))
            if self.state != "draft":
                not_done = slips.filtered(lambda s: s.state != "done")
                if not_done:
                    out.append(self._check_warn(
                        "Відомість затверджена, а листок ще не проведений остаточно",
                        fact=len(not_done), target=self._target_records(not_done, "hr.payslip")))
        elif self.ua_kind == "advance":
            sheet = self.env["ua.advance.sheet"].search([
                ("company_id", "=", self.company_id.id), ("year", "=", self.ua_year),
                ("month", "=", self.ua_month)], limit=1)
            if not sheet:
                out.append(self._check_error("Немає авансової відомості за цей місяць",
                                             target=self._target_record(self)))
            else:
                sheet_total = round(sum(sheet.line_ids.filtered(lambda l: l.amount > 0)
                                        .mapped("amount")), 2)
                if abs(sheet_total - total) > 0.01:
                    out.append(self._check_error(
                        "Сума відомості не збігається з авансовою відомістю",
                        fact="%.2f ≠ %.2f" % (total, sheet_total),
                        target=self._target_record(sheet)))
                else:
                    out.append(self._check_ok("Сума відомості збігається з авансовою відомістю",
                                              fact="%.2f" % total))

        out.append(self._ua_check_payments())
        out.append(self._check_ok("Стан документа", fact=STATE_LABELS.get(self.state, self.state)))
        return out

    def _ua_check_payments(self):
        """Чи стоять за відомістю справжні платежі і чи закрили вони рахунок."""
        self.ensure_one()
        if self.ua_legacy:
            return self._check_warn(
                "Перенесена історія: платежів за відомістю немає",
                fact="ua.payment.batch", target=self._target_record(self))
        if self.state in ("draft", "cancel"):
            return self._check_ok("Платежі ще не складені", fact=STATE_LABELS.get(self.state))
        payments = self.payment_ids
        if not payments:
            return self._check_error("Затверджена відомість без платежів",
                                     target=self._target_record(self))
        not_posted = payments.filtered(lambda p: p.state not in ("posted", "paid", "in_process"))
        if self.state == "uploaded" and not_posted:
            return self._check_error("Оплачена відомість із непроведеними платежами",
                                     fact=len(not_posted),
                                     target=self._target_records(not_posted, "account.payment"))
        if self.state != "uploaded":
            return self._check_ok("Платежі складені, чекають на оплату", fact=len(payments))
        return self._check_ok("Платежі проведені", fact=len(payments),
                              target=self._target_records(payments, "account.payment"))
