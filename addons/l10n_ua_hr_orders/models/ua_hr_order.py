# -*- coding: utf-8 -*-
"""Кадровий наказ: документ, що проводить зміну (прийняття, зміна окладу, переведення, відпустка,
звільнення, відрядження), а не друк заднім числом. Проведення (action_post) присвоює номер за
реєстром (К-1 кадрові / В-2 відпустки-відрядження) і виконує саме кадрову дію (створює чи змінює
hr.version / hr.leave). Скасування (action_cancel) прибирає наслідки, якщо їх ніхто не чіпав після
проведення; інакше просить виправити вручну."""
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .hr_leave import ORDER_WORTHY_LEAVE_CODES, is_leave_type_order_worthy

ORDER_TYPES = [
    ("hire", "Прийняття на роботу"),
    ("wage", "Зміна окладу"),
    ("transfer", "Переведення"),
    ("leave", "Відпустка"),
    ("dismissal", "Звільнення"),
    ("trip", "Відрядження"),
]
REGISTERS = [
    ("k1", "К-1, кадрові, 75 років"),
    ("v2", "В-2, відпустки і відрядження, 5 років"),
]
STATES = [
    ("draft", "Чернетка"),
    ("posted", "Проведено"),
    ("acknowledged", "Ознайомлено"),
    ("cancelled", "Скасовано"),
]
FTE = [("1", "повна ставка"), ("0.75", "0,75 ставки"), ("0.5", "0,5 ставки"), ("0.25", "0,25 ставки")]
CONTRACT_KIND = [("employment", "трудовий договір"), ("gph", "договір ЦПХ")]
REGISTER_BY_TYPE = {"leave": "v2", "trip": "v2"}
REF_RE = re.compile(r"№\s*(\S+)\s+від\s+(\d{2})\.(\d{2})\.(\d{4})")


def parse_order_ref(text):
    """«Наказ № 23-к від 14.05.2012» -> {'token': '23-к', 'number': 23, 'date': date(2012,5,14)}."""
    if not text:
        return None
    m = REF_RE.search(text)
    if not m:
        return None
    token, dd, mm, yyyy = m.groups()
    num = re.match(r"\d+", token)
    if not num:
        return None
    return {"token": token, "number": int(num.group()), "date": fields.Date.to_date("%s-%s-%s" % (yyyy, mm, dd))}


class UaHrOrder(models.Model):
    _name = "ua.hr.order"
    _inherit = ["mail.thread"]
    _description = "Кадровий наказ"
    _order = "date desc, id desc"

    name = fields.Char("Номер", readonly=True, copy=False, tracking=True)
    order_type = fields.Selection(ORDER_TYPES, "Вид наказу", required=True, default="hire", tracking=True)
    register = fields.Selection(REGISTERS, "Реєстр", compute="_compute_register", store=True, readonly=False, tracking=True)
    date = fields.Date("Дата наказу", default=fields.Date.context_today, required=True, tracking=True)
    employee_id = fields.Many2one("hr.employee", "Працівник", required=True, tracking=True)
    company_id = fields.Many2one("res.company", "Компанія", default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    state = fields.Selection(STATES, "Стан", default="draft", required=True, copy=False, tracking=True)
    note = fields.Text("Примітка")
    basis = fields.Char("Підстава")
    signed_file = fields.Binary("Скан підписаного наказу", attachment=True)
    signed_filename = fields.Char("Ім'я файлу")
    ack_date = fields.Date("Дата ознайомлення", readonly=True, copy=False)
    ack_user_id = fields.Many2one("res.users", "Ознайомлений", readonly=True, copy=False)
    version_id = fields.Many2one("hr.version", "Версія контракту", readonly=True, copy=False)
    leave_id = fields.Many2one("hr.leave", "Відпустка", readonly=True, copy=False)

    # -- допоміжні поля для безпечного скасування (не бізнес-дані, а слід дії) ------------------------
    cancel_write_date = fields.Datetime(readonly=True, copy=False, help="write_date створеного/зміненого запису одразу після проведення")
    comp_days_input_id = fields.Many2one("hr.payslip.input", readonly=True, copy=False)
    version_created = fields.Boolean(readonly=True, copy=False, default=True,
                                     help="False, якщо hire дозаповнив початкову (бутстрап) версію нового працівника, "
                                          "а не створив нову - тоді скасування не видаляє версію, а очищає поля.")

    # -- поля за видами (невидимі в формі, коли не той вид) --------------------------------------------
    date_from = fields.Date("З дати")
    date_to = fields.Date("По дату")
    job_title = fields.Char("Посада")
    department_id = fields.Many2one("hr.department", "Підрозділ")
    wage = fields.Monetary("Оклад", currency_field="currency_id")
    wage_old = fields.Monetary("Був оклад", compute="_compute_wage_old", currency_field="currency_id")
    fte = fields.Selection(FTE, "Ставка", default="1")
    kp_code = fields.Char("Код КП", size=10)
    prof_name = fields.Char("Професійна назва роботи")
    contract_type_id = fields.Many2one("hr.contract.type", "Вид договору")
    trial_date_end = fields.Date("Випробувальний строк до")
    main_job = fields.Boolean("Основне місце роботи", default=True)
    contract_kind = fields.Selection(CONTRACT_KIND, "Вид відносин", default="employment")
    # Значення за замовчуванням - типові дні виплат компанії (res.company.ua_pay_*, цей модуль);
    # наказ і трудовий договір друкують саме ці поля наказу/справи, а не звертаються до компанії
    # напряму, щоб конкретний наказ можна було змінити окремо.
    pay_advance_percent = fields.Float("Аванс, % окладу", default=lambda s: s.env.company.ua_pay_advance_percent)
    pay_advance_day = fields.Integer("Аванс до числа", default=lambda s: s.env.company.ua_pay_advance_day)
    pay_final_day = fields.Integer("Остаточний розрахунок до числа", default=lambda s: s.env.company.ua_pay_final_day)

    # -- переведення: старі значення поруч із новими (для друку і форми) -------------------------------
    department_id_old = fields.Many2one("hr.department", "Був підрозділ", compute="_compute_transfer_old")
    job_title_old = fields.Char("Була посада", compute="_compute_transfer_old")

    # Домен - лише UX-підказка у формі (many2one domain не блокує write()/create() через RPC),
    # тому реальна заборона - в _check_required() нижче, яка викликається з action_post().
    leave_type_id = fields.Many2one(
        "hr.leave.type", "Вид відпустки",
        domain=lambda model: [("work_entry_type_id.code", "in", sorted(ORDER_WORTHY_LEAVE_CODES))],
    )
    days = fields.Integer("Днів (календарних)", compute="_compute_days")
    sick_number = fields.Char("Номер лікарняного")

    dismissal_basis = fields.Char("Підстава припинення")
    comp_days = fields.Float("Днів компенсації")

    destination = fields.Char("Місце відрядження")
    purpose = fields.Char("Мета відрядження")

    @api.depends("order_type")
    def _compute_register(self):
        for order in self:
            order.register = REGISTER_BY_TYPE.get(order.order_type, "k1")

    @api.depends("employee_id", "order_type")
    def _compute_wage_old(self):
        for order in self:
            order.wage_old = order.employee_id.sudo().version_id.wage if order.employee_id and order.order_type in ("wage", "transfer") else 0.0

    @api.depends("date_from", "date_to")
    def _compute_days(self):
        for order in self:
            order.days = (order.date_to - order.date_from).days + 1 if order.date_from and order.date_to else 0

    @api.depends("employee_id", "order_type")
    def _compute_transfer_old(self):
        for order in self:
            version = order.employee_id.sudo().version_id if order.order_type == "transfer" and order.employee_id else False
            order.department_id_old = version.department_id if version else False
            order.job_title_old = version.job_title if version else False

    @api.onchange("order_type")
    def _onchange_order_type_basis(self):
        """Підстава за замовчуванням: заява - для прийняття, відпустки, звільнення. Не перебиває
        те, що людина вже написала."""
        if self.order_type in ("hire", "leave", "dismissal") and not self.basis:
            self.basis = _("заява")

    @api.onchange("prof_name")
    def _onchange_prof_name_clears_kp(self):
        """Змінюється посада - код професії більше не підставляється зі старої версії.

        Панчишин Христина була «Технік-конструктор» (3118), наказом стала «Менеджер
        із збуту», а код 3118 («Креслярі») переїхав разом з нею і пішов у штатний розпис.
        Код мусить бути обраний свідомо, тому поле очищається; якщо професія та сама
        і код правильний, людина вписує його знову."""
        for order in self:
            if order.order_type == "hire" or not order.employee_id or not order.prof_name:
                continue
            version = order.employee_id.sudo().version_id
            if not version:
                continue
            if order.prof_name != version.ua_prof_name and order.kp_code == version.ua_kp_code:
                order.kp_code = False

    @api.onchange("employee_id")
    def _onchange_employee_id_prefill(self):
        """Статистичні поля наказу (код КП, назва професії, ставка, підрозділ) - з поточної версії
        працівника, якщо їх ще не заповнили вручну."""
        if not self.employee_id or self.order_type == "hire":
            return
        version = self.employee_id.sudo().version_id
        if not version:
            return
        if not self.kp_code:
            self.kp_code = version.ua_kp_code
        if not self.prof_name:
            self.prof_name = version.ua_prof_name
        if not self.wage:
            self.wage = version.wage
        if not self.department_id:
            self.department_id = version.department_id
        if not self.job_title:
            self.job_title = version.job_title

    # -- текст ------------------------------------------------------------------------------------------
    def _order_ref_text(self):
        self.ensure_one()
        return _("Наказ № %(num)s від %(date)s") % {"num": self.name, "date": self.date.strftime("%d.%m.%Y")}

    def action_print_register(self):
        """Друк журналу реєстрації: вибрані накази, а без вибору - усе, що показує список.

        Журнал - не окремий документ, а перелік наказів реєстру за рік, тому рядки
        обирає пошук на списку «Журнал реєстрації наказів», а не поля майстра."""
        orders = self
        if not orders:
            orders = self.search(self.env.context.get("active_domain") or [])
        if not orders:
            raise UserError(_("Немає наказів для друку."))
        return self.env.ref("l10n_ua_hr_orders.action_report_ua_hr_order_register").report_action(orders)

    def content_line(self):
        """Короткий однорядковий зміст наказу - для журналу реєстрації."""
        self.ensure_one()
        o = self
        if o.order_type == "hire":
            return _("Прийняття, %(job)s, оклад %(wage)s грн") % {"job": o.prof_name or o.job_title or "-", "wage": "%.2f" % o.wage}
        if o.order_type == "wage":
            return _("Зміна окладу з %(old)s на %(new)s грн") % {"old": "%.2f" % o.wage_old, "new": "%.2f" % o.wage}
        if o.order_type == "transfer":
            return _("Переведення до %(dept)s, %(job)s") % {"dept": o.department_id.name or "-", "job": o.prof_name or o.job_title or "-"}
        if o.order_type == "leave":
            return _("%(type)s, %(days)s дн. з %(from)s") % {"type": o.leave_type_id.name or "-", "days": o.days, "from": o.date_from and o.date_from.strftime("%d.%m.%Y")}
        if o.order_type == "dismissal":
            return _("Звільнення %(date)s, %(basis)s") % {"date": o.date_to and o.date_to.strftime("%d.%m.%Y"), "basis": o.dismissal_basis or "-"}
        if o.order_type == "trip":
            return _("Відрядження до %(dest)s, %(days)s дн.") % {"dest": o.destination or "-", "days": o.days}
        return ""

    # -- проведення ---------------------------------------------------------------------------------------
    def _check_required(self):
        self.ensure_one()
        need = {
            "hire": ("date_from", "department_id", "wage"),
            "wage": ("date_from", "wage"),
            "transfer": ("date_from",),
            "leave": ("leave_type_id", "date_from", "date_to"),
            "dismissal": ("date_to", "dismissal_basis"),
            "trip": ("date_from", "date_to", "destination"),
        }[self.order_type]
        missing = [self._fields[f].string for f in need if not self[f]]
        if self.order_type == "hire" and not (self.job_title or self.prof_name):
            missing.append(_("Посада"))
        if missing:
            raise UserError(_("Заповніть поля: %s") % ", ".join(missing))
        if self.order_type == "leave" and not is_leave_type_order_worthy(self.leave_type_id):
            raise UserError(_(
                "Вид відпустки «%s» не потребує наказу за КЗпП - оформіть відсутність напряму, "
                "без наказу."
            ) % self.leave_type_id.name)

    def action_post(self):
        for order in self:
            if order.state != "draft":
                raise UserError(_("Проводити можна лише чернетку."))
            order._check_required()
            code = "ua.hr.order.%s" % order.register
            name = self.env["ir.sequence"].sudo().next_by_code(code, sequence_date=order.date)
            if not name:
                raise UserError(_("Не налаштовано нумерацію для реєстру «%s». Зверніться до адміністратора.") % order.register)
            order.name = name
            getattr(order, "_post_%s" % order.order_type)()
            order.state = "posted"
            order.message_post(body=_("Наказ № %s проведено.") % order.name)
        return True

    def _post_hire(self):
        self.ensure_one()
        vals = {
            "employee_id": self.employee_id.id,
            "date_version": self.date_from,
            "contract_date_start": self.date_from,
            "wage": self.wage,
            "job_title": self.prof_name or self.job_title,
            "department_id": self.department_id.id,
            "struct_id": self.env.ref("l10n_ua_payroll_rules.struct_ua_salary").id,
            "resource_calendar_id": self.company_id.resource_calendar_id.id,
            "contract_type_id": self.contract_type_id.id,
            "trial_date_end": self.trial_date_end,
            "ua_order_ref": self._order_ref_text(),
            "ua_kp_code": self.kp_code,
            "ua_prof_name": self.prof_name,
        }
        HrVersion = self.env["hr.version"].sudo().with_context(sync_contract_dates=True)
        # hr.employee.create() записує бутстрап-версію без contract_date_start (з date_version = сьогодні);
        # якщо hire припадає на той самий date_version (типово - прийняття в день заведення картки), треба
        # дозаповнити саме її, а не створювати другу версію з тим самим date_version (унікальний ключ впаде).
        bootstrap = self.env["hr.version"].sudo().search([
            ("employee_id", "=", self.employee_id.id), ("date_version", "=", self.date_from), ("contract_date_start", "=", False),
        ], limit=1)
        if bootstrap:
            version = bootstrap
            version.with_context(sync_contract_dates=True).write(vals)
            created = False
        else:
            vals["employee_id"] = self.employee_id.id
            previous = self.env["hr.version"].sudo().search(
                [("employee_id", "=", self.employee_id.id)], order="date_version desc", limit=1)
            if previous:
                # повторне прийняття: поля картки беремо з попередньої версії, договір - новий
                vals.update({"contract_date_end": False, "ua_end_order_ref": False, "ua_dismissal_basis": False})
                version = self._ua_next_version(previous, vals)
            else:
                version = HrVersion.create(vals)
            created = True
        self.employee_id.sudo().write({
            "ua_main_job": self.main_job,
            "ua_fte": self.fte,
            "ua_contract_kind": self.contract_kind,
            "ua_hire_date": self.date_from,
        })
        self.write({"version_id": version.id, "cancel_write_date": version.write_date, "version_created": created})

    def _post_wage(self):
        self.ensure_one()
        current = self.employee_id.sudo().version_id
        if not current:
            raise UserError(_("У працівника немає поточної версії контракту."))
        vals = {
            "employee_id": self.employee_id.id,
            "date_version": self.date_from,
            "contract_date_start": current.contract_date_start,
            "contract_date_end": current.contract_date_end,
            "wage": self.wage,
            "job_title": current.job_title,
            "department_id": current.department_id.id,
            "struct_id": current.struct_id.id,
            "resource_calendar_id": current.resource_calendar_id.id,
            "contract_type_id": current.contract_type_id.id,
            "trial_date_end": current.trial_date_end,
            "ua_order_ref": self._order_ref_text(),
            "ua_kp_code": current.ua_kp_code,
            "ua_prof_name": current.ua_prof_name,
        }
        version = self._ua_next_version(current, vals)
        self.write({"version_id": version.id, "cancel_write_date": version.write_date})

    def _ua_next_version(self, current, vals):
        """Нова версія договору - копія поточної зі зміненими полями наказу.

        Версія Odoo 19 тримає не лише оклад і посаду, а й поля картки: стать, сімейний стан,
        посаду з довідника, місце роботи, вид оплати, тижневу норму. Створена «з нуля» версія
        їх губила: після наказу про оклад у картці зникала стать, а погодинник ставав окладником."""
        return current.sudo().with_context(sync_contract_dates=True).copy(vals)

    def _post_transfer(self):
        self.ensure_one()
        current = self.employee_id.sudo().version_id
        if not current:
            raise UserError(_("У працівника немає поточної версії контракту."))
        # Переведення без зміни окладу лишає order.wage порожнім (0,00) - копіюємо чинний оклад
        # на сам наказ під час проведення, інакше друкована форма показує «Оклад 0,00».
        effective_wage = self.wage or current.wage
        vals = {
            "employee_id": self.employee_id.id,
            "date_version": self.date_from,
            "contract_date_start": current.contract_date_start,
            "contract_date_end": current.contract_date_end,
            "wage": effective_wage,
            "job_title": self.prof_name or self.job_title or current.job_title,
            "department_id": (self.department_id or current.department_id).id,
            "struct_id": current.struct_id.id,
            "resource_calendar_id": current.resource_calendar_id.id,
            "contract_type_id": current.contract_type_id.id,
            "trial_date_end": current.trial_date_end,
            "ua_order_ref": self._order_ref_text(),
            "ua_kp_code": self.kp_code or current.ua_kp_code,
            "ua_prof_name": self.prof_name or current.ua_prof_name,
        }
        version = self._ua_next_version(current, vals)
        self.write({"version_id": version.id, "cancel_write_date": version.write_date, "wage": effective_wage})

    def _post_leave(self):
        self.ensure_one()
        if self.leave_id:
            # наказ проводиться на вже наявну відпустку (гак hr.leave._action_validate) -
            # другу відпустку не створюємо, лише фіксуємо слід для безпечного скасування.
            self.write({"cancel_write_date": self.leave_id.write_date})
            return
        Leave = self.env["hr.leave"].sudo().with_company(self.employee_id.company_id).with_context(
            default_employee_id=self.employee_id.id, allowed_company_ids=[self.employee_id.company_id.id],
            ua_order_posting=True)
        leave = Leave.create({
            "employee_id": self.employee_id.id,
            "holiday_status_id": self.leave_type_id.id,
            "request_date_from": self.date_from,
            "request_date_to": self.date_to,
            "ua_order_ref": self._order_ref_text(),
            "ua_sick_number": self.sick_number,
        })
        leave.action_approve()
        leave.ua_order_id = self.id
        self.write({"leave_id": leave.id, "cancel_write_date": leave.write_date})

    def _ua_contract_versions(self, version):
        """Усі версії того самого договору: той самий працівник і той самий початок договору."""
        return self.env["hr.version"].sudo().with_context(active_test=False).search([
            ("employee_id", "=", version.employee_id.id),
            ("contract_date_start", "=", version.contract_date_start),
        ])

    def _post_dismissal(self):
        self.ensure_one()
        current = self.employee_id.sudo().version_id
        if not current:
            raise UserError(_("У працівника немає поточної версії контракту."))
        # Дата закінчення - на всі версії цього договору, не лише на поточну. Після зміни окладу
        # чи переведення версій кілька, і всі мають той самий початок договору: якщо закрити одну,
        # решта лишаються безстроковими, і рідна перевірка відмовляє - «already has a contract
        # running during the selected period». Звільнити людину з історією версій було неможливо.
        self._ua_contract_versions(current).with_context(sync_contract_dates=True).write({
            "contract_date_end": self.date_to})
        current.with_context(sync_contract_dates=True).write({
            "ua_end_order_ref": self._order_ref_text(),
            "ua_dismissal_basis": self.dismissal_basis,
        })
        self.employee_id.sudo().write({"ua_dismissal_date": self.date_to, "active": False})
        self.write({"version_id": current.id, "cancel_write_date": current.write_date})
        if self.comp_days:
            payslip = self.env["hr.payslip"].sudo().search([
                ("employee_id", "=", self.employee_id.id), ("state", "=", "draft"),
                ("date_from", "<=", self.date_to), ("date_to", ">=", self.date_to),
            ], limit=1)
            if payslip:
                inp = self.env["hr.payslip.input"].sudo().create({
                    "payslip_id": payslip.id, "contract_id": current.id, "code": "COMP_DAYS",
                    "name": _("Компенсація невикористаної відпустки"), "amount": self.comp_days,
                })
                self.comp_days_input_id = inp.id

    def _post_trip(self):
        self.ensure_one()
        # даних не змінює, лише реєструється і друкується
        return True

    # -- скасування -------------------------------------------------------------------------------------
    def action_cancel(self):
        for order in self:
            if order.state not in ("posted", "acknowledged"):
                raise UserError(_("Скасувати можна лише проведений або ознайомлений наказ."))
            if order.order_type in ("hire", "wage", "transfer"):
                order._cancel_created_version()
            elif order.order_type == "leave":
                order._cancel_created_leave()
            elif order.order_type == "dismissal":
                order._cancel_dismissal()
            else:  # trip: даних не змінював
                order.write({"state": "draft", "name": False, "ack_date": False, "ack_user_id": False})

    def _cancel_created_version(self):
        self.ensure_one()
        version = self.version_id
        if not version or not version.exists():
            self.write({"state": "draft", "name": False, "ack_date": False, "ack_user_id": False})
            return
        if version.write_date != self.cancel_write_date:
            raise UserError(_(
                "Дані версії контракту, яку створив наказ № %s, змінювали після проведення. "
                "Виправте вручну і за потреби видаліть версію «%s» самостійно."
            ) % (self.name, version.display_name))
        if self.order_type == "hire":
            self.employee_id.sudo().write({
                "ua_main_job": True, "ua_fte": "1", "ua_contract_kind": "employment", "ua_hire_date": False,
            })
        if self.version_created:
            version.unlink()
        else:
            # бутстрап-версія працівника - не видаляємо запис (кожен працівник має мати версію), лише
            # очищаємо поля, які на неї записав hire
            version.with_context(sync_contract_dates=True).write({
                "contract_date_start": False, "wage": 0.0, "job_title": False, "department_id": False,
                "contract_type_id": False, "trial_date_end": False, "ua_order_ref": False,
                "ua_kp_code": False, "ua_prof_name": False,
            })
        self.write({"state": "draft", "name": False, "version_id": False, "ack_date": False, "ack_user_id": False,
                   "cancel_write_date": False, "version_created": True})

    def _cancel_created_leave(self):
        self.ensure_one()
        leave = self.leave_id
        if not leave or not leave.exists():
            self.write({"state": "draft", "name": False, "ack_date": False, "ack_user_id": False})
            return
        if leave.write_date != self.cancel_write_date:
            raise UserError(_(
                "Відпустку, яку створив наказ № %s, змінювали після проведення. "
                "Виправте вручну і за потреби скасуйте відпустку «%s» самостійно."
            ) % (self.name, leave.display_name))
        leave.sudo().with_context(ua_order_posting=True).action_refuse()
        leave.sudo().unlink()
        self.write({"state": "draft", "name": False, "leave_id": False, "ack_date": False, "ack_user_id": False, "cancel_write_date": False})

    def _cancel_dismissal(self):
        self.ensure_one()
        version = self.version_id
        if not version or not version.exists():
            self.write({"state": "draft", "name": False, "ack_date": False, "ack_user_id": False})
            return
        if version.write_date != self.cancel_write_date:
            raise UserError(_(
                "Версію контракту, яку змінив наказ про звільнення № %s, редагували після проведення. "
                "Поверніть contract_date_end/підставу звільнення вручну."
            ) % self.name)
        self._ua_contract_versions(version).with_context(sync_contract_dates=True).write({
            "contract_date_end": False})
        version.with_context(sync_contract_dates=True).write({
            "ua_end_order_ref": False, "ua_dismissal_basis": False,
        })
        self.employee_id.sudo().write({"ua_dismissal_date": False, "active": True})
        if self.comp_days_input_id and self.comp_days_input_id.exists():
            self.comp_days_input_id.unlink()
        self.write({"state": "draft", "name": False, "ack_date": False, "ack_user_id": False, "cancel_write_date": False, "comp_days_input_id": False})

    # -- ознайомлення -----------------------------------------------------------------------------------
    def action_acknowledge(self):
        for order in self:
            if order.state != "posted":
                raise UserError(_("Ознайомити можна лише з проведеним наказом."))
            order.write({"state": "acknowledged", "ack_date": fields.Date.context_today(order), "ack_user_id": self.env.user.id})
