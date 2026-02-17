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

# Telegram replay bot (команды /replay, /strategies)
python src/services/control_bot_service.py
```

### Docker (рекомендуется для сервера)

```bash
# 1. Настрой окружение
cp .env.example .env
# отредактируй .env — впиши токен Telegram-бота и chat_id

# 2. Собери и запусти (scanner + market-data + signal-engine + notification + analytics + control-bot)
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

# 6. Остановить
docker compose down
```

Docker автоматически:
- перезапускает сканер и бота при падении (`restart: unless-stopped`)
- сохраняет данные (signals, cache) в папку `data/` через volume
- читает настройки из `.env`

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

Пример:

```text
/replay BTCUSDT 1200
```

Доп. переменные `.env`:

- `TELEGRAM_ALLOWED_USER_IDS=12345,67890` — allowlist пользователей (опционально)
- `BOT_DEBUG=true` — debug-логи бота

## Настройки

Все параметры — в `src/core/config.py` → класс `ScannerConfig`.  
Telegram-токены — в `.env` (см. `.env.example`).

| Параметр | По умолчанию | Описание |
|---|---|---|
| `symbols` | BTC, ETH, SOL | Список USDT-перп пар |
| `context.ema_period` | 50 | Период EMA на D1 для определения контекста |
| `trigger.min_wick_ratio` | 1.5 | Мин. соотношение тени к телу для свечи отказа |
| `take_profit.rr_target` | 3.0 | Цель Risk-Reward |
| `levels_mode` | manual | `manual` — ручные уровни, `auto` — авто (v2) |
| `levels_manual` | `{...}` | Словарь символ → список ценовых уровней |
| `enabled_strategies` | `matryoshka, ema_bounce, breakout, engulfing, momentum_break, ema_cross` | Список активных стратегий |

### Уровни

**Ручной режим (v1):** задайте ключевые уровни поддержки/сопротивления в `levels_manual`.  
**Авто-режим (v2):** установите `levels_mode = "auto"` — фрактальные свинги + кластеризация.

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
- **JSON** — `data/signals.json`
- **CSV** — `data/signals.csv` (дополнение)

## Тесты

```bash
pytest tests/ -v
```

27 юнит-тестов: EMA, ATR, расчёт теней, entry/SL/TP, триггеры, контекст, симуляция сделок.

## Структура проекта

```
├── src/                        # Исходный код
│   ├── main.py                 #   Точка входа (однократный / daemon)
│   ├── config.py               #   Параметры стратегии (dataclass)
│   ├── models.py               #   Candle, SignalCard, Direction
│   ├── data_fetcher.py         #   Загрузка OHLCV с Bybit (ccxt)
│   ├── indicators.py           #   EMA, ATR, расчёт теней
│   ├── levels.py               #   Уровни: ручные + авто (фракталы)
│   ├── signal_detector.py      #   Legacy-детектор (Matryoshka)
│   ├── strategies/             #   Набор стратегий (multi-strategy)
│   │   ├── base.py
│   │   ├── matryoshka.py
│   │   ├── ema_bounce.py
│   │   ├── breakout.py
│   │   ├── engulfing.py
│   │   ├── momentum_break.py
│   │   └── ema_cross.py
│   ├── probability.py          #   Бэктест вероятности
│   ├── output.py               #   Вывод: консоль / JSON / CSV
│   ├── cache.py                #   Кэш сигналов (дедупликация)
│   ├── telegram_notifier.py    #   Отправка в Telegram
│   └── telegram_bot.py         #   Telegram replay bot (/replay)
├── tests/                      # Юнит-тесты
│   ├── test_indicators.py
│   ├── test_signal_detector.py
│   └── test_probability.py
├── docs/                       # Документация
│   ├── STRATEGY.md             #   Описание стратегии простым языком
│   ├── LEARNING.md             #   Как учиться торговать через бота
│   └── ROADMAP.md              #   План разработки
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

## Дорожная карта

Полный план — в **[docs/ROADMAP.md](docs/ROADMAP.md)**.

Ближайшие задачи:
- Конфиг из YAML-файла
- Авто-фильтрация символов по объёму
- Лесенка TP с частичным закрытием
- Авто-уровни (фракталы + кластеризация)
