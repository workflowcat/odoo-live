import json
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

STAGES = [("new", "Нова"), ("collect", "Збір даних"), ("screen", "Скринінг"), ("assess", "Оцінка"), ("done", "Рішення")]
DECISIONS = [("cleared", "Погоджено"), ("flagged", "Погоджено з умовами"), ("rejected", "Відхилено")]
RISKS = [("low", "Низький"), ("medium", "Середній"), ("high", "Високий"), ("critical", "Критичний")]
GROUPS = [("counterparty", "Контрагент"), ("rail", "Платіжний провайдер"), ("person", "Фізична особа")]
REC = {"cleared": "cleared", "flagged": "flagged", "rejected": "rejected"}


class KycCase(models.Model):
    _name = "kyc.case"
    _description = "Справа KYC"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char("Номер", default="Новий", copy=False, readonly=True)
    partner_id = fields.Many2one("res.partner", "Контрагент", required=True, tracking=True, index=True)
    code = fields.Char("ЄДРПОУ / РНОКПП", compute="_compute_code", inverse="_inverse_code", store=True, readonly=False)
    kind = fields.Selection([("company", "Юрособа"), ("fop", "ФОП"), ("person", "Фізособа")], "Тип", default="company", required=True)
    subject_group = fields.Selection(GROUPS, "Група", default="counterparty", required=True)
    role = fields.Char("Роль у відносинах", help="Клієнт, постачальник, платіжний провайдер, директор, UBO…")
    introduced_by = fields.Char("Хто привів", help="Партнер або колега, від кого прийшов контрагент")
    stage = fields.Selection(STAGES, "Етап", default="new", required=True, tracking=True, group_expand="_expand_stages")
    decision = fields.Selection(DECISIONS, "Рішення", tracking=True, copy=False)
    risk = fields.Selection(RISKS, "Ризик", tracking=True)
    summary = fields.Text("Висновок")
    user_id = fields.Many2one("res.users", "Аналітик", default=lambda s: s.env.user, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company)
    active = fields.Boolean(default=True)

    # ЄДР snapshot (from the last screening)
    registry_name = fields.Char("Повна назва (ЄДР)")
    registry_status = fields.Char("Стан (ЄДР)")
    registry_date = fields.Date("Дата реєстрації")
    registry_kved = fields.Char("Основний КВЕД")
    registry_head = fields.Char("Керівник")
    registry_address = fields.Char("Адреса")
    registry_capital = fields.Float("Статутний капітал")
    registry_vat = fields.Char("ПДВ")
    registry_beneficiaries = fields.Text("Бенефіціари / засновники")
    screened_at = fields.Datetime("Скринінг ЄДР")

    # checklist
    check_registry = fields.Boolean("ЄДР перевірено")
    check_ubo = fields.Boolean("Структура власності зрозуміла")
    check_sanctions = fields.Boolean("Санкції / розшук перевірено")
    check_courts = fields.Boolean("Судові справи переглянуто")
    check_docs = fields.Boolean("Документи отримано")
    docs_requested_at = fields.Datetime("Документи запитано")

    screening_ids = fields.One2many("kyc.screening", "case_id", "Перевірки")
    screening_count = fields.Integer(compute="_compute_counts", store=True)
    high_count = fields.Integer("Червоних маркерів", compute="_compute_counts", store=True)
    warn_count = fields.Integer("Жовтих маркерів", compute="_compute_counts", store=True)

    decided_by = fields.Many2one("res.users", "Вирішив", readonly=True, copy=False)
    decided_on = fields.Datetime("Дата рішення", readonly=True, copy=False)
    register_id = fields.Char("ID у реєстрі KYC", readonly=True, copy=False)
    register_synced_at = fields.Datetime("Синхронізовано з реєстром", readonly=True, copy=False)

    @api.model
    def _expand_stages(self, states, domain, **kw):
        return [s[0] for s in STAGES]

    @api.depends("partner_id.company_registry", "partner_id.vat")
    def _compute_code(self):
        for c in self:
            if not c.code:
                c.code = c.partner_id.company_registry or ""

    def _inverse_code(self):
        for c in self:
            if c.code and c.partner_id and c.partner_id.company_registry != c.code:
                c.partner_id.company_registry = c.code

    @api.depends("screening_ids.severity")
    def _compute_counts(self):
        for c in self:
            c.screening_count = len(c.screening_ids)
            c.high_count = len(c.screening_ids.filtered(lambda s: s.severity == "high"))
            c.warn_count = len(c.screening_ids.filtered(lambda s: s.severity == "warn"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Новий") == "Новий":
                vals["name"] = self.env["ir.sequence"].next_by_code("kyc.case") or "KYC"
        return super().create(vals_list)

    # ---- stages -------------------------------------------------------
    def action_stage(self):
        self.ensure_one()
        order = [s[0] for s in STAGES]
        nxt = order[min(order.index(self.stage) + 1, len(order) - 1)]
        self.write({"stage": nxt})

    # ---- OpenDataBot via the bridge -----------------------------------
    def _clean_code(self):
        code = re.sub(r"\D", "", self.code or "")
        if len(code) not in (8, 10):
            raise UserError("Вкажіть ЄДРПОУ (8 цифр) або РНОКПП (10 цифр) у картці справи.")
        return code

    def action_screen_odb(self):
        self.ensure_one()
        code = self._clean_code()
        status, data = self.env["bp.bridge"].call("GET", f"/api/odb/screen/{code}")
        if status != 200:
            raise UserError(f"Скринінг не вдався: {data.get('error', data)}")
        reg = data.get("registry", {})
        bens = reg.get("beneficiaries") or []
        self.screening_ids.filtered(lambda s: s.source in ("odb_registry", "odb_warning")).unlink()
        rows = [{
            "case_id": self.id, "source": "odb_registry", "key": "registry", "severity": "info",
            "title": f"ЄДР: {reg.get('short_name') or reg.get('full_name')}",
            "detail": f"Стан: {reg.get('status')}; реєстрація {reg.get('registration_date')}; КВЕД {reg.get('kved')}; "
                      f"керівник {reg.get('head')}; капітал {reg.get('capital')}; ПДВ {reg.get('vat_status')} {reg.get('vat_code')}",
            "payload": json.dumps(data.get("raw", {}), ensure_ascii=False),
        }]
        for ch in data.get("checks", []):
            rows.append({"case_id": self.id, "source": "odb_warning", "key": ch.get("key"), "title": ch.get("title"),
                         "detail": ch.get("detail"), "severity": ch.get("severity", "info"),
                         "payload": json.dumps(ch, ensure_ascii=False)})
        self.env["kyc.screening"].create(rows)
        self.write({
            "kind": "fop" if data.get("kind") == "fop" else "company",
            "registry_name": reg.get("full_name"), "registry_status": reg.get("status"),
            "registry_date": reg.get("registration_date") or False, "registry_kved": reg.get("kved"),
            "registry_head": reg.get("head"), "registry_address": reg.get("address"),
            "registry_capital": reg.get("capital") or 0.0,
            "registry_vat": f"{reg.get('vat_status') or ''} {reg.get('vat_code') or ''}".strip(),
            "registry_beneficiaries": "\n".join(
                f"{b.get('name')} — {b.get('role') or ''} {b.get('amount_percent') or ''}%{(' · ' + b['country']) if b.get('country') else ''}".strip()
                for b in bens) or "не розкрито",
            "screened_at": fields.Datetime.now(), "check_registry": True,
            "stage": "screen" if self.stage in ("new", "collect") else self.stage,
        })
        if self.partner_id.is_company and reg.get("full_name") and not self.partner_id.comment:
            self.partner_id.comment = f"ЄДР: {reg.get('full_name')}"
        if not self.risk:
            self.risk = "high" if self.high_count else ("medium" if self.warn_count else "low")
        self.message_post(body=f"Скринінг ЄДР виконано: {len(rows) - 1} маркерів, "
                               f"червоних {self.high_count}, жовтих {self.warn_count}"
                               f"{' (з кешу)' if data.get('cached') else ''}.")
        return True

    @staticmethod
    def _extract_court(data):
        """OpenDataBot answers either {count, items} or {data: {count, items}} or a bare list."""
        node = data
        if isinstance(node, dict) and isinstance(node.get("data"), (dict, list)):
            node = node["data"]
        items = node if isinstance(node, list) else (node.get("items") or node.get("results") or node.get("decisions") or []) if isinstance(node, dict) else []
        if not isinstance(items, list):
            items = []
        count = None
        for src in (data, node):
            if isinstance(src, dict) and src.get("count") is not None:
                count = int(src["count"]); break
        return items, (count if count is not None else len(items))

    def action_search_courts(self):
        self.ensure_one()
        text = (self.registry_name or self.partner_id.name or "").strip()
        if not text:
            raise UserError("Немає назви для пошуку.")
        status, data = self.env["bp.bridge"].call("GET", "/api/odb/court", params={"text": text, "offset": 0})
        if status != 200:
            raise UserError(f"Пошук судових рішень не вдався: {data.get('error', data)}")
        items, count = self._extract_court(data)
        self.screening_ids.filtered(lambda s: s.source == "odb_court").unlink()
        sev = "high" if (count or 0) >= 10 else ("warn" if count else "info")
        self.env["kyc.screening"].create({
            "case_id": self.id, "source": "odb_court", "key": "court", "severity": sev,
            "title": f"Судові рішення: {count}",
            "detail": "\n".join(f"{str(i.get('date') or i.get('adjudication_date') or '')[:10]} · {i.get('court_name') or i.get('court') or ''} · {str(i.get('title') or i.get('subject') or i.get('cause_num') or i.get('number') or '')[:120]}"
                                for i in items[:10] if isinstance(i, dict)) or "Не знайдено",
            "payload": json.dumps(data, ensure_ascii=False)[:20000],
        })
        self.check_courts = True
        self.message_post(body=f"Пошук судових рішень за «{text}»: {count}.")
        return True

    # ---- mail ---------------------------------------------------------
    def action_request_documents(self):
        self.ensure_one()
        if not self.partner_id.email:
            raise UserError("У контрагента немає email. Заповніть його в картці контрагента.")
        tpl = self.env.ref("bp_kyc.mail_template_kyc_request_docs")
        tpl.send_mail(self.id, force_send=False)
        self.write({"docs_requested_at": fields.Datetime.now(), "stage": "collect" if self.stage == "new" else self.stage})
        self.message_post(body=f"Запит документів надіслано на {self.partner_id.email}.")
        return True

    # ---- decision + register -----------------------------------------
    def _decide(self, decision):
        self.ensure_one()
        if not self.risk:
            raise UserError("Оберіть рівень ризику перед рішенням.")
        self.write({"decision": decision, "stage": "done", "decided_by": self.env.user.id, "decided_on": fields.Datetime.now()})
        self.action_sync_register()
        tpl = self.env.ref("bp_kyc.mail_template_kyc_decision", raise_if_not_found=False)
        if tpl and self.partner_id.email and decision != "rejected":
            tpl.send_mail(self.id, force_send=False)
        return True

    def action_decide_cleared(self):
        return self._decide("cleared")

    def action_decide_flagged(self):
        return self._decide("flagged")

    def action_decide_rejected(self):
        return self._decide("rejected")

    def _register_payload(self):
        self.ensure_one()
        return {
            "name": self.registry_name or self.partner_id.name,
            "kind": "person" if self.kind == "person" else "company",
            "status": {"cleared": "clear", "flagged": "needs-edd", "rejected": "rejected"}.get(self.decision, "in-review"),
            "recommendation": REC.get(self.decision, "unverified"),
            "risk": self.risk or "",
            "subject_group": self.subject_group,
            "role": self.role or "",
            "partner": self.introduced_by or "",
            "summary": (self.summary or "").strip() or f"Odoo {self.name}: {self.registry_status or ''}".strip(),
        }

    def action_sync_register(self):
        self.ensure_one()
        bridge = self.env["bp.bridge"]
        payload = self._register_payload()
        code = re.sub(r"\D", "", self.code or "")
        if self.register_id:
            status, data = bridge.call("PATCH", f"/api/kyc/subjects/{self.register_id}",
                                       {**payload, "_note": f"Odoo {self.name}: {dict(DECISIONS).get(self.decision, 'оновлення')}",
                                        "_source": "manual", "_author": f"{self.env.user.name} via Odoo"})
        else:
            sid = f"edrpou-{code}" if code else None
            body = {**payload, **({"id": sid} if sid else {})}
            status, data = bridge.call("POST", "/api/kyc/subjects", body)
            if status == 409 and sid:
                status, data = bridge.call("PATCH", f"/api/kyc/subjects/{sid}", {**payload, "_note": f"Odoo {self.name}", "_source": "manual"})
                data = {**data, "id": sid}
        if status >= 400:
            raise UserError(f"Реєстр KYC відповів {status}: {data.get('error', data)}")
        rid = data.get("id") or (data.get("subject") or {}).get("id") or self.register_id
        self.write({"register_id": rid, "register_synced_at": fields.Datetime.now()})
        for s in self.screening_ids.filtered(lambda s: s.severity == "high" and not s.pushed):
            st, _ = bridge.call("POST", f"/api/kyc/subjects/{rid}/risks", {
                "title": s.title or s.key, "statement": (s.detail or "")[:1000], "found_in": "OpenDataBot via Odoo",
                "why": "Червоний маркер скринінгу", "severity": "high"})
            if st < 400:
                s.pushed = True
        self.message_post(body=f"Синхронізовано з реєстром KYC: {rid}.")
        return True

    def action_open_register(self):
        """The register (kyc-service) is an API without a public page; show where the subject lives."""
        self.ensure_one()
        if not self.register_id:
            raise UserError("Справа ще не в реєстрі.")
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": "Реєстр KYC", "type": "info", "sticky": False,
            "message": f"Суб'єкт {self.register_id} записано в kyc-service. Перегляд: OfficeKit → Контрагенти."}}
