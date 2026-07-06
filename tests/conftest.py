import pytest
import pytest_asyncio
from tortoise import Tortoise
from unittest.mock import AsyncMock
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
