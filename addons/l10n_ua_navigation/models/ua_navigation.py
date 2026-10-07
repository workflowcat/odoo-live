# -*- coding: utf-8 -*-
from odoo import api, models


class UaNavigation(models.AbstractModel):
    """Точка входу для data/apply.xml: перейменування і слова застосовуються не лише
    на встановлення, а й на кожне оновлення модуля."""
    _name = "ua.navigation"
    _description = "Навігація продукту: назви, слова, місце пунктів меню"

    @api.model
    def apply(self):
        from ..hooks import apply_navigation
        apply_navigation(self.env)
        return True
