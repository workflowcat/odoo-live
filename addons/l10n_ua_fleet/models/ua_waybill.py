"""Подорожній лист і облік паливно-мастильних матеріалів (ПММ).

Паливо, видане водію, лишається запасом компанії, доки його не списано: у кожного авто своє
місце зберігання «Бак: <номер>» поруч зі «Складом». Заправка зі складу - переміщення в бак,
заправка на АЗС - прихід у бак за ціною чека. Списує паливо подорожній лист.

Нормативна витрата (загальний вигляд формули з Норм витрат палива, наказ Мінтрансу № 43):

    Qн = (Hs * S / 100 + Hw * W / 100 + Hh * T) * (1 + D / 100)

    Hs - базова лінійна норма авто, л/100 км;   S - пробіг за спідометром, км;
    Hw - норма на транспортну роботу, л/100 т·км;  W - транспортна робота, т·км;
    Hh - норма на роботу на місці, л/год;       T - мотогодини;
    D  - сума коригувань у відсотках (зима, місто, інші умови).

Норми і відсотки - налаштування авто й компанії, а не правила в коді: перед використанням
їх звіряють з чинною редакцією наказу і власним наказом компанії.

Фактична витрата = залишок при виїзді + заправлено - залишок при поверненні. У межах норми
вона списується на рахунок витрат авто (23, 91, 92, 93 - за призначенням), понад норму - на
окремий рахунок (наприклад, 949 або 375, якщо стягують з водія). Економія лишається в баку.
Обидва списання - переміщення з бака на віртуальні місця списання авто, у яких стоїть
рахунок; проводку робить оцінка запасів Odoo.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MONTHS = [(str(n), name) for n, name in enumerate(
    ("січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень",
     "вересень", "жовтень", "листопад", "грудень"), start=1)]
STATES = [("draft", "Чернетка"), ("open", "Видано водію"), ("done", "Закрито"),
          ("cancel", "Скасовано")]


class UaFuelNormAdjustment(models.Model):
    _name = "ua.fuel.norm.adjustment"
    _description = "Коригування норми витрати палива"
    _order = "sequence, id"

    name = fields.Char("Назва", required=True, help="Наприклад: «Зима», «Місто 100-250 тис.».")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    percent = fields.Float("Відсоток", digits=(5, 2), required=True,
                           help="Підвищення (з плюсом) або зниження (з мінусом) норми.")
    month_from = fields.Selection(MONTHS, "Само з місяця",
                                  help="Порожньо - коригування обирають у листі вручну.")
    month_to = fields.Selection(MONTHS, "по місяць")
    note = fields.Char("Підстава", help="Пункт наказу або рішення про зимовий період.")

    @api.constrains("month_from", "month_to")
    def _check_months(self):
        for adjustment in self:
            if bool(adjustment.month_from) != bool(adjustment.month_to):
                raise ValidationError(_("Вкажіть обидва місяці або жодного."))

    def _applies(self, date):
        """Чи діє коригування само на цю дату (період може переходити через Новий рік)."""
        self.ensure_one()
        if not self.month_from or not date:
            return False
        start, end, month = int(self.month_from), int(self.month_to), date.month
        return start <= month <= end if start <= end else (month >= start or month <= end)

    @api.model
    def for_date(self, date, company):
        return self.search([("company_id", "=", company.id)]).filtered(lambda a: a._applies(date))


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    ua_fuel_product_id = fields.Many2one(
        "product.product", "Паливо", domain="[('is_storable', '=', True)]",
        help="Складський товар, яким заправляють авто (дизель, А-95).")
    ua_norm_base = fields.Float("Базова норма, л/100 км", digits=(6, 2))
    ua_norm_cargo = fields.Float("На транспортну роботу, л/100 т·км", digits=(6, 2))
    ua_norm_hour = fields.Float("Робота на місці, л/год", digits=(6, 2),
                                help="Для спецтехніки, генераторів, рефрижераторів.")
    ua_warehouse_id = fields.Many2one(
        "stock.warehouse", "Склад ПММ", check_company=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1))
    ua_expense_account_id = fields.Many2one(
        "account.account", "Рахунок витрат ПММ", check_company=True,
        help="Списання в межах норми: 23, 91, 92 чи 93 - за призначенням авто.")
    ua_overnorm_account_id = fields.Many2one(
        "account.account", "Рахунок витрати понад норму", check_company=True,
        help="Наприклад, 949 або 375, якщо понаднормову витрату стягують з водія.")
    ua_tank_location_id = fields.Many2one("stock.location", "Бак", readonly=True, copy=False)
    ua_expense_location_id = fields.Many2one("stock.location", "Списання в межах норми",
                                             readonly=True, copy=False)
    ua_overnorm_location_id = fields.Many2one("stock.location", "Списання понад норму",
                                              readonly=True, copy=False)
    ua_fuel_in_tank = fields.Float("Паливо в баку, л", compute="_compute_ua_fuel_in_tank",
                                   digits=(8, 2))
    ua_waybill_ids = fields.One2many("ua.waybill", "vehicle_id", "Подорожні листи")
    ua_waybill_count = fields.Integer("Подорожні листи", compute="_compute_ua_waybill_count")

    def _compute_ua_fuel_in_tank(self):
        for vehicle in self:
            vehicle.ua_fuel_in_tank = vehicle.ua_fuel_balance()

    def _compute_ua_waybill_count(self):
        for vehicle in self:
            vehicle.ua_waybill_count = len(vehicle.ua_waybill_ids)

    def ua_fuel_balance(self):
        """Скільки палива зараз у баку."""
        self.ensure_one()
        if not self.ua_tank_location_id or not self.ua_fuel_product_id:
            return 0.0
        quants = self.env["stock.quant"].sudo().search([
            ("location_id", "=", self.ua_tank_location_id.id),
            ("product_id", "=", self.ua_fuel_product_id.id)])
        return sum(quants.mapped("quantity"))

    def write(self, vals):
        result = super().write(vals)
        if {"ua_expense_account_id", "ua_overnorm_account_id"} & set(vals):
            for vehicle in self:
                if vehicle.ua_expense_location_id and vehicle.ua_expense_account_id:
                    vehicle.ua_expense_location_id.sudo().valuation_account_id = vehicle.ua_expense_account_id
                if vehicle.ua_overnorm_location_id and vehicle.ua_overnorm_account_id:
                    vehicle.ua_overnorm_location_id.sudo().valuation_account_id = vehicle.ua_overnorm_account_id
        return result

    def _ua_locations(self):
        """Бак і два місця списання авто; створюються під час першого листа."""
        self.ensure_one()
        if not (self.ua_fuel_product_id and self.ua_warehouse_id and self.ua_expense_account_id
                and self.ua_overnorm_account_id):
            raise UserError(_("%s: заповніть паливо, склад ПММ і рахунки списання на вкладці «ПММ».")
                            % self.display_name)
        Location = self.env["stock.location"].sudo()
        plate = self.license_plate or self.display_name
        company = self.company_id or self.env.company
        values = {}
        if not self.ua_tank_location_id:
            values["ua_tank_location_id"] = Location.create({
                "name": _("Бак: %s") % plate, "usage": "internal", "company_id": company.id,
                "location_id": self.ua_warehouse_id.view_location_id.id}).id
        for field, account, label in (
                ("ua_expense_location_id", self.ua_expense_account_id, _("Списання ПММ: %s")),
                ("ua_overnorm_location_id", self.ua_overnorm_account_id, _("ПММ понад норму: %s"))):
            if not self[field]:
                values[field] = Location.create({
                    # Odoo 19: місця обліку втрат без батьківського «Virtual Locations», як рідні
                    "name": label % plate, "usage": "inventory", "company_id": company.id,
                    "valuation_account_id": account.id}).id
        if values:
            super(FleetVehicle, self.sudo()).write(values)
        return self.ua_tank_location_id, self.ua_expense_location_id, self.ua_overnorm_location_id

    def action_ua_waybills(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("l10n_ua_fleet.action_ua_waybill")
        action["domain"] = [("vehicle_id", "=", self.id)]
        action["context"] = {"default_vehicle_id": self.id}
        return action


class StockMove(models.Model):
    _inherit = "stock.move"

    ua_waybill_id = fields.Many2one("ua.waybill", "Подорожній лист", index="btree_not_null",
                                    readonly=True, copy=False)
    ua_waybill_reversed = fields.Boolean("Сторновано скасуванням листа", readonly=True, copy=False)


class UaWaybill(models.Model):
    _name = "ua.waybill"
    _description = "Подорожній лист"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char("Номер", readonly=True, copy=False, default="/")
    company_id = fields.Many2one("res.company", "Компанія", required=True, index=True,
                                 default=lambda self: self.env.company)
    vehicle_id = fields.Many2one("fleet.vehicle", "Авто", required=True, index=True, tracking=True,
                                 check_company=True)
    license_plate = fields.Char(related="vehicle_id.license_plate")
    driver_id = fields.Many2one("res.partner", "Водій", tracking=True,
                                compute="_compute_driver_id", store=True, readonly=False)
    date = fields.Date("Дата виїзду", required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date("Дата повернення")
    route = fields.Char("Маршрут")
    purpose = fields.Char("Мета поїздки")
    odometer_start = fields.Float("Спідометр при виїзді", digits=(10, 0),
                                  compute="_compute_odometer_start", store=True, readonly=False,
                                  precompute=True)
    odometer_end = fields.Float("Спідометр при поверненні", digits=(10, 0))
    distance = fields.Float("Пробіг, км", compute="_compute_norm", store=True, digits=(10, 0))
    cargo_tkm = fields.Float("Транспортна робота, т·км", digits=(10, 1))
    engine_hours = fields.Float("Мотогодини", digits=(8, 2))
    adjustment_ids = fields.Many2many("ua.fuel.norm.adjustment", string="Коригування норми",
                                      compute="_compute_adjustment_ids", store=True, readonly=False,
                                      precompute=True)
    adjustment_pct = fields.Float("Коригування, %", compute="_compute_norm", store=True, digits=(6, 2))
    fuel_product_id = fields.Many2one(related="vehicle_id.ua_fuel_product_id", string="Паливо")
    fuel_start = fields.Float("Залишок при виїзді, л", readonly=True, copy=False, digits=(8, 2))
    refuel_ids = fields.One2many("ua.waybill.refuel", "waybill_id", "Заправки", copy=False)
    fuel_issued = fields.Float("Заправлено, л", compute="_compute_norm", store=True, digits=(8, 2))
    fuel_end = fields.Float("Залишок при поверненні, л", digits=(8, 2), copy=False)
    fuel_norm = fields.Float("За нормою, л", compute="_compute_norm", store=True, digits=(8, 2))
    fuel_actual = fields.Float("Фактично, л", compute="_compute_norm", store=True, digits=(8, 2))
    fuel_over = fields.Float("Понад норму, л", compute="_compute_norm", store=True, digits=(8, 2))
    fuel_saved = fields.Float("Економія, л", compute="_compute_norm", store=True, digits=(8, 2))
    move_ids = fields.One2many("stock.move", "ua_waybill_id", "Рух палива", readonly=True)
    odometer_log_id = fields.Many2one("fleet.vehicle.odometer", "Запис спідометра", readonly=True,
                                      copy=False)
    state = fields.Selection(STATES, "Стан", required=True, default="draft", tracking=True, copy=False)
    note = fields.Text("Примітка")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].with_company(
                    vals.get("company_id") or self.env.company.id).next_by_code(
                    "ua.waybill", sequence_date=vals.get("date")) or "/"
        return super().create(vals_list)

    @api.depends("vehicle_id")
    def _compute_driver_id(self):
        for waybill in self:
            waybill.driver_id = waybill.driver_id or waybill.vehicle_id.driver_id

    @api.depends("vehicle_id")
    def _compute_odometer_start(self):
        for waybill in self:
            waybill.odometer_start = waybill.odometer_start or waybill.vehicle_id.odometer

    @api.depends("date", "company_id")
    def _compute_adjustment_ids(self):
        Adjustment = self.env["ua.fuel.norm.adjustment"]
        for waybill in self:
            manual = waybill.adjustment_ids.filtered(lambda a: not a.month_from)
            waybill.adjustment_ids = manual | Adjustment.for_date(waybill.date, waybill.company_id)

    @api.depends("odometer_start", "odometer_end", "cargo_tkm", "engine_hours", "adjustment_ids.percent",
                 "vehicle_id.ua_norm_base", "vehicle_id.ua_norm_cargo", "vehicle_id.ua_norm_hour",
                 "fuel_start", "fuel_end", "refuel_ids.quantity")
    def _compute_norm(self):
        for waybill in self:
            vehicle = waybill.vehicle_id
            distance = max(waybill.odometer_end - waybill.odometer_start, 0.0) if waybill.odometer_end else 0.0
            pct = sum(waybill.adjustment_ids.mapped("percent"))
            norm = (vehicle.ua_norm_base * distance / 100.0
                    + vehicle.ua_norm_cargo * waybill.cargo_tkm / 100.0
                    + vehicle.ua_norm_hour * waybill.engine_hours) * (1.0 + pct / 100.0)
            issued = sum(waybill.refuel_ids.mapped("quantity"))
            actual = waybill.fuel_start + issued - waybill.fuel_end
            waybill.distance = distance
            waybill.adjustment_pct = pct
            waybill.fuel_issued = round(issued, 2)
            waybill.fuel_norm = round(norm, 2)
            waybill.fuel_actual = round(actual, 2)
            waybill.fuel_over = round(max(actual - norm, 0.0), 2)
            waybill.fuel_saved = round(max(norm - actual, 0.0), 2)

    def unlink(self):
        if self.filtered(lambda w: w.state in ("open", "done")):
            raise UserError(_("Виданий чи закритий лист не видаляють: його скасовують."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Стани
    # ------------------------------------------------------------------
    def action_open(self):
        """Видати лист водію: фіксуємо спідометр і залишок у баку."""
        for waybill in self:
            if waybill.state != "draft":
                raise UserError(_("Видати можна лише чернетку."))
            vehicle = waybill.vehicle_id
            vehicle._ua_locations()
            busy = self.search([("vehicle_id", "=", vehicle.id), ("state", "=", "open"),
                                ("id", "!=", waybill.id)], limit=1)
            if busy:
                raise UserError(_("Авто вже в рейсі за листом %s.") % busy.name)
            if waybill.odometer_start < vehicle.odometer:
                raise UserError(_("Спідометр при виїзді %(start)s менший за останній відомий %(last)s.",
                                  start="%g" % waybill.odometer_start, last="%g" % vehicle.odometer))
            waybill.write({"state": "open", "fuel_start": vehicle.ua_fuel_balance()})
        return True

    def _move(self, source, destination, quantity, price_unit=None):
        """Одне переміщення палива листом, одразу проведене."""
        self.ensure_one()
        product = self.vehicle_id.ua_fuel_product_id
        values = {
            "product_id": product.id, "product_uom_qty": quantity, "product_uom": product.uom_id.id,
            "location_id": source.id, "location_dest_id": destination.id,
            "company_id": self.company_id.id, "origin": self.name, "ua_waybill_id": self.id,
            "date": fields.Datetime.now(),
        }
        if price_unit is not None:
            values["price_unit"] = price_unit
        move = self.env["stock.move"].sudo().create(values)
        move._action_confirm()
        if source.usage == "internal":
            move._action_assign()
            if product.uom_id.compare(move.quantity, quantity) < 0:
                raise UserError(_(
                    "%(where)s: палива %(have)s л, а треба списати %(need)s л.",
                    where=source.display_name, have="%g" % move.quantity, need="%g" % quantity))
        else:
            move.quantity = quantity
        move.picked = True
        move._action_done()
        return move

    def action_done(self):
        """Закрити лист: заправки - у бак, фактична витрата - зі списанням за нормою."""
        for waybill in self:
            if waybill.state != "open":
                raise UserError(_("Закрити можна лише лист, виданий водію."))
            if not waybill.odometer_end or waybill.odometer_end < waybill.odometer_start:
                raise UserError(_("Вкажіть спідометр при поверненні, не менший за показник при виїзді."))
            if waybill.fuel_end < 0 or waybill.fuel_actual < 0:
                raise UserError(_(
                    "Залишок при поверненні %(end)s л більший, ніж було і заправлено (%(total)s л). "
                    "Перевірте показники.", end="%g" % waybill.fuel_end,
                    total="%g" % (waybill.fuel_start + waybill.fuel_issued)))
            tank, expense, overnorm = waybill.vehicle_id._ua_locations()
            warehouse = waybill.vehicle_id.ua_warehouse_id
            vendors = self.env.ref("stock.stock_location_suppliers")
            for refuel in waybill.refuel_ids:
                if refuel.source == "stock":
                    waybill._move(warehouse.lot_stock_id, tank, refuel.quantity)
                else:
                    waybill._move(vendors, tank, refuel.quantity, price_unit=refuel.price_unit)
            within = min(waybill.fuel_actual, waybill.fuel_norm)
            if within > 0:
                waybill._move(tank, expense, round(within, 2))
            if waybill.fuel_over > 0:
                waybill._move(tank, overnorm, waybill.fuel_over)
            log = self.env["fleet.vehicle.odometer"].sudo().create({
                "vehicle_id": waybill.vehicle_id.id, "value": waybill.odometer_end,
                "date": waybill.date_end or waybill.date})
            waybill.vehicle_id.invalidate_recordset(["odometer"])
            waybill.write({"state": "done", "odometer_log_id": log.id,
                           "date_end": waybill.date_end or waybill.date})
        return True

    def action_cancel(self):
        """Скасувати: рух палива сторнується, запис спідометра зникає."""
        for waybill in self:
            if waybill.state == "done":
                later = self.search([("vehicle_id", "=", waybill.vehicle_id.id),
                                     ("state", "in", ("open", "done")),
                                     ("odometer_start", ">=", waybill.odometer_end),
                                     ("id", "!=", waybill.id)], limit=1)
                if later:
                    raise UserError(_("Після цього листа вже є лист %s: скасуйте спершу його.")
                                    % later.name)
                for move in waybill.move_ids.filtered(
                        lambda m: m.state == "done" and not m.ua_waybill_reversed).sorted("id", reverse=True):
                    price = abs(move.value) / move.quantity if move.quantity and "value" in move._fields else None
                    reverse = waybill._move(move.location_dest_id, move.location_id, move.quantity,
                                            price_unit=price)
                    reverse.origin = _("Скасування %s") % waybill.name
                    move.ua_waybill_reversed = True
                    reverse.ua_waybill_reversed = True
                log = waybill.odometer_log_id
                waybill.odometer_log_id = False
                log.sudo().unlink()
                waybill.vehicle_id.invalidate_recordset(["odometer"])
            waybill.write({"state": "cancel"})
        return True

    def action_reset_draft(self):
        self.filtered(lambda w: w.state == "cancel").write({"state": "draft", "fuel_start": 0.0})
        return True

    def action_print(self):
        return self.env.ref("l10n_ua_fleet.action_report_ua_waybill").report_action(self)

    @staticmethod
    def litres(value):
        """27,50 - літри для друку."""
        return ("%.2f" % (value or 0.0)).replace(".", ",")


class UaWaybillRefuel(models.Model):
    _name = "ua.waybill.refuel"
    _description = "Заправка за подорожнім листом"
    _order = "waybill_id, date, id"

    waybill_id = fields.Many2one("ua.waybill", "Подорожній лист", required=True, index=True,
                                 ondelete="cascade")
    company_id = fields.Many2one(related="waybill_id.company_id", store=True)
    date = fields.Date("Дата", default=fields.Date.context_today)
    source = fields.Selection([("stock", "Зі складу"), ("vendor", "АЗС, паливна картка")],
                              "Звідки", required=True, default="stock")
    partner_id = fields.Many2one("res.partner", "АЗС / постачальник")
    quantity = fields.Float("Літрів", required=True, digits=(8, 2))
    price_unit = fields.Float("Ціна без ПДВ за літр", digits="Product Price",
                              help="Для заправки на АЗС: за цією ціною паливо приходить у бак.")
    reference = fields.Char("Чек, картка")

    @api.constrains("quantity", "source", "price_unit")
    def _check_values(self):
        for refuel in self:
            if refuel.quantity <= 0:
                raise ValidationError(_("Заправка - більше нуля літрів."))
            if refuel.source == "vendor" and refuel.price_unit <= 0:
                raise ValidationError(_("Для заправки на АЗС вкажіть ціну за літр."))
