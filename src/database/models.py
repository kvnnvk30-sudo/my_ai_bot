# src/database/models.py
"""
Модель пользователя бота.

Поля:
    telegram_id       — уникальный ID пользователя в Telegram
    current_provider  — "gemini" / "groq" / "cerebras" (ключ в PROVIDERS из providers.py)
    api_keys          — JSON-строка вида {"gemini": "...", "groq": "...", "cerebras": "..."},
                        хранится в БД в зашифрованном виде (Fernet), расшифровывается
                        только внутри get_key()/set_key()
    history           — JSON-список последних сообщений диалога
                        [{"role": "user"/"assistant", "content": "..."}]
    awaiting_input    — None / "gemini_key" / "groq_key" / "cerebras_key"
                        (замена aiogram FSM, см. handlers/settings.py и handlers/chat.py)

Крипто-логика заперта внутри модели: хэндлеры никогда не работают с Fernet напрямую,
только вызывают user.set_key(provider, raw_key) / user.get_key(provider).
"""

import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from tortoise import fields
from tortoise.models import Model

from src.config import settings  # settings.SECRET_KEY читается из .env (pydantic-settings)

# Провайдеры, которые понимает бот. Должно совпадать с ключами словаря PROVIDERS в providers.py
SUPPORTED_PROVIDERS = ("cerebras",)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """
    Fernet-ключ должен быть валидным 32-байтным base64-ключом.
    Кладём SECRET_KEY в .env одной строкой, сгенерированной один раз через
    `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    """
    key = settings.SECRET_KEY.encode() if isinstance(settings.SECRET_KEY, str) else settings.SECRET_KEY
    return Fernet(key)


class User(Model):
    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True, index=True)

    current_provider = fields.CharField(max_length=16, default="cerebras")

    # Хранится как ЗАШИФРОВАННАЯ строка (результат Fernet.encrypt), не как чистый JSON.
    api_keys_encrypted = fields.TextField(null=True)

    history = fields.JSONField(default=list)  # [{"role": "...", "content": "..."}, ...]

    awaiting_input = fields.CharField(max_length=32, null=True)  # None / "gemini_key" / ...

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return f"User(tg_id={self.telegram_id}, provider={self.current_provider})"

    # ------------------------------------------------------------------ #
    # Крипто-логика ключей провайдеров
    # ------------------------------------------------------------------ #

    def _load_keys_dict(self) -> dict:
        """Расшифровывает api_keys_encrypted и парсит JSON. Никогда не вызывается снаружи модели."""
        if not self.api_keys_encrypted:
            return {}
        try:
            raw = _get_fernet().decrypt(self.api_keys_encrypted.encode())
            return json.loads(raw.decode())
        except (InvalidToken, json.JSONDecodeError):
            # битые/старые данные — не роняем бота, просто считаем что ключей нет
            return {}

    def _dump_keys_dict(self, keys: dict) -> None:
        """Сериализует dict в JSON и шифрует обратно в api_keys_encrypted."""
        raw = json.dumps(keys).encode()
        self.api_keys_encrypted = _get_fernet().encrypt(raw).decode()

    async def set_key(self, provider: str, raw_key: str) -> None:
        """
        Сохраняет API-ключ провайдера в зашифрованном виде и сразу пишет в БД.

        Использование (в handlers/settings.py):
            await user.set_key("gemini", message.text)
        """
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Неизвестный провайдер: {provider}")

        keys = self._load_keys_dict()
        keys[provider] = raw_key
        self._dump_keys_dict(keys)
        await self.save(update_fields=["api_keys_encrypted"])

    def get_key(self, provider: str) -> str | None:
        """
        Возвращает расшифрованный API-ключ провайдера или None, если ключ не задан.

        Использование (в providers.py):
            key = user.get_key(user.current_provider)
        """
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Неизвестный провайдер: {provider}")

        keys = self._load_keys_dict()
        return keys.get(provider)

    async def clear_key(self, provider: str) -> None:
        """Удаляет ключ конкретного провайдера (например, по команде /reset_key)."""
        keys = self._load_keys_dict()
        keys.pop(provider, None)
        self._dump_keys_dict(keys)
        await self.save(update_fields=["api_keys_encrypted"])

    # ------------------------------------------------------------------ #
    # История диалога
    # ------------------------------------------------------------------ #

    HISTORY_LIMIT = 20  # сколько последних сообщений храним

    async def add_message(self, role: str, content: str) -> None:
        """
        Добавляет сообщение в историю и обрезает её до HISTORY_LIMIT.

        Использование (в handlers/chat.py):
            await user.add_message("user", message.text)
            answer = await PROVIDERS[user.current_provider](user.history, user.get_key(...))
            await user.add_message("assistant", answer)
        """
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.HISTORY_LIMIT:
            self.history = self.history[-self.HISTORY_LIMIT:]
        await self.save(update_fields=["history"])

    async def clear_history(self) -> None:
        self.history = []
        await self.save(update_fields=["history"])

    # ------------------------------------------------------------------ #
    # Состояние ожидания ввода (замена FSM)
    # ------------------------------------------------------------------ #

    async def set_awaiting(self, value: str | None) -> None:
        """
        value: None / "gemini_key" / "groq_key" / "cerebras_key"

        Использование:
            await user.set_awaiting("groq_key")   # после нажатия кнопки "Сменить ключ Groq"
            ...
            await user.set_awaiting(None)          # после того как ключ введён и сохранён
        """
        self.awaiting_input = value
        await self.save(update_fields=["awaiting_input"])