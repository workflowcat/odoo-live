# -*- coding: utf-8 -*-
"""Категорії обліку звужено до офіційних двох (офіцерський склад / рядовий, сержантський і старшинський
склад): старі значення "sergeants" і "soldiers" зливаються в "ranks", "officers" лишається без змін.

Список персонального обліку тепер веде поле tcc (required): старі документи без нього (до розбивки по
ТЦК) отримують ТЦК за найпоширенішим значенням серед власних рядків, інакше - позначку "?"."""


def migrate(cr, version):
    cr.execute("""
        UPDATE hr_employee SET ua_mil_category = 'ranks'
        WHERE ua_mil_category IN ('sergeants', 'soldiers')
    """)
    cr.execute("""
        UPDATE ua_military_list l SET tcc = COALESCE((
            SELECT ln.tcc FROM ua_military_list_line ln
            WHERE ln.list_id = l.id AND ln.tcc IS NOT NULL AND ln.tcc != ''
            GROUP BY ln.tcc ORDER BY count(*) DESC LIMIT 1
        ), '?')
        WHERE l.tcc IS NULL
    """)
