"""Сума прописом українською.

Нативний `res.currency.amount_to_text` спирається на num2words і локаль. Для
української первинки цього мало: у «гривні» жіночий рід, тому «одна гривня» і
«дві гривні», а не «один» і «два»; копійки на папері пишуть цифрами, але слово
поруч теж відмінюється - «01 копійка», «02 копійки», «05 копійок». Тому тут
власна, чиста функція без зовнішніх залежностей: її легко перевірити тестом і
вона дає однаковий результат на будь-якій базі, навіть без мови uk_UA.

Правило форми числівника українське: закінчення 1 (крім 11) - однина;
закінчення 2-4 (крім 12-14) - форма множини на -і; решта - родовий відмінок.
"""
from decimal import Decimal, ROUND_HALF_UP

ONES_M = ("", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять")
ONES_F = ("", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять")
TEENS = ("десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять",
         "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять")
TENS = ("", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят",
        "сімдесят", "вісімдесят", "дев'яносто")
HUNDREDS = ("", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот",
            "сімсот", "вісімсот", "дев'ятсот")

# Розряди від молодшого. Рід потрібен саме тут: тисяча жіночого роду
# («дві тисячі»), мільйон чоловічого («два мільйони»).
SCALES = (
    (None, None),
    (("тисяча", "тисячі", "тисяч"), "f"),
    (("мільйон", "мільйони", "мільйонів"), "m"),
    (("мільярд", "мільярди", "мільярдів"), "m"),
    (("трильйон", "трильйони", "трильйонів"), "m"),
)

# Форми валюти: (одна, дві, п'ять) плюс рід цілої частини.
UAH = {"unit": ("гривня", "гривні", "гривень"), "unit_gender": "f",
       "cent": ("копійка", "копійки", "копійок")}


def plural_form(number, forms):
    """Одна з трьох форм слова за українським правилом узгодження."""
    number = abs(int(number))
    if number % 100 in (11, 12, 13, 14):
        return forms[2]
    last = number % 10
    if last == 1:
        return forms[0]
    if last in (2, 3, 4):
        return forms[1]
    return forms[2]


def _group_to_words(value, gender):
    """Слова для числа 1..999 у потрібному роді."""
    ones = ONES_F if gender == "f" else ONES_M
    words = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        words.append(HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(TEENS[rest - 10])
    else:
        tens, units = divmod(rest, 10)
        if tens:
            words.append(TENS[tens])
        if units:
            words.append(ones[units])
    return words


def int_to_words_uk(value, gender="m"):
    """Ціле число словами. `gender` - рід одиниць (розряду без назви)."""
    value = int(value)
    if value == 0:
        return "нуль"
    prefix = []
    if value < 0:
        prefix = ["мінус"]
        value = -value

    groups = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    if len(groups) > len(SCALES):
        raise ValueError("число завелике для прописом: більше за трильйони")

    words = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        scale_forms, scale_gender = SCALES[index]
        words += _group_to_words(group, scale_gender or gender)
        if scale_forms:
            words.append(plural_form(group, scale_forms))
    return " ".join(prefix + words)


def split_amount(amount):
    """Ціла частина і копійки, заокруглені як на папері (половина вгору)."""
    quantum = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = -1 if quantum < 0 else 1
    quantum = abs(quantum)
    units = int(quantum)
    cents = int((quantum - units) * 100)
    return sign, units, cents


def amount_to_text_uk(amount, currency_forms=None, capitalize=True):
    """Сума прописом: ціла частина словами, копійки цифрами зі словом.

    2500.50 -> «Дві тисячі п'ятсот гривень 50 копійок».
    """
    forms = currency_forms or UAH
    sign, units, cents = split_amount(amount)
    words = int_to_words_uk(units, forms["unit_gender"])
    text = "%s %s %02d %s" % (
        words,
        plural_form(units, forms["unit"]),
        cents,
        plural_form(cents, forms["cent"]),
    )
    if sign < 0:
        text = "мінус " + text
    if capitalize:
        text = text[0].upper() + text[1:]
    return text


def amount_in_words(currency, amount):
    """Сума прописом для валюти документа.

    Гривню пишемо своєю функцією, іншу валюту віддаємо нативному Odoo: чужі
    валюти в українській первинці трапляються рідко і власних форм не варті.
    """
    if not currency or currency.name == "UAH":
        return amount_to_text_uk(amount)
    try:
        return currency.amount_to_text(amount)
    except Exception:  # noqa: BLE001 - друк не має падати через мову
        return ""


def mfo_from_iban(acc_number):
    """МФО банку з українського IBAN.

    UA + 2 контрольні + 6 цифр коду банку (це і є МФО) + 19 цифр рахунку.
    Якщо номер не схожий на український IBAN, повертаємо порожнє.
    """
    if not acc_number:
        return ""
    clean = "".join(ch for ch in str(acc_number) if ch.isalnum()).upper()
    if len(clean) != 29 or not clean.startswith("UA") or not clean[2:].isdigit():
        return ""
    return clean[4:10]
