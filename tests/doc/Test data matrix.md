# Матрица тест-данных — my_ai_bot

Строится по чек-листу `checklist_remaining.md`. Каждая строка — конкретный набор входных
данных для одного пункта чек-листа. ID теста удобно переиспользовать как имя pytest-функции
(`test_<id>`).

Обозначения: **ПУ** — предусловие, **ОР** — ожидаемый результат.

---

## 1. `providers.py`

| ID | Входные данные | ПУ | Действие | ОР | Пункт чек-листа |
|---|---|---|---|---|---|
| PRV-01 | `history=[{"role":"user","content":"Привет"}]`, `api_key="valid_key_123"` | SDK замокан, возвращает `choices[0].message.content="Привет!"` | `await ask_cerebras(history, api_key)` | Вызов `create()` содержит `messages=[{"role":"system","content":SYSTEM_PROMPT}, {"role":"user","content":"Привет"}]`, `model="gpt-oss-120b"` | `ask_cerebras` вызывает SDK с системным промптом |
| PRV-02 | `history=[]`, `api_key=None` | — | `await ask_cerebras([], None)` | `ProviderError` с текстом про отсутствие ключа, `Cerebras(...)` **не создаётся** (мок SDK не вызван) | `_require_key` до похода в SDK |
| PRV-03 | `history=[]`, `api_key=""` | — | `await ask_cerebras([], "")` | `ProviderError` (пустая строка = falsy) | `_require_key` до похода в SDK |
| PRV-04 | `api_key="valid_key"` | Мок SDK кидает `TimeoutError("connection timed out")` | `await ask_cerebras(history, api_key)` | `ProviderError("Cerebras: connection timed out")` | Обёртка сетевых ошибок |
| PRV-05 | `api_key="bad_key"` | Мок SDK кидает `Exception("401 Unauthorized")` | `await ask_cerebras(...)` | `ProviderError("Cerebras: 401 Unauthorized")` | Обёртка 401/403 |
| PRV-06 | `api_key="valid_key"` | Мок SDK кидает `Exception("429 Too Many Requests")` | `await ask_cerebras(...)` | `ProviderError` с тем же текстом внутри | Обёртка 429 |
| PRV-07 | `api_key="valid_key"` | Мок SDK кидает `Exception("500 Internal Server Error")` | `await ask_cerebras(...)` | `ProviderError` | Обёртка 5xx |
| PRV-08 | `history=[{"role":"user","content":"?"}]` | Мок SDK возвращает объект с `choices=[]` (пустой список) | `await ask_cerebras(...)` | `IndexError` внутри → пойман общим `except Exception` → `ProviderError("Cerebras: list index out of range")` | Неожиданная структура ответа SDK |
| PRV-09 | как PRV-08 | Мок SDK возвращает `choices[0].message.content=None` | `await ask_cerebras(...)` | Функция вернёт `None` как `answer` (не упадёт) — проверить, что `chat.py` корректно обработает `None` при `thinking.edit_text(answer)` | Неожиданная структура ответа SDK |
| PRV-10 | `history` — 25 сообщений подряд (превышает `HISTORY_LIMIT`) | Мок SDK эхо | `await ask_cerebras(history, key)` | В `messages` для SDK передаётся ровно то, что лежит в `history` на входе (обрезка — забота `models.py`, не `providers.py`) | Сигнатура/контракт `ask_cerebras` |
| PRV-11 | `api_key="valid_key"`, время выполнения синхронного мока — искусственная задержка 2 сек | Два параллельных вызова `ask_cerebras` из разных "пользователей" | `await asyncio.gather(ask_cerebras(...), ask_cerebras(...))` | Оба вызова завершаются за ~2 сек суммарно (параллельно), а не 4 сек последовательно — подтверждает `asyncio.to_thread` не блокирует loop | Нагрузочное / to_thread |

## 2. `database/models.py`

| ID | Входные данные | ПУ | Действие | ОР | Пункт чек-листа |
|---|---|---|---|---|---|
| MDL-01 | `provider="cerebras"`, `raw_key="sk-test-123"` | Новый `User` создан | `await user.set_key("cerebras", "sk-test-123")` | `user.api_keys_encrypted` не содержит подстроку `"sk-test-123"` в открытом виде; `user.get_key("cerebras") == "sk-test-123"` | Шифрование/дешифрование ключей |
| MDL-02 | `provider="openai"` (нет в `SUPPORTED_PROVIDERS`) | — | `await user.set_key("openai", "x")` | `ValueError("Неизвестный провайдер: openai")` | Проверка провайдера до похода в БД |
| MDL-03 | `provider="openai"` | — | `user.get_key("openai")` | `ValueError` | Проверка провайдера до похода в БД |
| MDL-04 | `api_keys_encrypted = "not-a-valid-fernet-token"` (записано напрямую, минуя `set_key`) | — | `user.get_key("cerebras")` | Возвращает `None`, исключение `InvalidToken` не пробрасывается наружу | Обработка битых данных |
| MDL-05 | `api_keys_encrypted` = валидный Fernet-токен, но внутри не JSON (например, зашифрованная строка `"not json"`) | — | `user.get_key("cerebras")` | Возвращает `None`, `json.JSONDecodeError` не пробрасывается | Обработка битых данных |
| MDL-06 | `SECRET_KEY` в конфиге — случайная строка длиной 10 символов (невалидный Fernet-ключ) | Приложение стартовало без ошибок (см. CFG-01) | Первый вызов `user.set_key(...)` или `user.get_key(...)` | Падает с исключением `Fernet`/`binascii` уже **в рантайме**, не на старте — зафиксировать этот момент явным тестом/логом | Ленивая проверка `SECRET_KEY` |
| MDL-07 | 20 вызовов `add_message` подряд с текстами `"msg-1"` … `"msg-20"`, затем ещё 5: `"msg-21"` … `"msg-25"` | — | После всех вызовов — `user.history` | Длина `== 20`; первый элемент `content == "msg-6"` (обрезаны первые 5, а не последние) | Обрезка `HISTORY_LIMIT` с начала |
| MDL-08 | Два независимых `User.get_or_create(telegram_id=X)` для одного и того же `X`, оба уже с непустой `history` | Оба инстанса загружены **до** правки | `await asyncio.gather(instance_a.add_message("user","A"), instance_b.add_message("user","B"))` | Итоговая `history` в БД содержит только одно из двух сообщений (last write wins) — тест должен явно зафиксировать потерю данных как известный риск | Конкурентные апдейты |
| MDL-09 | Новый `telegram_id`, ранее не существовавший | — | `user, created = await User.get_or_create(telegram_id=X)` | `created is True`; `user.current_provider == "cerebras"`; `user.history == []`; `user.awaiting_input is None` | Дефолты новой записи |
| MDL-10 | `provider="cerebras"`, ключ уже задан (`"old_key"`) | — | `await user.clear_key("cerebras")` | `user.get_key("cerebras") is None` | `clear_key` |
| MDL-11 | `provider="cerebras"`, ключ уже задан (`"old_key"`) | — | `await user.set_key("cerebras", "new_key")` (перезапись) | `user.get_key("cerebras") == "new_key"`; старое значение `"old_key"` нигде не восстанавливается | Перезапись ключа |

## 3. `config.py` / `.env.example`

| ID | Входные данные | ПУ | Действие | ОР | Пункт чек-листа |
|---|---|---|---|---|---|
| CFG-01 | `.env` без переменной `BOT_TOKEN` (остальное задано) | — | `import src.config` | `pydantic.ValidationError`, сообщение упоминает `BOT_TOKEN` и `field required` | Обязательные переменные |
| CFG-02 | `.env` без переменной `SECRET_KEY` | — | `import src.config` | `pydantic.ValidationError` с упоминанием `SECRET_KEY` | Обязательные переменные |
| CFG-03 | `.env` без переменной `DB_URL` | Остальное задано | `import src.config` | Импорт успешен, `settings.DB_URL == "sqlite://db.sqlite3"` | Дефолт `DB_URL` |
| CFG-04 | `.env` с `BOT_TOKEN=""` (пустая строка, но переменная присутствует) | — | `import src.config` | Уточнить ожидание: pydantic примет пустую строку как валидную (тип `str`) — фиксируем как баг/риск, если это не задумано | Валидация значений, не только наличия |
| CFG-05 | `.env` целиком отсутствует как файл | Переменные окружения тоже не заданы | `import src.config` | `pydantic.ValidationError` (multiple errors: `BOT_TOKEN`, `SECRET_KEY`) | Запуск без `.env` (acceptance/конфигурационное) |
| CFG-06 | `.env.example` (сам файл) | — | Ручной просмотр содержимого | Нет строк вида реального токена (`123456789:AAH...`) или реального Fernet-ключа — только плейсхолдеры | Секреты не в репозитории |

## 4. `main.py`

| ID | Входные данные | ПУ | Действие | ОР | Пункт чек-листа |
|---|---|---|---|---|---|
| MAIN-01 | Мок `Tortoise.init`/`generate_schemas`, мок `Bot`, мок `Dispatcher` | — | `await main()` (с моками) | Порядок вызовов: `Tortoise.init` → `generate_schemas` → `Bot(...)` → `Dispatcher()` → `include_router` x3 → `start_polling` | Инициализация БД до поллинга |
| MAIN-02 | Мок `Dispatcher`, реальные модули `common/settings_handlers/chat` | — | Сформировать список апдейтов: `/cancel` | Обрабатывает **`common.cmd_cancel`**, а не `settings_handlers.cmd_cancel` (проверка через spy/patch на обеих функциях — вторая не должна быть вызвана) | Дубликат `/cancel` — только один реально живой |
| MAIN-03 | Мок `bot.session.close`, мок `Tortoise.close_connections`, `start_polling` кидает `asyncio.CancelledError` (эмуляция `SIGTERM`) | — | `await main()` | `finally` блок отрабатывает: и `bot.session.close()`, и `Tortoise.close_connections()` вызваны по разу | Грейсфул-шатдаун |
| MAIN-04 | Реальный `logging` (без моков), уровень по умолчанию | Вызвать код, где есть `logger.exception(...)` (см. `chat.py`) | Перехватить `caplog`/вывод | Запись с уровнем `ERROR` (для `logger.exception`) присутствует в выводе — `basicConfig(level=INFO)` её не режет | Конфигурация логгера |

## 5. Новые находки

| ID | Входные данные | ПУ | Действие | ОР | Находка |
|---|---|---|---|---|---|
| FND-01 | Апдейт `/cancel`, `user.awaiting_input = "cerebras_key"` | Оба роутера (`common`, `settings_handlers`) зарегистрированы как в `main.py` | `dp.feed_update(bot, update_with_cancel)` | `send_message`/`answer` вызван **один раз** (не два) с текстом "Отменено." из `common.py`; `settings_handlers.cmd_cancel` не вызывается — иначе будет двойной ответ пользователю | Дублирующийся `/cancel` |
| FND-02 | `user.awaiting_input = "cerebras_key"`, входящее сообщение `message.text = "/sk-not-a-real-command-1234"` (ключ по случайности начинается с `/`) | `chat.router` зарегистрирован | `dp.feed_update(bot, update)` | Ни один хэндлер не отвечает (фильтр `~F.text.startswith("/")` исключает); `user.awaiting_input` остаётся `"cerebras_key"` — бот "зависает" в ожидании | Дыра в фильтре `chat.py` |
| FND-03 | То же, что FND-02, но `message.text = "обычный ключ без слэша"` | — | `dp.feed_update(bot, update)` | Ключ сохраняется штатно через `_save_api_key` (контрольный позитивный кейс к FND-02) | Дыра в фильтре `chat.py` (контроль) |

## 6. Сквозное

| ID | Входные данные | ПУ | Действие | ОР | Пункт чек-листа |
|---|---|---|---|---|---|
| SYN-01 | — | — | `set(SUPPORTED_PROVIDERS) == set(PROVIDERS.keys())` | `True` | Синхрон `SUPPORTED_PROVIDERS` / `PROVIDERS` |
| SYN-02 | Гипотетическое добавление `"groq"` только в `PROVIDERS`, но не в `SUPPORTED_PROVIDERS` (в тестовом фикстурном моде) | — | Тот же ассерт SYN-01 | `False` → тест падает намеренно, подтверждая, что барьер действительно ловит рассинхрон | Тест-барьер на будущее |

---

## Как использовать эту матрицу

- Каждая строка = один pytest-тест (unit, `AsyncMock` для SDK/БД, in-memory SQLite для `models.py`).
- Столбец **ОР** — это assert'ы теста.
- Столбец **Пункт чек-листа** — обратная ссылка на `checklist_remaining.md`, чтобы отмечать чекбоксы по мере прохождения тестов.
- MAIN-* и FND-01 требуют интеграционного стиля (`dp.feed_update` с замоканным `bot`), остальное — чистый unit.