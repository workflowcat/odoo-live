"""Перенесення даних з 1С/BAS у Odoo.

Що робить нативний Odoo і ми не переписуємо:
- читання CSV і XLSX, зіставлення колонок з полями, створення і оновлення
  записів - це base_import, «Імпорт» у будь-якому списку;
- початкові сальдо - це нативна початкова проводка компанії
  (res.company._update_opening_move): Odoo сам тримає її в чернетці, сам
  балансує різницю на рахунок нерозподіленого прибутку і сам не дає
  зіпсувати вже проведену проводку.

Що додаємо ми, бо в base_import цього немає:
- автовизначення колонок за заголовками 1С/BAS українською і російською
  («Код по ЕДРПОУ», «Наименование», «Остаток»);
- зіставлення номера рахунку 1С з кодом плану: у вивантаженні буває 361 або
  3611, у плані ПСБО код доповнений нулями до 361000;
- контроль Дт = Кт до створення проводки;
- пробний прогін: показує той самий звіт, але не записує нічого.
"""
import base64
import csv
import io
import re
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

# Для кожного типу імпорту: (ключ поля, [підрядки заголовка]).
# Пошук - підрядок без урахування регістру; перший збіг перемагає, зайнята
# колонка вдруге не призначається. Порядок ключів важливий: вужчі поля йдуть
# раніше, щоб «код» (артикул) не забрав колонку «Код по ЕДРПОУ» чи «Штрихкод».
HEADER_MAP = {
    "partners": [
        ("edrpou", ["едрпоу", "єдрпоу", "окпо", "код по едрпоу"]),
        ("ipn", ["іпн", "ипн", "инн", "пдв"]),
        ("name", ["наименование", "назва", "найменування", "контрагент"]),
        ("email", ["почта", "пошта", "email", "e-mail"]),
        ("phone", ["телефон", "тел"]),
        ("street", ["адрес", "адреса"]),
        ("city", ["город", "місто"]),
    ],
    "products": [
        ("barcode", ["штрихкод", "штрих-код", "barcode"]),
        ("cost", ["себестоимость", "собівартість", "закупочная", "закупівельна"]),
        ("price", ["цена", "ціна"]),
        ("uom", ["ед. изм", "од. вим", "одиниця", "единица"]),
        ("name", ["наименование", "назва", "номенклатура"]),
        ("code", ["артикул", "код"]),
    ],
    "balances": [
        ("account", ["счет", "рахунок", "счёт"]),
        ("debit", ["дебет", "дт"]),
        ("credit", ["кредит", "кт"]),
    ],
}

# Обов'язкові поля: хоча б одне з кожної групи.
REQUIRED_MAP = {
    "partners": [("name", "edrpou")],
    "products": [("name", "code")],
    "balances": [("account",), ("debit", "credit")],
}


class _DryRunDone(Exception):
    """Службовий сигнал: пробний прогін дійшов до кінця, транзакцію відкотити."""


class UaMigrate(models.TransientModel):
    _name = "ua.migrate"
    _description = "Перенесення з 1С/BAS"

    import_type = fields.Selection(
        [
            ("partners", "Контрагенти"),
            ("products", "Номенклатура"),
            ("balances", "Початкові сальдо"),
        ],
        "Що переносимо", required=True, default="partners",
    )
    data_file = fields.Binary("Файл CSV або XLSX", required=True)
    data_filename = fields.Char("Імʼя файлу")
    dry_run = fields.Boolean(
        "Пробний прогін", default=True,
        help="Показати, що вийде, і нічого не записати.",
    )
    date_opening = fields.Date(
        "Сальдо на дату",
        default=lambda self: date(fields.Date.context_today(self).year, 1, 1),
        help="Дата, на яку взяті залишки. Нативна початкова проводка Odoo "
             "отримує попередній день: сальдо на 1 січня - це проводка 31 грудня.",
    )
    allow_unbalanced = fields.Boolean(
        "Дозволити небаланс",
        help="Якщо Дт не дорівнює Кт, різницю нативний Odoo відносить на "
             "рахунок нерозподіленого прибутку. Без цього прапорця такий "
             "файл не приймається.",
    )
    state = fields.Selection(
        [("draft", "Завантаження"), ("done", "Готово")], "Стан", default="draft",
    )
    result_html = fields.Html("Звіт", readonly=True)

    # ------------------------------------------------------------------
    # Читання файлу
    # ------------------------------------------------------------------
    @api.model
    def _decode(self, raw):
        """Байти CSV у текст: спершу utf-8 (з BOM), фолбек cp1251 - так вивантажує 1С."""
        for encoding in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UserError("Не вдалося прочитати файл: невідоме кодування.")

    @api.model
    def _delimiter(self, text):
        """Роздільник: ';' (звичайний для 1С), ',' або табуляція."""
        sample = text[:4096]
        try:
            return csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
        except csv.Error:
            first = sample.splitlines()[0] if sample.splitlines() else ""
            if ";" in first:
                return ";"
            if "\t" in first:
                return "\t"
            return ","

    @api.model
    def _amount(self, raw):
        """Число: кома як десятковий роздільник, пробіли і нерозривні пробіли в тисячах.

        Якщо є і кома, і крапка - десятковим вважаємо останній знак.
        """
        txt = str(raw or "").strip().replace("\xa0", "").replace(" ", "")
        if not txt:
            return 0.0
        if "," in txt and "." in txt:
            if txt.rfind(",") > txt.rfind("."):
                txt = txt.replace(".", "").replace(",", ".")
            else:
                txt = txt.replace(",", "")
        else:
            txt = txt.replace(",", ".")
        try:
            return float(txt)
        except ValueError:
            raise UserError("Не число: «%s»" % raw) from None

    def _rows_from_file(self):
        """Файл у список рядків (списків рядкових значень)."""
        raw = base64.b64decode(self.data_file)
        name = (self.data_filename or "").lower()
        if name.endswith((".xlsx", ".xlsm")):
            return self._rows_from_xlsx(raw)
        text = self._decode(raw)
        reader = csv.reader(io.StringIO(text), delimiter=self._delimiter(text))
        return [[(c or "").strip() for c in row] for row in reader]

    @api.model
    def _rows_from_xlsx(self, raw):
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = book[book.sheetnames[0]]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if cell is None else str(cell).strip() for cell in row])
        book.close()
        return rows

    def _read(self):
        """(мапа поле → індекс колонки, рядки даних без заголовка)."""
        rows = [r for r in self._rows_from_file() if any((c or "").strip() for c in r)]
        if not rows:
            raise UserError("Файл порожній або жодного рядка не розпізнано.")
        header = [(c or "").strip().lower() for c in rows[0]]
        colmap, taken = {}, set()
        for key, needles in HEADER_MAP[self.import_type]:
            for idx, title in enumerate(header):
                if idx in taken:
                    continue
                if any(n in title for n in needles):
                    colmap[key] = idx
                    taken.add(idx)
                    break
        for group in REQUIRED_MAP[self.import_type]:
            if not any(k in colmap for k in group):
                raise UserError(
                    "Не знайдено колонку для «%s». Заголовок файлу: %s"
                    % (" / ".join(group), ", ".join(header)))
        return colmap, rows[1:]

    @staticmethod
    def _cell(row, colmap, key):
        idx = colmap.get(key)
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    # ------------------------------------------------------------------
    # Зіставлення номера рахунку 1С з кодом плану
    # ------------------------------------------------------------------
    def _account_index(self):
        """Коди плану компанії: {код: рахунок} плюс довжини кодів, які трапляються."""
        accounts = self.env["account.account"].with_company(self.env.company).search(
            [("company_ids", "in", self.env.company.id)])
        by_code = {acc.code: acc for acc in accounts if acc.code}
        widths = sorted({len(code) for code in by_code}, reverse=True)
        return by_code, widths

    @staticmethod
    def _match_account(raw_code, by_code, widths):
        """«361», «3611», «361000» → рахунок плану.

        Спершу пробуємо код як є, потім доповнений нулями до довжини, яка
        трапляється в плані, потім те саме для щоразу коротшого префікса.
        Так вивантаження з субрахунком 3611 знаходить 361000, якщо окремого
        субрахунку в плані немає.
        """
        digits = re.sub(r"\D", "", raw_code or "")
        if not digits:
            return None
        for length in range(len(digits), 0, -1):
            prefix = digits[:length]
            if prefix in by_code:
                return by_code[prefix]
            for width in widths:
                if len(prefix) < width and prefix.ljust(width, "0") in by_code:
                    return by_code[prefix.ljust(width, "0")]
        return None

    # ------------------------------------------------------------------
    # Звіт
    # ------------------------------------------------------------------
    @staticmethod
    def _line(mark, text, hint=""):
        tail = " - %s" % html_escape(hint) if hint else ""
        return "<div>%s %s%s</div>" % (mark, html_escape(text), tail)

    # ------------------------------------------------------------------
    # Контрагенти
    # ------------------------------------------------------------------
    def _do_partners(self, colmap, rows, counters, report):
        Partner = self.env["res.partner"]
        for line_no, row in enumerate(rows, start=2):
            name = self._cell(row, colmap, "name")
            edrpou = re.sub(r"\s", "", self._cell(row, colmap, "edrpou"))
            if not name and not edrpou:
                counters["skipped"] += 1
                report.append(self._line("×", "рядок %d" % line_no, "немає ні назви, ні ЄДРПОУ"))
                continue
            partner = Partner.browse()
            if edrpou:
                partner = Partner.search([("company_registry", "=", edrpou)], limit=1)
            if not partner and name:
                partner = Partner.search([("name", "=ilike", name)], limit=1)
            vals = {}
            for key, fname in (("ipn", "vat"), ("phone", "phone"), ("email", "email"),
                               ("street", "street"), ("city", "city")):
                value = self._cell(row, colmap, key)
                if value:
                    vals[fname] = value
            if edrpou:
                vals["company_registry"] = edrpou
            if partner:
                partner.write(vals)
                counters["updated"] += 1
                report.append(self._line("=", partner.display_name, "оновлено"))
            else:
                vals.update({"name": name or ("ЄДРПОУ %s" % edrpou), "is_company": True})
                partner = Partner.create(vals)
                counters["created"] += 1
                report.append(self._line("+", partner.display_name, "створено"))

    # ------------------------------------------------------------------
    # Номенклатура
    # ------------------------------------------------------------------
    def _do_products(self, colmap, rows, counters, report):
        Product = self.env["product.product"]
        for line_no, row in enumerate(rows, start=2):
            name = self._cell(row, colmap, "name")
            code = self._cell(row, colmap, "code")
            if not name and not code:
                counters["skipped"] += 1
                report.append(self._line("×", "рядок %d" % line_no, "немає ні назви, ні артикулу"))
                continue
            price = self._amount(self._cell(row, colmap, "price"))
            cost = self._amount(self._cell(row, colmap, "cost"))
            product = Product.browse()
            if code:
                product = Product.search([("default_code", "=", code)], limit=1)
            if not product and name:
                product = Product.search([("name", "=ilike", name)], limit=1)
            if product:
                vals = {}
                if price:
                    vals["list_price"] = price
                if cost:
                    vals["standard_price"] = cost
                if vals:
                    product.write(vals)
                counters["updated"] += 1
                report.append(self._line("=", product.display_name, "оновлено"))
            else:
                vals = {
                    "name": name or code,
                    "default_code": code or False,
                    "type": "consu",
                    "list_price": price,
                    "standard_price": cost,
                    "sale_ok": price > 0,
                    "purchase_ok": cost > 0,
                }
                barcode = self._cell(row, colmap, "barcode")
                if barcode:
                    vals["barcode"] = barcode
                product = Product.create(vals)
                counters["created"] += 1
                report.append(self._line("+", product.display_name, "створено"))

    # ------------------------------------------------------------------
    # Початкові сальдо
    # ------------------------------------------------------------------
    def _do_balances(self, colmap, rows, counters, report):
        company = self.env.company
        by_code, widths = self._account_index()
        if not by_code:
            raise UserError(
                "У компанії %s немає плану рахунків - спершу встановіть його."
                % company.display_name)
        to_update, total_debit, total_credit = {}, 0.0, 0.0
        for line_no, row in enumerate(rows, start=2):
            raw_code = self._cell(row, colmap, "account")
            if not raw_code:
                counters["skipped"] += 1
                report.append(self._line("×", "рядок %d" % line_no, "порожній номер рахунку"))
                continue
            debit = self._amount(self._cell(row, colmap, "debit"))
            credit = self._amount(self._cell(row, colmap, "credit"))
            if not debit and not credit:
                counters["skipped"] += 1
                report.append(self._line("×", "рядок %d" % line_no, "нульові дебет і кредит"))
                continue
            account = self._match_account(raw_code, by_code, widths)
            if not account:
                counters["skipped"] += 1
                report.append(self._line(
                    "×", "рядок %d: рахунок %s" % (line_no, raw_code), "немає в плані"))
                continue
            prev_debit, prev_credit = to_update.get(account, (0.0, 0.0))
            to_update[account] = (prev_debit + debit, prev_credit + credit)
            total_debit += debit
            total_credit += credit
            counters["created"] += 1
            report.append(self._line(
                "+", "%s %s" % (account.code, account.name),
                "Дт %.2f / Кт %.2f" % (debit, credit)))
        if not to_update:
            raise UserError("Жодного рядка сальдо не розпізнано - проводку не створено.")
        diff = round(total_debit - total_credit, 2)
        report.append(self._line(
            "Σ", "разом", "Дт %.2f / Кт %.2f, різниця %.2f" % (total_debit, total_credit, diff)))
        if abs(diff) >= 0.01 and not self.allow_unbalanced:
            raise UserError(
                "Сальдо не збалансоване: Дт %.2f, Кт %.2f, різниця %.2f. "
                "Перевірте вивантаження або поставте «Дозволити небаланс» - "
                "тоді різницю буде віднесено на нерозподілений прибуток."
                % (total_debit, total_credit, diff))
        company.account_opening_date = self.date_opening
        company._update_opening_move({acc: vals for acc, vals in to_update.items()})
        move = company.account_opening_move_id
        report.append(self._line(
            "→", move.name or "Початкова проводка",
            "нативна початкова проводка компанії від %s, у чернетці" % move.date))

    # ------------------------------------------------------------------
    # Дія
    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        if not self.data_file:
            raise UserError("Завантажте файл.")
        colmap, rows = self._read()
        counters = {"created": 0, "updated": 0, "skipped": 0}
        report = []
        handler = {
            "partners": self._do_partners,
            "products": self._do_products,
            "balances": self._do_balances,
        }[self.import_type]
        if self.dry_run:
            # Пробний прогін: робимо все по-справжньому і відкочуємо.
            try:
                with self.env.cr.savepoint():
                    handler(colmap, rows, counters, report)
                    raise _DryRunDone()
            except _DryRunDone:
                pass
        else:
            handler(colmap, rows, counters, report)

        label = dict(self._fields["import_type"].selection)[self.import_type]
        head = "<p><b>%s%s: рядків %d.</b><br/>створено %d, оновлено %d, пропущено %d</p>" % (
            html_escape(label),
            " (пробний прогін, нічого не записано)" if self.dry_run else "",
            sum(counters.values()), counters["created"], counters["updated"], counters["skipped"])
        shown = report[:60]
        if len(report) > 60:
            shown.append("<p>… та ще %d рядків.</p>" % (len(report) - 60))
        self.write({"result_html": head + "".join(shown), "state": "done"})
        return {
            "type": "ir.actions.act_window",
            "name": "Перенесення з 1С",
            "res_model": "ua.migrate",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
