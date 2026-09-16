# -*- coding: utf-8 -*-
"""Категорії обліку звужено до офіційних двох, як у l10n_ua_military: старі значення "sergeants"
і "soldiers" на картці справи прийняття зливаються в "ranks"."""


def migrate(cr, version):
    cr.execute("""
        UPDATE ua_hire_case SET mil_category = 'ranks'
        WHERE mil_category IN ('sergeants', 'soldiers')
    """)
