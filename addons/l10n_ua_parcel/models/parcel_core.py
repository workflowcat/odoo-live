"""Спільна мова статусів відправлень і переклад відповідей перевізників.

Без Odoo: лише таблиці й функції, щоб тести і перевірки працювали без бази.

Стани, як у сервісах відстеження (AfterShip та подібні), лише українською:
    new              - номер є, перевізник ще не прийняв
    in_transit       - прийнято, у дорозі
    customs          - на митниці
    out_for_delivery - кур'єр везе одержувачу
    at_pickup        - чекає у відділенні чи поштоматі
    failed_attempt   - невдала спроба вручення
    delivered        - вручено
    returning        - повертається відправнику
    returned         - повернуто відправнику
    exception        - проблема: знищено, вилучено, зберігання припинено
    cancelled        - скасовано або видалено

Нова пошта: TrackingDocument.getStatusDocuments на https://api.novaposhta.ua/v2.0/json/,
до 100 номерів за запит, повна інформація - з телефоном відправника чи одержувача.
Відповідь - лише поточний стан (StatusCode, Status, TrackingUpdateDate), тому подію
пишемо, коли код чи текст змінився. Коди - за довідником API, перевіряйте чинний.

Укрпошта: https://www.ukrposhta.ua/status-tracking/0.0.1/statuses (POST, до 50 штрихкодів,
токен Bearer з додатка до договору). Відповідь - уся історія подій: event, eventName, date,
name (відділення), index, country, eventReason_id. Повернення відправнику - event 41000
з eventReason_id 10 (разом 41010). Коди - за додатком Б документації, перевіряйте чинну.
"""
import re
from datetime import datetime

STATES = [
    ("new", "Створено"),
    ("in_transit", "У дорозі"),
    ("customs", "На митниці"),
    ("out_for_delivery", "Везе кур'єр"),
    ("at_pickup", "Чекає у відділенні"),
    ("failed_attempt", "Невдала спроба"),
    ("delivered", "Отримано"),
    ("returning", "Повертається"),
    ("returned", "Повернуто"),
    ("exception", "Проблема"),
    ("cancelled", "Скасовано"),
]
STATE_LABELS = dict(STATES)
FINAL_STATES = ("delivered", "returned", "cancelled")
# Стани, що вимагають дії людини: забрати, домовитися, з'ясувати.
ATTENTION_STATES = ("customs", "at_pickup", "failed_attempt", "returning", "exception")

# Нова пошта, StatusCode -> стан.
NP_CODES = {
    1: "new",            # Відправник створив накладну, вантаж ще не передав
    2: "cancelled",      # Накладну видалено
    3: "new",            # Номер не знайдено
    4: "in_transit",     # На сортуванні
    41: "in_transit",    # На сортуванні в межах міста
    5: "in_transit",     # Прямує до міста одержувача
    6: "in_transit",     # У місті одержувача
    7: "at_pickup",      # Прибуло у відділення
    8: "at_pickup",      # Прибуло в поштомат
    9: "delivered",      # Отримано
    10: "delivered",     # Отримано, грошовий переказ відправлено
    11: "delivered",     # Отримано, грошовий переказ видано
    12: "new",           # Нова пошта комплектує відправлення
    14: "at_pickup",     # Видано на огляд одержувачу
    101: "out_for_delivery",  # На шляху до одержувача
    102: "returning",    # Повернення: збіг строк зберігання
    103: "returning",    # Відмова одержувача
    104: "in_transit",   # Змінено адресу
    105: "exception",    # Зберігання припинено
    106: "delivered",    # Отримано, створено накладну зворотної доставки
    108: "returning",    # Відмова одержувача
    111: "failed_attempt",  # Невдала спроба: одержувача немає на адресі чи на зв'язку
    112: "in_transit",   # Одержувач переніс дату доставки
    124: "exception",    # Знищено внаслідок ворожої атаки
}

# Укрпошта, event -> стан (додаток Б). Коди міжнародних подій - окремим словником.
UP_CODES = {
    10100: "in_transit",   # Прийнято у відділенні
    17100: "in_transit",   # Прийнято (міжнародне)
    20700: "in_transit",   # Надійшло в сортувальний центр
    20800: "in_transit",   # Відправлено
    20900: "in_transit",   # Відправлено у відділення доставки
    21500: "in_transit",   # Відправлено у відділення доставки
    21400: "at_pickup",    # Передано на зберігання
    21700: "at_pickup",    # Надійшло у відділення доставки
    29500: "out_for_delivery",  # Передано для вручення (міжнародне)
    29700: "at_pickup",    # Чекає в пункті видачі (міжнародне)
    31100: "failed_attempt",    # Невдала спроба вручення
    31200: "returning",    # Повертається відправнику
    31300: "in_transit",   # Переслано в інше відділення
    31400: "failed_attempt",    # Невдала спроба, передано на зберігання
    41000: "delivered",    # Вручено
    41010: "returned",     # Вручено відправнику (повернення)
    48000: "delivered",    # Вручено в країні одержувача
    10600: "cancelled",    # Приймання скасовано на прохання відправника
    10602: "cancelled",    # Приймання скасовано
    10603: "cancelled",    # Видалено клієнтом
    35500: "returning",    # Повертається відправнику (міжнародне)
    55800: "exception",    # Вилучено чи знищено через вміст
    56100: "exception",    # Знищено на вимогу відправника
    82800: "in_transit",   # Випущено митницею
    89100: "in_transit",   # Випущено митницею
}
# Митні події Укрпошти: 80700-80841, 82700, 87500, 88500, 89000.
UP_CUSTOMS = {80700, 82700, 87500, 88500, 89000}
UP_RETURN_REASON = 10   # eventReason_id для 41000: вручено відправнику

# Номери, які впізнаємо самі. Решту перевізників можна описати шаблоном у довіднику.
# Міжнародний поштовий номер S10 (RR123456789UA, LP...CN): в Україні його веде Укрпошта.
S10 = re.compile(r"[A-Z]{2}\d{9}[A-Z]{2}")
NUMBER_PATTERNS = [
    ("novaposhta", re.compile(r"(20|59)\d{12}")),
    ("ukrposhta", re.compile(r"\d{13}")),
    ("ukrposhta", S10),
]
SPLIT = re.compile(r"[\s,;]+")
WORD = re.compile(r"[A-Z0-9]{8,30}")
PHONE = re.compile(r"(380|0)\d{9}")
GROUPED = re.compile(r"(?<![\d.])\d{2,4}(?: \d{2,4}){2,}(?![\d.])")


def clean_number(text):
    """Номер без пробілів і дефісів, великими літерами."""
    return re.sub(r"[\s\-]", "", (text or "")).upper()


def detect_carrier(number, extra_patterns=()):
    """Код перевізника за номером або None. extra_patterns - [(код, regex-рядок), ...] з довідника,
    вони перевіряються першими."""
    number = clean_number(number)
    for code, pattern in extra_patterns:
        try:
            if pattern and re.fullmatch(pattern, number):
                return code
        except re.error:
            continue
    for code, rx in NUMBER_PATTERNS:
        if rx.fullmatch(number):
            return code
    return None


def find_numbers(text):
    """Усі схожі на номери відправлень слова з тексту (лист постачальника, таблиця, список)."""
    seen, out = set(), []
    # «20 4501 2345 6789» - номер, записаний групами цифр: склеюємо групи по 2-4 цифри.
    text = GROUPED.sub(lambda m: m.group(0).replace(" ", ""), text or "")
    for word in SPLIT.split(text):
        word = clean_number(word.strip(".:()[]\"'#№"))
        if not WORD.fullmatch(word) or sum(c.isdigit() for c in word) < 6 or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def looks_like_phone(word):
    """Український телефон (380XXXXXXXXX чи 0XXXXXXXXX) - не номер відправлення."""
    return bool(PHONE.fullmatch(clean_number(word)))


def _date(value):
    """Дата-час перевізника в naive datetime (київський час) або None."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d.%m.%Y %H:%M:%S",
                "%d-%m-%Y %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:19] if "T" in value else value, fmt)
        except ValueError:
            continue
    return None


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def np_result(row):
    """Рядок відповіді Нової пошти -> спільний вигляд."""
    try:
        code = int(row.get("StatusCode") or 0)
    except (TypeError, ValueError):
        code = 0
    state = NP_CODES.get(code, "in_transit" if code else "new")
    text = (row.get("Status") or "").strip()
    place = ", ".join(x for x in (row.get("CityRecipient"), row.get("WarehouseRecipient")) if x)
    cod = _num(row.get("RedeliverySum")) or _num(row.get("AfterpaymentOnGoodsCost"))
    when = _date(row.get("TrackingUpdateDate")) or _date(row.get("DateScan"))
    if state == "delivered":
        when = _date(row.get("RecipientDateTime")) or when
    return {
        "number": clean_number(row.get("Number")),
        "found": code != 3,
        "state": state,
        "events": [{"code": str(code), "text": text, "place": place, "date": when, "state": state}],
        "expected": _date(row.get("ScheduledDeliveryDate")),
        "delivered": _date(row.get("RecipientDateTime")) if state == "delivered" else None,
        "storage_from": _date(row.get("DateFirstDayStorage")),
        "cost": _num(row.get("DocumentCost")),
        "weight": _num(row.get("DocumentWeight")),
        "seats": int(_num(row.get("SeatsAmount"))),
        "cod": cod,
        "from_place": ", ".join(x for x in (row.get("CitySender"), row.get("WarehouseSender")) if x),
        "to_place": place,
        "reason": (row.get("UndeliveryReasonsSubtypeDescription") or row.get("UndeliveryReasons") or ""),
    }


def up_state(event, reason_id=None):
    try:
        event = int(event)
    except (TypeError, ValueError):
        return None
    if event == 41000 and reason_id is not None and int(reason_id or 0) == UP_RETURN_REASON:
        return "returned"
    if event in UP_CUSTOMS or 80800 <= event <= 80841:
        return "customs"
    if event in UP_CODES:
        return UP_CODES[event]
    # Решта міжнародних подій - це рух між сортуваннями і обмінами.
    return "in_transit"


def up_results(rows):
    """Список подій Укрпошти (усі номери разом) -> {номер: спільний вигляд}."""
    by_number = {}
    for row in rows or []:
        number = clean_number(row.get("barcode"))
        if not number:
            continue
        state = up_state(row.get("event"), row.get("eventReason_id"))
        text = (row.get("eventName") or "").strip()
        if row.get("eventReason"):
            text = "%s (%s)" % (text, row["eventReason"])
        place = " ".join(x for x in (row.get("index"), row.get("name")) if x)
        if row.get("country") and row.get("country") not in ("UA", "Україна", "Ukraine"):
            place = ("%s, %s" % (place, row["country"])).strip(", ")
        by_number.setdefault(number, []).append({
            "step": row.get("step") or 0, "code": str(row.get("event") or ""), "text": text,
            "place": place, "date": _date(row.get("date")), "state": state})
    out = {}
    for number, events in by_number.items():
        events.sort(key=lambda e: (e["date"] or datetime.min, e["step"]))
        last = events[-1]
        out[number] = {
            "number": number, "found": True, "state": last["state"], "events": events,
            "delivered": last["date"] if last["state"] in ("delivered", "returned") else None,
            "to_place": last["place"],
        }
    return out


def generic_results(rows):
    """Відповідь моста чи файлу в спільному вигляді: [{number, state?, code?, text, events?: [...]}]."""
    out = {}
    for row in rows or []:
        number = clean_number(row.get("number"))
        if not number:
            continue
        events = []
        for ev in row.get("events") or [row]:
            state = ev.get("state") if ev.get("state") in STATE_LABELS else None
            events.append({"code": str(ev.get("code") or ""), "text": (ev.get("text") or "").strip(),
                           "place": ev.get("place") or "", "date": _date(ev.get("date")),
                           "state": state or row.get("state") or "in_transit"})
        events.sort(key=lambda e: e["date"] or datetime.min)
        state = row.get("state") if row.get("state") in STATE_LABELS else events[-1]["state"]
        out[number] = {"number": number, "found": row.get("found", True), "state": state,
                       "events": events, "expected": _date(row.get("expected")),
                       "delivered": _date(row.get("delivered")), "cod": _num(row.get("cod"))}
    return out
