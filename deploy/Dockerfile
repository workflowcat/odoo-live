# Серверний образ: Odoo 19 CE + наші і OCA модулі + pypdf.
# Контекст збірки - корінь репозиторію (див. deploy/docker-compose.server.yml):
#   docker build -f deploy/Dockerfile -t odoo-live-server:<тег> .
#
# Відмінності від odoo/Dockerfile (образ для Cloudflare Containers на базу Supabase):
#   - pypdf у самому образі, а не `pip install` у кожному разовому контейнері;
#   - конфіг без db_sslmode=require: Postgres стоїть поруч, у тій самій мережі docker;
#   - вхідна точка не створює базу і не ставить модулі - це робить deploy/deploy.sh.
FROM odoo:19

USER root
# pypdf потрібен друку первинних документів (l10n_ua_docs); в образі odoo:19 його немає
RUN pip install --no-cache-dir --break-system-packages pypdf
COPY addons /mnt/extra-addons
COPY deploy/odoo.server.conf /etc/odoo/odoo.server.conf
# Той самий конфіг ще й під звичним іменем: scripts/demo_hire.py запускає
# `odoo shell -c /etc/odoo/odoo.conf` з власними --db_* і чекає знайти addons_path
COPY deploy/odoo.server.conf /etc/odoo/odoo.conf
COPY deploy/entrypoint.sh /usr/local/bin/odoo-server-entrypoint
RUN chmod +x /usr/local/bin/odoo-server-entrypoint \
    && chown -R odoo:odoo /mnt/extra-addons /etc/odoo
USER odoo

EXPOSE 8069 8072
ENTRYPOINT ["/usr/local/bin/odoo-server-entrypoint"]
CMD []
