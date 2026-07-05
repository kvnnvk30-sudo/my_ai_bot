"""
src/handlers/chat.py

Основной хэндлер текстовых сообщений.

Логика (без aiogram FSM, см. models.User.awaiting_input):
    1. Получить/создать User по telegram_id.
    2. Если user.awaiting_input задан — это НЕ обычное сообщение чата,
       а ввод API-ключа (пользователь нажал кнопку в /settings и теперь
       присылает строку-ключ). Сохраняем ключ, сбрасываем awaiting_input
       и выходим — дальше в обработку чата не идём.
    3. Иначе — обычное сообщение чата:
         - добавляем текст в user.history
         - дёргаем PROVIDERS[user.current_provider](history, api_key)
         - ловим ProviderError ОДНИМ except (хэндлер не знает про
           исключения конкретных SDK — google.api_core, groq.APIError, ...)
         - добавляем ответ ассистента в историю
         - редактируем "думаю..." на финальный ответ

Регистрация роутера — в src/main.py (явные импорты, без pkgutil/importlib):

    from src.handlers import common, settings, chat
    for module in (common, settings, chat):
        dp.include_router(module.router)
"""

import logging

from aiogram import F, Router
from aiogram.types import Message

from src.database.models import SUPPORTED_PROVIDERS, User
from src.providers import PROVIDERS, ProviderError

logger = logging.getLogger(__name__)

router = Router(name="chat")


@router.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message) -> None:
    """
    Единственный обработчик "обычного" текста (не команд).

    Порядок проверок важен: сначала awaiting_input (ввод ключа),
    и только потом — обычный чат с нейронкой.
    """
    user, _ = await User.get_or_create(telegram_id=message.from_user.id)

    # --- 1. Пользователь вводит API-ключ (замена aiogram FSM) --------------
    if user.awaiting_input:
        await _save_api_key(message, user)
        return

    # --- 2. Обычное сообщение чата -------------------------------------------
    await _handle_chat_message(message, user)


async def _save_api_key(message: Message, user: User) -> None:
    """
    user.awaiting_input хранит строку вида "gemini_key" / "groq_key" / "cerebras_key"
    (см. handlers/settings.py — она выставляется там при нажатии кнопки
    "Сменить ключ ..."). Имя провайдера — это часть строки до "_key".
    """
    provider = user.awaiting_input.removesuffix("_key")

    if provider not in SUPPORTED_PROVIDERS:
        # Не должно случаться при нормальной работе бота, но лучше не падать
        # на рассинхроне состояния, чем уронить хэндлер.
        await user.set_awaiting(None)
        await message.answer(
            "Что-то пошло не так со статусом ввода ключа. Попробуйте снова через /settings."
        )
        return

    raw_key = message.text.strip()
    await user.set_key(provider, raw_key)
    await user.set_awaiting(None)

    await message.answer(f"✅ Ключ для «{provider}» сохранён.")


async def _handle_chat_message(message: Message, user: User) -> None:
    ask = PROVIDERS.get(user.current_provider)
    if ask is None:
        # На случай рассинхрона current_provider (в БД) и словаря PROVIDERS (в коде)
        await message.answer(
            f"Провайдер «{user.current_provider}» не найден. Выберите модель в /settings."
        )
        return

    api_key = user.get_key(user.current_provider)

    await user.add_message("user", message.text)

    thinking = await message.answer("💭 Думаю...")

    try:
        answer = await ask(user.history, api_key)
    except ProviderError as e:
        # Единая ошибка для всех провайдеров — не отсутствие ключа,
        # так сбой самого SDK/сети, текст уже готов к показу пользователю
        await thinking.edit_text(f"⚠️ {e}")
        return
    except Exception:
        logger.exception("Unexpected error while calling provider %s", user.current_provider)
        await thinking.edit_text("⚠️ Непредвиденная ошибка. Попробуйте ещё раз позже.")
        return

    await user.add_message("assistant", answer)
    await thinking.edit_text(answer)