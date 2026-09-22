# -*- coding: utf-8 -*-
"""Перегляд документів і друк браузером.

Один маршрут на один документ і на пакет. Кожен документ рендериться наявним
шаблоном QWeb у HTML, тіла складаються в одну сторінку. Друк і збереження в PDF
робить браузер: вікна Odoo зі звітом і окремого завантаження немає.

Орієнтацію сторінки беремо з налаштувань звіту. Браузер її не знає, тому кожна
частина пакета отримує іменовану сторінку CSS: інакше альбомний табель П-5
друкується книжковим і втрачає праві колонки.
"""
import json
import re

from lxml import html as lxml_html
from markupsafe import Markup, escape

from odoo import http
from odoo.http import request

DRAFT_STATES = ("draft", "verify")

PAGE_CSS = """
@page { size: A4 portrait; margin: 10mm; }
@page ua_land { size: A4 landscape; margin: 8mm; }
html, body { background: #e9e8e4; }
.ua-toolbar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 12px;
  padding: 10px 18px; background: #fff; border-bottom: 1px solid #d6d4ce; font: 13px -apple-system, "Segoe UI", Roboto, sans-serif; }
.ua-toolbar b { font-weight: 600; }
.ua-toolbar .ua-count { color: #6b6a66; }
.ua-toolbar button { font: inherit; padding: 5px 14px; border: 1px solid #714b67; background: #714b67; color: #fff; cursor: pointer; }
.ua-toolbar button:focus-visible { outline: 2px solid #3a6cbf; outline-offset: 2px; }
.ua-toc { color: #6b6a66; }
.ua-sec { position: relative; background: #fff; margin: 18px auto; box-shadow: 0 1px 4px rgba(0,0,0,.12);
  width: 210mm; min-height: 297mm; padding: 10mm; box-sizing: border-box; overflow: hidden; }
.ua-sec.ua-land { width: 297mm; min-height: 210mm; }
.ua-sec.ua-draft::before { content: "ЧЕРНЕТКА"; position: absolute; top: 40%; left: 50%;
  transform: translate(-50%, -50%) rotate(-24deg); font: 700 96px ui-monospace, Menlo, monospace;
  color: rgba(0,0,0,.07); letter-spacing: .06em; pointer-events: none; z-index: 5; }
@media print {
  html, body { background: #fff; }
  .ua-toolbar { display: none; }
  .ua-sec { margin: 0; box-shadow: none; width: auto; min-height: 0; padding: 0; page: auto; break-after: page; }
  .ua-sec.ua-land { page: ua_land; }
  .ua-sec:last-child { break-after: auto; }
}
"""


class UaPrintBundle(http.Controller):

    @http.route("/ua/print", type="http", auth="user", methods=["GET"])
    def print_bundle(self, items="[]", title="", embed="", **kw):
        try:
            parsed = json.loads(items)
        except ValueError:
            return request.not_found()
        Report = request.env["ir.actions.report"]
        head = None
        sections = []
        for item in parsed:
            report_name = item.get("r")
            ids = [int(i) for i in item.get("ids") or []]
            if not report_name or not ids:
                continue
            report = Report._get_report_from_name(report_name)
            if not report:
                continue
            # права перевіряє сам рендер: читання записів іде від поточного користувача
            records = request.env[report.model].browse(ids).exists()
            if not records:
                continue
            content, _fmt = Report._render_qweb_html(report_name, records.ids)
            doc = lxml_html.fromstring(content)
            if head is None:
                found = doc.find("head")
                head = lxml_html.tostring(found, encoding="unicode") if found is not None else ""
            body = doc.find("body")
            inner = "".join(lxml_html.tostring(child, encoding="unicode") for child in (body if body is not None else doc))
            landscape = (report.paperformat_id or request.env.company.paperformat_id).orientation == "Landscape"
            draft = "state" in records._fields and any(r.state in DRAFT_STATES for r in records)
            classes = "ua-sec" + (" ua-land" if landscape else "") + (" ua-draft" if draft else "")
            name = item.get("t") or report.name
            sections.append((name, classes, inner))

        if not sections:
            return request.make_response("Немає документів для перегляду.", headers=[("Content-Type", "text/plain; charset=utf-8")])

        page_title = title or (sections[0][0] if len(sections) == 1 else "Пакет документів")
        toc = " · ".join(escape(s[0]) for s in sections)
        # заголовок <head> беремо з першого документа: стилі звітів спільні
        head = head or "<head></head>"
        # звіт приносить свій заголовок «Odoo Report»: замінюємо назвою документа
        head = re.sub(r"<title>.*?</title>", "", head, flags=re.S)
        head = head.replace("</head>", "<link rel='icon' href='/web/static/img/favicon.ico'/><style>%s</style><title>%s</title></head>" % (PAGE_CSS, escape(page_title)))
        body = "".join('<section class="%s" data-title="%s">%s</section>' % (cls, escape(name), inner) for name, cls, inner in sections)
        toolbar = ('<div class="ua-toolbar"><b>%s</b><span class="ua-count">%s</span>'
                   '<span class="ua-toc">%s</span><span style="flex:1"></span>'
                   '<button type="button" onclick="window.print()">Друк</button></div>') % (
            escape(page_title), escape("документів: %s" % len(sections)), toc)
        if embed:
            # усередині екрана «Період» друк викликає сам екран, свій рядок кнопок не потрібен
            toolbar = ""
        html_out = Markup('<!DOCTYPE html><html lang="uk">%s<body>%s%s</body></html>') % (Markup(head), Markup(toolbar), Markup(body))
        return request.make_response(str(html_out), headers=[("Content-Type", "text/html; charset=utf-8")])
