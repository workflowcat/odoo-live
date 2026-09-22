# -*- coding: utf-8 -*-
"""Акт приймання-передачі ТМЦ із готової доставки.

Доставка вже вміє друкуватися видатковою накладною і ТТН - це робить
`l10n_ua_docs_stock` через домішок `ua.docs.source`. Акт приймання-передачі
потрібен там, де накладної замало: передача матеріалів у переробку, повернення
обладнання, передача цінностей матеріально відповідальній особі. Форма та сама,
підписи інші: «передав» і «прийняв», а не «відпустив» і «одержав».

Даних понад ті, що вже дає домішок, майже не треба - лише хто передав і хто
прийняв, коли це не керівники сторін.
"""
from odoo import fields, models


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
