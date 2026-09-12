"""Після встановлення: домашня дія «Період» для бухгалтерів і кадровиків.

«Період» - робоче місце місяця, тому воно і має відкриватися першим. Раніше
домашньою дією було «Зведення» (аналітика) або «Пульт команд» (навігація).
"""


def post_init_hook(env):
    action = env.ref("l10n_ua_period.action_ua_period", raise_if_not_found=False)
    if not action:
        return
    # дії різних моделей (client і act_window), тому збираємо саме id
    replace = []
    for xmlid in ("l10n_ua_dashboard.action_ua_dashboard", "l10n_ua_hub.action_ua_hub_item"):
        old = env.ref(xmlid, raise_if_not_found=False)
        if old:
            replace.append(old.id)
    users = env["res.users"]
    for xmlid in ("hr.group_hr_user", "account.group_account_user"):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            users |= group.all_user_ids
    for user in users:
        if not user.action_id or user.action_id.id in replace:
            user.action_id = action.id
