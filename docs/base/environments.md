# Три оточення: Mac, staging, prod

Стан на 2026-09-22. Сервера ще немає: усе нижче написано так, щоб після створення машини
лишилося вставити токени і запустити два скрипти. Файли - у теці `deploy/`.

## Що де

| Оточення | Де живе | База | Адреса | Дані |
| --- | --- | --- | --- | --- |
| Розробка | Mac, docker compose, проєкт `odoo-live-base` | `payroll` (8130), `demo` (8131) | `127.0.0.1` | робочі, одноразові |
| staging | Hetzner, проєкт `odoo-stage`, порт 8140 лише на петлі | `stage` | `https://staging.<домен>` | демо «Ясен Меблі», перезбирається на кожен деплой |
| prod | Hetzner, проєкт `odoo-prod`, порт 8150 лише на петлі | `odoo` | `https://app.<домен>` | живі дані компанії |

Обидва серверні набори стоять на одній машині, але не перетинаються: свій Postgres 17,
свій том, свій Odoo (2 воркери, `proxy_mode`, `dbfilter` на свою базу, вкладення в базі).
Портів назовні немає взагалі: `ufw` пускає лише ssh, а до Odoo веде тільки Cloudflare Tunnel.
Міст `worker/` (OpenDataBot, kyc-service) лишається як є, його ніхто не чіпає.

## Як їде код

1. Кома в `main` - GitHub Actions ганяє `tests` (контракт і тести на свіжій базі).
2. Зелені тести - автоматичний `deploy/deploy.sh staging <sha>`: збірка образу, база `stage`
   з нуля, встановлення модулів, `scripts/demo_business.py` наливає демо-життя, перевірка
   `/web/login` і JSON-RPC `version`. Свіже демо на кожен push, нічого цінного там немає.
3. Andrii дивиться `https://staging.<домен>`.
4. Тег `vX.Y.Z` - робота `deploy-prod` чекає на ручне підтвердження в середовищі `production`,
   потім `deploy/deploy.sh prod vX.Y.Z`: `pg_dump` живої бази в `deploy/backups/prod/`,
   `odoo -u <наші встановлені модулі> --stop-after-init`, перезапуск, та сама перевірка.
5. Раз на день о 00:20 UTC cron знімає копію prod (тримаємо 14), щонеділі - копію staging
   (тримаємо 4). Якщо заданий `RCLONE_REMOTE`, копія ще й їде в S3-сумісне сховище.

Репетиція міграції перед великим релізом:
`deploy/deploy.sh staging main --with-prod-copy` підніме останню копію prod у базі
`stage_prodcopy`, прожене на ній оновлення модулів і вимкне там крони і пошту. Якщо оновлення
на копії впало, на живу базу не викочуємо.

## Що Andrii робить один раз

1. **Сервер.** Hetzner Cloud, Ubuntu 24.04, клас CX32 або CPX31 (4 vCPU, 8 ГБ, 80-160 ГБ NVMe),
   локація Nuremberg або Helsinki. Далі:
   `ssh root@<ip> 'bash -s' < deploy/server-setup.sh`. Скрипт ставить docker, фаєрвол,
   автооновлення, користувача `deploy`, мережу `odoo-edge`, своп, cron копій і друкує
   відкритий ключ. Ключ треба додати в GitHub > `workflowcat/odoo-live` > Deploy keys
   (лише читання) і запустити скрипт ще раз, щоб пройшов клон.
2. **Домен і DNS.** Обрати домен (варіанти: `bp-office.com`, піддомен уже наявного домену).
   Зона має бути в Cloudflare. Записи створює сам тунель, руками в DNS нічого не треба.
3. **Тунель.** Cloudflare Zero Trust > Networks > Tunnels > Create tunnel > Docker.
   Скопіювати токен у `deploy/env.tunnel`. У Public Hostnames додати чотири маршрути:
   `staging.<домен>` на `http://odoo-staging:8069`, той самий хост зі шляхом `/websocket`
   на `http://odoo-staging:8072`, і так само `app.<домен>` на `odoo-prod`.
   Шлях `/websocket` потрібен, бо Odoo з воркерами тримає вебсокети окремим процесом.
4. **Access.** Zero Trust > Access > Applications: два застосунки (`staging.<домен>`,
   `app.<домен>`), політика Allow за поштами команди, метод входу - одноразовий код на пошту
   або Google. Без цього сторінка входу Odoo світитиметься в інтернет.
5. **Секрети.** Заповнити на сервері `deploy/env.staging`, `deploy/env.prod`, `deploy/env.tunnel`
   за зразками поруч і покласти ті самі значення в 1Password:
   `op item edit "odoo-live" --vault ToolKit "STAGE_PG_PASSWORD[password]=..."` і далі за списком.
   У GitHub > Settings > Secrets and variables > Actions додати `DEPLOY_HOST`, `DEPLOY_USER`,
   `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` (і `DEPLOY_PORT`, якщо ssh не на 22).
   У Settings > Environments створити `production` з обов'язковим рецензентом.
6. **Workflow.** Скопіювати `deploy/ci-deploy.yml.example` в `.github/workflows/deploy.yml`
   (ця тека належить іншій сесії, тому копіює людина) і замінити `<домен>`.
7. **Перший запуск.** `deploy/deploy.sh staging --no-pull`, потім `deploy/deploy.sh prod --no-pull`.
   На порожній базі prod скрипт сам поставить `l10n_ua_navigation`, план `ua_psbo`, українську мову.

## Відкат

- **Код.** У `deploy/env.prod` поставити `IMAGE_TAG=<sha попереднього образу>` і запустити
  `deploy/deploy.sh prod --no-pull`. Закріплений тег не перезбирається, якщо такий образ уже
  є на машині. Образи лежать локально; `docker images dp-odoo-server` показує, що є.
- **Дані.** `deploy/restore.sh prod --latest --yes` бере найсвіжішу копію з `deploy/backups/prod/`,
  зупиняє Odoo, перезаливає базу і піднімає назад. Конкретний файл - замість `--latest`
  шлях до нього. Копія перед кожним оновленням модулів лежить там же з іменем `pre-upgrade-*`.
- Відкат коду і даних разом робиться в такому порядку: спершу дані, потім образ тієї ж дати.

## Скільки це коштує

- CX32 (4 vCPU shared, 8 ГБ, 80 ГБ) - близько 14 євро на місяць; CPX31 (4 vCPU AMD, 8 ГБ, 160 ГБ) -
  близько 16 євро. Ціни треба звірити на сайті Hetzner, вони мінялися.
- Два Odoo по 2 воркери плюс два Postgres у 8 ГБ вміщаються, якщо на staging не ганяти
  важкі звіти одночасно з роботою prod. Своп 2 ГБ скрипт створює одразу.
- Cloudflare Tunnel і Access до 50 користувачів - безплатні.
- Резервні копії в S3-сумісному сховищі (Backblaze B2, Hetzner Object Storage) - одиниці євро.
- Перший крок угору, коли стане тісно: CPX41 (8 vCPU, 16 ГБ), без зміни будь-чого в цих файлах.

## Чого ще немає

- Сервер не створений: усе нижче перевірено лише локально, на Mac. Не перевірено: тунель,
  Access, ssh з GitHub Actions, cron, rclone, робота під навантаженням.
- Пошта з Odoo (вихідний SMTP) не налаштована - ні на staging, ні на prod.
- Копію prod (`stage_prodcopy`) видно лише через `?db=`, і для цього треба розширити
  `ODOO_DB_FILTER` у `deploy/env.staging` до `^(stage|stage_prodcopy)$`.
- Пароль Postgres на staging - `odoo`, бо `scripts/demo_hire.py` зашиває `--db_password=odoo`
  у власний виклик `docker compose run odoo shell`. Порт Postgres назовні не публікується,
  база одноразова, але прибрати це варто: один параметр у тому скрипті - і пароль стане
  такий самий сильний, як на prod.
- Моніторинг і сповіщення про падіння: немає. Поки що ознака - лист від cron і `docker ps`.
- Копії не шифруються перед відправкою в хмару.
- Відкат на попередній образ спирається на локальні образи машини; реєстру образів немає.
