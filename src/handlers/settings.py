# src/handlers/settings.py
"""
Хэндлеры настроек: смена текущего провайдера + ввод/смена API-ключей.

Состояние ввода — НЕ aiogram FSM, а строковое поле User.awaiting_input
(см. src/database/models.py). Логика:

    1. Пользователь жмёт inline-кнопку "Сменить ключ <provider>"
       -> await user.set_awaiting(f"{provider}_key")
       -> бот отправляет message-запрос "пришли ключ"
    2. Следующее текстовое сообщение пользователя ловит handle_awaited_input()
       (этот хэндлер должен быть зарегистрирован ДО chat.py в main.py,
       либо иметь фильтр, который chat.py явно пропускает —
       см. src/handlers/chat.py: там первой строкой идёт проверка
       user.awaiting_input и, если оно не None, управление не доходит
       до этого модуля).

Крипто-логика Fernet нигде здесь не используется напрямую — только
user.set_key() / user.get_key() / user.clear_key().
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.models import SUPPORTED_PROVIDERS, User

router = Router(name="settings")

# Человекочитаемые названия провайдеров для кнопок/текста
PROVIDER_LABELS = {
    "gemini": "Gemini",
    "groq": "Groq",
    "cerebras": "Cerebras",
}

# ---------------------------------------------------------------------- #
# Вспомогательное
# ---------------------------------------------------------------------- #

async def _get_user(telegram_id: int) -> User:
    user, _ = await User.get_or_create(telegram_id=telegram_id)
    return user


def _settings_keyboard(user: User) -> InlineKeyboardMarkup:
    """
    Клавиатура настроек: для каждого провайдера — кнопка выбора (с отметкой
    текущего) и кнопка смены ключа (с отметкой, задан ключ или нет).
    """
    builder = InlineKeyboardBuilder()

    for provider in SUPPORTED_PROVIDERS:
        label = PROVIDER_LABELS.get(provider, provider)
        is_current = provider == user.current_provider
        prefix = "✅ " if is_current else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{prefix}Использовать {label}",
                callback_data=f"settings:use:{provider}",
            )
        )

    for provider in SUPPORTED_PROVIDERS:
        label = PROVIDER_LABELS.get(provider, provider)
        has_key = user.get_key(provider) is not None
        mark = "🔑" if has_key else "➕"
        builder.row(
            InlineKeyboardButton(
                text=f"{mark} Ключ {label}",
                callback_data=f"settings:setkey:{provider}",
            )
        )

    return builder.as_markup()


def _settings_text(user: User) -> str:
    current_label = PROVIDER_LABELS.get(user.current_provider, user.current_provider)
    lines = [f"⚙️ Настройки\n\nТекущая модель: <b>{current_label}</b>\n"]
    for provider in SUPPORTED_PROVIDERS:
        label = PROVIDER_LABELS.get(provider, provider)
        status = "ключ задан" if user.get_key(provider) is not None else "ключ не задан"
        lines.append(f"• {label}: {status}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- #
# /settings — открыть меню
# ---------------------------------------------------------------------- #

@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = await _get_user(message.from_user.id)
    await message.answer(
        _settings_text(user),
        reply_markup=_settings_keyboard(user),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------- #
# Выбор текущего провайдера
# ---------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("settings:use:"))
async def cb_use_provider(callback: CallbackQuery) -> None:
    provider = callback.data.split(":", 2)[2]

    if provider not in SUPPORTED_PROVIDERS:
        await callback.answer("Неизвестный провайдер", show_alert=True)
        return

    user = await _get_user(callback.from_user.id)

    if user.get_key(provider) is None:
        await callback.answer(
            f"Сначала задай API-ключ для {PROVIDER_LABELS.get(provider, provider)}",
            show_alert=True,
        )
        return

    user.current_provider = provider
    await user.save(update_fields=["current_provider"])

    await callback.message.edit_text(
        _settings_text(user),
        reply_markup=_settings_keyboard(user),
        parse_mode="HTML",
    )
    await callback.answer(f"Модель переключена на {PROVIDER_LABELS.get(provider, provider)}")


# ---------------------------------------------------------------------- #
# Запрос на смену ключа — ставим awaiting_input
# ---------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("settings:setkey:"))
async def cb_set_key_prompt(callback: CallbackQuery) -> None:
    provider = callback.data.split(":", 2)[2]

    if provider not in SUPPORTED_PROVIDERS:
        await callback.answer("Неизвестный провайдер", show_alert=True)
        return

    user = await _get_user(callback.from_user.id)
    await user.set_awaiting(f"{provider}_key")

    label = PROVIDER_LABELS.get(provider, provider)
    await callback.message.answer(
        f"Пришли API-ключ для <b>{label}</b> одним сообщением.\n"
        f"Отправь /cancel, чтобы отменить.",
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------- #
# /cancel — сбросить ожидание ввода
# ---------------------------------------------------------------------- #

@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    user = await _get_user(message.from_user.id)
    if user.awaiting_input is None:
        await message.answer("Нечего отменять.")
        return
    await user.set_awaiting(None)
    await message.answer("Отменено.")


# ---------------------------------------------------------------------- #
# Приём введённого ключа
#
# ВАЖНО: этот хэндлер ловит ЛЮБОЕ текстовое сообщение, если у пользователя
# выставлен awaiting_input. Он должен быть зарегистрирован раньше chat.py
# (main.py: dp.include_router(settings.router) до dp.include_router(chat.router)),
# либо chat.py сам должен проверять user.awaiting_input и пропускать обработку,
# если оно установлено (так и описано в CONTEXT.md).
# ---------------------------------------------------------------------- #