import asyncio
import binascii 
import pytest
from src.database import models as models_module
from src.database.models import User
 
 



pytestmark = pytest.mark.asyncio


async def test_mdl_01_set_key_encrypts_and_get_key_decrypts(create_user):
    user= create_user
    await user.set_key("cerebras", "sk-test-123")
    assert "sk-test-123" is not user.api_keys_encrypted
    assert user.get_key("cerebras") == "sk-test-123"

async def test_mdl_02_set_key_unknown_provider_raises_before_db_write(create_user):
    user = await create_user
    with pytest.raises(ValueError, match="Неизвестный провайдер: openai"):
        await user.set_key("openai", "x")
        assert user.api_keys_encrypted is None
        await user.refresh_from_db()
        assert user.api_keys_encrypted is None


async def test_mdl_03_get_key_unknown_provider_raises(create_user):
    user = await create_user
    with pytest.raises(ValueError):
        user.get_key("openai")


async def test_mdl_04_clear_key_removes_key(create_user):
    user = await create_user
    user.api_keys_encrypted = "not-a-valid-fernet-token"
    assert user.get_key("cerebras") is None


    fernet = models_module._get_fernet()
    user.api_keys_encrypted = fernet.encrypt(b"not json").decode()
    assert user.get_key("cerebras") is None


 
async def test_mdl_06_invalid_secret_key_fails_lazily_at_first_use(monkeypatch):
    monkeypatch.setattr(models_module.settings, "SECRET_KEY", "short-invalid-key", raising=False)
    models_module._get_fernet.cache_clear()
 
    user = await User.create(telegram_id=6)  
    with pytest.raises((ValueError, binascii.Error)):
        await user.set_key("cerebras", "sk-whatever")
 
 
async def test_mdl_07_history_trimmed_from_the_start(create_user):
    user= create_user
    for i in range(1, 21):  # msg-1 .. msg-20
        await user.add_message("user", f"msg-{i}")
    for i in range(21, 26):  # msg-21 .. msg-25
        await user.add_message("user", f"msg-{i}")
 
    assert len(user.history) == 20
    assert user.history[0]["content"] == "msg-6"
    assert user.history[-1]["content"] == "msg-25"
 
async def test_mdl_08_concurrent_add_message_last_write_wins():
    telegram_id = 8
    base_user = await User.create(telegram_id=telegram_id)
    await base_user.add_message("user", "base")  # непустая history до "гонки"
 
    instance_a = await User.get(telegram_id=telegram_id)
    instance_b = await User.get(telegram_id=telegram_id)
 
    await asyncio.gather(
        instance_a.add_message("user", "A"),
        instance_b.add_message("user", "B"),
    )
 
    fresh = await User.get(telegram_id=telegram_id)
    assert len(fresh.history) == 2, (
        "Если это упало — конкурентность починили (длина стала 3), "
        "нужно обновить тест под новое поведение"
    )
    last_content = fresh.history[-1]["content"]
    assert last_content in ("A", "B")
 
async def test_mdl_09_new_record_defaults():
    user, created = await User.get_or_create(telegram_id=9)

    assert created is True
    assert user.current_provider == "cerebras"
    assert user.history == []
    assert user.awaiting_input is None

async def test_mdl_10_clear_key_removes_key(create_user):
    user = await create_user
    await user.set_key("cerebras", "old_key")
    await user.clear_key("cerebras")
    assert user.get_key("cerebras") is None
 
async def test_mdl_11_set_key_overwrites_old_value(create_user):
    user = create_user
    await user.set_key("cerebras", "old_key")
    await user.set_key("cerebras", "new_key") 
    assert user.get_key("cerebras") == "new_key"
    assert "old_key" not in user.api_keys_encrypted
 

