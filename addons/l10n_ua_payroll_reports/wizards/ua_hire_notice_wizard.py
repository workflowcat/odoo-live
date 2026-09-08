"""Повідомлення про прийняття працівника на роботу / укладення ЦПХ (J3001005, постанова КМУ 413 у редакції 184 від 21.02.2025).
Подається до ДПС до початку роботи працівника (можна в день прийняття, до допуску до роботи)."""
import base64
from datetime import date

from odoo import fields, models
from odoo.exceptions import UserError

CATEGORY = {"main": "1", "parttime": "2", "gig": "3", "gph": "4", "domestic": "5"}


class UaHireNoticeWizard(models.TransientModel):
    _name = "ua.hire.notice.wizard"
    _description = "Повідомлення про прийняття працівника (J3001005)"

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)
    employee_ids = fields.Many2many("hr.employee", string="Працівники", required=True,
                                    default=lambda s: s.env["hr.employee"].browse(s.env.context.get("active_ids", [])) if s.env.context.get("active_model") == "hr.employee" else False)
    notice_type = fields.Selection([("H01", "початкове"), ("H02", "скасовуюче")], default="H01", required=True, string="Тип")
    number = fields.Integer("Номер повідомлення (C_DOC_CNT)", default=1, required=True, help="Порядковий номер документа цього типу в періоді")
    fill_date = fields.Date("Дата формування", default=fields.Date.today, required=True)
    citizenship_ua = fields.Boolean("Усі громадяни України", default=True)
    log = fields.Text(readonly=True)

    def _rows(self):
        rows = []
        for emp in self.employee_ids.sudo():
            kind = emp.ua_contract_kind or "employment"
            if kind == "fop":
                raise UserError(f"{emp.name}: для ФОП-підрядника повідомлення не подається.")
            v = emp.version_ids.filtered("contract_date_start").sorted("contract_date_start")[-1:]
            if not v:
                raise UserError(f"{emp.name}: немає версії контракту з датою початку.")
            cat = CATEGORY["gph"] if kind == "gph" else (CATEGORY["main"] if emp.ua_main_job else CATEGORY["parttime"])
            order_no, order_date = "", v.contract_date_start
            ref = (v.ua_order_ref or "").strip()
            if ref:
                # «Наказ № 12-к від 17.08.2026» -> номер 12-к, дата 17.08.2026
                import re
                m = re.search(r"№\s*([\w\-/]+)", ref); order_no = m.group(1) if m else ref
                m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", ref)
                if m:
                    order_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            ln, fn, mn = emp._ua_name_parts()
            rows.append({"G5": cat, "G6S": emp.ua_rnokpp or "", "G7S": None, "G81S": ln, "G82S": fn, "G83S": mn or None,
                         "G9": "1" if self.citizenship_ua else "0", "G10S": (order_no or None) if kind == "employment" else None,
                         "G11D": order_date, "G12D": v.contract_date_start})
        return rows

    def action_generate(self):
        self.ensure_one()
        c = self.company_id
        if not (c.company_registry and c.ua_sti_code):
            raise UserError("Заповніть ЄДРПОУ і код ДПІ у картці компанії.")
        rows = self._rows()
        body = [("HPAGES", 1), (self.notice_type, True), ("HTIN", c.company_registry), ("HNAME", c.name)]
        for col in ["G5", "G6S", "G7S", "G81S", "G82S", "G83S", "G9", "G10S", "G11D", "G12D"]:
            for i, r in enumerate(rows, 1):
                body.append((f"T1RXXXX{col}", r.get(col), {"ROWNUM": i}))
        body += [("HFILL", self.fill_date), ("HKBOS", c.ua_director_rnokpp or ""), ("HBOS", c.ua_director_name or ""),
                 ("HKBUH", c.ua_accountant_rnokpp or None), ("HBUH", c.ua_accountant_name or None)]
        d = self.fill_date
        X = self.env["ua.dps.xml"]
        _, data = X.build(c, "J30", "010", "5", 1, d.month, d.year, body, linked=None, c_doc_cnt=self.number, c_doc_stan=1, fill_date=d)
        fname = X.file_name(c.company_registry, c.ua_sti_code, "J30", "010", "05", 1, 0, self.number, 1, d.month, d.year, c.ua_sti_code)
        errs = X.validate(data, "J3001005")
        ok, msg = (not errs), ("валідний за J3001005.xsd" if not errs else "; ".join(errs)[:500])
        att = self.env["ir.attachment"].create({"name": fname, "datas": base64.b64encode(data), "res_model": self._name, "res_id": self.id, "mimetype": "application/xml"})
        for emp in self.employee_ids:
            emp.message_post(body=f"Повідомлення про прийняття (J3001005) сформовано: {fname}. {msg}", attachment_ids=[self.env["ir.attachment"].create({"name": fname, "datas": base64.b64encode(data), "res_model": "hr.employee", "res_id": emp.id, "mimetype": "application/xml"}).id])
        self.log = f"{fname}: {'валідний за XSD' if ok else msg}\nПрацівників у повідомленні: {len(rows)}. Подати до ДПС до початку роботи (кабінет платника або через програму з КЕП)."
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}
