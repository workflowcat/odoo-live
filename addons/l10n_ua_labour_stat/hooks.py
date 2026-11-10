def post_init_hook(env):
    """Розкласти наявні правила зарплати за рядками фонду оплати праці (типові значення)."""
    env["hr.salary.rule"]._ua_pv_fill_defaults()
