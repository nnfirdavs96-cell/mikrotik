# WiFi Access Manager

MVP-система управления доступом клиентов к интернету через главный **MikroTik**.
Клиент подключается к Wi-Fi, проходит регистрацию через captive portal (телефон
→ SMS-код → выбор тарифа → оплата), после чего его IP автоматически добавляется
в MikroTik `address-list allowed_clients` и интернет активируется.

Управление MikroTik выполняется **только через RouterOS API** (порты `8728` /
`8729`-SSL). SSH / telnet / WinBox / CLI **не используются**.

---

## Статус и дорожная карта

### ✅ Этап 1 — MVP (готово)

| Блок | Что умеет |
|------|-----------|
| **Client Portal** `/portal` | телефон → SMS/OTP → выбор тарифа → оплата → авто-активация (IP в `allowed_clients`) |
| **Admin Panel** `/admin` | dashboard, MikroTik (CRUD + Test Connection), клиенты (поиск/фильтр/activate/deactivate/block/edit), тарифы, платежи, SMS/OTP-логи, access-логи, синхронизация, настройки, подключенные клиенты |
| **MikroTik module** | RouterOS API: DHCP leases, add/remove/sync `allowed_clients`; не падает при офлайн-роутере |
| **REST API** | `X-API-Key`; clients, mikrotik, sync, payments webhook, tasks/expire, `/health` |
| **Провайдеры** | mock SMS + mock оплата (для теста без внешних сервисов) |
| **Прочее** | session-auth админки (пароль — hash), OTP — hash, Alembic, systemd, авто-сид админа и тарифов |

### ✅ Этап 2 — расширение (готово)

| Фича | Что делает | Флаг в `.env` |
|------|-----------|---------------|
| **Лимит скорости** | simple queue на IP клиента из `tariff.speed_limit` при активации, удаление при деактивации | `APPLY_QUEUES` |
| **Контроль трафика** | планировщик читает байты очереди и деактивирует при превышении `tariff.traffic_limit` | `TRAFFIC_CHECK_ENABLED` |
| **Авто-expire** | встроенный APScheduler вместо cron (старт в lifespan) | `SCHEDULER_ENABLED` |
| **Реальный SMS** | `HTTPSMSProvider` — любой REST SMS-шлюз через `.env` | `SMS_PROVIDER=http` |
| **Реальная оплата** | `HTTPPaymentProvider` — редирект на шлюз + подтверждение по webhook | `PAYMENT_PROVIDER=http` |

Подробности и переменные — в разделе [«Этап 2 (реализовано)»](#этап-2-реализовано).

### 🟡 Этап 3 — в работе

| Фича | Статус |
|------|--------|
| **Шифрование пароля MikroTik** в БД (Fernet, ключ в `.env`, обратная совместимость с plaintext) | ✅ готово |
| **Экспорт CSV** клиентов и платежей (с учётом фильтров) | ✅ готово |
| **Личный кабинет** клиента (вход по номеру, история, продление тарифа) | ✅ готово |
| Автоматический **captive redirect** (hotspot/DNS) | 🔜 |
| **Несколько активных MikroTik** + несколько guest-сетей | 🔜 |
| Готовые пресеты под конкретных SMS/платёжных провайдеров | 🔜 |

### Как это работает (в двух словах)

```
Клиент → Wi-Fi → DHCP (MikroTik выдаёт IP)
   → /portal: backend берёт IP (request.client.host) → по RouterOS API находит
     DHCP lease → получает MAC/hostname
   → клиент вводит телефон → OTP (mock: код в логах/на экране; http: реальный SMS)
   → выбор тарифа → оплата (mock: тест-кнопка; http: редирект на шлюз → webhook)
   → backend: status=active, expires_at=now+дни, IP в allowed_clients,
     (опц.) simple queue со скоростью тарифа
   → MikroTik firewall выпускает allowed_clients в интернет
Планировщик: по истечению срока или превышению трафика → деактивация,
   IP и очередь удаляются из MikroTik.
```

---

## 1. Описание проекта

Система состоит из трёх частей:

| Часть | Назначение |
|------|------------|
| **Admin Panel** (`/admin`) | Управление MikroTik, клиентами, тарифами, платежами, логами; ручная активация/деактивация; синхронизация. |
| **Client Portal** (`/portal`) | Самостоятельная регистрация клиента: телефон → SMS-код → тариф → оплата → доступ. |
| **MikroTik API Service** | Работа с DHCP leases и firewall `address-list` через RouterOS API. |

Стек: Python 3, FastAPI, SQLAlchemy, Alembic, Jinja2, Bootstrap 5, SQLite
(легко переключается на PostgreSQL через `DATABASE_URL`), Uvicorn, librouteros.

## 2. Архитектура работы

```
[Клиент Wi-Fi] --DHCP--> [MikroTik] <--RouterOS API--> [Backend (этот проект)]
        |                                                      |
        \--- HTTP --> [Captive Portal /portal] --------------/
                                                              |
                                          [SQLite/PostgreSQL] + [Admin /admin]
```

- Backend определяет IP клиента (`request.client.host` / `X-Forwarded-For`).
- По IP через RouterOS API находится DHCP lease → берётся MAC и hostname.
- После оплаты IP добавляется в `allowed_clients`, firewall выпускает клиента в интернет.

## 3. Схема работы клиента

```
Wi-Fi → /portal → [IP/MAC из DHCP lease] → ввод телефона → SMS-код →
выбор тарифа → тестовая оплата → IP в allowed_clients → интернет
```

## 4. Схема работы администратора

```
/admin/login → Dashboard → добавить MikroTik → Test Connection →
клиенты / тарифы / платежи / логи → ручная активация/деактивация → Sync
```

## 5. Требования к серверу

- Linux (Ubuntu Server 20.04+/22.04+ или CentOS/Rocky 8+).
- Python 3.10+ (рекомендуется 3.11).
- Сетевой доступ с backend-сервера к MikroTik по API-порту (8728/8729).
- 512 МБ RAM достаточно для MVP.

## 6. Установка на Ubuntu

```bash
apt update
apt install python3 python3-venv python3-pip git -y

cd /opt
git clone <project-url> wifi-access-manager
cd wifi-access-manager

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# отредактируйте .env (пароли, секреты)

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 7. Установка на CentOS / Rocky

```bash
dnf install python3 python3-pip git -y

cd /opt
git clone <project-url> wifi-access-manager
cd wifi-access-manager

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 8. Настройка .env

Все настройки задаются через `.env` (см. `.env.example`):

```
APP_NAME=WiFi Access Manager
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./wifi_access.db
SECRET_KEY=change_this_secret_key
API_SECRET_KEY=change_this_api_key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong_password
DEFAULT_ALLOWED_LIST=allowed_clients
DEFAULT_GUEST_NETWORK=192.168.50.0/24
SMS_PROVIDER=mock
PAYMENT_PROVIDER=mock
DEFAULT_CURRENCY=TJS
PORTAL_REQUIRE_LEASE=false
```

Переход на **PostgreSQL**:

```
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/wifi
```

(установите драйвер: `pip install psycopg2-binary`).

При первом запуске автоматически создаются: первый администратор (из `.env`),
таблицы БД и несколько примеров тарифов.

## 9. Запуск вручную

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Admin panel: `http://SERVER_IP:8000/admin`
- Client portal: `http://SERVER_IP:8000/portal`

### Миграции (Alembic)

Для MVP таблицы создаются автоматически при старте. Для управляемых миграций:

```bash
alembic upgrade head                       # применить миграции
alembic revision --autogenerate -m "msg"   # создать новую миграцию
```

## 10. Настройка systemd

```bash
cp systemd/wifi-access-manager.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wifi-access-manager
systemctl status wifi-access-manager
```

(файл сервиса см. `systemd/wifi-access-manager.service`).

## 11. Настройка MikroTik API

Включить API:

```
/ip service enable api
/ip service set api port=8728
```

Для SSL:

```
/ip service enable api-ssl
/ip service set api-ssl port=8729
```

Создать отдельного пользователя для API:

```
/user group add name=api-policy policy=read,write,api,test
/user add name=api_user group=api-policy password=strong_password
```

Ограничить доступ к API только с IP backend-сервера:

```
/ip firewall filter
add chain=input src-address=<SERVER_IP> protocol=tcp dst-port=8728 action=accept comment="Allow MikroTik API from backend server"
add chain=input protocol=tcp dst-port=8728 action=drop comment="Block MikroTik API from others"
```

## 12. Настройка firewall MikroTik

> ⚠️ **ВНИМАНИЕ перед применением правил:**
> - Сделайте **backup** MikroTik (см. п. 24).
> - Сначала тестируйте на **отдельной guest Wi-Fi** сети.
> - **Не применяйте** правила на основной офисной сети.
> - Сначала добавьте **разрешающие** правила для админской сети.
> - **Не применяйте drop rule** без проверки.
> - API-порт MikroTik **нельзя** открывать в интернет.
> - Разрешите доступ к API только с IP сервера, где работает программа.
> - Для production используйте **API-SSL 8729**.

Пример правил (гостевая сеть `192.168.50.0/24`, backend `<BACKEND_SERVER_IP>`):

```
/ip firewall filter
add chain=forward src-address-list=allowed_clients action=accept comment="Allow paid WiFi clients"
add chain=forward src-address=192.168.50.0/24 dst-address=<BACKEND_SERVER_IP> action=accept comment="Allow access to portal server"
add chain=forward src-address=192.168.50.0/24 protocol=udp dst-port=53 action=accept comment="Allow DNS for guest clients"
add chain=forward src-address=192.168.50.0/24 protocol=udp dst-port=67,68 action=accept comment="Allow DHCP for guest clients"
add chain=forward src-address=192.168.50.0/24 action=drop comment="Block unpaid WiFi clients"

/ip firewall nat
add chain=srcnat src-address=192.168.50.0/24 out-interface-list=WAN action=masquerade comment="NAT guest WiFi"
```

## 13. Настройка guest Wi-Fi сети

- Выделите для гостей отдельную подсеть, например `192.168.50.0/24`.
- Включите на ней DHCP-сервер MikroTik (из него берутся IP/MAC клиентов).
- Backend-сервер должен быть доступен гостям (например `192.168.50.2`).
- Комментарий, который программа пишет в `allowed_clients`:
  `wifi-client | phone=<phone> | mac=<mac> | client_id=<id>`.

## 14. Как открыть web-панель администратора

Откройте `http://SERVER_IP:8000/admin`, войдите с `ADMIN_USERNAME` /
`ADMIN_PASSWORD` из `.env`.

## 15. Как добавить MikroTik через web-панель

`Admin → MikroTik → Добавить MikroTik`. Заполните name, host, port, username,
password, Use SSL, Is Active, comment. Для MVP активным может быть только один
MikroTik — при включении нового активного остальные снимаются с активного.

## 16. Как проверить MikroTik API

В списке MikroTik нажмите **Test Connection** (иконка вилки). Программа
подключится по RouterOS API, обновит `last_status` / `last_error` и покажет
результат. Также можно через REST: `POST /api/mikrotik/{id}/test`.

## 17. Как создать тариф

`Admin → Тарифы → Создать тариф`. Поля: name, description, price, currency,
validity_days, speed_limit (опц.), traffic_limit (опц.), is_active. Для MVP
тариф определяет срок доступа (`validity_days`); скорость/трафик подготовлены в
БД, но не применяются на MikroTik.

## 18. Как клиент проходит регистрацию

1. Подключается к гостевому Wi-Fi.
2. Открывает `http://SERVER_IP:8000/portal`.
3. Вводит **только** номер телефона (IP/MAC берутся из DHCP lease автоматически).
4. Получает SMS-код и подтверждает его.
5. Выбирает тариф.
6. Оплачивает (в MVP — кнопка «Тестовая оплата»).
7. Получает интернет — IP добавляется в `allowed_clients`.

## 19. Как работает SMS mock provider

`SMS_PROVIDER=mock`: SMS не отправляется реально — текст пишется в консольные
логи и таблицу `sms_logs`. Для удобства теста код также показывается на экране
портала. Реальный провайдер подключается реализацией класса `SMSProvider` в
`app/services/sms.py` и регистрацией в `get_sms_provider()`.

## 20. Как работает mock payment provider

`PAYMENT_PROVIDER=mock`: на странице оплаты кнопка «Тестовая оплата» сразу
переводит платёж в статус `paid` и активирует клиента. Реальный электронный
кошелёк подключается реализацией `PaymentProvider` в
`app/services/payments.py` + webhook `POST /api/payments/webhook`.

## 21. Как активируется интернет

После успешной оплаты:
1. `payment.status = paid`, `paid_at = now`.
2. `client.status = 1 (active)`, `activated_at = now`.
3. `client.expires_at = now + tariff.validity_days`.
4. IP клиента добавляется в `allowed_clients` (без дубликатов).
5. В `access_logs` пишется `activate_after_payment`.

## 22. Как деактивируется интернет после окончания тарифа

Задача expire-clients находит клиентов с `expires_at < now` и `status=1`,
ставит `status=3 (expired)`, удаляет IP из `allowed_clients` и пишет лог.

Запуск вручную / по cron:

```bash
curl -X POST http://SERVER_IP:8000/api/tasks/expire-clients -H "X-API-Key: <API_SECRET_KEY>"
```

Пример cron (каждые 10 минут):

```
*/10 * * * * curl -s -X POST http://127.0.0.1:8000/api/tasks/expire-clients -H "X-API-Key: <API_SECRET_KEY>" >/dev/null 2>&1
```

В дальнейшем можно заменить на APScheduler/Celery.

## 23. Как проверить REST API через curl

Все эндпоинты, кроме `/health`, требуют заголовок `X-API-Key: <API_SECRET_KEY>`.

```bash
# Health
curl http://SERVER_IP:8000/health

# Клиенты
curl http://SERVER_IP:8000/api/clients -H "X-API-Key: SECRET"

# Активировать / деактивировать
curl -X POST http://SERVER_IP:8000/api/clients/1/activate   -H "X-API-Key: SECRET"
curl -X POST http://SERVER_IP:8000/api/clients/1/deactivate -H "X-API-Key: SECRET"

# Проверить MikroTik
curl -X POST http://SERVER_IP:8000/api/mikrotik/1/test -H "X-API-Key: SECRET"

# DHCP leases
curl http://SERVER_IP:8000/api/mikrotik/1/dhcp-leases -H "X-API-Key: SECRET"

# Синхронизация
curl -X POST http://SERVER_IP:8000/api/sync/mikrotik -H "X-API-Key: SECRET"

# Expire clients
curl -X POST http://SERVER_IP:8000/api/tasks/expire-clients -H "X-API-Key: SECRET"
```

Полный список эндпоинтов — в интерактивной документации: `http://SERVER_IP:8000/docs`.

### Сводка REST API

| Метод | Путь | Назначение |
|------|------|-----------|
| GET | `/health` | API / БД / MikroTik статус (без ключа) |
| GET | `/api/clients` | Список клиентов (`?q=`, `?status=`) |
| GET | `/api/clients/{id}` | Один клиент |
| PUT | `/api/clients/{id}` | Изменить клиента |
| DELETE | `/api/clients/{id}` | Удалить (с удалением IP, если активен) |
| POST | `/api/clients/{id}/activate` | Активировать |
| POST | `/api/clients/{id}/deactivate` | Деактивировать |
| POST | `/api/clients/{id}/block` | Заблокировать |
| POST | `/api/clients/by-mac/{mac}/activate` | Активировать по MAC |
| POST | `/api/clients/by-mac/{mac}/deactivate` | Деактивировать по MAC |
| GET | `/api/mikrotik` | Список устройств |
| POST | `/api/mikrotik` | Добавить устройство |
| POST | `/api/mikrotik/{id}/test` | Проверить соединение |
| GET | `/api/mikrotik/{id}/dhcp-leases` | DHCP leases |
| GET | `/api/mikrotik/{id}/connected-clients` | Подключенные клиенты |
| POST | `/api/sync/mikrotik` | Синхронизация |
| POST | `/api/payments/webhook` | Webhook оплаты |
| POST | `/api/tasks/expire-clients` | Деактивация по истечению |

## 24. Как сделать backup MikroTik перед применением правил

На MikroTik:

```
/system backup save name=before-wifi-access
/export file=before-wifi-access
```

Скачайте файлы `before-wifi-access.backup` и `before-wifi-access.rsc`
(Files в WinBox/WebFig) и сохраните в безопасном месте. Восстановление:
`/system backup load name=before-wifi-access`.

## 25. Рекомендации по безопасности

1. Админ-панель защищена логином/паролем; пароль хранится как hash.
2. Пароль MikroTik **шифруется в БД** (Fernet) — в открытом виде не хранится (см. `ENCRYPTION_KEY`).
3. Все секреты — через `.env` (не коммитьте `.env` в git, см. `.gitignore`).
4. REST API защищён заголовком `X-API-Key`.
5. OTP не хранится открытым текстом (только salted-hash).
6. API MikroTik **нельзя** открывать в интернет.
7. Для production используйте **API-SSL 8729**.
8. Для production используйте **HTTPS** для portal и admin (reverse proxy: nginx/Caddy).
9. Для production выделите **отдельную guest Wi-Fi** сеть.
10. Ограничьте доступ к API MikroTik только с IP backend-сервера.
11. Смените `SECRET_KEY`, `API_SECRET_KEY`, `ADMIN_PASSWORD` перед запуском.

---

## Структура проекта

```
app/
  main.py            config.py     database.py   models.py
  schemas.py         auth.py       dependencies.py
  mikrotik/          client.py     service.py
  services/          clients.py    access_control.py  logs.py   sync.py
                     mikrotik_devices.py  sms.py  otp.py  payments.py
                     tariffs.py    expire.py  portal.py
  routers/           admin.py      portal.py
                     api_clients.py  api_mikrotik.py  api_sync.py
                     api_health.py   api_payments.py  api_tasks.py
  templates/         (admin_*.html, portal_*.html, base.html, login.html)
  static/            css/style.css  js/app.js
alembic/             env.py  versions/0001_initial.py
systemd/             wifi-access-manager.service
requirements.txt     .env.example  README.md
```

## Статусы клиента

| Код | Статус | Цвет |
|----|--------|------|
| 0 | inactive | красный |
| 1 | active | зелёный |
| 2 | pending_payment | жёлтый |
| 3 | expired | серый |
| 4 | blocked | тёмно-красный |

## Этап 2 (реализовано)

Реализованы 4 фичи второго этапа. Все управляются через `.env`.

### 1. Ограничение скорости по тарифу (simple queues)

При активации клиента, если у тарифа задан `speed_limit`, на MikroTik
создаётся **simple queue** для IP клиента (`max-limit`), при деактивации —
удаляется. Имя очереди: `<QUEUE_PREFIX>-<client_id>`.

- `speed_limit` принимает форматы: `10M` (одинаково на upload/download) или
  `10M/20M` (upload/download).
- Включается флагом `APPLY_QUEUES=true`.

### 2. Контроль трафика по тарифу (квота)

Если у тарифа задан `traffic_limit` (например `5GB`, `500M`), планировщик
периодически читает счётчики байт у simple queue клиента и при превышении
квоты деактивирует его (статус `expired`).

- Включается флагом `TRAFFIC_CHECK_ENABLED=true`.
- Поддерживаемые единицы: `k`, `M`, `G`, `T` (и без единиц — байты).

### 3. Авто-expire через встроенный планировщик (APScheduler)

Вместо cron приложение само запускает фоновый планировщик:
- задача `expire_clients` каждые `EXPIRE_INTERVAL_MINUTES` минут;
- задача контроля трафика каждые `TRAFFIC_CHECK_INTERVAL_MINUTES` (если включена).

Управление: `SCHEDULER_ENABLED=true`. Старый ручной endpoint
`POST /api/tasks/expire-clients` и cron по-прежнему работают.

### 4. Реальный SMS-провайдер (generic HTTP)

`SMS_PROVIDER=http` включает `HTTPSMSProvider` — универсальный клиент под
любой REST SMS API:

```
SMS_PROVIDER=http
SMS_API_URL=https://sms-gateway.example/send
SMS_API_KEY=your_key
SMS_API_METHOD=POST           # GET | POST
SMS_API_AUTH_HEADER=Authorization
SMS_API_AUTH_PREFIX=Bearer    # пробел добавляется автоматически
SMS_PHONE_PARAM=phone         # имя поля для номера
SMS_TEXT_PARAM=text           # имя поля для текста
SMS_SENDER=YourName           # необязательно
SMS_EXTRA_PARAMS={"unicode":1}  # необязательно, JSON
SMS_JSON_BODY=true            # POST как JSON или form
```

Если провайдер другой структуры — достаточно поменять имена полей.

### 5. Реальная оплата (generic HTTP gateway)

`PAYMENT_PROVIDER=http` включает `HTTPPaymentProvider`. Поток:

1. Клиент жмёт «Перейти к оплате» → backend создаёт платёж через
   `PAYMENT_API_URL` и **редиректит** пользователя на платёжную страницу
   (`payment_url` из ответа шлюза).
2. Шлюз после оплаты вызывает наш `POST /api/payments/webhook`
   (`X-API-Key`) со статусом `paid` → клиент активируется, IP добавляется в
   `allowed_clients`.
3. Шлюз возвращает пользователя на `PAYMENT_RETURN_URL` (обычно
   `/portal/success`).

```
PAYMENT_PROVIDER=http
PAYMENT_API_URL=https://pay.example/create
PAYMENT_API_KEY=your_key
PAYMENT_RETURN_URL=https://wifi.example/portal/success
PAYMENT_CALLBACK_URL=https://wifi.example/api/payments/webhook
PAYMENT_PAY_URL_FIELD=payment_url   # поле ответа с URL оплаты
PAYMENT_ID_FIELD=id                 # поле ответа с id платежа
PUBLIC_BASE_URL=https://wifi.example
```

Тело запроса к шлюзу: `amount, currency, client_id, tariff_id, return_url,
callback_url`. Если у твоего шлюза другой формат — скажи, адаптирую провайдер.

> По умолчанию `SMS_PROVIDER=mock` и `PAYMENT_PROVIDER=mock` — всё работает
> без внешних сервисов. Реальные провайдеры включаются сменой значения на
> `http` и заполнением соответствующих переменных.

## Этап 3 (в работе)

### Шифрование пароля MikroTik в БД (готово)

Пароль роутера больше не хранится в открытом виде: колонка `password`
шифруется прозрачным типом `EncryptedString` (Fernet) — в БД лежит токен
вида `gAAAAA...`, а приложение работает с обычным значением.

- **Ключ:** `ENCRYPTION_KEY` в `.env`. Если пусто — ключ детерминированно
  выводится из `SECRET_KEY` (работает без доп. настройки).
- Свой ключ:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- **Обратная совместимость:** старые plaintext-пароли (до включения
  шифрования) читаются как есть. Чтобы зашифровать их — открой устройство в
  админке и пересохрани (Edit → Save) либо нажми Test после ввода пароля.
- ⚠️ Если задал `ENCRYPTION_KEY` и потом его сменил — ранее зашифрованные
  пароли расшифровать не выйдет (придётся ввести заново). Меняешь
  `SECRET_KEY` без отдельного `ENCRYPTION_KEY` — тот же эффект.

### Экспорт CSV (готово)

В админке на страницах **Клиенты** и **Платежи** есть кнопка **«Экспорт CSV»** —
выгружает данные с учётом текущих фильтров (поиск/статус/телефон). Файлы в
UTF-8 с BOM (корректно открываются в Excel).

- Клиенты: `GET /admin/clients.csv?q=&status=`
- Платежи: `GET /admin/payments.csv?status=&phone=`

### Личный кабинет клиента + продление тарифа (готово)

Возвращающийся клиент входит в кабинет по номеру телефона (без повторной
регистрации устройства):

- `/portal/login` → ввод номера → SMS/OTP → `/portal/cabinet`.
- В кабинете: статус, тариф, срок, IP/MAC, **история платежей** и кнопка
  **«Продлить / сменить тариф»**.
- **Продление**: оплата нового тарифа **добавляет** дни к текущему сроку (если
  он ещё активен) или начинает срок заново (если истёк) — логика
  `extend_expiry`. Работает и для mock-, и для реальной оплаты (webhook).
- При входе кабинет обновляет IP/MAC из текущего DHCP lease (если роутер
  доступен), чтобы `allowed_clients` оставался актуальным.

### Остальное по этапу 3

Автоматический captive redirect (hotspot/DNS), несколько активных MikroTik
одновременно и несколько guest-сетей.

> **MVP-замечание:** при `PORTAL_REQUIRE_LEASE=false` портал продолжает работу,
> даже если MikroTik недоступен или DHCP lease не найден (удобно для теста без
> оборудования). В production установите `PORTAL_REQUIRE_LEASE=true`.
