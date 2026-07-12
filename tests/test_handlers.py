import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from aiogram.types import Chat, Message
from aiogram.types import User as TgUser
import pytest
from aiogram import Dispatcher
from aiogram.types import Update
from src.database.models import SUPPORTED_PROVIDERS
from src.handlers import chat, common, settings
from src.handlers.chat import _handle_chat_message, _save_api_key, handle_message
from src.handlers.common import cmd_cancel, cmd_help, cmd_reset, cmd_start
from src.handlers.settings import _settings_keyboard, cb_use_provider
from src.providers import PROVIDERS, ProviderError

pytestmark = pytest.mark.asyncio


async def test_start_resets_awaiting_input_for_existing_user(create_user):
    # The user is already "stuck" waiting for the key.
    user = create_user
    user.awaiting_input = "cerebras_key"
    await user.save()

    mock_message = MagicMock()
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    # The user presses /start.
    await cmd_start(mock_message)

    await user.refresh_from_db()
    assert user.awaiting_input is None


async def test_reset_only_clears_history(create_user):
    user = create_user
    await user.set_key("cerebras", "dummy_key")
    user.current_provider = "cerebras"
    await user.save()

    await user.add_message("user", "Hello")
    await user.add_message("assistant", "Hi there!")

    provider_before_reset = user.current_provider
    key_before = user.get_key("cerebras")

    mock_message = MagicMock()
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    await cmd_reset(mock_message)
    await user.refresh_from_db()
    assert user.history == []
    assert user.current_provider == provider_before_reset
    assert user.get_key("cerebras") == key_before


async def test_help_lists_all_supported_providers():
    mock_message = MagicMock()
    mock_message.answer = AsyncMock()

    await cmd_help(mock_message)

    answer_text = mock_message.answer.call_args[0][0]
    for provider in SUPPORTED_PROVIDERS:
        assert provider in answer_text


async def test_use_provider_without_key_blocks_switch():
    create_mock_user = MagicMock()
    create_mock_user.get_key.return_value = None

    mock_callback = MagicMock()
    mock_callback.data = "settings:use:cerebras"
    mock_callback.from_user.id = 84546531532153215
    mock_callback.message.edit_text = AsyncMock()
    mock_callback.answer = AsyncMock()

    # FIX: patch _get_user where cb_use_provider actually looks it up
    # (src.handlers.settings), not in this test module's globals().
    with patch(
        "src.handlers.settings._get_user",
        new=AsyncMock(return_value=create_mock_user),
    ):
        await cb_use_provider(mock_callback)

    mock_callback.answer.assert_called_with(
        "Сначала задай API-ключ для Cerebras", show_alert=True
    )
    mock_callback.message.edit_text.assert_not_called()


async def test_unknown_provider_short_circuits_before_db():
    mock_callback = MagicMock()
    mock_callback.data = "settings:use:unknown_provider"
    mock_callback.from_user.id = 123456789
    mock_callback.answer = AsyncMock()

    with patch("src.database.models.User.get_or_create", new=AsyncMock()) as mock_get_or_create:
        await cb_use_provider(mock_callback)

    mock_callback.answer.assert_called_with(
        "Неизвестный провайдер", show_alert=True
    )
    mock_get_or_create.assert_not_called()


async def test_cancel_after_setkey_prompt_resets_state(create_user):
    new_user = create_user
    new_user.awaiting_input = "cerebras_key"
    await new_user.save()

    mock_message = MagicMock()
    mock_message.from_user.id = new_user.telegram_id
    mock_message.answer = AsyncMock()

    await cmd_cancel(mock_message)

    await new_user.refresh_from_db()
    assert new_user.awaiting_input is None


async def test_settings_keyboard_shows_key_icon_after_save(create_user):
    user = create_user
    await user.set_key("cerebras", "fake-api-key")

    keyboard = _settings_keyboard(user)

    key_button = next(
        btn for row in keyboard.inline_keyboard for btn in row
        if btn.callback_data == "settings:setkey:cerebras"
    )
    assert "🔑" in key_button.text
    assert "➕" not in key_button.text


async def test_save_api_key_unknown_provider_from_awaiting(create_user):
    user = create_user
    user.awaiting_input = "unknown_key"
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "fake-api-key"
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    await _save_api_key(mock_message, user)
    await user.refresh_from_db()
    assert user.awaiting_input is None


async def test_save_api_key_rejects_blank_string(create_user):
    user = create_user
    user.awaiting_input = "cerebras_key"
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "   "  # Blank string with spaces
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    await _save_api_key(mock_message, user)
    await user.refresh_from_db()

    # The awaiting_input should still be set since the key was invalid
    assert user.awaiting_input == "cerebras_key"


async def test_missing_provider_does_not_touch_history(create_user):
    user = create_user
    # current_provider is CharField(max_length=16) — "nonexistent_provider"
    # (20 chars) fails DB validation. Use a name that still fits and is
    # absent from PROVIDERS.
    user.current_provider = "bad_provider"
    await user.add_message("user", "Hello")
    await user.save()
    mock_message = MagicMock()
    mock_message.text = "Test message"
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()
    await _handle_chat_message(mock_message, user)
    await user.refresh_from_db()
    assert len(user.history) == 1  # Only the initial message should be present

async def test_provider_error_does_not_pollute_history(create_user):
    user = create_user
    user.current_provider = "cerebras"
    await user.add_message("user", "Hello")
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "Test message"
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    # FIX: raise the real ProviderError, not a generic Exception,
    # so this test actually exercises the `except ProviderError` branch.
    with patch(
        "src.handlers.chat.PROVIDERS",
        {"cerebras": AsyncMock(side_effect=ProviderError("Provider error"))},
    ):
        await _handle_chat_message(mock_message, user)

    await user.refresh_from_db()
    assert len(user.history) == 2
    assert user.history[-1]["role"] == "user"
    assert user.history[-1]["content"] == "Test message"
    # и явно проверить, что запись от ассистента не добавилась:
    assert all(msg["role"] != "assistant" for msg in user.history)


async def _hanging_provider(history, api_key):
    await asyncio.sleep(30)
    return "unused"


@pytest.mark.timeout(5)
async def test_hanging_provider_without_exception(create_user):
    user = create_user
    user.current_provider = "cerebras"
    await user.add_message("user", "Hello")
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "Test message"
    mock_message.from_user.id = user.telegram_id
    thinking_message = MagicMock(edit_text=AsyncMock())
    mock_message.answer = AsyncMock(return_value=thinking_message)

    with patch(
        "src.handlers.chat.PROVIDERS",
        {"cerebras": AsyncMock(side_effect=_hanging_provider)},
    ):
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                _handle_chat_message(mock_message, user),
                timeout=2,
            )

    thinking_message.edit_text.assert_not_awaited()


async def test_unexpected_exception_is_logged(create_user, caplog):
    user = create_user
    user.current_provider = "cerebras"
    await user.add_message("user", "Hello")
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "Test message"
    mock_message.from_user.id = user.telegram_id
    thinking_message = MagicMock(edit_text=AsyncMock())
    mock_message.answer = AsyncMock(return_value=thinking_message)

    with patch(
        "src.handlers.chat.PROVIDERS",
        {"cerebras": AsyncMock(side_effect=Exception("boom"))},
    ):
        with caplog.at_level(logging.ERROR):
            await _handle_chat_message(mock_message, user)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    thinking_message.edit_text.assert_awaited_once_with(
        "⚠️ Непредвиденная ошибка. Попробуйте ещё раз позже."
    )


async def test_unknown_slash_command_gives_some_response(create_user):
    dp = Dispatcher()
    for module in (common, settings, chat):
        dp.include_router(module.router)
    user = create_user

    chat_obj = Chat(id=user.telegram_id, type="private")
    tg_user = TgUser(id=user.telegram_id, is_bot=False, first_name="Test")
    real_message = Message.model_construct(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=chat_obj,
        from_user=tg_user,
        text="/nonexistent_command",
    )
    update = Update(update_id=1, message=real_message)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    await dp.feed_update(bot=mock_bot, update=update)

    mock_bot.send_message.assert_awaited()


async def test_chat_handler_checks_awaiting_input_regardless_of_router_order(create_user):
    """
    Инвариант: handle_message обязан проверять user.awaiting_input первой
    строкой, независимо от того, в каком порядке роутеры зарегистрированы
    в main.py. Эту проверку нельзя убирать как "дублирующую".
    """
    user = create_user
    user.awaiting_input = "cerebras_key"
    await user.save()

    mock_message = MagicMock()
    mock_message.text = "some-api-key"
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    await handle_message(mock_message)

    await user.refresh_from_db()
    assert user.awaiting_input is None


def test_supported_providers_and_providers_dict_are_in_sync():
    assert set(SUPPORTED_PROVIDERS) == set(PROVIDERS.keys())