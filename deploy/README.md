# deploy/ - staging і prod на одному сервері

Опис оточень і що робить Andrii один раз - `docs/base/environments.md`. Тут - що є в цій теці.

| Файл | Що це |
| --- | --- |
| `Dockerfile` | серверний образ: Odoo 19 + наші модулі + pypdf; контекст збірки - корінь репозиторію |
| `entrypoint.sh` | складає `/tmp/odoo.conf`, чекає Postgres, запускає `odoo` з переданими аргументами |
| `odoo.server.conf` | статична частина конфігу (без `db_*`, `workers`, `admin_passwd` - їх дописує entrypoint) |
| `docker-compose.server.yml` | спільна частина: Postgres 17, Odoo, томи, ротація логів, healthcheck |
| `docker-compose.staging.yml` | накладка staging (проєкт `odoo-stage`, порт 8140) |
| `docker-compose.prod.yml` | накладка prod (проєкт `odoo-prod`, порт 8150) |
| `docker-compose.tunnel.yml` | один cloudflared на весь сервер, окремий проєкт `odoo-tunnel` |
| `env.*.example` | імена змінних; значення - на сервері і в менеджері паролів |
| `server-setup.sh` | підняти чисту Ubuntu 24.04: docker, ufw, unattended-upgrades, користувач, клон, cron |
| `deploy.sh` | `deploy.sh <staging\|prod> [git-ref]` - код, образ, база, модулі, перезапуск, перевірка |
| `backup.sh` | `backup.sh daily\|weekly` - pg_dump, прибирання старих, за бажанням rclone |
| `restore.sh` | `restore.sh <оточення> <файл.dump>` - відновлення бази, за бажанням з оновленням модулів |
| `ci-deploy.yml.example` | зразок workflow для `.github/workflows/` (та тека належить іншій сесії) |

Швидко:

```bash
deploy/deploy.sh staging                      # main, база stage з нуля + демо-дані
deploy/deploy.sh staging main --with-prod-copy # ще й репетиція міграції на копії prod
deploy/deploy.sh prod v1.4.0                  # pg_dump, оновлення модулів, перезапуск
deploy/backup.sh daily
deploy/restore.sh prod --latest --yes         # відкат живої бази на останню копію
```

Локальна перевірка без сервера (свій проєкт, без тунелю, порт свій):

```bash
deploy/deploy.sh staging --no-pull --no-tunnel --project dp_stage --env-file /tmp/env.dp
docker compose -p dp_stage -f deploy/docker-compose.server.yml -f deploy/docker-compose.staging.yml down -v
```
