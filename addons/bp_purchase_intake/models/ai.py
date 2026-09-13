"""Document reading through Cloudflare Workers AI (REST API).

Now: the Cloudflare account of the person running the stand (CF_ACCOUNT_ID + CF_API_TOKEN, or
CF_API_TOKEN_FILE refreshed by scripts/cf_token.sh from the wrangler login).
Later: the same two calls move behind a bridge route; only this model changes.
"""
import base64
import io
import json
import logging
import os

import requests

from odoo import models
from odoo.exceptions import UserError
from odoo.tools.misc import file_open

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct"
DEFAULT_VISION_MODEL = "@cf/meta/llama-4-scout-17b-16e-instruct"
IMAGE_MAX_SIDE = 1800
UA = "odoo-bp-purchase-intake/1.0"


def pdf_page_images(content, max_pages=3):
    """Images of the pages of a scanned PDF (the largest embedded image per page), as PIL images."""
    from PIL import Image
    from odoo.tools.pdf import PdfFileReader
    images = []
    reader = PdfFileReader(io.BytesIO(content), strict=False)
    for page in list(reader.pages)[:max_pages]:
        resources = page.get("/Resources")
        resources = resources.get_object() if resources is not None else {}
        xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
        if xobjects is None:
            continue
        best = None
        for key in xobjects.get_object():
            obj = xobjects.get_object()[key].get_object()
            if obj.get("/Subtype") != "/Image":
                continue
            width, height = int(obj.get("/Width", 0)), int(obj.get("/Height", 0))
            filters = obj.get("/Filter")
            filters = [str(f) for f in filters] if isinstance(filters, list) else [str(filters)] if filters else []
            try:
                if "/DCTDecode" in filters:
                    img = Image.open(io.BytesIO(obj._data))
                elif "/JPXDecode" in filters:
                    continue
                else:
                    data = obj.get_data()
                    space = str(obj.get("/ColorSpace"))
                    bits = int(obj.get("/BitsPerComponent", 8))
                    mode = "1" if bits == 1 else "RGB" if "RGB" in space else "L" if "Gray" in space else None
                    if not mode:
                        continue
                    img = Image.frombytes(mode, (width, height), data)
            except Exception:  # noqa: BLE001 - an unreadable image is skipped, not fatal
                _logger.info("skip embedded image %s", key, exc_info=True)
                continue
            if best is None or width * height > best[0]:
                best = (width * height, img)
        if best:
            images.append(best[1])
    return images


def image_data_url(img):
    """PIL image (or raw bytes) to a JPEG data URL small enough for the vision model."""
    from PIL import Image, ImageOps
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class BpAi(models.AbstractModel):
    _name = "bp.ai"
    _description = "Розбір документів (Workers AI)"

    def _cf(self):
        icp = self.env["ir.config_parameter"].sudo()
        account = os.environ.get("CF_ACCOUNT_ID") or icp.get_param("bp_ai.cf_account_id") or ""
        token = os.environ.get("CF_API_TOKEN") or ""
        path = os.environ.get("CF_API_TOKEN_FILE") or ""
        if not token and path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                token = f.read().strip()
        if not account or not token:
            raise UserError("Workers AI не налаштовано: задайте CF_ACCOUNT_ID і CF_API_TOKEN "
                            "(або CF_API_TOKEN_FILE) у середовищі Odoo.")
        return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai", token

    def model_name(self):
        return (os.environ.get("BP_AI_MODEL")
                or self.env["ir.config_parameter"].sudo().get_param("bp_ai.model") or DEFAULT_MODEL)

    def vision_model_name(self):
        return (os.environ.get("BP_AI_VISION_MODEL")
                or self.env["ir.config_parameter"].sudo().get_param("bp_ai.vision_model") or DEFAULT_VISION_MODEL)

    def _post(self, url, token, **kw):
        headers = {"Authorization": f"Bearer {token}", "User-Agent": UA}
        try:
            r = requests.post(url, headers=headers, timeout=kw.pop("timeout", 120), **kw)
        except requests.RequestException as e:
            raise UserError(f"Cloudflare недоступний: {e}") from e
        if r.status_code in (401, 403):
            raise UserError("Cloudflare відхилив токен (401/403). Для локального стенду запустіть "
                            "scripts/cf_token.sh, для постійної роботи задайте CF_API_TOKEN.")
        try:
            data = r.json()
        except ValueError:
            raise UserError(f"Cloudflare повернув не JSON ({r.status_code}): {r.text[:200]}")
        if r.status_code >= 400 or not data.get("success", True):
            raise UserError(f"Cloudflare {r.status_code}: {json.dumps(data.get('errors') or data, ensure_ascii=False)[:300]}")
        return data

    def to_markdown(self, filename, content, mimetype="application/pdf"):
        """PDF or image to text. Free for PDFs with a text layer. Returns (text, tokens)."""
        base, token = self._cf()
        data = self._post(f"{base}/tomarkdown", token, files={"files": (filename or "document.pdf", content, mimetype)})
        item = (data.get("result") or [{}])[0]
        text = item.get("data") or ""
        if "## Contents" in text:
            text = text.split("## Contents", 1)[1]
        return text.strip(), item.get("tokens") or 0

    @staticmethod
    def load_spec(name):
        with file_open(f"bp_purchase_intake/data/{name}.json", "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def extract_json(self, spec, text=None, images=None):
        """Run the extraction prompt with JSON mode, on document text or on page images. Returns (dict, usage, model)."""
        base, token = self._cf()
        if images:
            model = self.vision_model_name()
            content = [{"type": "text", "text": f"Документ на зображенні ({len(images)} стор.)."}] + \
                      [{"type": "image_url", "image_url": {"url": image_data_url(img)}} for img in images]
        else:
            model = self.model_name()
            content = "Документ:\n\n" + (text or "")
        payload = {
            "messages": [{"role": "system", "content": spec["system"]}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": spec["schema"]},
            "max_tokens": 3000, "temperature": 0,
        }
        data = self._post(f"{base}/run/{model}", token, json=payload, timeout=240)
        result = data.get("result") or {}
        out = result.get("response")
        if out is None and result.get("choices"):
            out = result["choices"][0]["message"].get("content")
        if isinstance(out, str):
            s = out.strip()
            s = s[s.find("{"):s.rfind("}") + 1] if "{" in s else s
            try:
                out = json.loads(s)
            except ValueError:
                raise UserError(f"Модель {model} повернула не JSON: {out[:200]}")
        if not isinstance(out, dict):
            raise UserError(f"Модель {model} не повернула результат.")
        return out, result.get("usage") or {}, model
