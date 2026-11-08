"""Ядро класифікатора комплектуючих без Odoo: одиниці, маса прокату, розбір назв.

Модуль не імпортує odoo, тому його перевіряють звичайним python (tests/core_check.py)
і ним же користуються моделі. Довідник (види, характеристики, варіанти) приходить
сюди як прості словники: з data/classifier.json або з записів бази.

Розбір назви йде так:
1. normalize(): нижній регістр, кома в числах -> крапка, «х», «*», «×» між числами -> «x»,
   «Ø», «⌀», «ф», «d» перед числом -> «ø».
2. Варіанти вибору (марки, стандарти, покриття, класи міцності) шукаються за
   псевдонімами, довший псевдонім перемагає, знайдене вирізається з тексту.
3. Вид визначається за ключовими словами (довше слово сильніше) і за стандартом,
   який однозначно вказує вид (DIN 934 - гайка).
4. Розмір читає рецепт виду (thread_length, dims, bearing, insert ...) з решти тексту.
5. Значення за замовчуванням: крок різьби - крупний за ISO 261.

Числа в довідниках - довідкові (ISO 261, ISO 4017/4032, DIN 933/934, ISO 15, ISO 1832,
густина марок): звіряйте з чинною редакцією стандарту перед конструкторськими рішеннями.
"""
import math
import re

# ----------------------------------------------------------------------------- одиниці
# код -> (позначення, вимір, множник до базової одиниці виміру)
UNITS = {
    "mm": ("мм", "length", 1.0),
    "cm": ("см", "length", 10.0),
    "m": ("м", "length", 1000.0),
    "in": ("дюйм", "length", 25.4),
    "g": ("г", "mass", 0.001),
    "kg": ("кг", "mass", 1.0),
    "t": ("т", "mass", 1000.0),
    "mm2": ("мм²", "area", 1.0),
    "m2": ("м²", "area", 1e6),
    "kg_m": ("кг/м", "linear_mass", 1.0),
    "kg_m2": ("кг/м²", "area_mass", 1.0),
    "kg_m3": ("кг/м³", "density", 1.0),
    "mah": ("мА·год", "charge", 1.0),
    "ah": ("А·год", "charge", 1000.0),
    "v": ("В", "voltage", 1.0),
    "a": ("А", "current", 1.0),
    "w": ("Вт", "power", 1.0),
    "kv": ("об/хв/В", "kv", 1.0),
    "c": ("C", "c_rating", 1.0),
    "awg": ("AWG", "awg", 1.0),
    "deg": ("°", "angle", 1.0),
    "pcs": ("шт", "count", 1.0),
    "s": ("S", "cells", 1.0),
    "hrc": ("HRC", "hardness", 1.0),
}
UNIT_WORDS = {
    "мм": "mm", "mm": "mm", "см": "cm", "cm": "cm", "м": "m", "m": "m", "метр": "m",
    "дюйм": "in", "in": "in", '"': "in", "г": "g", "g": "g", "кг": "kg", "kg": "kg",
    "т": "t", "t": "t", "тонн": "t", "mah": "mah", "маг": "mah", "мач": "mah",
    "ah": "ah", "аг": "ah",
}


def convert(value, from_unit, to_unit):
    """Переводить число між одиницями одного виміру; інший вимір - ValueError."""
    if from_unit == to_unit or not from_unit or not to_unit:
        return value
    f, t = UNITS[from_unit], UNITS[to_unit]
    if f[1] != t[1]:
        raise ValueError("Одиниці різного виміру: %s і %s" % (f[0], t[0]))
    return value * f[2] / t[2]


def parse_quantity(text, unit):
    """«0,5 м» -> 500.0 для характеристики в мм; число без одиниці - в одиниці характеристики."""
    s = (text or "").strip().lower().replace(",", ".")
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([a-zа-яіїєґ\"]*)\.?$", s)
    if not m:
        raise ValueError("Не число: %r" % text)
    value = float(m.group(1))
    word = m.group(2)
    if word and unit:
        src = UNIT_WORDS.get(word)
        if src is None:
            raise ValueError("Невідома одиниця «%s»" % word)
        value = convert(value, src, unit)
    return value


def fmt_num(value, comma=True, digits=3):
    """8.0 -> «8», 8.50 -> «8,5»; для кодів comma=False дає «8.5»."""
    if value is None or value is False:
        return ""
    text = ("%." + str(digits) + "f") % float(value)
    text = text.rstrip("0").rstrip(".") if "." in text else text
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",") if comma else text


# ----------------------------------------------------------------------------- маса прокату
# Форма -> (характеристики в мм, площа перерізу в мм²). Кути без радіусів заокруглень:
# це теоретична маса, як у довідниках сортаменту, а не маса з урахуванням допусків.
SHAPES = {
    "round": (("diameter",), lambda d: math.pi * d["diameter"] ** 2 / 4.0),
    "hex": (("across_flats",), lambda d: math.sqrt(3) / 2.0 * d["across_flats"] ** 2),
    "square": (("side",), lambda d: d["side"] ** 2),
    "flat": (("width", "thickness"), lambda d: d["width"] * d["thickness"]),
    "pipe": (("outer_d", "wall"),
             lambda d: math.pi * (d["outer_d"] - d["wall"]) * d["wall"]),
    "rect_pipe": (("height", "width", "wall"),
                  lambda d: 2.0 * d["wall"] * (d["height"] + d["width"] - 2.0 * d["wall"])),
    "angle": (("side_a", "side_b", "thickness"),
              lambda d: d["thickness"] * (d["side_a"] + d["side_b"] - d["thickness"])),
    "wire": (("diameter",), lambda d: math.pi * d["diameter"] ** 2 / 4.0),
}
SHEET = "sheet"


def section_area(shape, dims):
    """Площа перерізу в мм² або None, якщо бракує розміру."""
    if shape not in SHAPES:
        return None
    names, fn = SHAPES[shape]
    if any(not dims.get(n) for n in names):
        return None
    if shape in ("pipe", "rect_pipe") and dims["wall"] * 2 >= min(
            dims.get("outer_d") or dims.get("width"), dims.get("height") or 1e9):
        raise ValueError("Стінка труби завтовшки з половину перерізу або більше")
    return fn(dims)


def linear_mass(shape, dims, density):
    """Маса погонного метра, кг/м: площа (мм²) × густина (кг/м³) × 1e-6."""
    area = section_area(shape, dims)
    if area is None or not density:
        return None
    return area * density * 1e-6


def area_mass(thickness, density):
    """Маса квадратного метра листа, кг/м²."""
    if not thickness or not density:
        return None
    return thickness * density / 1000.0


def piece_mass(shape, dims, density):
    """Маса одного прутка, труби чи листа, кг, якщо задано довжину (і ширину листа)."""
    if shape == SHEET:
        per_m2 = area_mass(dims.get("thickness"), density)
        if per_m2 and dims.get("width") and dims.get("length"):
            return per_m2 * dims["width"] * dims["length"] / 1e6
        return None
    per_m = linear_mass(shape, dims, density)
    if per_m and dims.get("stock_length"):
        return per_m * dims["stock_length"] / 1000.0
    return None


# ----------------------------------------------------------------------------- кріплення
# ISO 261, крупний крок
COARSE_PITCH = {
    1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5,
    12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5,
    33: 3.5, 36: 4.0,
}
# Розмір під ключ, мм: ISO 4017/4032 і DIN 933/934 (ГОСТ 7798/5915 - основні розміри як у DIN).
SPANNER = {
    "iso": {3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18, 14: 21, 16: 24, 18: 27,
            20: 30, 22: 34, 24: 36, 27: 41, 30: 46, 36: 55},
}
SPANNER["din"] = {**SPANNER["iso"], 10: 17, 12: 19, 14: 22, 22: 32}


def spanner(table, diameter):
    return SPANNER.get(table or "", {}).get(diameter)


# ----------------------------------------------------------------------------- підшипники
# ISO 15 (ГОСТ 8338): позначення -> (d, D, B), мм
BEARINGS = {
    "623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6),
    "627": (7, 22, 7), "608": (8, 22, 7), "629": (9, 26, 8),
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10),
    "6004": (20, 42, 12), "6005": (25, 47, 12), "6006": (30, 55, 13), "6007": (35, 62, 14),
    "6008": (40, 68, 15), "6009": (45, 75, 16), "6010": (50, 80, 16),
    "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12),
    "6204": (20, 47, 14), "6205": (25, 52, 15), "6206": (30, 62, 16), "6207": (35, 72, 17),
    "6208": (40, 80, 18), "6209": (45, 85, 19), "6210": (50, 90, 20),
    "6300": (10, 35, 11), "6301": (12, 37, 12), "6302": (15, 42, 13), "6303": (17, 47, 14),
    "6304": (20, 52, 15), "6305": (25, 62, 17), "6306": (30, 72, 19), "6307": (35, 80, 21),
    "6308": (40, 90, 23), "6309": (45, 100, 25), "6310": (50, 110, 27),
}
# Ущільнення ISO -> префікс ГОСТ (ГОСТ 3189): 6204-2RS = 180204
SEAL_GOST = {"open": "", "z": "6", "2z": "8", "rs": "16", "2rs": "18"}
GOST_SEAL = {v: k for k, v in SEAL_GOST.items() if v}
SEAL_WORDS = {"2rs": "2rs", "2rsr": "2rs", "2rs1": "2rs", "2rsh": "2rs", "llu": "2rs",
              "ddu": "2rs", "rs": "rs", "rs1": "rs", "rsr": "rs", "2z": "2z", "zz": "2z",
              "2zr": "2z", "z": "z", "zr": "z", "open": "open"}
GOST_SERIES = {"1": "0", "2": "2", "3": "3"}
ISO_SERIES = {v: k for k, v in GOST_SERIES.items()}


def bearing_from_gost(code):
    """«180204» -> («6204», «2rs»); «204» -> («6204», «open»); інакше None."""
    code = code.strip()
    seal = "open"
    for prefix in ("18", "16", "8", "6"):
        if len(code) in (5, 6) and code.startswith(prefix) and len(code) - len(prefix) == 4:
            seal = GOST_SEAL[prefix]
            code = code[len(prefix):]
            break
    code = code.lstrip("0") if len(code) == 4 else code
    if len(code) != 3 or code[0] not in GOST_SERIES:
        return None
    iso = "6" + GOST_SERIES[code[0]] + code[1:]
    return (iso, seal) if iso in BEARINGS else None


def bearing_gost(iso, seal):
    """«6204», «2rs» -> «180204»; мініатюрні 6xx у ГОСТ не перекладаємо."""
    if len(iso) != 4 or iso[1] not in ISO_SERIES:
        return ""
    body = ISO_SERIES[iso[1]] + iso[2:]
    prefix = SEAL_GOST.get(seal or "open", "")
    return prefix + ("0" + body if prefix else body)


# ----------------------------------------------------------------------------- пластини ISO 1832
INSERT_SHAPE = {"c": "C ромб 80°", "d": "D ромб 55°", "k": "K паралелограм 55°",
                "r": "R кругла", "s": "S квадрат 90°", "t": "T трикутник 60°",
                "v": "V ромб 35°", "w": "W тригон 80°"}
INSERT_CLEARANCE = {"a": 3, "b": 5, "c": 7, "d": 15, "e": 20, "f": 25, "g": 30, "n": 0, "p": 11}
# (форма, код розміру) -> діаметр вписаного кола, мм
INSERT_IC = {
    ("c", "06"): 6.35, ("c", "09"): 9.525, ("c", "12"): 12.7, ("c", "16"): 15.875,
    ("c", "19"): 19.05, ("d", "07"): 6.35, ("d", "11"): 9.525, ("d", "15"): 12.7,
    ("s", "09"): 9.525, ("s", "12"): 12.7, ("s", "15"): 15.875, ("s", "19"): 19.05,
    ("t", "11"): 6.35, ("t", "16"): 9.525, ("t", "22"): 12.7, ("v", "11"): 6.35,
    ("v", "16"): 9.525, ("w", "06"): 9.525, ("w", "08"): 12.7, ("r", "10"): 10.0,
    ("r", "12"): 12.0, ("k", "16"): 9.525,
}
INSERT_THICKNESS = {"01": 1.59, "t1": 1.98, "02": 2.38, "03": 3.18, "t3": 3.97, "04": 4.76,
                    "06": 6.35, "07": 7.94, "09": 9.52}
INSERT_RE = re.compile(
    r"(?<![a-z0-9])([cdkrstvw])([abcdefgnp])([acefghjkmu])([agmnrtwx])\s?"
    r"(\d{2})(t1|t3|\d{2})(\d{2}|m0)(?:[-\s]?([a-z]{1,3}\d?))?(?![a-z0-9])")


def decode_insert(text):
    """«cnmg 120408-pm» -> словник характеристик пластини або None."""
    m = INSERT_RE.search(text)
    if not m:
        return None
    shape, clearance, tol, kind, size, thick, radius, breaker = m.groups()
    out = {
        "designation": ("%s%s%s%s %s%s%s" % (shape, clearance, tol, kind, size, thick,
                                              radius)).upper() + (
            "-" + breaker.upper() if breaker else ""),
        "insert_shape": shape,
        "clearance": float(INSERT_CLEARANCE.get(clearance, 0)),
        "corner_r": 0.0 if radius == "m0" else int(radius) / 10.0,
    }
    if (shape, size) in INSERT_IC:
        out["ic"] = INSERT_IC[(shape, size)]
    if thick in INSERT_THICKNESS:
        out["thickness"] = INSERT_THICKNESS[thick]
    return out, m.span()


# ----------------------------------------------------------------------------- нормалізація
LETTERS = "a-zа-яіїєґ"
_X = re.compile(r"(?<=\d)\s*[xх×*]\s*(?=[\d.])")
_DIAM = re.compile(r"(?<![%s])(?:ø|⌀|ф|d|діам\.?|діаметр|диам\.?|dia\.?)\s*(?=\d)" % LETTERS)
_COMMA = re.compile(r"(?<=\d),(?=\d)")
_SPACE = re.compile(r"\s+")


def normalize(text):
    s = (text or "").lower().replace("ё", "е").replace(" ", " ")
    s = s.replace("–", "-").replace("—", "-")
    s = _COMMA.sub(".", s)
    s = _X.sub("x", s)
    s = _DIAM.sub("ø", s)
    return _SPACE.sub(" ", s).strip()


def _alias_re(alias):
    """Псевдонім як окреме слово; «оцинк*» - початок слова («оцинкований»)."""
    prefix = alias.endswith("*")
    a = re.escape(normalize(alias.rstrip("*")))
    tail = r"(?![0-9]|[.][0-9])" if prefix else r"(?![0-9%s]|[.][0-9])" % LETTERS
    return re.compile(r"(?<![0-9%s])%s%s" % (LETTERS, a, tail))


NUM = r"(\d+(?:\.\d+)?)"
THREAD_RE = re.compile(
    r"(?<![%s0-9.])[мm]\s?(\d{1,2}(?:\.\d)?)(?:\s?x\s?%s)?(?:\s?x\s?%s)?" % (LETTERS, NUM, NUM))
GROUP_RE = re.compile(r"(?<![\d.])%s(?:x%s)+" % (NUM, NUM))
GROUP_ALL = re.compile(r"\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)+")
NUMBER_RE = re.compile(r"(?<![\d.%s])%s(?![\d])" % (LETTERS, NUM))


# ----------------------------------------------------------------------------- довідник
class Spec:
    """Довідник для розбору: види, характеристики, варіанти з псевдонімами.

    classes: {code: {"name", "keywords": [..], "recipe", "dims": [..], "lines": [attr..],
                     "parent"}}
    attributes: {code: {"kind", "unit", "choices": {code: {"name", "number", "aliases",
                                                           "class", "density", "spanner"}}}}
    """

    def __init__(self, classes, attributes):
        self.classes = classes
        self.attributes = attributes
        self._aliases = []
        for attr_code, attr in attributes.items():
            for choice_code, choice in (attr.get("choices") or {}).items():
                names = list(choice.get("aliases") or []) + [choice.get("name") or ""]
                # «DIN 933» пишуть і як «DIN933»: варіант без пробілів для назв з цифрами
                names += [n.replace(" ", "") for n in names
                          if " " in n and re.search(r"\d", n)]
                for alias in names:
                    norm = normalize(alias)
                    if len(norm.rstrip("*")) >= 2:
                        self._aliases.append((len(norm.rstrip("*")), norm.endswith("*"),
                                              _alias_re(norm), attr_code, choice_code))
        # довший псевдонім першим; за рівної довжини точний («д16т») раніше за початок
        # слова («алюм*»): конкретна марка важить більше за загальне «алюміній»
        self._aliases.sort(key=lambda a: (-a[0], a[1]))
        self._aliases = [(length, rx, attr, choice)
                         for length, _prefix, rx, attr, choice in self._aliases]
        self._keywords = []
        for class_code, cls in classes.items():
            for word in cls.get("keywords") or []:
                norm = normalize(word)
                self._keywords.append((len(norm), re.compile(
                    r"(?<![%s])%s" % (LETTERS, re.escape(norm))), class_code))
        self._keywords.sort(key=lambda k: -k[0])

    def depth(self, class_code):
        n, code = 0, class_code
        while code and n < 20:
            code = self.classes.get(code, {}).get("parent")
            n += 1
        return n

    def choice(self, attr, code):
        return ((self.attributes.get(attr) or {}).get("choices") or {}).get(code) or {}


def _consume(text, span):
    return text[:span[0]] + " " * (span[1] - span[0]) + text[span[1]:]


def _match_choices(spec, text, attrs=None):
    """Варіанти за псевдонімами: {attr: choice}; знайдене вирізається з тексту.

    attrs - лише ці характеристики (другий прохід, коли вид уже відомий).
    """
    found = {}
    for _length, rx, attr, choice in spec._aliases:
        if attr in found or (attrs is not None and attr not in attrs):
            continue
        m = rx.search(text)
        if m:
            found[attr] = choice
            text = _consume(text, m.span())
    return found, text


def _detect_class(spec, text, choices):
    scores = {}
    for length, rx, class_code in spec._keywords:
        m = rx.search(text)
        if m:
            # назва зазвичай починається з типу виробу: «Болт з шестигранною головою»
            score = 10 * length + (500 if m.start() <= 2 else 0)
            scores[class_code] = max(scores.get(class_code, 0), score)
    for attr, choice in choices.items():
        hint = spec.choice(attr, choice).get("class")
        if hint and hint in spec.classes:
            scores[hint] = scores.get(hint, 0) + 1000
    if not scores:
        return None
    return max(scores, key=lambda c: (scores[c], spec.depth(c)))


def _thread_choice(spec, diameter):
    thread = spec.attributes.get("thread") or {}
    for code, choice in (thread.get("choices") or {}).items():
        if choice.get("number") == diameter:
            return code
    return None


# ----------------------------------------------------------------------------- рецепти
def _groups(text):
    return [[float(x) for x in g.split("x")] for g in GROUP_ALL.findall(text)]


def _numbers(text):
    return [float(x) for x in NUMBER_RE.findall(GROUP_ALL.sub(" ", text))]


def _stock_length(text):
    m = re.search(r"(?:l\s?=\s?|довж\w*\.?\s?|дл\.\s?)%s\s?(мм|м|mm|m)?(?![%s])" % (NUM, LETTERS),
                  text)
    if m:
        value, unit = float(m.group(1)), m.group(2)
        if unit in ("м", "m") or (not unit and value <= 12):
            value *= 1000.0
        return value, m.span()
    m = re.search(r"(?<![\d.x])(\d+(?:\.\d+)?)\s?(?:м|m)(?![%s0-9²2])" % LETTERS, text)
    if m and 1 <= float(m.group(1)) <= 12:
        return float(m.group(1)) * 1000.0, m.span()
    return None, None


def recipe_thread_length(spec, text, values):
    m = THREAD_RE.search(text)
    if m:
        before = text[:m.start()].rstrip()
        if not (before and before[-1].isdigit()):
            d = float(m.group(1))
            code = _thread_choice(spec, d)
            if code:
                values["thread"] = code
            a, b = m.group(2), m.group(3)
            if a and b:
                values["pitch"], values["length"] = float(a), float(b)
            elif a:
                if float(a) < 5:
                    values["pitch"] = float(a)
                else:
                    values["length"] = float(a)
            text = _consume(text, m.span())
    if "length" not in values:
        m = re.search(r"(?:l\s?=\s?|довж\w*\.?\s?)%s" % NUM, text) or \
            re.search(r"(?<![\d.])%s\s?мм" % NUM, text)
        if m:
            values["length"] = float(m.group(1))
    if "thread" not in values:
        # «шайба 8», «гайка 10» без літери М
        for n in _numbers(text):
            code = _thread_choice(spec, n)
            if code:
                values["thread"] = code
                break
    return values


def recipe_dims(spec, text, values, dims, sort_desc=False):
    stock, span = _stock_length(text)
    if stock:
        values["stock_length"] = stock
        text = _consume(text, span)
    groups = _groups(text)
    numbers = groups[0] if groups else []
    m = re.search(r"ø\s?%s" % NUM, text)
    if m and dims and not numbers:
        numbers = [float(m.group(1))]
    if not numbers:
        numbers = _numbers(text)[:len(dims)]
    if sort_desc:
        numbers = sorted(numbers, reverse=True)
    for name, value in zip(dims, numbers):
        values.setdefault(name, value)
    return values


def recipe_sheet(spec, text, values):
    m = re.search(r"(?:s\s?=\s?|товщ\w*\.?\s?|t\s?=\s?)%s" % NUM, text)
    if m:
        values["thickness"] = float(m.group(1))
    groups = _groups(text)
    if groups:
        g = groups[0]
        if len(g) == 3:
            rest = sorted(g)
            values.setdefault("thickness", rest[0])
            values["width"], values["length"] = rest[1], rest[2]
        elif len(g) == 2 and "thickness" in values:
            values["width"], values["length"] = sorted(g)
        elif len(g) == 2:
            values["width"], values["length"] = sorted(g)
    if "thickness" not in values:
        nums = _numbers(text)
        if nums:
            values["thickness"] = nums[0]
    return values


def recipe_angle(spec, text, values):
    groups = _groups(text)
    if groups:
        g = groups[0]
        if len(g) == 3:
            values["side_a"], values["side_b"], values["thickness"] = g
        elif len(g) == 2:
            values["side_a"] = values["side_b"] = max(g)
            values["thickness"] = min(g)
    stock, _span = _stock_length(text)
    if stock:
        values["stock_length"] = stock
    return values


def recipe_rivet(spec, text, values):
    groups = _groups(text)
    if groups and len(groups[0]) >= 2:
        values["diameter"], values["length"] = groups[0][0], groups[0][1]
    return values


def recipe_drill(spec, text, values):
    m = re.search(r"ø\s?%s" % NUM, text)
    nums = [float(m.group(1))] if m else _numbers(text)
    if nums:
        values["diameter"] = nums[0]
    return values


def recipe_endmill(spec, text, values):
    # «z4» сильніше за «4 зуби»: у «10 z4» число перед z - діаметр
    m = re.search(r"(?<![%s])z\s?=?\s?(\d{1,2})(?![\d.])" % LETTERS, text) or re.search(
        r"(?<![\d.])(\d{1,2})\s?(?:зуб\w*|пер\w*|fl\w*)(?![%s])" % LETTERS, text)
    if m:
        values["flutes"] = float(m.group(1))
        text = _consume(text, m.span())
    m = re.search(r"(?<![%s])r\s?=?\s?%s" % (LETTERS, NUM), text)
    if m:
        values["corner_r"] = float(m.group(1))
        text = _consume(text, m.span())
    groups = _groups(text)
    if groups:
        values["diameter"] = groups[0][0]
        if len(groups[0]) > 1:
            values["cut_length"] = groups[0][1]
    else:
        recipe_drill(spec, text, values)
    return values


def recipe_tap(spec, text, values):
    return recipe_thread_length(spec, text, values)


def recipe_insert(spec, text, values):
    decoded = decode_insert(text)
    if decoded:
        values.update(decoded[0])
    return values


def recipe_disc(spec, text, values):
    groups = _groups(text)
    if groups:
        g = groups[0]
        for name, value in zip(("diameter", "thickness", "bore"), g):
            values[name] = value
    return values


def recipe_bearing(spec, text, values):
    iso = seal = None
    m = re.search(r"(?<![\d.])(6[023]\d{2}|6[2][3-9]|608)(?:[-\s]?(2rsr|2rs1|2rsh|2rs|rs1|rsr|rs|"
                  r"2zr|2z|zz|zr|z|llu|ddu))?(?![\d%s])" % LETTERS, text)
    if m:
        iso = m.group(1)
        seal = SEAL_WORDS.get(m.group(2)) if m.group(2) else values.get("seal", "open")
    else:
        for m in re.finditer(r"(?<![\d.])(\d{3,6})(?![\d.])", text):
            found = bearing_from_gost(m.group(1))
            if found:
                iso, seal = found
                break
    if iso:
        values["designation"] = iso
        values["seal"] = seal
        if iso in BEARINGS:
            values["inner_d"], values["outer_d"], values["width"] = (
                float(x) for x in BEARINGS[iso])
        gost = bearing_gost(iso, seal)
        if gost:
            values["gost_designation"] = gost
    return values


def recipe_oring(spec, text, values):
    groups = _groups(text)
    if groups and len(groups[0]) >= 2:
        values["inner_d"], values["section"] = groups[0][0], groups[0][1]
    return values


def recipe_motor(spec, text, values):
    m = re.search(r"(\d{3,5})\s?(?:kv|кв)(?![%s])" % LETTERS, text)
    if m:
        values["kv"] = float(m.group(1))
        text = _consume(text, m.span())
    m = re.search(r"(?<![\d.])(\d{2})(\d{2})(?![\d.])", text)
    if m:
        values["stator"] = m.group(1) + m.group(2)
        values["stator_d"], values["stator_h"] = float(m.group(1)), float(m.group(2))
    return values


def recipe_prop(spec, text, values):
    groups = _groups(text)
    if groups:
        g = groups[0]
        values["prop_d"], values["prop_pitch"] = g[0], g[1] if len(g) > 1 else None
        if len(g) > 2:
            values["blades"] = g[2]
        if values.get("prop_pitch") is None:
            values.pop("prop_pitch")
    m = re.search(r"(\d)\s?(?:лоп\w*|blade\w*|bl)(?![%s])" % LETTERS, text)
    if m:
        values["blades"] = float(m.group(1))
    return values


def recipe_battery(spec, text, values):
    m = re.search(r"(?<![\d.])(\d{1,2})\s?s(?:\d?p)?(?![%s])" % LETTERS, text)
    if m:
        values["cells"] = float(m.group(1))
    m = re.search(r"(\d{3,5})\s?(?:mah|маг|мач|ма·год|ма\s?год)", text)
    if m:
        values["capacity"] = float(m.group(1))
    else:
        m = re.search(r"%s\s?(?:ah|аг|а·год)(?![%s])" % (NUM, LETTERS), text)
        if m:
            values["capacity"] = float(m.group(1)) * 1000.0
    m = re.search(r"(?<![\d.])(\d{2,3})\s?c(?![%s])" % LETTERS, text)
    if m:
        values["c_rating"] = float(m.group(1))
    return values


def recipe_esc(spec, text, values):
    m = re.search(r"(?<![\d.])(\d{2,3})\s?a(?![%s])" % LETTERS, text)
    if m:
        values["current"] = float(m.group(1))
    m = re.search(r"(\d)\s?-\s?(\d{1,2})\s?s(?![%s])" % LETTERS, text)
    if m:
        values["cells_range"] = "%s-%sS" % (m.group(1), m.group(2))
    return values


def recipe_awg(spec, text, values):
    m = re.search(r"(?:(\d{1,2})\s?awg|awg\s?(\d{1,2}))", text)
    if m:
        values["awg"] = float(m.group(1) or m.group(2))
    return values


def recipe_cable(spec, text, values):
    groups = _groups(text)
    if groups and len(groups[0]) >= 2:
        values["cores"], values["cross_section"] = groups[0][0], groups[0][1]
    return values


def recipe_range(spec, text, values):
    m = re.search(r"(?<![\d.])(\d+)\s?-\s?(\d+)(?![\d.])", text)
    if m:
        values["range"] = "%s-%s" % (m.group(1), m.group(2))
        text = _consume(text, m.span())
    m = re.search(r"(?<![\d])(0\.\d{1,3})(?![\d])", text)
    if m:
        values["resolution"] = float(m.group(1))
    return values


RECIPES = {
    "thread_length": recipe_thread_length,
    "tap": recipe_tap,
    "sheet": recipe_sheet,
    "angle": recipe_angle,
    "rivet": recipe_rivet,
    "drill": recipe_drill,
    "endmill": recipe_endmill,
    "insert": recipe_insert,
    "disc": recipe_disc,
    "bearing": recipe_bearing,
    "oring": recipe_oring,
    "motor": recipe_motor,
    "prop": recipe_prop,
    "battery": recipe_battery,
    "esc": recipe_esc,
    "awg": recipe_awg,
    "cable": recipe_cable,
    "range": recipe_range,
}


def parse(spec, text):
    """Назва -> {"class", "values", "confidence", "missing"}.

    confidence: частка обов'язкових характеристик виду, які вдалося заповнити (0..1);
    без виду - 0.
    """
    norm = normalize(text)
    hints, rest = _match_choices(spec, norm)
    class_code = _detect_class(spec, norm, hints)
    if not class_code:
        return {"class": None, "values": {}, "confidence": 0.0, "missing": []}
    cls = spec.classes[class_code]
    # «Труба 40x20x2» без слова «профільна»: три розміри - інший вид
    switch = cls.get("switch_dims") or {}
    groups = _groups(rest)
    if groups and str(len(groups[0])) in switch and switch[str(len(groups[0]))] in spec.classes:
        class_code = switch[str(len(groups[0]))]
        cls = spec.classes[class_code]
    lines = cls.get("lines") or {}
    # другий прохід: лише характеристики виду, щоб «силікон» у проводі не з'їла марка гуми
    choices, rest = _match_choices(spec, norm, set(lines))
    values = {a: c for a, c in choices.items() if a in lines}
    recipe = cls.get("recipe") or "dims"
    if recipe == "dims":
        recipe_dims(spec, rest, values, cls.get("dims") or [], cls.get("sort_desc"))
    elif recipe in RECIPES:
        RECIPES[recipe](spec, rest, values)
    # характеристики, яких вид не має, відкидаємо (рецепт міг знайти зайве)
    values = {a: v for a, v in values.items() if a in lines and v not in (None, "")}
    if "pitch" in lines and "pitch" not in values and values.get("thread"):
        d = spec.choice("thread", values["thread"]).get("number")
        if d in COARSE_PITCH:
            values["pitch"] = COARSE_PITCH[d]
    for attr, line in lines.items():
        if attr not in values and line.get("default") not in (None, ""):
            values[attr] = line["default"]
    required = [a for a, line in lines.items() if line.get("required")]
    missing = [a for a in required if a not in values]
    confidence = 1.0 if not required else (len(required) - len(missing)) / float(len(required))
    return {"class": class_code, "values": values, "confidence": round(confidence, 2),
            "missing": missing}


# ----------------------------------------------------------------------------- назви і ключі
_SEGMENT = re.compile(r"\[([^\[\]]*)\]")
_PLACE = re.compile(r"\{(\w+)\}")


def _display(spec, attr, value, for_code):
    a = spec.attributes.get(attr) or {}
    if a.get("kind") == "choice":
        choice = spec.choice(attr, value)
        if for_code:
            return (choice.get("code_text") or str(value)).upper()
        return choice.get("name") or str(value)
    if a.get("kind") == "bool":
        return a.get("name", attr) if value else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return fmt_num(value, comma=not for_code)
    return str(value)


def render(spec, template, values, extra=None, for_code=False):
    """Шаблон «Болт {thread}[×{length}][ {grade}]» -> текст.

    Частина в [] виводиться, лише коли всі її {поля} заповнені; {prefix} та інші
    поля з extra підставляються як є.
    """
    extra = extra or {}

    def value_of(name):
        if name in extra:
            return str(extra[name] or "")
        if name == "pitch_fine":
            fine = pitch_fine(spec, values)
            return fmt_num(fine, comma=not for_code) if fine else ""
        if name in values and values[name] not in (None, "", False):
            return _display(spec, name, values[name], for_code)
        return ""

    def fill(part):
        return _PLACE.sub(lambda m: value_of(m.group(1)), part)

    def segment(m):
        part = m.group(1)
        names = _PLACE.findall(part)
        if any(not value_of(n) for n in names):
            return ""
        return fill(part)

    text = _SEGMENT.sub(segment, template or "")
    text = fill(text)
    if for_code:
        return re.sub(r"-{2,}", "-", text.replace(" ", "")).strip("-")
    return _SPACE.sub(" ", text).strip(" -")


def pitch_fine(spec, values):
    """Крок різьби, лише коли він не крупний (М8×1 замість М8)."""
    pitch, thread = values.get("pitch"), values.get("thread")
    if not pitch or not thread:
        return None
    d = spec.choice("thread", thread).get("number")
    if d in COARSE_PITCH and abs(COARSE_PITCH[d] - pitch) < 1e-6:
        return None
    return pitch


def spec_from_data(data):
    """Spec з data/classifier.json (той самий вигляд, що будують моделі з бази)."""
    attributes = {}
    for a in data.get("attributes") or []:
        attributes[a["code"]] = dict(a, choices={
            c["code"]: dict(c) for c in a.get("choices") or []})
    classes = {}
    for c in data.get("classes") or []:
        cls = dict(c)
        lines = {}
        parent = c.get("parent")
        chain = []
        while parent:
            chain.append(parent)
            parent = next((x.get("parent") for x in data["classes"] if x["code"] == parent), None)
        for line in c.get("lines") or []:
            lines[line["attr"]] = {"required": line.get("required", False),
                                   "key": line.get("key", True),
                                   "rule": line.get("rule", "equal"),
                                   "default": line.get("default")}
        cls["lines"] = lines
        classes[c["code"]] = cls
    return Spec(classes, attributes)


def equivalence_groups(data_or_list):
    """{attr: [(set, level, note)]} з розділу equivalences."""
    items = data_or_list.get("equivalences") if isinstance(data_or_list, dict) else data_or_list
    groups = {}
    for g in items or []:
        groups.setdefault(g["attr"], []).append(
            (set(g["members"]), g.get("level", "check"), g.get("note") or ""))
    return groups


def component_key(class_code, values, key_attrs):
    """Відбиток для пошуку дублів: вид і ключові характеристики в сталому вигляді."""
    parts = [class_code or ""]
    for attr in sorted(key_attrs):
        value = values.get(attr)
        if value in (None, "", False):
            continue
        if isinstance(value, float):
            value = fmt_num(value, comma=False, digits=4)
        parts.append("%s=%s" % (attr, str(value).strip().lower()))
    return "|".join(parts)


# ----------------------------------------------------------------------------- аналоги
def compare(spec, class_lines, mine, theirs, groups):
    """Чи може «theirs» замінити «mine». Повертає (рівень, [причини]) або None.

    class_lines: {attr: {"rule": equal|equivalent|ge|any, "key": bool}}
    groups: {attr: [(set варіантів, рівень full|check, примітка)]}
    рівень: full - повна заміна; check - заміна з перевіркою (причини пояснюють, що звірити).
    """
    level = "full"
    reasons = []
    for attr, line in class_lines.items():
        if not line.get("key") or line.get("rule") == "any":
            continue
        a, b = mine.get(attr), theirs.get(attr)
        if a == b:
            continue
        rule = line.get("rule") or "equal"
        name = (spec.attributes.get(attr) or {}).get("name", attr)
        if a in (None, "") or b in (None, ""):
            if rule == "equal":
                return None
            level = "check"
            reasons.append("%s: не вказано в одного з виробів" % name)
            continue
        if rule == "ge":
            na = spec.choice(attr, a).get("number") if isinstance(a, str) else a
            nb = spec.choice(attr, b).get("number") if isinstance(b, str) else b
            if na is not None and nb is not None and nb >= na:
                level = "check"
                reasons.append("%s: %s замість %s (вище)" % (
                    name, _display(spec, attr, b, False), _display(spec, attr, a, False)))
                continue
            return None
        if rule == "equivalent":
            # найтісніша група: спершу повна заміна, далі найменша (DIN 933 = ISO 4017
            # точніше, ніж ширша група з ГОСТ 7798)
            hits = [(glevel != "full", len(members), glevel, note)
                    for members, glevel, note in groups.get(attr) or []
                    if a in members and b in members]
            if not hits:
                return None
            hit = min(hits, key=lambda h: (h[0], h[1]))[2:]
            if hit[0] != "full":
                level = "check"
                reasons.append("%s: %s замість %s%s" % (
                    name, _display(spec, attr, b, False), _display(spec, attr, a, False),
                    " - " + hit[1] if hit[1] else ""))
            continue
        return None
    # розмір під ключ між DIN і ISO
    if mine.get("standard") != theirs.get("standard") and mine.get("thread"):
        d = spec.choice("thread", mine["thread"]).get("number")
        sa = spanner(spec.choice("standard", mine.get("standard")).get("spanner"), d)
        sb = spanner(spec.choice("standard", theirs.get("standard")).get("spanner"), d)
        if sa and sb and sa != sb:
            level = "check"
            reasons.append("розмір під ключ %s → %s мм: перевірте інструмент і місце під ключ"
                           % (fmt_num(sa), fmt_num(sb)))
    return level, reasons
