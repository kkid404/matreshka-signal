# План реализации Web-дашборда

## Цель

Сделать минимальный web-интерфейс для просмотра сигналов и запуска scan/replay без Telegram.

Roadmap item: `- [ ] Web-дашборд — мини-интерфейс для просмотра сигналов (FastAPI + React / Streamlit)`.

## Выбранный путь для MVP

**Streamlit MVP** (быстрее в доставке и проще в поддержке на текущем этапе).

Почему:
- не требует отдельного frontend-бандлера;
- можно переиспользовать существующий `signal-engine-service` API;
- короткий цикл изменений для продукта и UX.

## Scope MVP (v1)

1. Подключение к `signal-engine-service` по URL.
2. Кнопка `Run Scan` (`POST /scan/run`) и отображение карточек в таблице.
3. Блок `Replay`:
   - ввод `symbol`;
   - ввод `lookback`;
   - кнопка `Run Replay` (`POST /replay/run`).
4. Таблица сигналов с ключевыми полями:
   - symbol, strategy, direction, timeframe;
   - signal time;
   - entry, entry zone, stop loss, take profit, RR;
   - probability %, sample size, TradingView link.
5. Базовые метрики:
   - количество сигналов;
   - LONG/SHORT split;
   - список активных стратегий.

## Не входит в MVP

- Реaltime streaming/websocket.
- Редактирование risk-профиля.
- Сложные чарты свечей внутри дашборда.
- Авторизация и ролевая модель.

## Архитектура

- Новый сервис `web-dashboard` в `docker-compose`.
- Streamlit-приложение в `src/services/web_dashboard_streamlit.py`.
- Источник данных: `signal-engine-service` через существующий `SignalEngineClient`.

## Конфиг

Переменные окружения:
- `WEB_DASHBOARD_HOST=0.0.0.0`
- `WEB_DASHBOARD_PORT=8501`
- `SIGNAL_ENGINE_SERVICE_URL=http://signal-engine:8082`

## Этапы реализации

### Этап 1 (MVP)
- [x] Добавить документ-план.
- [x] Добавить Streamlit app + базовый UI.
- [x] Подключить docker-compose сервис.
- [x] Обновить зависимости и README.
- [х] Smoke-run в docker.

### Этап 2 (после MVP)
- [ ] Фильтры по стратегии/направлению/символу.
- [ ] История запусков scan/replay.
- [ ] Экспорт таблицы в CSV/JSON.

### Этап 3 (optional)
- [ ] Переход на FastAPI + React при росте требований.
- [ ] Добавить auth и multi-user профили.

## Критерии готовности MVP

- Сервис поднимается через `docker-compose up --build`.
- Открывается UI по `http://localhost:8501`.
- `Run Scan` и `Run Replay` возвращают сигналы и отображают таблицу.
- Ошибки backend отображаются в UI без падения приложения.
