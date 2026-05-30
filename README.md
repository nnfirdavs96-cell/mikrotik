# WiFi Access Manager

Система управления платным доступом к интернету через **MikroTik** (Captive
Portal / Hotspot / firewall address-list). Клиент подключается к Wi-Fi, сам
проходит регистрацию через мобильный портал (телефон → SMS/OTP → тариф →
оплата), после чего ему **автоматически** открывается интернет. Администратор
управляет всем из web-панели.

> Управление MikroTik выполняется **только через RouterOS API** (порты `8728` /
> `8729`-SSL). SSH / telnet / WinBox / CLI не используются.

---

## Содержание

1. [Возможности](#возможности)
2. [Архитектура](#архитектура)
3. [Стек](#стек)
4. [Быстрый старт](#быстрый-старт)
5. [Конфигурация (.env)](#конфигурация-env)
6. [Настройка MikroTik](#настройка-mikrotik)
7. [Админ-панель](#админ-панель)
8. [Клиентский портал](#клиентский-портал)
9. [Режимы доступа](#режимы-доступа)
10. [Фоновые задачи (scheduler)](#фоновые-задачи-scheduler)
11. [Интеграции SMS и оплаты](#интеграции-sms-и-оплаты)
12. [REST API](#rest-api)
13. [Модели БД](#модели-бд)
14. [Деплой (systemd)](#деплой-systemd)
15. [Безопасность](#безопасность)
16. [Диагностика проблем](#диагностика-проблем)
17. [Структура проекта](#структура-проекта)
18. [Статус и дальнейшее развитие](#статус-и-дальнейшее-развитие)

---

## Возможности

**Клиентский портал**
- Регистрация по номеру телефона, подтверждение через SMS/OTP (с TTL и
  rate-limit), выбор тарифа, оплата, автоматическая активация интернета.
- IP/MAC определяются автоматически из DHCP lease (или hotspot host) — клиент
  их не вводит.
- Личный кабинет: вход по номеру, история платежей, **продление тарифа** без
  повторной регистрации.
- Captive-редирект: портал открывается автоматически («Войти в сеть»).

**Админ-панель**
- Dashboard со статистикой, управление MikroTik (CRUD + Test Connection).
- Клиенты: поиск/фильтр, activate/deactivate/block/delete/edit, ручная
  привязка устройства из DHCP, редактируемые MAC/IP.
- Подключенные клиенты (DHCP leases) с действиями прямо в таблице.
- Точки доступа (CAPsMAN: CAP + Wi-Fi клиенты, hotspot-сессии).
- Тарифы, платежи, SMS/OTP логи, расширенные access logs (actor/phone/mac/ip).
- **Firewall** — применение правил MikroTik из UI по кнопке.
- **Интеграции** — настройка SMS/оплаты и режима доступа из UI.
- Синхронизация с MikroTik, настройки.
- Светлая/тёмная тема, скрывающийся сайдбар, многослойный «водяной» фон.

**Управление доступом** (переключаемый режим)
- `address_list` — IP клиента в firewall `allowed_clients` + ограничение
  скорости по тарифу через simple queue.
- `hotspot` — hotspot-user по MAC (enable/disable + сброс сессии).

**Автоматизация**
- Авто-деактивация по истечению тарифа (scheduler).
- Контроль трафика по тарифу (по счётчикам queue).
- Периодическая синхронизация IP/hostname/last_seen из DHCP leases.

**Безопасность**
- Пароль MikroTik шифруется в БД (Fernet), пароль админа — hash, OTP — hash.
- REST API защищён `X-API-Key`, все действия пишутся в access logs.

---

## Архитектура

```
[Клиент Wi-Fi] --DHCP--> [MikroTik контроллер (CAPsMAN)] <--RouterOS API--> [Backend]
       |                         |  (раздаёт IP, гейтит доступ)                  |
       |                         +-- CAP 1 ... CAP N (точки доступа)             |
       \------- HTTP --> [Captive Portal /portal] -----------------------------/
                                                          [SQLite/PostgreSQL] + [Admin /admin]
```

- Один главный MikroTik — **контроллер** (CAPsMAN), к нему подключены точки
  доступа (CAP). Управляет точками сам MikroTik; приложение работает только с
  контроллером.
- DHCP-сервер один (на контроллере) → IP/MAC клиента определяются независимо от
  того, к какой CAP он подключён; роуминг между CAP не рвёт сессию.
- Доступ гейтится на контроллере (`allowed_clients` + firewall, либо hotspot) —
  одинаково для всех точек.

**Поток клиента:**
```
Wi-Fi → DHCP → /portal: backend берёт IP (request.client.host) → по RouterOS API
находит DHCP lease (или hotspot host) → MAC/hostname → телефон → OTP →
тариф → оплата → status=active, expires_at=now+дни, доступ открыт на MikroTik
→ интернет. По истечению/превышению трафика scheduler деактивирует.
```

---

## Стек

Python 3.10+ · FastAPI · SQLAlchemy 2 · Jinja2 · Bootstrap 5.3 · Uvicorn ·
APScheduler · cryptography (Fernet) · passlib · httpx · **librouteros**
(RouterOS API). БД: SQLite (по умолчанию), легко переключается на PostgreSQL
через `DATABASE_URL`.

---

## Быстрый старт

### Ubuntu / Debian
```bash
apt update && apt install -y python3 python3-venv python3-pip git

cd /opt
git clone https://github.com/nnfirdavs96-cell/mikrotik.git wifi-access-manager
cd wifi-access-manager

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # отредактируйте секреты
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### CentOS / Rocky
```bash
dnf install -y python3 python3-pip git
# далее так же: venv, pip install, cp .env, uvicorn
```

После запуска:
- Админка: `http://SERVER_IP:8000/admin` (логин/пароль из `.env`)
- Портал: `http://SERVER_IP:8000/portal`
- API docs (Swagger): `http://SERVER_IP:8000/docs`

При первом запуске автоматически создаются таблицы, первый администратор (из
`.env`) и примеры тарифов. Схема БД авто-мигрируется (добавление новых колонок).

---

## Конфигурация (.env)

Все настройки — через `.env` (см. `.env.example`). Часть из них можно менять и
из админки (раздел «Интеграции») — значения в БД переопределяют `.env`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `APP_NAME` | WiFi Access Manager | Название |
| `APP_HOST` / `APP_PORT` | 0.0.0.0 / 8000 | Хост/порт |
| `DATABASE_URL` | sqlite:///./wifi_access.db | БД (PostgreSQL: `postgresql+psycopg2://...`) |
| `SECRET_KEY` | change_this | Подпись сессий |
| `API_SECRET_KEY` | change_this | Ключ REST API (`X-API-Key`) |
| `ENCRYPTION_KEY` | (из SECRET_KEY) | Fernet-ключ шифрования пароля MikroTik |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | admin / … | Первый админ |
| `DEFAULT_ALLOWED_LIST` | allowed_clients | Имя address-list |
| `DEFAULT_GUEST_NETWORK` | 192.168.50.0/24 | Гостевая подсеть |
| `MIKROTIK_TIMEOUT` | 10 | Таймаут API, сек |
| `DEFAULT_CURRENCY` | TJS | Валюта |
| `OTP_LENGTH` / `OTP_TTL_MINUTES` / `OTP_MAX_ATTEMPTS` | 6 / 5 / 3 | OTP |
| `OTP_RATE_LIMIT_MAX` / `_WINDOW_MINUTES` / `OTP_RESEND_COOLDOWN_SECONDS` | 5 / 60 / 60 | Анти-спам OTP |
| `PORTAL_REQUIRE_LEASE` | false | Требовать DHCP lease для регистрации |
| `ACCESS_MODE` | address_list | Режим доступа: `address_list` / `hotspot` |
| `ACCESS_HOTSPOT_PROFILE` | (пусто) | Профиль hotspot-user |
| `APPLY_QUEUES` / `QUEUE_PREFIX` | true / wam | Лимит скорости через simple queue |
| `SCHEDULER_ENABLED` | true | Фоновый планировщик |
| `EXPIRE_INTERVAL_MINUTES` | 10 | Период авто-expire |
| `TRAFFIC_CHECK_ENABLED` / `_INTERVAL_MINUTES` | false / 15 | Контроль трафика |
| `LEASE_SYNC_ENABLED` / `_INTERVAL_MINUTES` | false / 5 | Авто-синхронизация leases |
| `CAPTIVE_REDIRECT_ENABLED` / `CAPTIVE_PORTAL_URL` | false / (пусто) | Captive-редирект |
| `PUBLIC_BASE_URL` | (пусто) | Внешний URL портала (для return/callback/captive) |
| `SMS_PROVIDER` / `SMS_API_*` | mock | SMS-провайдер (см. Интеграции) |
| `PAYMENT_PROVIDER` / `PAYMENT_API_*` | mock | Платёжный шлюз (см. Интеграции) |

Сгенерировать ключи:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                       # SECRET_KEY / API_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
```

---

## Настройка MikroTik

### 1. Включить API
```
/ip service enable api
/ip service set api port=8728
# для SSL:
/ip service enable api-ssl
/ip service set api-ssl port=8729
```

### 2. Отдельный API-пользователь
```
/user group add name=api-policy policy=read,write,api,test
/user add name=api_user group=api-policy password=strong_password
```

### 3. Ограничить API только с IP сервера
```
/ip firewall filter
add chain=input src-address=<SERVER_IP> protocol=tcp dst-port=8728 action=accept comment="Allow API from backend"
add chain=input protocol=tcp dst-port=8728 action=drop comment="Block API from others"
```

### 4. Firewall для гостевой сети
Можно применить **из админки** (страница «Firewall», см. ниже) или вручную:
```
/ip firewall filter
add chain=forward src-address-list=allowed_clients action=accept comment="WAM: allow paid"
add chain=forward src-address=192.168.50.0/24 dst-address=<SERVER_IP> action=accept comment="WAM: allow portal"
add chain=forward src-address=192.168.50.0/24 protocol=udp dst-port=53 action=accept comment="WAM: DNS"
add chain=forward src-address=192.168.50.0/24 protocol=udp dst-port=67,68 action=accept comment="WAM: DHCP"
add chain=forward src-address=192.168.50.0/24 action=drop comment="WAM: block unpaid"

/ip firewall nat
add chain=srcnat src-address=192.168.50.0/24 dst-address=<SERVER_IP> action=accept comment="WAM: no-nat portal"
add chain=srcnat src-address=192.168.50.0/24 action=masquerade comment="WAM: NAT guest"
```

> ⚠️ Перед применением: сделайте **backup** (`/system backup save name=before-wam`),
> тестируйте на **отдельной guest-сети**, не применяйте `drop` без проверки,
> убедитесь, что админ-доступ к роутеру не пропал. Правило `drop` ограничено
> только гостевой подсетью.

### 5. Корректное определение IP клиента
Чтобы backend видел **реальный IP клиента**, а не IP роутера, трафик
гость→сервер портала **не должен маскарадиться** — нужно правило `no-nat`
(см. выше, или включается на странице Firewall). Иначе пользуйтесь ручной
привязкой устройства в админке.

### 6. Captive-редирект (опц.)
В `.env`: `CAPTIVE_REDIRECT_ENABLED=true`, `PUBLIC_BASE_URL=http://<SERVER_IP>:8000`.
На MikroTik — dst-nat неоплаченного HTTP на портал (можно из страницы Firewall):
```
/ip firewall nat
add chain=dstnat src-address=192.168.50.0/24 src-address-list=!allowed_clients \
    protocol=tcp dst-port=80 action=dst-nat to-addresses=<SERVER_IP> to-ports=8000 comment="WAM: captive"
```
> HTTPS не перехватывается (так во всех captive-системах), но окно «Войти в сеть»
> у телефонов появляется по HTTP-пробам и открывает портал.

### 7. Hotspot (опц., для режима `hotspot`)
```
/ip hotspot setup                       # мастер на гостевом интерфейсе/бридже
/ip hotspot walled-garden ip add dst-address=<SERVER_IP> action=accept
# login page настроить на redirect к /portal
```

---

## Админ-панель

`http://SERVER_IP:8000/admin` (вход из `admin_users`, первый — из `.env`).

| Страница | URL | Назначение |
|---|---|---|
| Dashboard | `/admin` | Статистика, статус MikroTik, последние действия |
| Клиенты | `/admin/clients` | Поиск/фильтр, activate/deactivate/block/delete/edit, CSV |
| Редактирование клиента | `/admin/clients/{id}/edit` | Все поля + привязка устройства из DHCP |
| Подключенные | `/admin/connected-clients` | DHCP leases + действия + привязка |
| Точки доступа | `/admin/access-points` | CAPsMAN: CAP, Wi-Fi клиенты, hotspot-сессии |
| MikroTik | `/admin/mikrotik` | CRUD устройств + Test Connection + Set Active |
| Тарифы | `/admin/tariffs` | CRUD тарифов |
| Платежи | `/admin/payments` | Фильтры, CSV |
| SMS / OTP | `/admin/sms-logs` | Логи SMS |
| Access logs | `/admin/logs` | Действия (actor/phone/mac/ip), фильтры |
| Синхронизация | `/admin/sync` | Привести allowed_clients к БД |
| **Firewall** | `/admin/firewall` | Применить правила MikroTik из UI (предпросмотр/применить/удалить) |
| **Интеграции** | `/admin/integrations` | SMS/оплата + режим доступа |
| Настройки | `/admin/settings` | Сводка конфигурации |

Кнопки клиента: **Activate** (status=1, доступ на MikroTik, `activated_at`),
**Deactivate** (status=0, снять доступ), **Block** (status=4), **Delete**
(удалить + снять доступ), **Edit** (все поля). MAC/IP редактируемы и
привязываются из списка DHCP leases.

---

## Клиентский портал

`http://SERVER_IP:8000/portal` — адаптирован под телефон.

| Шаг | URL |
|---|---|
| Приветствие | `/portal` |
| Ввод телефона | `/portal/phone` → `/portal/send-otp` |
| Подтверждение OTP | `/portal/verify` → `/portal/verify-otp` |
| Выбор тарифа | `/portal/tariffs` → `/portal/select-tariff` |
| Оплата | `/portal/payment` → `/portal/create-payment` → `/portal/mock-pay` |
| Успех / ошибка | `/portal/success` / `/portal/payment-failed` |
| Личный кабинет | `/portal/login` → `/portal/cabinet` (статус, история, продление) |

Для MVP OTP-код показывается на экране (mock SMS), оплата — кнопкой «Тестовая
оплата». При истечении тарифа продление **добавляет** дни к текущему сроку.

---

## Режимы доступа

Переключается в **Интеграции → Режим доступа** или `ACCESS_MODE` в `.env`:

- **`address_list`** (по умолчанию): activate → IP в `allowed_clients`
  (+ simple queue по тарифу); deactivate → удаление по `client_id`/IP. Просто и
  надёжно для одного контроллера.
- **`hotspot`**: activate → создать/включить hotspot-user по MAC (+ опц.
  профиль); deactivate → отключить и сбросить активную сессию. Требует
  настроенного Hotspot и MAC у клиента.

Кнопки, портал и планировщик работают в обоих режимах.

---

## Фоновые задачи (scheduler)

Встроенный APScheduler (`SCHEDULER_ENABLED=true`):
- **expire** (`EXPIRE_INTERVAL_MINUTES`): деактивирует клиентов с истёкшим
  `expires_at` (status=expired), снимает доступ.
- **traffic** (`TRAFFIC_CHECK_ENABLED`): читает байты simple queue и деактивирует
  при превышении `traffic_limit` тарифа.
- **lease sync** (`LEASE_SYNC_ENABLED`): обновляет IP/hostname/`last_seen`
  клиентов по MAC из DHCP leases.

Альтернатива через cron / API: `POST /api/tasks/expire-clients`.

---

## Интеграции SMS и оплаты

Страница **Интеграции** (`/admin/integrations`) — настройка без правки `.env`
(значения сохраняются в БД и переопределяют `.env`; секретные ключи маскируются).

- **SMS**: `mock` (код в логах/на экране) или `http` — любой REST-шлюз
  (URL, ключ, метод GET/POST, имена полей телефон/текст/отправитель, JSON/form).
  Кнопка «Тест SMS».
- **Оплата**: `mock` (тест-кнопка) или `http` — создание платежа + редирект на
  страницу шлюза; подтверждение через webhook `POST /api/payments/webhook`
  (заголовок `X-API-Key`), возврат на `PAYMENT_RETURN_URL`.

---

## REST API

Все эндпоинты, кроме `/health`, требуют заголовок `X-API-Key: <API_SECRET_KEY>`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Статус API / БД / MikroTik (без ключа) |
| GET | `/api/clients` | Список клиентов (`?q=`, `?status=`) |
| GET | `/api/clients/{id}` | Один клиент |
| PUT | `/api/clients/{id}` | Изменить клиента |
| DELETE | `/api/clients/{id}` | Удалить (снять доступ, если активен) |
| POST | `/api/clients/{id}/activate` · `/deactivate` · `/block` | Управление |
| POST | `/api/clients/by-mac/{mac}/activate` · `/deactivate` | По MAC |
| POST | `/api/clients/{id}/bind-device` | Привязать MAC/IP/hostname |
| GET | `/api/connected-clients` | DHCP leases активного устройства |
| GET | `/api/mikrotik` · POST `/api/mikrotik` | Список / добавить устройство |
| POST | `/api/mikrotik/{id}/test` | Проверить соединение |
| GET | `/api/mikrotik/{id}/dhcp-leases` · `/connected-clients` | Данные роутера |
| GET | `/api/mikrotik/{id}/capsman` · `/hotspot-hosts` | CAPsMAN / Hotspot |
| POST | `/api/sync/mikrotik` · `/api/sync/mikrotik/{id}` | Синхронизация |
| POST | `/api/payments/webhook` | Webhook оплаты |
| POST | `/api/tasks/expire-clients` | Деактивация по истечению |

Примеры:
```bash
curl http://SERVER_IP:8000/health
curl http://SERVER_IP:8000/api/clients -H "X-API-Key: SECRET"
curl -X POST http://SERVER_IP:8000/api/clients/1/activate -H "X-API-Key: SECRET"
curl -X POST http://SERVER_IP:8000/api/sync/mikrotik -H "X-API-Key: SECRET"
```

---

## Модели БД

| Таблица | Назначение |
|---|---|
| `admin_users` | Администраторы (пароль — hash) |
| `mikrotik_devices` | Роутеры (пароль шифруется, `guest_network`, статус) |
| `clients` | Клиенты: phone, mac/ip, hostname, status, tariff, expires_at, last_seen |
| `tariffs` | Тарифы: цена, срок, скорость, трафик |
| `otp_codes` | OTP (hash, TTL, попытки) |
| `sms_logs` | Логи SMS |
| `payments` | Платежи (статус, провайдер, paid_at) |
| `access_logs` | Действия: action, actor, phone/mac/ip, статусы, результат/ошибка |
| `app_settings` | Runtime-настройки интеграций/режима (поверх `.env`) |

Статусы клиента: `0` inactive · `1` active · `2` pending_payment · `3` expired ·
`4` blocked.

Миграции: схема авто-добавляет недостающие колонки при старте. Для управляемых
миграций есть Alembic (`alembic upgrade head`).

---

## Деплой (systemd)

```bash
cp systemd/wifi-access-manager.service /etc/systemd/system/
nano /etc/systemd/system/wifi-access-manager.service   # проверьте пути
systemctl daemon-reload
systemctl enable --now wifi-access-manager
systemctl status wifi-access-manager
journalctl -u wifi-access-manager -f
```

Юнит запускает службу под `www-data`. Поскольку SQLite пишет в каталог проекта,
выдайте права:
```bash
chown -R www-data:www-data /opt/wifi-access-manager
```

Обновление:
```bash
cd /opt/wifi-access-manager && git pull origin main && \
venv/bin/pip install -r requirements.txt && \
chown -R www-data:www-data /opt/wifi-access-manager && \
systemctl restart wifi-access-manager
```

Для production рекомендуется reverse-proxy (nginx/Caddy) с HTTPS.

---

## Безопасность

1. Админка защищена логином/паролем; пароль — hash (pbkdf2).
2. Пароль MikroTik **шифруется** в БД (Fernet, `ENCRYPTION_KEY`).
3. OTP хранится только как salted-hash; есть rate-limit.
4. REST API — заголовок `X-API-Key`.
5. Все действия логируются в `access_logs` (actor/phone/mac/ip).
6. API MikroTik **нельзя** открывать в интернет; разрешать только с IP сервера.
7. Для production: API-SSL 8729, HTTPS для портала/админки, отдельная guest-сеть.
8. Смените `SECRET_KEY`, `API_SECRET_KEY`, `ADMIN_PASSWORD`, задайте
   `ENCRYPTION_KEY` до ввода реальных данных.

---

## Диагностика проблем

| Симптом | Причина / решение |
|---|---|
| `attempt to write a readonly database` | Каталог/БД принадлежат root, служба под www-data → `chown -R www-data:www-data /opt/wifi-access-manager` |
| `detected dubious ownership` (git) | `git config --global --add safe.directory /opt/wifi-access-manager` |
| `address already in use :8000` | Запущен старый процесс → `systemctl restart` или `pkill -f "uvicorn app.main"` |
| В клиенте виден IP роутера, MAC пустой | Трафик гость→портал маскарадится → добавьте `no-nat` (Firewall) или привяжите устройство вручную |
| `Test Connection` = error | На роутере выключен `api`, неверный порт/SSL, firewall роутера не пускает IP сервера |
| Портал не открывается у гостя | Нет правила allow к серверу портала / DNS; проверьте firewall и `PUBLIC_BASE_URL` |
| `librouteros not installed` | `pip install -r requirements.txt` в активированном venv |

`/health` показывает статус БД и MikroTik.

---

## Структура проекта

```
app/
  main.py  config.py  database.py  models.py  schemas.py  auth.py  crypto.py  dependencies.py
  mikrotik/   client.py  service.py
  services/   clients.py  access_control.py  sync.py  expire.py  traffic.py  scheduler.py
              mikrotik_devices.py  sms.py  otp.py  payments.py  tariffs.py  portal.py
              firewall.py  settings_store.py  logs.py
  routers/    admin.py  portal.py  api_clients.py  api_mikrotik.py  api_sync.py
              api_health.py  api_payments.py  api_tasks.py  api_compat.py
  templates/  base.html  login.html  admin_*.html  portal_*.html
  static/     css/style.css  js/app.js
alembic/      env.py  versions/0001_initial.py
systemd/      wifi-access-manager.service
requirements.txt  .env.example  README.md
```

---

## Статус и дальнейшее развитие

**Готово:** портал + кабинет + продление, админ-панель (вкл. Firewall и
Интеграции из UI), MikroTik RouterOS API (DHCP, address-list, queues, CAPsMAN,
Hotspot), два режима доступа, captive-редирект, scheduler (expire/traffic/lease),
шифрование пароля, rate-limit OTP, расширенные логи, CSV-экспорт, REST API,
светлая/тёмная тема + многослойный «водяной» фон.

**Можно развивать:** полноценный hotspot-as-access с авто-логином, реальные
пресеты SMS/платёжных провайдеров под конкретные сервисы, модальное
редактирование и авто-refresh таблиц, биллинг/отчётность, мультиязычность.

> **MVP-замечание:** при `PORTAL_REQUIRE_LEASE=false` портал работает даже без
> доступного MikroTik (удобно для теста). В production ставьте `true` и
> настройте firewall + определение IP.
