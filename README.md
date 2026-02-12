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
```

### Docker (рекомендуется для сервера)

```bash
# 1. Настрой окружение
cp .env.example .env
# отредактируй .env — впиши токен Telegram-бота и chat_id

# 2. Собери и запусти
docker compose up -d

# 3. Посмотри логи
docker compose logs -f

# 4. Остановить
docker compose down
```

Docker автоматически:
- перезапускает сканер при падении (`restart: unless-stopped`)
- сохраняет данные (signals, cache) в папку `data/` через volume
- читает настройки из `.env`

## Настройки

Все параметры — в `src/config.py` → класс `ScannerConfig`.  
Telegram-токены — в `.env` (см. `.env.example`).

| Параметр | По умолчанию | Описание |
|---|---|---|
| `symbols` | BTC, ETH, SOL | Список USDT-перп пар |
| `context.ema_period` | 50 | Период EMA на D1 для определения контекста |
| `trigger.min_wick_ratio` | 1.5 | Мин. соотношение тени к телу для свечи отказа |
| `take_profit.rr_target` | 3.0 | Цель Risk-Reward |
| `levels_mode` | manual | `manual` — ручные уровни, `auto` — авто (v2) |
| `levels_manual` | `{...}` | Словарь символ → список ценовых уровней |

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

## Логика стратегии

Подробное описание простым языком — в **[docs/STRATEGY.md](docs/STRATEGY.md)**.

1. **Контекст D1** — EMA(50) определяет направление: LONG ONLY / SHORT ONLY
2. **Касание уровня H4** — цена должна быть на заданном уровне поддержки/сопротивления
3. **Триггерная свеча H4** — свеча отказа с достаточной тенью и правильным закрытием
4. **Entry / SL / TP** — рассчитываются по экстремумам сигнальной свечи и RR target
5. **Валидация** — проверка корректности расстояния SL
6. **Вероятность** — бэктест идентичных сетапов на истории H4

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
│   ├── signal_detector.py      #   Пайплайн поиска сетапа (5 шагов)
│   ├── probability.py          #   Бэктест вероятности
│   ├── output.py               #   Вывод: консоль / JSON / CSV
│   ├── cache.py                #   Кэш сигналов (дедупликация)
│   └── telegram_notifier.py    #   Отправка в Telegram
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
- **[docs/LEARNING.md](docs/LEARNING.md)** — как научиться торговать через бота
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — план разработки

## Дорожная карта

Полный план — в **[docs/ROADMAP.md](docs/ROADMAP.md)**.

Ближайшие задачи:
- Конфиг из YAML-файла
- Авто-фильтрация символов по объёму
- Лесенка TP с частичным закрытием
- Авто-уровни (фракталы + кластеризация)
