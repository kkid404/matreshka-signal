# Matryoshka Scanner — Сканер сетапов Bybit

Сканер сигналов по стратегии «Матрёшка» на бессрочных USDT-фьючерсах Bybit.  
**НЕ открывает сделки** — выдаёт карточки сигналов для ручного принятия решений.

## Быстрый старт

### Локально

```bash
pip install -r requirements.txt
python src/main.py              # однократный скан
python src/main.py --daemon     # непрерывный режим (каждые 5 мин)
# Логи в консоль + файл
python src/main.py --daemon --log-file scanner.log
 
# С debug-режимом
python src/main.py --daemon --log-file scanner.log --debug

# Telegram replay bot (команды /replay, /strategies, /risk_profile, /set_budget ...)
python src/services/control_bot_service.py

# Web Dashboard (Streamlit MVP)
streamlit run src/services/web_dashboard_streamlit.py
```

### Docker (рекомендуется для сервера)

```bash
# 1. Настрой окружение
cp .env.example .env
# отредактируй .env — впиши токен Telegram-бота и chat_id

# 2. Собери и запусти (scanner + market-data + signal-engine + notification + analytics + control-bot + web-dashboard)
docker compose up -d

# 3. Посмотри логи scanner
docker compose logs -f scanner

# 4. Посмотри логи control-bot
docker compose logs -f control-bot

# 5. Посмотри логи внутренних сервисов
docker compose logs -f market-data
docker compose logs -f notification-service
docker compose logs -f signal-engine
docker compose logs -f analytics
docker compose logs -f web-dashboard

# 6. Остановить
docker compose down
```

Docker автоматически:
- перезапускает сканер и бота при падении (`restart: unless-stopped`)
- сохраняет данные (signals, cache) в папку `data/` через volume
- читает настройки из `.env`

Web dashboard (MVP):
- URL: `http://localhost:8501`
- источник данных: `signal-engine-service` (`/scan/run`, `/replay/run`, `/strategies`)

Схема доставки сигналов в текущей архитектуре:

1. `scanner` запрашивает `signal-engine-service` (`/scan/run`).
2. `signal-engine-service` получает свечи/символы через `market-data-service`.
3. Для каждого найденного сигнала публикуется событие `signal.created`.
4. Независимые подписчики обрабатывают событие:
   - `notification-service` отправляет карточку в Telegram,
   - `analytics-service` обновляет агрегированную статистику.

## Telegram Replay Bot

Бот нужен для удобной проверки стратегий на исторических данных прямо из Telegram.

Команды:

- `/start` — справка
- `/help` — справка
- `/strategies` — активные стратегии
- `/replay SYMBOL LOOKBACK` — прогон истории и отправка по 1 последнему сигналу на каждую стратегию
- `/risk_profile` — показать риск-профиль
- `/set_budget <amount>` — установить бюджет (USDT)
- `/set_risk <percent>` — установить риск на сделку (%)
- `/set_limits <max_positions> <daily_risk_pct>` — лимиты по позициям и дневному риску
- `/risk_help` — справка по risk-management

Пример:

```text
/replay BTCUSDT 1200
```

Доп. переменные `.env`:

- `TELEGRAM_ALLOWED_USER_IDS=12345,67890` — allowlist пользователей (опционально)
- `BOT_DEBUG=true` — debug-логи бота
- `RISK_PROFILES_FILE=data/risk_profiles.json` — путь к файлу профилей риск-менеджмента
- `RISK_QTY_STEP=0` — шаг количества для округления размера позиции
- `RISK_MIN_QTY=0` — минимальный размер позиции
- `RISK_MIN_NOTIONAL=0` — минимальный номинал позиции
- `RISK_PROFILE_BACKEND=file|postgres` — backend хранения риск-профилей
- `POSTGRES_DSN=postgresql://...` — DSN PostgreSQL для риск-профилей
- `REDIS_URL=redis://redis:6379/0` — Redis для dedup signal cache
- `WEB_DASHBOARD_HOST=0.0.0.0` — bind host для Streamlit dashboard
- `WEB_DASHBOARD_PORT=8501` — порт Streamlit dashboard

## Настройки

Все параметры — в `src/core/config.py` → класс `ScannerConfig`.  
Telegram-токены — в `.env` (см. `.env.example`).

| Параметр | По умолчанию | Описание |
|---|---|---|
| `symbols` | BTC, ETH, SOL | Список USDT-перп пар |
| `symbol_filter.min_volume_24h` | 10000000 | Минимальный 24h объём для отбора символов |
| `symbol_filter.min_open_interest` | 0 | Минимальный OI (quote value) для отбора символов |
| `context.ema_period` | 50 | Период EMA на D1 для определения контекста |
| `trigger.min_wick_ratio` | 1.5 | Мин. соотношение тени к телу для свечи отказа |
| `take_profit.rr_target` | 3.0 | Цель Risk-Reward |
| `take_profit.ladder_enabled` | false | Включить лесенку TP с частичным закрытием |
| `validation.max_tp_distance_pct` | 30.0 | Ограничение максимальной дистанции TP от entry (реалистичность TP) |
| `validation.min_sl_atr_multiple` / `max_sl_atr_multiple` | 0.1 / 8.0 | ATR-фильтр дистанции стоп-лосса |
| `validation.max_tp_atr_multiple` | 20.0 | ATR-фильтр дистанции тейк-профита |
| `validation.max_candle_gap_factor` | 2.5 | Порог пропусков свечей (gap) для отбраковки символа |
| `validation.max_zero_volume_share` | 0.35 | Порог неликвидности (доля свечей с нулевым объёмом) |
| `levels_mode` | auto | `manual` — ручные уровни, `auto` — авто-уровни (swing + cluster + nearest) |
| `auto_levels.swing_order` | 5 | Порядок фрактала для поиска swing highs/lows |
| `auto_levels.cluster_tolerance_pct` | 0.5 | Допуск (%) для кластеризации близких уровней |
| `auto_levels.nearest_count` | 8 | Кол-во ближайших авто-уровней к reference price |
| `levels_manual` | `{...}` | Словарь символ → список ценовых уровней |
| `enabled_strategies` | `matryoshka, ema_bounce, breakout, engulfing, momentum_break, ema_cross` | Список активных стратегий |

### Уровни

**Ручной режим:** задайте ключевые уровни поддержки/сопротивления в `levels_manual`.  
**Авто-режим:** `levels_mode = "auto"` — фрактальные swing highs/lows + кластеризация + выбор N ближайших уровней.

### Режим касания уровня

- **`range_touch`** — уровень попадает между Low и High свечи
- **`tolerance_touch`** — цена закрытия в пределах допуска % (или множителя ATR) от уровня

### Буфер стоп-лосса

- **`percent`** — буфер = цена × значение / 100
- **`atr`** — буфер = ATR × значение
- **`fixed`** — абсолютное значение в тиках

## Логика стратегий

Подробное описание простым языком — в **[docs/STRATEGY.md](docs/STRATEGY.md)**.

Сканер поддерживает несколько стратегий одновременно:

1. **Matryoshka** — строгий отскок от уровня (редкие, но более «чистые» сигналы)
2. **EMA Bounce** — отскок от EMA21 по тренду D1 (частые сигналы)
3. **Breakout** — пробой уровня с подтверждением объёмом
4. **Engulfing** — свеча поглощения у уровня
5. **Momentum Break** — продолжение импульса после пробоя локального диапазона (частые сигналы)
6. **EMA Cross** — свежий кросс EMA9/EMA21 по тренду D1 (частые сигналы)

### Как получить больше сигналов

Для более частых сигналов оставьте только быстрые стратегии в `src/core/config.py`:

```python
enabled_strategies = [
    "ema_bounce",
    "momentum_break",
    "ema_cross",
]
```

Для более консервативного режима:

```python
enabled_strategies = [
    "matryoshka",
    "breakout",
    "engulfing",
]
```

## Вывод результатов

- **Консоль** — rich-карточки сигналов + сводная таблица
- **Telegram** — карточки сигналов в чат/канал (настраивается в `.env`)
  - включая диапазон приемлемых цен входа (Entry Zone)
  - для replay-бота: блок Risk Management (budget, risk amount, recommended size)
- **JSON** — `data/signals.json`
- **CSV** — `data/signals.csv` (включая `entry_min_price`, `entry_max_price`)

### Что дополнительно проверяется перед сканом

- Пустые/недостаточные исторические данные (D1/H4)
- Неликвидные пары (слишком высокая доля свечей с нулевым объёмом)
- Пропуски свечей и нарушения порядка времени
- Реалистичность TP и ATR-ограничения по дистанциям SL/TP

## Тесты

```bash
pytest tests/ -v
```

Покрыты юнит- и интеграционные сценарии: индикаторы, сигнал-детектор, probability, risk profile, position sizing, replay/risk команды Telegram-бота.

## Структура проекта

```
├── src/                        # Исходный код
│   ├── main.py                 #   Точка входа scanner runtime (single/daemon/replay CLI)
│   ├── application/            #   Use-cases и orchestration
│   ├── core/                   #   Домен: models/config/signal_detector/position_sizing/risk_profile и др.
│   ├── infrastructure/         #   HTTP-клиенты и кодеки
│   ├── services/               #   Сервисы: control-bot, signal-engine, notification
│   ├── strategies/             #   Набор торговых стратегий
│   └── telegram_notifier.py    #   Форматирование/отправка Telegram-карточек
├── tests/                      # Юнит-тесты
│   ├── test_indicators.py
│   ├── test_signal_detector.py
│   ├── test_probability.py
│   ├── test_auto_levels.py
│   ├── test_risk_profile.py
│   ├── test_position_sizing.py
│   ├── test_control_bot_risk_commands.py
│   └── test_signal_card_entry_range.py
├── docs/                       # Документация
│   ├── STRATEGY.md             #   Описание стратегии простым языком
│   ├── LEARNING.md             #   Как учиться торговать через бота
│   ├── ROADMAP.md              #   План разработки
│   ├── RISK_MANAGEMENT_PLAN.md #   План и статус risk-management
│   └── WEB_DASHBOARD_PLAN.md   #   План реализации web-dashboard
├── data/                       # Выходные файлы (gitignored)
├── Dockerfile                  # Docker-образ
├── docker-compose.yml          # Запуск на сервере
├── .env.example                # Шаблон переменных окружения
├── .gitignore
├── requirements.txt
└── README.md
```

## Документация

- **[docs/STRATEGY.md](docs/STRATEGY.md)** — как работает стратегия (для начинающих)
- **[docs/THEORY.md](docs/THEORY.md)** — теория по всем стратегиям: логика, слабые места, фильтры
- **[docs/LEARNING.md](docs/LEARNING.md)** — как научиться торговать через бота
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — план разработки
- **[docs/WEB_DASHBOARD_PLAN.md](docs/WEB_DASHBOARD_PLAN.md)** — этапы внедрения web-dashboard

## Дорожная карта

Полный план — в **[docs/ROADMAP.md](docs/ROADMAP.md)**.

Ближайшие задачи:
- Интеграционный тест на 1–2 реальных монетах с ручной сверкой
- Персистентное хранилище сигналов (`signal.created`) в PostgreSQL
- История запусков scan/replay в dashboard
- Экспорт таблиц/срезов в CSV/JSON из dashboard
