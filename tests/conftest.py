from cryptography.fernet import Fernet
import pytest
import pytest_asyncio
from tortoise import Tortoise
from src.database import models as models_module
from src.database.models import SUPPORTED_PROVIDERS, User


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models":["src.database.models"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()

@pytest.fixture
async def create_user():
    telegram_id=82618686165
    user, _ = await User.get_or_create(telegram_id=telegram_id)
    yield user



@pytest.fixture(autouse=True)
def fresh_fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(models_module.settings, "SECRET_KEY", key, raising=False)
    models_module._get_fernet.cache_clear()
    yield
    models_module._get_fernet.cache_clear()
 
