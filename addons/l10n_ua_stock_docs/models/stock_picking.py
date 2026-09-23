# -*- coding: utf-8 -*-
"""Акт приймання-передачі ТМЦ із готової доставки.

Доставка вже вміє друкуватися видатковою накладною і ТТН - це робить
`l10n_ua_docs_stock` через домішок `ua.docs.source`. Акт приймання-передачі
потрібен там, де накладної замало: передача матеріалів у переробку, повернення
обладнання, передача цінностей матеріально відповідальній особі. Форма та сама,
підписи інші: «передав» і «прийняв», а не «відпустив» і «одержав».

Даних понад ті, що вже дає домішок, майже не треба - лише хто передав і хто
прийняв, коли це не керівники сторін.

Друге, що тут живе, з паперу не випливає: мітка операції зовнішнього клієнта.
Складський екран поза Odoo робить приймання і переміщення тими самими трьома
дієсловами, що й інвентаризація, і так само не має права записати документ
двічі після обриву звʼязку. Тому на доставці є `ua_client_ref` і
`ua_get_or_create` - рівно той механізм, що вже стоїть на `ua.stock.inventory`.
Мітку клієнт раніше ліпив у `origin` (`WEB/<opId>`), але `origin` це підстава
документа, він не унікальний і в нього пишуть люди.

Третє - сума документа для журналу. Нативна доставка грошей не знає: ціни живуть
у закупівлі й продажу, а оцінку несе рух (`stock.move.value`). Журнал складу
(«Надходження» у вигляді 1С) хоче колонку «Сума», тому `ua_amount` - сума рядків
за собівартістю: проведений рух дає свою оцінку (`value`), непроведений -
кількість × облікову ціну товару в компанії документа. Поле не зберігається:
облікова ціна змінюється, і збережене число застаріло б. Відповідальний - нативне
`user_id`, свого поля не треба.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ua_act_handover = fields.Char(
        "Передав (ПІБ, посада)",
        help="Хто передає цінності. Порожньо - в акті друкується підписант компанії.")
    ua_act_receiver = fields.Char(
        "Прийняв (ПІБ, посада)",
        help="Хто приймає цінності. Порожньо - в акті друкується підписант контрагента.")
    ua_act_condition = fields.Char(
        "Стан цінностей",
        help="Рядок, що друкується в акті: «у справному стані», «з дефектами» тощо.")
    ua_client_ref = fields.Char(
        "Мітка операції", index=True, copy=False,
        help="Мітка зовнішнього клієнта. Не повторюється в межах компанії: "
             "повторне створення з тією самою міткою віддає ту саму доставку.")

    ua_amount = fields.Float(
        "Сума за собівартістю", digits=(16, 2), compute="_compute_ua_amount",
        help="Проведений рух - його оцінка, непроведений - кількість × облікова ціна "
             "товару. Скасовані рядки не рахуються.")

    _ua_client_ref_unique = models.Constraint(
        "UNIQUE(company_id, ua_client_ref)",
        "Доставка з такою міткою операції в цій компанії вже є.",
    )

    @api.depends("move_ids.state", "move_ids.quantity", "move_ids.product_uom_qty",
                 "move_ids.value")
    def _compute_ua_amount(self):
        for picking in self:
            total = 0.0
            for move in picking.move_ids:
                if move.state == "cancel":
                    continue
                if move.state == "done" and move.value:
                    total += abs(move.value)
                    continue
                quantity = move.quantity or move.product_uom_qty
                in_product_uom = move.product_uom._compute_quantity(
                    quantity, move.product_id.uom_id, round=False)
                price = move.product_id.with_company(picking.company_id).standard_price
                total += in_product_uom * price
            picking.ua_amount = round(total, 2)

    @api.model
    def ua_get_or_create(self, client_ref, vals=None):
        """Доставка за міткою клієнта: є - віддаємо, немає - створюємо.

        Захист від подвійного запису при обриві звʼязку. Другий виклик із тією
        самою міткою повертає першу доставку і НЕ чіпає її вміст: клієнт
        повторює запит, а не переписує вже прийнятий товар.

        Компанію у значення не дописуємо: на `stock.picking` `company_id` - збережене
        `related` від виду документа, і правду про компанію каже
        `picking_type_id`. Тому нею ж і шукаємо; без виду документа беремо
        компанію викликача.
        """
        if not client_ref:
            raise UserError("Без мітки операції доставка не створюється.")
        values = dict(vals or {})
        company_id = False
        if values.get("picking_type_id"):
            company_id = self.env["stock.picking.type"].browse(
                values["picking_type_id"]).company_id.id
        company_id = company_id or values.get("company_id") or self.env.company.id
        existing = self.search([
            ("ua_client_ref", "=", client_ref),
            ("company_id", "=", company_id),
        ], limit=1)
        if existing:
            return existing
        values["ua_client_ref"] = client_ref
        return self.create(values)

    def _ua_act_parties(self):
        """Підписанти акта: свої поля, а якщо порожні - підписанти сторін."""
        self.ensure_one()
        seller = self._ua_docs_seller()
        buyer = self._ua_docs_buyer()
        return {
            "handover": self.ua_act_handover or seller["director"] or "",
            "receiver": self.ua_act_receiver or buyer["director"] or "",
            "condition": self.ua_act_condition or "у справному стані",
        }
