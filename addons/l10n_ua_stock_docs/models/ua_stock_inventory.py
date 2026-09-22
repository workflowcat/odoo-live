# -*- coding: utf-8 -*-
"""Інвентаризація запасів за Положенням № 879.

Рахує залишки нативний Odoo: у нього є режим коригування залишків, де комірник
ставить фактичну кількість, а система сама робить переміщення і проводку. Двох
речей там немає, і обидві потрібні українському підприємству.

Перша - папір. Наказ № 879 вимагає інвентаризаційний опис (усі позиції, що
рахували) і звіряльну відомість (тільки розбіжності), обидва з комісією і
підписами. Нативний Odoo друкує список залишків, а не ці дві форми.

Друга - рахунок лишків. У Odoo 19 у локації списання один рахунок оцінки, і
він працює в обидві сторони: нестача лягає Дт 947 (правильно), лишок - Кт 947
(неправильно, бо це не зменшення втрат, а дохід). Тому документ після
проведення перекидає лишок з 947 на 719 «Інші доходи від операційної
діяльності» окремою проводкою. Одна проводка на весь документ, з посиланням на
його номер.

Спрощення, які треба знати:

* норми природного убутку не рахуємо - уся нестача йде на 947, розподіл на
  «у межах норм / понад норми» робить бухгалтер вручну;
* нестачі понад норми до встановлення винних мають висіти на позабалансовому
  субрахунку 072 - позабаланс у продукті не ведеться;
* різниця по товару лягає на один quant локації, а не розкидається по всіх.

Зовнішній клієнт (складський екран поза Odoo) працює тими самими трьома
дієсловами, що й решта продукту: створити - `ua_get_or_create`, показати план -
`plan`, провести - `action_apply`. Стан документа клієнт не пише: для цього є
`action_start_count`. Мітка операції клієнта лежить у `ua_client_ref` і не
повторюється в межах компанії, тому повторний виклик після обриву звʼязку дає той
самий документ, а не другий.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

ACC_SURPLUS = "ua_psbp_719"
ACC_SHORTAGE = "ua_psbp_947"


def _qty(value):
    """Кількість для людського рядка: без хвоста нулів, але з дробом, коли він є."""
    text = "%.3f" % value
    return text.rstrip("0").rstrip(".") if "." in text else text


class UaStockInventory(models.Model):
    _name = "ua.stock.inventory"
    _description = "Інвентаризація запасів"
    _order = "date desc, id desc"

    name = fields.Char("Номер", readonly=True, copy=False, default="Новий", index=True)
    date = fields.Date("Дата", required=True, default=fields.Date.context_today)
    company_id = fields.Many2one(
        "res.company", string="Компанія", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    location_id = fields.Many2one(
        "stock.location", string="Склад", required=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        help="Рядки заповнюються залишками цієї локації та її дочірніх.")
    basis = fields.Char(
        "Підстава",
        help="Наказ про проведення інвентаризації: номер і дата.")
    chair = fields.Char("Голова комісії")
    members = fields.Char("Члени комісії")
    keeper = fields.Char(
        "Матеріально відповідальна особа",
        help="Хто відповідає за цінності. Її підпис стоїть під описом.")
    state = fields.Selection(
        [("draft", "Чернетка"), ("counting", "Підрахунок"), ("done", "Проведено")],
        string="Стан", default="draft", required=True, copy=False)
    ua_client_ref = fields.Char(
        "Мітка операції", index=True, copy=False,
        help="Мітка зовнішнього клієнта. Не повторюється в межах компанії: "
             "повторне створення з тією самою міткою віддає той самий документ.")

    _ua_client_ref_unique = models.Constraint(
        "UNIQUE(company_id, ua_client_ref)",
        "Документ інвентаризації з такою міткою операції в цій компанії вже є.",
    )

    line_ids = fields.One2many("ua.stock.inventory.line", "inventory_id", string="Рядки")
    move_ids = fields.Many2many("stock.move", string="Коригування", readonly=True, copy=False)
    surplus_move_id = fields.Many2one(
        "account.move", "Проводка лишків", readonly=True, copy=False,
        help="Перекидання лишків з 947 на 719.")

    amount_surplus = fields.Monetary(
        "Лишки", currency_field="currency_id", compute="_compute_amounts", store=True)
    amount_shortage = fields.Monetary(
        "Нестачі", currency_field="currency_id", compute="_compute_amounts", store=True)

    @api.depends("line_ids.amount_diff")
    def _compute_amounts(self):
        for record in self:
            amounts = record.line_ids.mapped("amount_diff")
            record.amount_surplus = sum(value for value in amounts if value > 0)
            record.amount_shortage = -sum(value for value in amounts if value < 0)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "Новий") in (False, "", "Новий"):
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "ua.stock.inventory") or "Новий"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Службове
    # ------------------------------------------------------------------
    def _account(self, xmlid):
        self.ensure_one()
        chart = self.env["account.chart.template"].with_company(self.company_id).sudo()
        account = chart.ref(xmlid, raise_if_not_found=False)
        if account:
            return account
        code = xmlid.rsplit("_", 1)[-1]
        Account = self.env["account.account"].sudo().with_company(self.company_id)
        for candidate in Account.search(
            [("code", "=like", code + "%"), ("company_ids", "in", self.company_id.ids)],
            order="code",
        ):
            if candidate.code.rstrip("0") == code or candidate.code == code:
                return candidate
        raise UserError(
            "У плані рахунків компанії «%s» немає рахунку %s."
            % (self.company_id.name, code))

    def _quants(self, category_ids=None, location_ids=None):
        """Залишки складу документа, за потреби звужені категорією і полицями.

        Категорія береться разом із дочірніми (`child_of`): «Сировина» накриває
        всі свої підкатегорії. Полиці так само, і завжди в межах локації
        документа - звуження не може вивести опис за склад, на який його виписано.
        """
        self.ensure_one()
        domain = [
            ("location_id", "child_of", self.location_id.id),
            ("company_id", "=", self.company_id.id),
        ]
        if location_ids:
            allowed = self.env["stock.location"].search([
                ("id", "child_of", list(location_ids)),
                ("id", "child_of", self.location_id.id),
            ])
            domain.append(("location_id", "in", allowed.ids))
        if category_ids:
            categories = self.env["product.category"].search(
                [("id", "child_of", list(category_ids))])
            domain.append(("product_id.categ_id", "in", categories.ids))
        return self.env["stock.quant"].search(domain)

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------
    def action_fill(self, category_ids=None, location_ids=None):
        """Заповнити опис залишками складу. Старі рядки замінюються свіжими.

        Без аргументів - уся локація, як було. З `category_ids` і `location_ids`
        (списки id) опис звужується: комірник рахує одну категорію за раз, і
        сировина не лізе в опис готової продукції.
        """
        for record in self:
            if record.state == "done":
                raise UserError("Інвентаризацію «%s» уже проведено." % record.name)
            totals = {}
            for quant in record._quants(category_ids, location_ids):
                if not quant.product_id.is_storable:
                    continue
                totals.setdefault(quant.product_id, 0.0)
                totals[quant.product_id] += quant.quantity
            if not totals:
                raise UserError(
                    "У локації «%s» немає залишків%s."
                    % (record.location_id.display_name,
                       " за заданим звуженням" if (category_ids or location_ids) else ""))
            record.line_ids = [(5, 0, 0)] + [
                (0, 0, {
                    "product_id": product.id,
                    "qty_book": quantity,
                    "qty_fact": quantity,
                    "cost": product.with_company(record.company_id).standard_price,
                })
                for product, quantity in sorted(
                    totals.items(), key=lambda item: item[0].display_name)
            ]
            record.state = "counting"
        return True

    def action_start_count(self):
        """Перевести опис із чернетки в підрахунок, не пишучи `state` ззовні.

        Потрібно тому, що зовнішній клієнт часто приносить свої рядки: він будує
        аркуш підрахунку сам зі `stock.quant` і не кличе `action_fill`. Без цієї
        кнопки йому довелося б писати внутрішній стан моделі руками.
        """
        for record in self:
            if record.state == "done":
                raise UserError("Інвентаризацію «%s» уже проведено." % record.name)
            if not record.line_ids:
                raise UserError(
                    "Опис «%s» порожній: додайте рядки або заповніть залишками."
                    % record.name)
            record.state = "counting"
        return True

    @api.model
    def ua_get_or_create(self, client_ref, vals=None):
        """Документ за міткою клієнта: є - віддаємо, немає - створюємо.

        Захист від подвійного запису при обриві звʼязку. Другий виклик із тією
        самою міткою повертає перший документ і НЕ чіпає його вміст: клієнт
        повторює запит, а не переписує чужий підрахунок.
        """
        if not client_ref:
            raise UserError("Без мітки операції документ не створюється.")
        values = dict(vals or {})
        company_id = values.get("company_id") or self.env.company.id
        existing = self.search([
            ("ua_client_ref", "=", client_ref),
            ("company_id", "=", company_id),
        ], limit=1)
        if existing:
            return existing
        values["company_id"] = company_id
        values["ua_client_ref"] = client_ref
        return self.create(values)

    def plan(self):
        """Що зробить проведення: розбіжності, суми на 947 і 719, дата, перешкоди.

        Рядки того самого вигляду, що в `ua.period.close.plan()`: `text`, `level`
        (`info` / `warn` / `crit`), за потреби `target`. Хоч один рядок `crit` -
        `action_apply` впаде, і кнопка підтвердження нічого не змінить.
        """
        self.ensure_one()
        currency = self.company_id.currency_id
        today = fields.Date.context_today(self)
        target_lines = {"model": "ua.stock.inventory.line",
                        "domain": [("inventory_id", "=", self.id)]}

        if self.state == "done":
            return [{
                "text": "Інвентаризацію «%s» уже проведено %s: повторне проведення "
                        "нічого не додасть." % (self.name, self.date.strftime("%d.%m.%Y")),
                "level": "info",
                "target": target_lines,
            }]

        rows = []
        if self.state != "counting":
            rows.append({
                "text": "Опис ще не в підрахунку: заповніть його залишками або "
                        "додайте рядки і натисніть «Почати підрахунок».",
                "level": "crit",
                "target": target_lines,
            })
        if self.date > today:
            rows.append({
                "text": "Дату опису поставлено на %s - цей день ще не настав. Запаси "
                        "рахують у день підрахунку, тому проведення не пройде." % (
                            self.date.strftime("%d.%m.%Y")),
                "level": "crit",
            })

        diff_lines = self._lines_with_diff()
        rows.append({
            "text": "Розбіжностей: %s рядків із %s." % (len(diff_lines), len(self.line_ids)),
            "level": "info",
            "target": target_lines,
        })
        if diff_lines:
            for line in diff_lines[:20]:
                rows.append({
                    "text": "%s: за обліком %s, фактично %s, різниця %s на %.2f %s." % (
                        line.product_id.display_name,
                        _qty(line.qty_book), _qty(line.qty_fact), _qty(line.qty_diff),
                        line.amount_diff, currency.symbol or currency.name),
                    "level": "info",
                })
        if not currency.is_zero(self.amount_surplus):
            rows.append({
                "text": "Лишок %.2f: нативна оцінка запасів кладе Дт 201 Кт 947, а документ "
                        "перекидає цю суму Дт 947 Кт 719 - лишок це дохід, а не менша "
                        "нестача." % self.amount_surplus,
                "level": "info",
            })
        if not currency.is_zero(self.amount_shortage):
            rows.append({
                "text": "Нестача %.2f: Дт 947 Кт 201. Норми природного убутку не рахуються, "
                        "уся сума йде на 947 - розподіл «у межах норм / понад норми» "
                        "робить бухгалтер." % self.amount_shortage,
                "level": "warn",
            })
        if not diff_lines:
            rows.append({
                "text": "Розбіжностей немає: проведення лише закриє документ, жодної "
                        "проводки не буде.",
                "level": "warn",
            })
        else:
            rows.append({
                "text": "Обидві проводки - нативна оцінка запасів і наша 947 -> 719 - "
                        "лягають датою опису %s." % self.date.strftime("%d.%m.%Y"),
                "level": "info",
            })
        if any(row["level"] == "crit" for row in rows):
            rows.append({
                "text": "Поки ці перешкоди лишаються, провести опис не вийде.",
                "level": "warn",
            })
        return rows

    def _apply_line(self, line):
        """Коригування залишку по одному рядку. Повертає створене переміщення."""
        self.ensure_one()
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        quants = Quant.search([
            ("product_id", "=", line.product_id.id),
            ("location_id", "child_of", self.location_id.id),
            ("company_id", "=", self.company_id.id),
        ])
        target = quants.sorted("quantity", reverse=True)[:1] or Quant.create({
            "product_id": line.product_id.id,
            "location_id": self.location_id.id,
        })
        before = self.env["stock.move"].search(
            [("is_inventory", "=", True), ("product_id", "=", line.product_id.id)]).ids
        target.inventory_quantity = target.quantity + line.qty_diff
        # Дата документа їде в нативне коригування: `stock_account` читає
        # `force_period_date` і ставить її своїй проводці оцінки запасів. Без цього
        # нативна проводка датувалася б сьогоднішнім днем, а наша 947 -> 719 - датою
        # опису, і два боки однієї операції розходилися б по періодах.
        target.with_context(force_period_date=self.date).action_apply_inventory()
        return self.env["stock.move"].search([
            ("is_inventory", "=", True),
            ("product_id", "=", line.product_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "done"),
            ("id", "not in", before),
        ])

    def action_apply(self):
        """Провести: коригування складу плюс проводка лишків 947 -> 719.

        Обидві проводки - нативна оцінка запасів і наша 947 -> 719 - датуються
        датою опису і проводяться одразу. Тому дата в майбутньому не приймається:
        запаси рахують у день підрахунку, а не наперед. Якби ми пустили майбутню
        дату, нативне мʼяке проведення відклало б свою проводку в чернетку з
        автопроведенням, а наша лягла б у книги вже сьогодні - і на рахунку 947
        висів би дебет без зустрічного кредиту 201.
        """
        for record in self:
            if record.state != "counting":
                raise UserError("Спершу заповніть опис залишками складу.")
            today = fields.Date.context_today(record)
            if record.date > today:
                raise UserError(
                    "Інвентаризацію «%s» датовано %s - цей день ще не настав. "
                    "Опис складають у день підрахунку: поставте дату не пізнішу "
                    "за %s." % (record.name,
                                record.date.strftime("%d.%m.%Y"),
                                today.strftime("%d.%m.%Y")))
            moves = self.env["stock.move"]
            for line in record.line_ids:
                if record.company_id.currency_id.is_zero(line.qty_diff):
                    continue
                moves |= record._apply_line(line)
            record.move_ids = [(6, 0, moves.ids)]
            record._post_surplus(moves)
            record.state = "done"
        return True

    def _post_surplus(self, moves):
        """Лишок - це дохід, а не менша нестача: 947 закриваємо, 719 кредитуємо.

        Сума береться з самих переміщень (`value`), тобто з того ж числа, яким
        нативна оцінка запасів дебетувала рахунок запасів. Підрахункова
        собівартість опису тут ні до чого: якщо вона розійшлася з обліковою,
        правду каже переміщення.
        """
        self.ensure_one()
        surplus = sum(
            move.value for move in moves
            if move.location_id.usage == "inventory" and move.value > 0)
        surplus = round(surplus, 2)
        if self.company_id.currency_id.is_zero(surplus):
            return self.env["account.move"]
        journal = self.company_id.account_stock_journal_id or self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.company_id.id)], limit=1)
        if not journal:
            raise UserError("Немає журналу для проводки лишків.")
        label = "Лишки інвентаризації %s" % self.name
        entry = self.env["account.move"].sudo().create({
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "date": self.date,
            "ref": label,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {"account_id": self._account(ACC_SHORTAGE).id,
                        "name": label, "balance": surplus}),
                (0, 0, {"account_id": self._account(ACC_SURPLUS).id,
                        "name": label, "balance": -surplus}),
            ],
        })
        entry.action_post()
        self.surplus_move_id = entry
        return entry

    def action_open_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Коригування залишків",
            "res_model": "stock.move",
            "domain": [("id", "in", self.move_ids.ids)],
            "view_mode": "list,form",
        }

    # ------------------------------------------------------------------
    # Дані для друку
    # ------------------------------------------------------------------
    def _lines_with_diff(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: not self.company_id.currency_id.is_zero(line.qty_diff))


class UaStockInventoryLine(models.Model):
    _name = "ua.stock.inventory.line"
    _description = "Рядок інвентаризації"
    _order = "id"

    inventory_id = fields.Many2one("ua.stock.inventory", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="inventory_id.company_id", store=True)
    currency_id = fields.Many2one(related="inventory_id.currency_id")
    product_id = fields.Many2one("product.product", string="Номенклатура", required=True)
    uom_id = fields.Many2one(related="product_id.uom_id", string="Од.")
    qty_book = fields.Float("За обліком", digits="Product Unit of Measure")
    qty_fact = fields.Float("Фактично", digits="Product Unit of Measure")
    qty_diff = fields.Float(
        "Різниця", compute="_compute_diff", store=True, digits="Product Unit of Measure")
    cost = fields.Float(
        "Облікова ціна",
        help="Оцінка одиниці на момент заповнення опису.")
    amount_diff = fields.Monetary(
        "Сума різниці", currency_field="currency_id", compute="_compute_diff", store=True,
        help="Більше нуля - лишок (Кт 719), менше - нестача (Дт 947).")

    @api.depends("qty_book", "qty_fact", "cost")
    def _compute_diff(self):
        for line in self:
            line.qty_diff = line.qty_fact - line.qty_book
            line.amount_diff = round(line.qty_diff * line.cost, 2)
