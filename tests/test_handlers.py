import pytest
from unittest.mock import MagicMock,AsyncMock
from src.database.models import SUPPORTED_PROVIDERS
from src.handlers.common import cmd_start,cmd_reset,cmd_help

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