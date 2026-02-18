# План декомпозиции Matryoshka Scanner на микросервисы

## 1) Что есть сейчас (по коду)

Сейчас проект — **модульный монолит** с двумя точками входа:

1. `src/main.py` — сканер (single/daemon/replay) + отправка в Telegram + сохранение в JSON/CSV.
2. `src/telegram_bot.py` — long-polling Telegram-бот для команды `/replay`.

Ключевые признаки «каши», которые мешают росту:

- В `main.py` смешаны orchestration, бизнес-логика, инфраструктура и CLI.
- Replay-логика дублируется между `main.py` и `telegram_bot.py`.
- Telegram-интеграция напрямую встроена в runtime сканера.
- Нет явных контрактов между подсистемами (данные, сигналы, уведомления).

## 2) Целевая архитектура (минимально-реалистичная)

Важно: для текущего масштаба не стоит делать 10+ сервисов. Оптимально начать с **4 сервисов**.

### Сервис A — `market-data-service`
**Ответственность:**
- Получение символов и свечей с Bybit через `ccxt`.
- Нормализация таймфреймов, ретраи, пагинация.

**Сейчас в коде:**
- `src/data_fetcher.py`

**Контракт (пример):**
- REST/gRPC:
  - `GET /symbols?mode=top_n&n=100`
  - `GET /candles?symbol=BTCUSDT&tf=4h&limit=1000`

---

### Сервис B — `signal-engine-service`
**Ответственность:**
- Прогон стратегий и формирование `SignalCard`.
- Дедупликация сигналов, запуск daemon-сканов.
- Replay-расчёт для символа/периода.

**Сейчас в коде:**
- `src/main.py` (оркестрация скана, replay)
- `src/strategies/*`
- `src/probability.py`, `src/levels.py`, `src/cache.py`, `src/models.py`

**Контракт (пример):**
- `POST /scan/run` → список сигналов
- `POST /replay/run` → по 1 последнему сигналу на стратегию
- Публикация событий: `signal.created`

---

### Сервис C — `notification-service`
**Ответственность:**
- Форматирование карточек и доставка уведомлений.
- Каналы: Telegram (первый), позже webhook/email.

**Сейчас в коде:**
- `src/telegram_notifier.py`
- часть форматирования/отправки из `src/main.py`, `src/telegram_bot.py`

**Контракт (пример):**
- Подписка на `signal.created`
- `POST /notify/text`
- `POST /notify/signal-card`

---

### Сервис D — `control-bot-service`
**Ответственность:**
- Telegram long-polling/webhook, команды `/help`, `/strategies`, `/replay`.
- Авторизация пользователей (`allowed_user_ids`).
- Инициирование replay через API `signal-engine-service`.

**Сейчас в коде:**
- `src/telegram_bot.py`

**Контракт (пример):**
- `POST /commands/replay` (внутренне вызывает `signal-engine-service`)

## 3) Схема взаимодействия

1. `control-bot-service` получает `/replay`.
2. Вызывает `signal-engine-service /replay/run`.
3. `signal-engine-service` получает свечи из `market-data-service`.
4. `signal-engine-service` публикует `signal.created`.
5. `notification-service` отправляет карточки в Telegram.

Для daemon-скана:
1. Планировщик внутри `signal-engine-service` запускает `scan/run`.
2. Новые сигналы публикуются как события.
3. `notification-service` рассылает уведомления.

## 4) Данные и инфраструктура

Рекомендуемый минимальный стек:

- **PostgreSQL** — история сигналов, replay-джобы, аудит команд.
- **Redis** — кэш/дедуп и rate-limit.
- **NATS или Redis Streams** — шина событий `signal.created`.
- **API Gateway (опционально на старте)** — единая внешняя точка доступа.

## 5) Границы ответственности (чтобы не размылись снова)

- `market-data-service` **не знает** о стратегиях и Telegram.
- `signal-engine-service` **не отправляет** сообщения напрямую.
- `notification-service` **не считает** сигналы.
- `control-bot-service` **не содержит** торговой логики, только управление.

## 6) Пошаговая миграция без «большого взрыва»

### Этап 0 — Подготовка (1–2 дня)
- Внутри текущего репо разложить код по пакетам `application/domain/infrastructure` (без изменения поведения).
- Вынести replay/use-cases в отдельный модуль, чтобы убрать дубли из `main.py` и `telegram_bot.py`.

### Этап 1 — Выделить `notification-service` (самый простой)
- Перенести `telegram_notifier.py` в отдельный сервис.
- В монолите оставить HTTP-клиент уведомлений.

### Этап 2 — Выделить `control-bot-service`
- `telegram_bot.py` вынести в отдельный контейнер/сервис.
- Бот перестаёт напрямую импортировать scan/replay функции, ходит в API движка.

### Этап 3 — Выделить `signal-engine-service`
- Сканы/стратегии/replay переезжают в отдельный сервис.
- Текущий `main.py` становится thin-runner или удаляется.

### Этап 4 — Выделить `market-data-service`
- Общая точка доступа к свечам/символам.
- Добавить кэш свечей и ограничение по API-лимитам.

### Этап 5 — Перевод на событийную модель
- Внедрить `signal.created`.
- Уведомления и аналитика подписываются независимо.

## 7) Предлагаемая структура репозитория (target)

```text
/services
  /market-data-service
  /signal-engine-service
  /notification-service
  /control-bot-service
/libs
  /contracts           # pydantic-схемы API/events
  /observability       # логирование, tracing, общие middleware
/infrastructure
  docker-compose.yml
  k8s/ (опционально позже)
/docs
  MICROSERVICES_PLAN.md
```

## 8) Риски и как их снизить

- **Риск:** рост сложности из-за сетевых вызовов.
  - **Мера:** сначала 2 сервиса (engine + bot), остальные выделять постепенно.
- **Риск:** рассинхрон контрактов.
  - **Мера:** общий пакет `/libs/contracts` + контрактные тесты.
- **Риск:** деградация скорости replay.
  - **Мера:** кэш свечей в Redis, батч-запросы в data-service.

## 9) Что делать прямо сейчас (практичный MVP)

1. Удалить дубли replay-логики, оставить единый use-case.
2. Вынести Telegram-отправку в отдельный HTTP-сервис (`notification-service`).
3. Переключить `telegram_bot.py` на вызов API replay вместо прямого импорта функций.
4. Только после этого выделять `market-data-service`.

---

Этот путь даёт управляемую эволюцию: от текущего рабочего монолита к микросервисам без остановки разработки и без высокорискового рефакторинга одним большим коммитом.
