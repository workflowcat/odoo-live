"""Після встановлення: відкривати «Головну» одразу для бухгалтерів і кадровиків, якщо у них ще немає власної домашньої дії."""


def post_init_hook(env):
    action = env.ref("l10n_ua_hub.action_ua_hub_item", raise_if_not_found=False)
    if not action:
        return
    group_xmlids = ["hr.group_hr_user", "account.group_account_user"]
    users = env["res.users"]
    for xmlid in group_xmlids:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            users |= group.all_user_ids
    for user in users:
        if not user.action_id:
            user.action_id = action.id
