# -*- coding: utf-8 -*-
"""Перенесення наявних даних у накази, щоб журнал реєстрації не був порожній, і виставлення
нумерації так, щоб наступний номер за реєстром і роком був більший за максимальний перенесений.

Номери НЕ переприсвоюються - береться те, що вже записано в ua_order_ref/ua_end_order_ref/
ua.leave.ua_order_ref (текст «Наказ № 23-к від 14.05.2012»)."""
from datetime import date

from .models.ua_hr_order import parse_order_ref


def post_init_hook(env):
    Order = env["ua.hr.order"].sudo()
    Version = env["hr.version"].sudo()
    Leave = env["hr.leave"].sudo()
    Sequence = env["ir.sequence"].sudo()

    max_by_year = {}  # (register, year) -> максимальний перенесений номер

    def track(register, parsed):
        key = (register, parsed["date"].year)
        max_by_year[key] = max(max_by_year.get(key, 0), parsed["number"])

    orders_vals = []

    # hire / wage: за кожним працівником - найраніша версія з ua_order_ref = hire, решта = wage
    versions_by_employee = {}
    for v in Version.search([("ua_order_ref", "!=", False)], order="employee_id, date_version, id"):
        versions_by_employee.setdefault(v.employee_id.id, []).append(v)

    for emp_id, versions in versions_by_employee.items():
        for idx, v in enumerate(versions):
            parsed = parse_order_ref(v.ua_order_ref)
            if not parsed:
                continue
            track("k1", parsed)
            orders_vals.append({
                "name": parsed["token"], "order_type": "hire" if idx == 0 else "wage", "register": "k1",
                "date": parsed["date"], "employee_id": emp_id, "state": "posted", "version_id": v.id,
                "company_id": (v.company_id or v.employee_id.company_id).id,
                "wage": v.wage, "date_from": v.contract_date_start,
            })

    # dismissal: hr.version.ua_end_order_ref
    for v in Version.search([("ua_end_order_ref", "!=", False), ("employee_id", "!=", False)]):
        parsed = parse_order_ref(v.ua_end_order_ref)
        if not parsed:
            continue
        track("k1", parsed)
        orders_vals.append({
            "name": parsed["token"], "order_type": "dismissal", "register": "k1",
            "date": parsed["date"], "employee_id": v.employee_id.id, "state": "posted", "version_id": v.id,
            "company_id": (v.company_id or v.employee_id.company_id).id,
            "date_to": v.contract_date_end, "dismissal_basis": v.ua_dismissal_basis,
        })

    # leave: hr.leave.ua_order_ref
    for lv in Leave.search([("ua_order_ref", "!=", False), ("employee_id", "!=", False)]):
        parsed = parse_order_ref(lv.ua_order_ref)
        if not parsed:
            continue
        track("v2", parsed)
        orders_vals.append({
            "name": parsed["token"], "order_type": "leave", "register": "v2",
            "date": parsed["date"], "employee_id": lv.employee_id.id, "state": "posted", "leave_id": lv.id,
            "company_id": lv.employee_id.company_id.id,
            "date_from": lv.request_date_from, "date_to": lv.request_date_to,
            "leave_type_id": lv.holiday_status_id.id, "sick_number": lv.ua_sick_number,
        })

    # запобіжник: версії або відпустки без працівника (залишки видалених карток) наказів не дають
    orders_vals = [v for v in orders_vals if v.get("employee_id")]
    if orders_vals:
        Order.create(orders_vals)

    # нумерація: для кожного (реєстр, рік) з перенесеними номерами - наступний номер > максимального
    for (register, year), max_num in max_by_year.items():
        code = "ua.hr.order.%s" % register
        seq = Sequence.search([("code", "=", code)], limit=1)
        if not seq:
            continue
        rng = seq._get_current_sequence(date(year, 6, 15))
        if rng.number_next <= max_num:
            rng.write({"number_next": max_num + 1})


def backfill_leave_orders(env):
    """Ідемпотентно: (1) підтягує hr.leave.ua_order_id там, де вже є ua.hr.order з leave_id
    на цю відпустку (наприклад - перенесене post_init_hook до появи поля ua_order_id), і
    (2) створює й проводить наказ В-2 для вже підтверджених (state='validate') наказових
    відпусток, які досі не мають жодного наказу.

    Повертає {"linked": N, "created": N} - скільки записів кожного виду опрацьовано."""
    Leave = env["hr.leave"].sudo()
    Order = env["ua.hr.order"].sudo()

    linked = 0
    orders_with_leave = Order.search([("order_type", "=", "leave"), ("leave_id", "!=", False)])
    for order in orders_with_leave:
        if order.leave_id and not order.leave_id.ua_order_id:
            order.leave_id.ua_order_id = order.id
            linked += 1

    created = 0
    candidates = Leave.search([("state", "=", "validate"), ("ua_order_id", "=", False)])
    for leave in candidates:
        if not leave._ua_order_worthy():
            continue
        leave._ua_create_order()
        created += 1

    return {"linked": linked, "created": created}
