"""Після встановлення: домашня дія «Зведення» для бухгалтерів і кадровиків.

Замінює домашню дію хабу (l10n_ua_hub), якщо вона там була - «Зведення» стає новою стартовою
сторінкою, «Головна» (хаб) лишається пультом команд, доступним з меню.
"""


def post_init_hook(env):
    action = env.ref("l10n_ua_dashboard.action_ua_dashboard", raise_if_not_found=False)
    if not action:
        return
    hub_action = env.ref("l10n_ua_hub.action_ua_hub_item", raise_if_not_found=False)
    group_xmlids = ["hr.group_hr_user", "account.group_account_user"]
    users = env["res.users"]
    for xmlid in group_xmlids:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            users |= group.all_user_ids
    for user in users:
        if not user.action_id or (hub_action and user.action_id.id == hub_action.id):
            user.action_id = action.id
