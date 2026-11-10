"""Шаблони кадрових наказів компанії.

Шаблон - назва наказу і HTML-текст з підстановками {{ключ}}. Ключі фіксовані (PLACEHOLDERS):
кожен бере значення з наказу, працівника або компанії. Значення екрануються, тож шаблон не
може вставити розмітку чи код; невідомий ключ лишається в тексті як є.
"""
import re

from markupsafe import Markup, escape

from odoo import api, fields, models

from odoo.addons.l10n_ua_hr_orders.models.ua_hr_order import FTE, ORDER_TYPES

KEY_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


def _date(value):
    return value.strftime("%d.%m.%Y") if value else "____________"


def _money(value):
    return "{:,.2f}".format(value or 0.0).replace(",", " ").replace(".", ",")


def _num(value):
    return ("%g" % (value or 0)).replace(".", ",")


def _position(o):
    return o.prof_name or o.job_title or o.employee_id.job_title or "-"


PLACEHOLDERS = [
    ("номер", "Номер наказу", lambda o: o.name or "____"),
    ("дата", "Дата наказу", lambda o: _date(o.date)),
    ("компанія", "Назва компанії", lambda o: o.company_id.name),
    ("єдрпоу", "Код ЄДРПОУ компанії", lambda o: o.company_id.company_registry or "-"),
    ("керівник", "Керівник компанії", lambda o: o.company_id.ua_director_name or ""),
    ("працівник", "Прізвище, ім'я, по батькові працівника", lambda o: o.employee_id.name),
    ("посада", "Посада (професійна назва роботи)", _position),
    ("код_кп", "Код КП", lambda o: o.kp_code or ""),
    ("підрозділ", "Підрозділ", lambda o: o.department_id.name or o.employee_id.department_id.name or "-"),
    ("оклад", "Оклад, грн", lambda o: _money(o.wage)),
    ("був_оклад", "Попередній оклад, грн", lambda o: _money(o.wage_old)),
    ("ставка", "Ставка", lambda o: dict(FTE).get(o.fte, "")),
    ("місце_роботи", "Основне місце чи сумісництво",
     lambda o: "основне місце роботи" if o.main_job else "за сумісництвом"),
    ("вид_договору", "Вид трудового договору",
     lambda o: o.contract_type_id.name or "безстроковий трудовий договір"),
    ("випробування_до", "Випробувальний строк до", lambda o: _date(o.trial_date_end)),
    ("аванс_відсоток", "Аванс, % окладу", lambda o: _num(o.pay_advance_percent)),
    ("аванс_до", "Аванс до числа", lambda o: str(o.pay_advance_day or "")),
    ("розрахунок_до", "Остаточний розрахунок до числа", lambda o: str(o.pay_final_day or "")),
    ("з_дати", "З дати", lambda o: _date(o.date_from)),
    ("по_дату", "По дату (для звільнення - дата звільнення)", lambda o: _date(o.date_to)),
    ("днів", "Календарних днів", lambda o: str(o.days or 0)),
    ("вид_відпустки", "Вид відпустки", lambda o: o.leave_type_id.name or "-"),
    ("підстава", "Підстава", lambda o: o.basis or ""),
    ("підстава_звільнення", "Підстава припинення (стаття КЗпП)", lambda o: o.dismissal_basis or "________________"),
    ("днів_компенсації", "Днів компенсації за невикористану відпустку", lambda o: _num(o.comp_days)),
    ("місце_відрядження", "Місце відрядження", lambda o: o.destination or "-"),
    ("мета_відрядження", "Мета відрядження", lambda o: o.purpose or ""),
    ("примітка", "Примітка до наказу", lambda o: o.note or ""),
]
GETTERS = {key: getter for key, _label, getter in PLACEHOLDERS}


def unknown_keys(body):
    return sorted({key for key in KEY_RE.findall(str(body or "")) if key not in GETTERS})


class UaHrOrderTemplate(models.Model):
    _name = "ua.hr.order.template"
    _description = "Шаблон кадрового наказу"
    _order = "order_type, sequence, id"

    name = fields.Char("Шаблон", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    order_type = fields.Selection(ORDER_TYPES, "Вид наказу", required=True)
    company_id = fields.Many2one("res.company", "Компанія", help="Порожньо - для всіх компаній.")
    title = fields.Char("Назва в наказі", required=True, help="Наприклад: «Про прийняття на роботу».")
    body = fields.Html("Текст наказу", sanitize=True, sanitize_style=True)
    unknown = fields.Char("Невідомі підстановки", compute="_compute_preview")
    preview_order_id = fields.Many2one("ua.hr.order", "Перегляд на наказі",
                                       domain="[('order_type', '=', order_type)]")
    preview_html = fields.Html("Перегляд", compute="_compute_preview", sanitize=False)
    placeholders_html = fields.Html("Підстановки", compute="_compute_placeholders_html", sanitize=False)

    @api.depends("body", "title", "preview_order_id")
    def _compute_preview(self):
        for template in self:
            template.unknown = ", ".join("{{%s}}" % key for key in unknown_keys(template.body))
            order = template.preview_order_id
            template.preview_html = template._ua_render(order) if order else False

    def _compute_placeholders_html(self):
        rows = Markup("").join(Markup("<tr><td><code>{{%s}}</code></td><td>%s</td></tr>") % (key, label)
                               for key, label, _getter in PLACEHOLDERS)
        for template in self:
            template.placeholders_html = Markup("<table class='table table-sm'>%s</table>") % rows

    def _ua_render(self, order):
        """Текст шаблону з підставленими значеннями наказу."""
        self.ensure_one()
        order.ensure_one()

        def value(match):
            getter = GETTERS.get(match.group(1))
            return str(escape(getter(order))) if getter else match.group(0)

        return Markup(KEY_RE.sub(value, str(self.body or "")))

    @api.model
    def _ua_for(self, order_type, company):
        """Шаблон компанії, а без нього - спільний; серед рівних - перший за порядком."""
        templates = self.search([("order_type", "=", order_type), ("company_id", "in", [company.id, False])],
                                order="sequence, id")
        return templates.filtered("company_id")[:1] or templates[:1]


class UaHrOrder(models.Model):
    _inherit = "ua.hr.order"

    template_id = fields.Many2one(
        "ua.hr.order.template", "Шаблон", compute="_compute_template_id", store=True, readonly=False,
        domain="[('order_type', '=', order_type), ('company_id', 'in', [company_id, False])]",
        help="Шаблон компанії для цього виду наказу. Порожньо - друкується типовий текст.")

    @api.depends("order_type", "company_id")
    def _compute_template_id(self):
        Template = self.env["ua.hr.order.template"]
        for order in self:
            keep = order.template_id
            if order.state not in (False, "draft") or (keep and keep.order_type == order.order_type):
                order.template_id = keep
            else:
                order.template_id = Template._ua_for(order.order_type, order.company_id) if order.company_id \
                    else Template

    def ua_template_body(self):
        """Текст наказу за шаблоном для друку."""
        self.ensure_one()
        return self.template_id._ua_render(self) if self.template_id else Markup("")
