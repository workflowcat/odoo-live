"""Сума словами для друкованих форм.

Каса друкує суму прописом. Українські слова дає локаль uk_UA, але вона є не в
кожній базі, тому мову беремо лише тоді, коли вона справді увімкнена; інакше
друкуємо тією мовою, якою працює користувач, і форма все одно будується.
"""


def amount_in_words(env, currency, amount):
    if env["res.lang"].search_count([("code", "=", "uk_UA")]):
        currency = currency.with_context(lang="uk_UA")
    return currency.amount_to_text(amount)
