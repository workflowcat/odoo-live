# Odoo 19 CE + Bot&Partners addons, for Cloudflare Containers (linux/amd64) or any Docker host.
# Build: docker build --platform linux/amd64 -t odoo-live ./odoo   (context is the repo root when built by wrangler; see below)
FROM odoo:19
USER root
COPY addons /mnt/extra-addons
COPY odoo/odoo.live.conf /etc/odoo/odoo.conf
COPY odoo/entrypoint.sh /usr/local/bin/odoo-live-entrypoint
RUN chmod +x /usr/local/bin/odoo-live-entrypoint && chown -R odoo:odoo /mnt/extra-addons /etc/odoo
USER odoo
EXPOSE 8069
ENTRYPOINT ["/usr/local/bin/odoo-live-entrypoint"]
