# -*- coding: utf-8 -*-
"""Звідки беруться рядки журналу змін.

Зміни ловить OCA-модуль `auditlog`: на кожну нашу модель стоїть правило
(`auditlog.rule`) з білим списком полів. Своїх гачків у `write()`, `create()` і
`unlink()` більше немає - жодна ділова модель нічого про журнал не знає.

Перекладає рядки цей файл. `create_logs()` - той самий виклик, яким auditlog
складає свій технічний запис, - складає заразом і рядок черги бухгалтера
(`ua.change.log`) тими самими словами, що й раніше: «Оклад», «було → стало»,
різниця в гривнях, період документа. Кожен рядок черги тримає посилання
`auditlog_log_id` на технічний запис, з якого він зроблений.

Фільтр - у самому правилі. `get_auditlog_fields()` повертає лише білий список,
тому auditlog навіть не дивиться на обчислювані збережені поля, підписників і
решту технічної тріски: рядка без ділового поля просто не виникає, хоч би хто
писав - людина, крон чи OdooBot.

Що писати, каже правило, а не код:
    ua_area        - ділянка журналу;
    ua_field_ids   - поля і їхні назви людською мовою (білий список);
    ua_period_ym   - «<шлях>:<поле року>:<поле місяця>», порожній шлях = сам запис;
    ua_period_date - шлях до дати документа, якщо року й місяця в записі немає;
    ua_company     - шлях до компанії, «-» = компанія користувача;
    ua_label       - назва запису: частини через «+» зшиваються через « · »,
                     запасні варіанти через «|»; порожньо = display_name.

Чотири моделі мають правило, якого декларацією не опишеш (номер чернетки наказу,
проміжні стани розрахунку листка, порожні рядки введення, квартал у прогоні
звіту) - вони живуть у SPECIAL нижче.

Вимкнути запис у чергу на час скрипта: контекст `ua_no_log=True` (так само, як до
переходу на auditlog - scripts/period_check.py, people_check.py, papers_check.py).
Технічний запис auditlog при цьому лишається: аудит не вимикають, ховають лише
чергу бухгалтера.
"""
import logging

from odoo import api, fields, models, tools

from .ua_change_log import AREAS

_logger = logging.getLogger(__name__)

# Контексти, за яких черга бухгалтера мовчить: свідомо мовчазний скрипт і
# завантаження даних модуля.
SKIP_KEYS = ("ua_no_log", "install_mode")


def _walk(record, path):
    """Значення за шляхом через крапку: 'sheet_id.company_id'."""
    for part in path.split("."):
        if not record:
            return record
        record = record[part]
    return record


def _pick(record, expr):
    """Перший непорожній із запасних варіантів: 'ua_employee_id.name|ua_label'."""
    for alternative in expr.split("|"):
        value = _walk(record, alternative.strip())
        if value:
            return value
    return ""


def _order_label(record):
    """Чернетка наказу ще не має номера. Пишемо вид наказу і працівника."""
    if record.name:
        return "%s · %s" % (record.name, record.employee_id.name or "")
    kind = dict(record._fields["order_type"].selection).get(record.order_type, "наказ")
    return "%s (чернетка) · %s" % (kind, record.employee_id.name or "")


def _payslip_keep(fname, old, new):
    """Проміжні стани розрахунку не цікаві. Пишемо проведення і скасування."""
    if fname == "state":
        return "done" in (old, new) or "cancel" in (old, new)
    return True


def _run_period(record):
    month = record.month or (record.quarter * 3 if record.quarter
                             else fields.Date.context_today(record).month)
    return record.year, month


SPECIAL = {
    "ua.hr.order": {"label": _order_label},
    "hr.payslip": {"keep": _payslip_keep},
    # Розрахунок листка створює порожні рядки введення для кожного правила. Їх не пишемо.
    "hr.payslip.input": {"loggable": lambda record: bool(record.amount)},
    "ua.report.run": {"period": _run_period},
}


class UaChangeField(models.Model):
    """Одне поле в білому списку правила: технічна назва і слово для бухгалтера."""

    _name = "ua.change.field"
    _description = "Поле під наглядом журналу змін"
    _order = "sequence, id"

    rule_id = fields.Many2one("auditlog.rule", "Правило", required=True,
                              ondelete="cascade", index=True)
    sequence = fields.Integer("Порядок", default=10)
    field_name = fields.Char("Поле", required=True)
    label = fields.Char("Назва в журналі", required=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        self.env.registry.clear_cache()
        return super().unlink()


class AuditlogRule(models.Model):
    """Правило auditlog плюс те, що з нього треба журналу змін."""

    _inherit = "auditlog.rule"

    ua_area = fields.Selection(AREAS, "Ділянка журналу")
    ua_field_ids = fields.One2many("ua.change.field", "rule_id", "Поля журналу змін")
    ua_period_ym = fields.Char("Період: рік і місяць",
                               help="«<шлях>:<поле року>:<поле місяця>», порожній шлях - сам запис")
    ua_period_date = fields.Char("Період: дата документа", help="Шлях до поля дати")
    ua_company = fields.Char("Компанія", help="Шлях до компанії; «-» - компанія користувача")
    ua_label = fields.Char("Назва запису", help="Частини через «+», запасні варіанти через «|»")

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    # ------------------------------------------------------------------ правила
    @tools.ormcache()
    def _ua_rules(self):
        """Білий список і правила періоду за моделями. Кеш реєстру, а не запит на кожен запис."""
        out = {}
        for rule in self.sudo().search([("ua_area", "!=", False)]):
            name = rule.model_model or rule.model_id.model
            if not name or name not in self.env:
                continue
            model = self.env[name]
            names, labels = [], {}
            for line in rule.ua_field_ids:
                if line.field_name not in model._fields:
                    _logger.warning("Журнал змін: у %s немає поля %s", name, line.field_name)
                    continue
                names.append(line.field_name)
                labels[line.field_name] = line.label
            out[name] = {
                "area": rule.ua_area,
                "order": names,
                "labels": labels,
                "ym": rule.ua_period_ym or "",
                "date": rule.ua_period_date or "",
                "company": rule.ua_company or "",
                "label": rule.ua_label or "",
            }
        return out

    @api.model
    def get_auditlog_fields(self, model):
        """Білий список замість усіх збережених полів - тут і відсікається тріска."""
        spec = self._ua_rules().get(model._name)
        if spec:
            return list(spec["order"])
        return super().get_auditlog_fields(model)

    # ------------------------------------------------------------------ переклад
    def create_logs(self, uid, res_model, res_ids, method, old_values=None,
                    new_values=None, additional_log_values=None):
        spec = self._ua_rules().get(res_model)
        last_log = 0
        if spec:
            self.env.cr.execute("SELECT COALESCE(MAX(id), 0) FROM auditlog_log")
            last_log = self.env.cr.fetchone()[0]
        res = super().create_logs(uid, res_model, res_ids, method, old_values,
                                  new_values, additional_log_values)
        if spec:
            self._ua_queue(spec, uid, res_model, res_ids, method,
                           old_values or {}, new_values or {}, last_log)
        return res

    def _ua_queue(self, spec, uid, res_model, res_ids, method, old_values, new_values, last_log):
        """Рядки черги бухгалтера з того самого, з чого auditlog зробив свої записи."""
        env = self.env
        if method not in ("create", "write", "unlink"):
            return
        if any(env.context.get(key) for key in SKIP_KEYS) or not env.registry.ready:
            return
        special = SPECIAL.get(res_model, {})
        loggable = special.get("loggable")
        keep = special.get("keep")
        model = env[res_model].sudo()

        links = {}
        for log in env["auditlog.log"].sudo().search([
            ("id", ">", last_log), ("model_model", "=", res_model),
            ("method", "=", method), ("res_id", "in", list(res_ids)),
        ]):
            links.setdefault(log.res_id, log.id)

        rows = []
        for res_id in res_ids:
            record = model.browse(res_id)
            if not record.exists():
                continue
            if loggable and not loggable(record):
                continue
            log_id = links.get(res_id, False)
            if method in ("create", "unlink"):
                rows.append(self._ua_row(spec, record, uid, method, log_id=log_id))
                continue
            before, after = old_values.get(res_id) or {}, new_values.get(res_id) or {}
            for fname in spec["order"]:
                if fname not in before or fname not in after:
                    continue
                field = record._fields.get(fname)
                if not field:
                    continue
                old_raw, new_raw = before[fname], after[fname]
                old_text = self._ua_fmt(field, old_raw)
                new_text = self._ua_fmt(field, new_raw)
                if old_text == new_text:
                    continue
                if keep and not keep(fname, old_raw, new_raw):
                    continue
                old_num, new_num = self._ua_num(field, old_raw), self._ua_num(field, new_raw)
                delta = (new_num - old_num) if (old_num is not None and new_num is not None) else 0.0
                rows.append(self._ua_row(spec, record, uid, "write", spec["labels"][fname],
                                         old_text, new_text, delta, log_id))
        if rows:
            env["ua.change.log"].sudo().with_context(ua_no_log=True).create(rows)

    def _ua_row(self, spec, record, uid, operation, what="", old="", new="", amount=0.0, log_id=False):
        year, month = self._ua_period(spec, record)
        return {
            "user_id": uid,
            "company_id": self._ua_company(spec, record).id,
            "area": spec["area"],
            "operation": operation,
            "model_name": record._name,
            "res_id": record.id,
            "res_name": (self._ua_label(spec, record) or "")[:120],
            "what": what,
            "old_value": (old or "")[:120],
            "new_value": (new or "")[:120],
            "amount": amount,
            "year": year,
            "month": month,
            "auditlog_log_id": log_id,
        }

    # ------------------------------------------------------------------ значення
    def _ua_fmt(self, field, value):
        """Те саме слово, що бачить бухгалтер: назва зв'язку, підпис вибору, дві копійки."""
        if value is False or value is None:
            return ""
        if field.type == "many2one":
            if isinstance(value, (tuple, list)):
                return (len(value) > 1 and value[1]) or ""
            return self.env[field.comodel_name].browse(value).display_name or ""
        if field.type in ("one2many", "many2many"):
            ids = [v[0] if isinstance(v, (tuple, list)) else v for v in (value or [])]
            return ", ".join(self.env[field.comodel_name].browse(ids).mapped("display_name"))
        if field.type == "selection":
            return dict(field._description_selection(self.env)).get(value, str(value))
        if field.type in ("float", "monetary"):
            return "%.2f" % value
        if field.type == "boolean":
            return "так" if value else "ні"
        return str(value)

    def _ua_num(self, field, value):
        if field.type in ("float", "monetary", "integer"):
            return float(value or 0.0)
        return None

    # ------------------------------------------------------------------ період, компанія, назва
    def _ua_period(self, spec, record):
        """Рядок належить періоду документа, а не дню правки."""
        rule = SPECIAL.get(record._name, {}).get("period")
        if rule:
            year, month = rule(record)
            if year:
                return int(year), int(month)
        if spec["ym"]:
            path, _, rest = spec["ym"].partition(":")
            year_field, _, month_field = rest.partition(":")
            holder = _walk(record, path) if path else record
            if holder and holder[year_field]:
                return int(holder[year_field]), int(holder[month_field])
        if spec["date"]:
            day = _walk(record, spec["date"])
            if day:
                return day.year, day.month
        today = fields.Date.context_today(record)
        return today.year, today.month

    def _ua_company(self, spec, record):
        path = spec["company"]
        if path and path != "-":
            company = _walk(record, path)
            if company:
                return company
        elif not path and "company_id" in record._fields and record.company_id:
            return record.company_id
        return self.env.company

    def _ua_label(self, spec, record):
        rule = SPECIAL.get(record._name, {}).get("label")
        if rule:
            return rule(record)
        if not spec["label"]:
            return record.display_name or "%s %s" % (record._name, record.id)
        return " · ".join(str(_pick(record, part.strip()) or "")
                          for part in spec["label"].split("+"))
