#!/usr/bin/env bash
# Підготовка свіжої машини Ubuntu 24.04 під staging і prod odoo-live.
# Запускати від root на новому сервері Hetzner:
#
#   ssh root@<ip> 'bash -s' < deploy/server-setup.sh
#   або: scp deploy/server-setup.sh root@<ip>:/tmp/ && ssh root@<ip> bash /tmp/server-setup.sh
#
# Ідемпотентний: другий запуск нічого не ламає і не переписує ключі.
# Змінні (необов'язкові):
#   REPO_URL      типово git@github.com:workflowcat/odoo-live.git
#   DEPLOY_USER   типово deploy
#   GH_DEPLOY_PUBKEY  відкритий ключ, яким GitHub Actions заходитиме на сервер
#   SWAP_GB       типово 2 (0 - не робити своп)
#
# Що НЕ робить: не створює env-файли з секретами, не ставить тунель, не ставить бази.
# Після нього лишається: покласти deploy/env.staging, deploy/env.prod, deploy/env.tunnel
# і запустити deploy/deploy.sh.
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:workflowcat/odoo-live.git}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_HOME="/home/$DEPLOY_USER"
REPO_DIR="$DEPLOY_HOME/odoo-live"
EDGE_NETWORK="${EDGE_NETWORK:-odoo-edge}"
SWAP_GB="${SWAP_GB:-2}"

[ "$(id -u)" = "0" ] || {
    echo "Запускати від root" >&2
    exit 2
}

say() { echo; echo "== $* =="; }

say "пакети"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw unattended-upgrades \
    postgresql-client python3 rclone jq

say "docker"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        >/etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker --version
docker compose version

say "ротація логів docker"
if [ ! -f /etc/docker/daemon.json ]; then
    mkdir -p /etc/docker
    cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
JSON
    systemctl restart docker
fi

say "автооновлення безпеки"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true

say "фаєрвол: назовні лише ssh"
ufw --force default deny incoming
ufw --force default allow outgoing
ufw allow OpenSSH
ufw --force enable
ufw status verbose

say "користувач $DEPLOY_USER"
id -u "$DEPLOY_USER" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_HOME/.ssh"

if [ -n "${GH_DEPLOY_PUBKEY:-}" ]; then
    touch "$DEPLOY_HOME/.ssh/authorized_keys"
    grep -qF "$GH_DEPLOY_PUBKEY" "$DEPLOY_HOME/.ssh/authorized_keys" ||
        echo "$GH_DEPLOY_PUBKEY" >>"$DEPLOY_HOME/.ssh/authorized_keys"
    chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh/authorized_keys"
    chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
fi

say "ключ розгортання для GitHub"
KEY="$DEPLOY_HOME/.ssh/id_ed25519"
if [ ! -f "$KEY" ]; then
    sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -N "" -C "odoo-live deploy" -f "$KEY"
fi
touch "$DEPLOY_HOME/.ssh/known_hosts"
ssh-keyscan -t ed25519 github.com 2>/dev/null >>"$DEPLOY_HOME/.ssh/known_hosts" || true
sort -u -o "$DEPLOY_HOME/.ssh/known_hosts" "$DEPLOY_HOME/.ssh/known_hosts"
chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh/known_hosts"
chmod 644 "$DEPLOY_HOME/.ssh/known_hosts"
echo
echo "Відкритий ключ - додати в GitHub > workflowcat/odoo-live > Settings > Deploy keys (лише читання):"
cat "$KEY.pub"
echo

say "репозиторій"
if [ ! -d "$REPO_DIR/.git" ]; then
    if sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$REPO_DIR"; then
        echo "склоновано в $REPO_DIR"
    else
        echo "Клон не вдався - спершу додайте ключ вище в Deploy keys, потім запустіть скрипт ще раз."
    fi
else
    echo "$REPO_DIR уже є"
fi
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$REPO_DIR/deploy/backups" \
    "$REPO_DIR/deploy/backups/prod" "$REPO_DIR/deploy/backups/staging" 2>/dev/null || true

say "мережа docker для тунелю"
docker network inspect "$EDGE_NETWORK" >/dev/null 2>&1 || docker network create "$EDGE_NETWORK" >/dev/null
echo "$EDGE_NETWORK на місці"

say "своп ${SWAP_GB}G"
if [ "$SWAP_GB" != "0" ] && [ ! -f /swapfile ]; then
    fallocate -l "${SWAP_GB}G" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
free -h | head -3

say "cron резервних копій"
cat >/etc/cron.d/odoo-live-backup <<CRON
# Копії баз odoo-live. Час у UTC.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# щодня о 00:20 UTC (03:20 за Києвом влітку) - жива база
20 0 * * *   $DEPLOY_USER  $REPO_DIR/deploy/backup.sh daily  >> $REPO_DIR/deploy/backups/backup.log 2>&1
# щонеділі о 00:50 UTC - staging
50 0 * * 0   $DEPLOY_USER  $REPO_DIR/deploy/backup.sh weekly >> $REPO_DIR/deploy/backups/backup.log 2>&1
CRON
chmod 644 /etc/cron.d/odoo-live-backup
echo "/etc/cron.d/odoo-live-backup записано"

say "готово"
cat <<TXT
Лишилося:
  1. Додати ключ вище в GitHub Deploy keys і, якщо клон не пройшов, повторити цей скрипт.
  2. Покласти $REPO_DIR/deploy/env.staging, env.prod, env.tunnel (зразки поруч, значення з 1Password).
  3. sudo -u $DEPLOY_USER $REPO_DIR/deploy/deploy.sh staging --no-pull
     sudo -u $DEPLOY_USER $REPO_DIR/deploy/deploy.sh prod --no-pull
  4. У Cloudflare Zero Trust дописати маршрути тунелю і політику Access.
TXT
