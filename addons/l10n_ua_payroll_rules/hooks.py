# -*- coding: utf-8 -*-
"""Українська мова має бути активною до того, як щось напише with_context(lang='uk_UA').

На порожній базі Odoo ставиться англійською, і uk_UA лежить у res.lang вимкненою.
Перший же гачок, який пише українську назву («Invalid language code: uk_UA»), падає.
Тому вмикаємо мову в найнижчому модулі зарплатного ланцюга: усе, що ставиться після
l10n_ua_payroll_rules, вже застає її активною. План рахунків (l10n_ua_chart) стоїть
в іншій гілці графа і вмикає її в себе так само.
"""
import logging

_logger = logging.getLogger(__name__)

UK = "uk_UA"


def ensure_uk_lang(env):
    """Увімкнути uk_UA разом із перекладами. Повертає запис res.lang або порожній набір."""
    Lang = env["res.lang"].with_context(active_test=False)
    lang = Lang.search([("code", "=", UK)], limit=1)
    if not lang or lang.active:
        return lang
    try:
        env["base.language.install"].create({
            "lang_ids": [(6, 0, lang.ids)], "overwrite": False,
        }).lang_install()
    except Exception as error:   # переклади недоступні - достатньо самої мови
        _logger.warning("Не вдалося завантажити переклади uk_UA (%s); вмикаємо мову без них", error)
        env["res.lang"]._activate_lang(UK)
    return Lang.search([("code", "=", UK)], limit=1)


def post_init_hook(env):
    ensure_uk_lang(env)
