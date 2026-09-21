"""Вивантаження регістрів у xlsx на базі OCA report_xlsx.

Один невеликий клас на регістр: шапка, колонки, рядки, підсумок. Числа вже
пораховані моделлю регістру, тут лише розкладка по клітинках.
"""
from odoo import models

MONEY = "#,##0.00"


class UaLedgerXlsxAbstract(models.AbstractModel):
    _name = "report.l10n_ua_ledger.abstract_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Регістри головної книги: спільне для xlsx"

    def _formats(self, workbook):
        return {
            "title": workbook.add_format({"bold": True, "font_size": 13}),
            "head": workbook.add_format({"bold": True, "border": 1, "align": "center",
                                         "valign": "vcenter", "text_wrap": True}),
            "text": workbook.add_format({"border": 1}),
            "money": workbook.add_format({"border": 1, "num_format": MONEY}),
            "total": workbook.add_format({"bold": True, "border": 1}),
            "total_money": workbook.add_format({"bold": True, "border": 1, "num_format": MONEY}),
        }

    def _write_header(self, sheet, styles, title, report, columns):
        sheet.write(0, 0, title, styles["title"])
        sheet.write(
            1, 0,
            "%s, період з %s по %s"
            % (report.company_id.name, report.date_from, report.date_to),
        )
        for index, (header, width) in enumerate(columns):
            sheet.set_column(index, index, width)
            sheet.write(3, index, header, styles["head"])
        return 4


class UaOsvXlsx(models.AbstractModel):
    _name = "report.l10n_ua_ledger.ua_osv_xlsx"
    _inherit = "report.l10n_ua_ledger.abstract_xlsx"
    _description = "Оборотно-сальдова відомість, xlsx"

    def generate_xlsx_report(self, workbook, data, reports):
        styles = self._formats(workbook)
        for report in reports:
            sheet = workbook.add_worksheet("ОСВ")
            columns = [
                ("Код", 10), ("Рахунок", 45),
                ("Сальдо на початок, Дт", 18), ("Сальдо на початок, Кт", 18),
                ("Оборот Дт", 16), ("Оборот Кт", 16),
                ("Сальдо на кінець, Дт", 18), ("Сальдо на кінець, Кт", 18),
            ]
            row = self._write_header(sheet, styles, "Оборотно-сальдова відомість", report, columns)
            for line in report.line_ids:
                sheet.write(row, 0, line.code or "", styles["text"])
                sheet.write(row, 1, line.name or "", styles["text"])
                for index, value in enumerate(
                    (line.open_debit, line.open_credit, line.debit,
                     line.credit, line.close_debit, line.close_credit), start=2
                ):
                    sheet.write(row, index, value, styles["money"])
                row += 1
            sheet.write(row, 0, "Разом", styles["total"])
            sheet.write(row, 1, "", styles["total"])
            for index, value in enumerate(
                (report.total_open_debit, report.total_open_credit,
                 report.total_debit, report.total_credit,
                 report.total_close_debit, report.total_close_credit), start=2
            ):
                sheet.write(row, index, value, styles["total_money"])
            sheet.write(
                row + 2, 0,
                "Контроль подвійного запису: "
                + ("оборот Дт = оборот Кт" if report.control_ok else "оборот Дт не дорівнює Кт"),
            )


class UaAccountCardXlsx(models.AbstractModel):
    _name = "report.l10n_ua_ledger.ua_account_card_xlsx"
    _inherit = "report.l10n_ua_ledger.abstract_xlsx"
    _description = "Картка рахунку, xlsx"

    def generate_xlsx_report(self, workbook, data, reports):
        styles = self._formats(workbook)
        for report in reports:
            sheet = workbook.add_worksheet("Картка рахунку")
            columns = [
                ("Дата", 12), ("Документ", 20), ("Підстава", 28), ("Партнер", 24),
                ("Зміст", 28), ("Кор. рахунок", 14),
                ("Дт", 14), ("Кт", 14), ("Сальдо", 16),
            ]
            title = "Картка рахунку %s %s" % (
                report._acc_code(report.account_id), report.account_id.name or ""
            )
            row = self._write_header(sheet, styles, title, report, columns)
            sheet.write(row, 0, "Сальдо на початок", styles["total"])
            for index in range(1, 8):
                sheet.write(row, index, "", styles["total"])
            sheet.write(row, 8, report.opening_balance, styles["total_money"])
            row += 1
            for line in report.line_ids:
                for index, value in enumerate((
                    str(line.date or ""), line.move_name or "", line.ref or "",
                    line.partner_name or "", line.label or "", line.counterpart or "",
                )):
                    sheet.write(row, index, value, styles["text"])
                sheet.write(row, 6, line.debit, styles["money"])
                sheet.write(row, 7, line.credit, styles["money"])
                sheet.write(row, 8, line.balance, styles["money"])
                row += 1
            sheet.write(row, 0, "Оборот за період", styles["total"])
            for index in range(1, 6):
                sheet.write(row, index, "", styles["total"])
            sheet.write(row, 6, report.total_debit, styles["total_money"])
            sheet.write(row, 7, report.total_credit, styles["total_money"])
            sheet.write(row, 8, report.closing_balance, styles["total_money"])


class UaAccountAnalysisXlsx(models.AbstractModel):
    _name = "report.l10n_ua_ledger.ua_account_analysis_xlsx"
    _inherit = "report.l10n_ua_ledger.abstract_xlsx"
    _description = "Аналіз рахунку, xlsx"

    def generate_xlsx_report(self, workbook, data, reports):
        styles = self._formats(workbook)
        for report in reports:
            sheet = workbook.add_worksheet("Аналіз рахунку")
            columns = [
                ("Кор. рахунок", 14), ("Назва", 45),
                ("Дт наш - Кт кор.", 18), ("Кт наш - Дт кор.", 18),
            ]
            title = "Аналіз рахунку %s %s" % (
                report._acc_code(report.account_id), report.account_id.name or ""
            )
            row = self._write_header(sheet, styles, title, report, columns)
            for line in report.line_ids:
                sheet.write(row, 0, line.corr_code or "", styles["text"])
                sheet.write(row, 1, line.corr_name or "", styles["text"])
                sheet.write(row, 2, line.debit, styles["money"])
                sheet.write(row, 3, line.credit, styles["money"])
                row += 1
            sheet.write(row, 0, "Разом", styles["total"])
            sheet.write(row, 1, "", styles["total"])
            sheet.write(row, 2, report.total_debit, styles["total_money"])
            sheet.write(row, 3, report.total_credit, styles["total_money"])
