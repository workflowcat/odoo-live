#!/usr/bin/env python3
"""Створює модуль пакета команди: каркас, який одразу встановлюється і проходить перевірки.

    python3 scripts/new_pack.py acme_pack --title "Acme: склад запчастин" --industry trade
    python3 scripts/new_pack.py acme_pack --pack acme_parts --requires stock,mrp --dest ../acme-addons

Що виходить (docs/customization.md, «Пакет команди»):

    <dest>/<module>/
      __manifest__.py        залежить від l10n_ua_catalog і того, що в --requires
      catalog/<pack>.json    одна категорія і один товар - замініть своїми
      tests/test_pack.py     пакет завантажується і повторне завантаження нічого не створює
      README.md              що це і як оновлювати

Далі: заповнити JSON, `python3 scripts/catalog_check.py <шлях до json>`, встановити модуль,
у Налаштуваннях відкрити «Галузеві каталоги» і завантажити пакет у компанію.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
INDUSTRIES = ("defense", "manufacturing", "procurement", "retail", "services", "trade", "other")

MANIFEST = '''{{
    "name": {title},
    "summary": "Пакет команди: довідники і налаштування поверх odoo-live",
    "version": "19.0.1.0.0",
    "category": "Productivity",
    "author": {author},
    "license": "LGPL-3",
    "depends": {depends},
    "data": [],
    "installable": True,
}}
'''

TEST = '''"""Пакет {pack} завантажується, а повторне завантаження нічого не створює."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "{module}")
class TestPack(TransactionCase):

    def test_pack_loads_and_reloads(self):
        catalog = self.env["ua.catalog"]
        self.assertIn("{pack}", catalog._ua_packs())
        first = catalog._ua_load_pack("{pack}", self.env.company)
        self.assertTrue(first.get("products"), first)
        second = catalog._ua_load_pack("{pack}", self.env.company)
        for section, actions in second.items():
            if isinstance(actions, dict):
                self.assertNotIn("created", actions, section)
'''

README = '''# {title}

Пакет команди поверх odoo-live: довідники в `catalog/{pack}.json`, власні поля, друковані форми і
правила - у цьому модулі, ядро і OCA не змінюються. Правила - `docs/customization.md` в odoo-live.

- Перевірка без бази: `python3 scripts/catalog_check.py {rel_json}`
- Завантаження: Налаштування - Галузеві каталоги - «{title}» - компанія - Завантажити.
- Оновлення пакета: змініть JSON, оновіть модуль, завантажте ще раз у режимі «Оновити раніше
  завантажене». Ключі (`key`) не перейменовуйте: за ними завантажувач знаходить свої записи.
'''


def skeleton(pack, title, industry, requires):
    return {
        "schema": 1,
        "pack": pack,
        "name": title,
        "summary": "Стартові довідники команди. Опишіть, для кого пакет і що в ньому.",
        "industry": industry,
        "requires": requires,
        "sources": [],
        "notes": ["Ціни і норми - орієнтир, замініть своїми."],
        "categories": [
            {"key": "c_root", "name": title},
        ],
        "products": [
            {"key": "example", "code": "%s-001" % pack[:6].upper(), "name": "Приклад товару",
             "category": "@c_root", "uom": "шт", "cost": 100, "price": 150},
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Новий модуль пакета команди.")
    parser.add_argument("module", help="технічна назва модуля, напр. acme_pack")
    parser.add_argument("--pack", help="id пакета (типово - назва модуля)")
    parser.add_argument("--title", help="назва пакета українською")
    parser.add_argument("--industry", default="other", choices=INDUSTRIES)
    parser.add_argument("--requires", default="stock",
                        help="модулі Odoo через кому, напр. stock,mrp,purchase")
    parser.add_argument("--author", default="Team")
    parser.add_argument("--dest", default=os.path.join(ROOT, "addons"),
                        help="тека addons, куди покласти модуль")
    args = parser.parse_args(argv)

    pack = args.pack or args.module
    for value, what in ((args.module, "назва модуля"), (pack, "id пакета")):
        if not MODULE.match(value):
            parser.error("%s «%s»: лише a-z, 0-9 і _, від 3 символів" % (what, value))
    if args.module.startswith(("l10n_ua_", "bp_")):
        parser.error("префікси l10n_ua_ і bp_ належать ядру; візьміть назву команди")
    title = args.title or pack.replace("_", " ").capitalize()
    requires = [m.strip() for m in args.requires.split(",") if m.strip()]
    path = os.path.join(os.path.abspath(args.dest), args.module)
    if os.path.exists(path):
        parser.error("%s уже існує" % path)

    os.makedirs(os.path.join(path, "catalog"))
    os.makedirs(os.path.join(path, "tests"))
    depends = ["l10n_ua_catalog"] + [m for m in requires if m != "l10n_ua_catalog"]
    files = {
        "__init__.py": "",
        "__manifest__.py": MANIFEST.format(
            title=json.dumps(title, ensure_ascii=False),
            author=json.dumps(args.author, ensure_ascii=False),
            depends=json.dumps(depends)),
        "tests/__init__.py": "from . import test_pack\n",
        "tests/test_pack.py": TEST.format(pack=pack, module=args.module),
        "catalog/%s.json" % pack: json.dumps(skeleton(pack, title, args.industry, requires),
                                             ensure_ascii=False, indent=2) + "\n",
    }
    rel_json = os.path.relpath(os.path.join(path, "catalog", pack + ".json"), ROOT)
    files["README.md"] = README.format(title=title, pack=pack, rel_json=rel_json)
    for name, text in files.items():
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    print("Створено %s" % os.path.relpath(path, os.getcwd()))
    print("Далі: заповніть %s і запустіть python3 scripts/catalog_check.py %s" % (rel_json, rel_json))
    print("Тег тестів: %s" % args.module)
    return 0


if __name__ == "__main__":
    sys.exit(main())
