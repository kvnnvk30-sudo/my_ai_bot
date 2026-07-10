import pytest
from unittest.mock import MagicMock,AsyncMock
from src.database.models import SUPPORTED_PROVIDERS
from src.handlers.common import cmd_start,cmd_reset,cmd_help,cmd_cancel 
from src.handlers.settings import _get_user, _settings_keyboard
from src.handlers.settings import cb_use_provider,cb_use_provider,cb_set_key_prompt
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.asyncio
async def test_start_resets_awaiting_input_for_existing_user(create_user):
    #The user is already "stuck" waiting for the key.
    user = create_user
    user.awaiting_input = "cerebras_key"
    await user.save()

    # Create a mock message object
    mock_message = MagicMock()
    mock_message.from_user.id = user.telegram_id
    mock_message.answer = AsyncMock()

    # The user presses /start.
    await cmd_start(mock_message)

    # Check that the user's awaiting_input is reset to None
    await user.refresh_from_db()
    assert user.awaiting_input is None


@pytest.mark.asyncio
async def test_reset_only_clears_history(create_user):
    # Create a user and set some initial state
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
    assert user.history == []  # History should be cleared
    assert user.current_provider == provider_before_reset  # Current provider should remain unchanged
    assert user.get_key("cerebras") == key_before  # API key should remain


async def test_help_lists_all_supported_providers():
    # Create a mock message object
    mock_message = MagicMock()
    mock_message.answer = AsyncMock()

    # Call the help command
    await cmd_help(mock_message)

    # Check that the answer contains all supported providers
    answer_text = mock_message.answer.call_args[0][0]
    for provider in SUPPORTED_PROVIDERS:
        assert provider in answer_text


async def test_use_provider_without_key_blocks_switch():
    # Create a mock user without an API key for the provider
    create_mock_user =MagicMock()
    create_mock_user.get_key.return_value = None
    # Create a mock callback query object
    mock_callback = MagicMock()
    mock_callback.data = "settings:use:cerebras"
    mock_callback.from_user.id =84546531532153215
    mock_callback.message.edit_text = AsyncMock()
    mock_callback.answer = AsyncMock()

    # Patch the _get_user function to return our mock user
    _get_user_backup = _get_user  # Backup the original function
    try:
        globals()['_get_user'] = AsyncMock(return_value=create_mock_user)

        # Call the callback handler
        await cb_use_provider(mock_callback)

        # Check that the callback answer was called with the expected message
        mock_callback.answer.assert_called_with(
            "Сначала задай API-ключ для Cerebras", show_alert=True
        )
        # Ensure that edit_text was not called since the switch should be blocked
        mock_callback.message.edit_text.assert_not_called()
    finally:
        globals()['_get_user'] = _get_user_backup  # Restore the original function


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
    new_user =create_user
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