"""Картка контрагента з ЄДР. Джерело: OpenDataBot через міст odoo-live (/api/odb/screen/:code, кеш 24 години)."""
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

CITY_WORDS = ("місто ", "м. ", "м.", "село ", "с. ", "селище ", "смт ", "смт.")


def split_address(text):
    """«79022, Львівська обл., місто Львів, вулиця Городоцька, будинок 174» → (індекс, місто, вулиця)."""
    text = (text or "").strip()
    if not text:
        return "", "", ""
    parts = [p.strip() for p in text.split(",") if p.strip() and p.strip().lower() != "україна"]
    zip_code = ""
    for p in list(parts):
        if re.fullmatch(r"\d{5}", p):
            zip_code = p; parts.remove(p); break
    city, rest = "", []
    for p in parts:
        low = p.lower()
        if not city and any(low.startswith(w) for w in CITY_WORDS):
            city = re.sub(r"^(місто|м\.|село|с\.|селище|смт\.?)\s*", "", p, flags=re.I).strip()
        elif not city and ("обл" in low or "район" in low or "р-н" in low):
            continue
        else:
            rest.append(p)
    return zip_code, city, ", ".join(rest)


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_ua_new_from_edr(self):
        """Кнопка «Контрагент з ЄДР» у шапці списку: разовий діалог на одне поле - код."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Контрагент з ЄДР"),
            "res_model": "ua.partner.edr.wizard",
            "view_mode": "form",
            "target": "new",
        }

    ua_edr_kind = fields.Selection([("company", "Юрособа"), ("fop", "ФОП")], "Тип у ЄДР", readonly=True)
    ua_edr_full_name = fields.Char("Повна назва (ЄДР)", readonly=True)
    ua_edr_status = fields.Char("Стан у ЄДР", readonly=True)
    ua_edr_registration_date = fields.Date("Дата реєстрації", readonly=True)
    ua_kved = fields.Char("Основний КВЕД", readonly=True)
    ua_edr_head = fields.Char("Керівник", readonly=True)
    ua_edr_capital = fields.Float("Статутний капітал, грн", readonly=True)
    ua_vat_status = fields.Char("ПДВ", readonly=True)
    ua_edr_checks = fields.Text("Маркери ризику", readonly=True)
    ua_edr_synced_at = fields.Datetime("Оновлено з ЄДР", readonly=True)

    def _ua_edr_code(self):
        code = re.sub(r"\D", "", self.company_registry or self.vat or "")
        if len(code) not in (8, 10):
            raise UserError(_("Вкажіть ЄДРПОУ (8 цифр) або РНОКПП ФОП (10 цифр) у полі «ЄДРПОУ / РНОКПП» контрагента %s.", self.display_name))
        return code

    def action_fill_from_edr(self):
        # Запит у міст іде з системним токеном, тож право на картку перевіряємо до нього.
        self.check_access("write")
        Bridge = self.env["bp.bridge"]
        for partner in self:
            code = partner._ua_edr_code()
            status, data = Bridge._call("GET", f"/api/odb/screen/{code}")
            if status != 200:
                raise UserError(_("ЄДР не відповів для %s: %s", code, data.get("error", data)))
            partner._ua_apply_edr(code, data)
        return True

    def _ua_apply_edr(self, code, data):
        reg = data.get("registry") or {}
        kind = "fop" if data.get("kind") == "fop" else "company"
        zip_code, city, street = split_address(reg.get("address"))
        name_now = (self.name or "").strip()
        vals = {
            "company_registry": code, "is_company": True, "ua_edr_kind": kind,
            "ua_edr_full_name": reg.get("full_name") or "", "ua_edr_status": reg.get("status") or "",
            "ua_edr_registration_date": reg.get("registration_date") or False, "ua_kved": reg.get("kved") or "",
            "ua_edr_head": reg.get("head") or "", "ua_edr_capital": reg.get("capital") or 0.0,
            "ua_vat_status": " ".join(x for x in [reg.get("vat_status"), reg.get("vat_code")] if x) or "",
            "ua_edr_synced_at": fields.Datetime.now(),
            "ua_edr_checks": "\n".join(f"{'!' if c.get('severity') == 'high' else '?' if c.get('severity') == 'warn' else '·'} {c.get('title')}: {c.get('detail')}"
                                       for c in data.get("checks", []) if c.get("present")) or "маркерів немає",
        }
        if not name_now or re.fullmatch(r"\d+", name_now) or name_now == code:
            vals["name"] = reg.get("short_name") or reg.get("full_name") or name_now
        if zip_code and not self.zip:
            vals["zip"] = zip_code
        if city and not self.city:
            vals["city"] = city
        if street and not self.street:
            vals["street"] = street
        if reg.get("vat_code") and not self.vat:
            vals["vat"] = re.sub(r"\D", "", reg["vat_code"])
        if reg.get("email") and not self.email:
            vals["email"] = reg["email"]
        if reg.get("phone") and not self.phone:
            vals["phone"] = reg["phone"]
        if not self.country_id:
            vals["country_id"] = self.env.ref("base.ua").id
        self.write(vals)
        head = (reg.get("head") or "").strip()
        if head and kind == "company" and not self.child_ids.filtered(lambda c: c.name == head):
            self.env["res.partner"].create({"name": head, "parent_id": self.id, "type": "contact", "function": reg.get("head_role") or "Керівник"})
        high = [c for c in data.get("checks", []) if c.get("present") and c.get("severity") == "high"]
        self.message_post(body=_("Заповнено з ЄДР (OpenDataBot): %s, стан «%s», КВЕД %s, керівник %s. Маркерів високого ризику: %s.",
                                 reg.get("full_name") or code, reg.get("status") or "-", reg.get("kved") or "-", head or "-", len(high)))
        return True

    def cron_ua_edr_refresh(self, limit=50):
        """Щотижневе оновлення стану у ЄДР для контрагентів із кодом; вимкнено за замовчуванням (платні запити)."""
        for p in self.search([("company_registry", "!=", False), ("is_company", "=", True)], order="ua_edr_synced_at asc", limit=limit):
            try:
                p.action_fill_from_edr()
            except Exception:
                continue
