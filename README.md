# Telegram-бот с переключением ИИ (Claude / GPT / Gemini) — Zero-Boilerplate

Мульти-провайдерный AI-бот, спроектированный так, чтобы вайбкодинг с бесплатными нейронками не ломался на масштабировании. Каждое архитектурное решение здесь — сознательный отказ от "правильного" паттерна в пользу того, что ИИ-кодер не путает.

---

## Стек

- **Python 3.11+**
- **Aiogram 3.x** — Telegram framework
- **Tortoise ORM + SQLite** — слой данных (Active Record, Django-style)
- **Pydantic v2 + pydantic-settings** — конфиг из `.env`
- **anthropic / openai / google-generativeai** — официальные SDK нейросетей
- **cryptography (Fernet)** — шифрование API-ключей пользователей
- **pytest + pytest-asyncio + AsyncMock** — тесты

---

## Дерево проекта

```text
my_ai_bot/
│
├── .env                  # Токен бота, SECRET_KEY для шифрования, режим dev/prod
├── .env.example          # Шаблон для Git
├── .gitignore            # venv, db.sqlite3, логи
├── CONTEXT.md            # Инструкция-инъекция для ИИ-кодера
├── README.md             # Этот файл
├── docker-compose.yml    # Только для финального деплоя
├── Dockerfile
├── requirements.txt
│
├── tests/                # Отдельная зона тестов, изолирована от src/
│   ├── __init__.py
│   ├── conftest.py       # Инициализация Tortoise ORM в памяти (sqlite://:memory:)
│   ├── test_models.py    # Тесты User: set_key/get_key, history, awaiting_input
│   ├── test_providers.py # Тесты диспетчера PROVIDERS (моки SDK-вызовов)
│   └── test_handlers.py  # Тесты хэндлеров через AsyncMock объектов Aiogram
│
└── src/
    ├── __init__.py
    ├── main.py            # Конфиг, явные include_router, старт бота, init ORM
    ├── providers.py        # ask_claude / ask_gpt / ask_gemini + словарь-диспетчер
    │
    ├── database/
    │   ├── __init__.py
    │   └── models.py       # User: current_provider, api_keys (JSON, шифр.),
    │                        #       history (JSON), awaiting_input
    │                        #       + методы set_key() / get_key() (крипто внутри)
    │
    └── handlers/
        ├── __init__.py
        ├── common.py        # /start, /help
        ├── settings.py      # смена модели + ввод/смена API-ключей
        └── chat.py          # сообщение → providers[current_provider] → ответ
```

---

## Архитектурные принципы

### 1. Провайдеры — функции, не классы
Один файл `providers.py`. Никаких абстрактных классов и фабрик. Три async-функции с одинаковой сигнатурой `(history: list) -> str` + словарь-диспетчер в конце файла:

```python
PROVIDERS = {
    "claude": ask_claude,
    "gpt": ask_gpt,
    "gemini": ask_gemini,
}
```

Новая нейронка = новая функция + новая строка в словаре. Всё в одном месте.

### 2. Ключи и история — поля в `User`, не отдельные таблицы
- `api_keys` — одно JSON-поле, зашифровано целиком через Fernet: `{"claude": "...", "gpt": "...", "gemini": "..."}`
- `history` — JSON-список последних N сообщений, обновляется одним `.append()`

Никаких JOIN, никаких запросов с фильтрами — всё через `user.поле`.

### 3. Роутинг — явные импорты, не `pkgutil`/`importlib`
```python
from src.handlers import common, settings, chat
for module in (common, settings, chat):
    dp.include_router(module.router)
```
Прозрачно для дебага, легко объяснить ИИ, не ломается на магии автосканирования.

### 4. Состояние ввода — строковое поле, не aiogram FSM
`User.awaiting_input`: `None` / `"claude_key"` / `"gpt_key"` / `"gemini_key"`.
Хэндлер ставит значение при нажатии кнопки, `chat.py` первой строкой проверяет это поле — никакого `FSMContext` и `StatesGroup`.

### 5. Крипто-логика заперта в модели
Методы `user.set_key(provider, raw_key)` и `user.get_key(provider)` сами дергают Fernet. Хэндлеры никогда не импортируют `cryptography` напрямую — не могут забыть зашифровать/расшифровать.

### 6. Docker — только для продакшена
Разработка — обычный `python src/main.py`. Никаких путей, volume и прав доступа на этапе вайбкодинга.

---

## Итог оптимизации

| Было бы (классический подход) | Стало |
|---|---|
| Абстрактный класс + 3 наследника + фабрика | 1 файл, 3 функции, 1 словарь |
| Таблица `ApiKey` с JOIN | Поле `User.api_keys` |
| Таблица `Message` с фильтрами/`order_by` | Поле `User.history` |
| Динамический импорт (`pkgutil`) | 3 явных `import` |
| aiogram FSM (`StatesGroup`, `FSMContext`) | 1 строковое поле `awaiting_input` |
| Fernet-вызовы в хэндлерах | 2 метода в модели |

**Результат:** вся бизнес-логика бота — 4 файла (`main.py`, `models.py`, `providers.py` + 3 хэндлера). Ни одного JOIN, ни одного класса-наследника, ни одной магической автоматизации. Каждая фича ИИ пишет в рамках одного файла, не трогая остальные.