"""
src/handlers/common.py

Базовые команды бота: /start, /help, /reset.

Здесь нет никакой логики провайдеров и ключей — только приветствие,
создание пользователя в БД (get_or_create) и общая справка.
Смена модели / ввод API-ключа — в handlers/settings.py,
сам диалог с нейронкой — в handlers/chat.py.

Опирается на модель User из src/database/models.py:
  - user.current_provider   — какая модель сейчас выбрана
  - user.awaiting_input     — сбрасываем при /start на случай рестарта бота
                              посреди ввода ключа (см. models.py)
  - user.clear_history()    — используется в /reset
  - SUPPORTED_PROVIDERS     — список моделей для текста /help
"""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from src.database.models import SUPPORTED_PROVIDERS, User

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    /start — создаёт пользователя при первом обращении.

    Если пользователь уже существовал и завис в состоянии awaiting_input
    (например, бот перезапустился в момент ожидания API-ключа) — сбрасываем
    это состояние, чтобы обычное сообщение не улетело в set_key() по ошибке.
    """
    user, created = await User.get_or_create(telegram_id=message.from_user.id)

    if not created and user.awaiting_input is not None:
        await user.set_awaiting(None)

    text = (
        "👋 Привет! Я бот-прокладка к нескольким ИИ "
        f"({', '.join(SUPPORTED_PROVIDERS)}).\n\n"
        f"Сейчас выбрана модель: <b>{user.current_provider}</b>.\n"
        "Просто напиши сообщение — и получишь ответ от неё.\n\n"
        "Команды:\n"
        "/settings — сменить модель или указать свой API-ключ\n"
        "/reset — очистить историю диалога\n"
        "/help — справка"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """/help — список команд и поддерживаемых провайдеров."""
    text = (
        "ℹ️ <b>Как пользоваться ботом</b>\n\n"
        f"Поддерживаемые модели: {', '.join(SUPPORTED_PROVIDERS)}\n\n"
        "• Любое обычное сообщение уходит в текущую выбранную модель\n"
        "• /settings — выбрать модель и ввести/сменить свой API-ключ для неё\n"
        "• /reset — очистить историю переписки (ключи и выбранная модель не трогаются)\n"
        "• /start — приветствие и пересоздание записи пользователя, если что-то сломалось"
    )
    await message.answer(text)


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """/reset — очищает только историю диалога (user.history), больше ничего не трогает."""
    user, _ = await User.get_or_create(telegram_id=message.from_user.id)
    await user.clear_history()
    await message.answer("🧹 История очищена. Начинаем с чистого листа.")