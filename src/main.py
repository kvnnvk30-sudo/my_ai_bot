import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from tortoise import Tortoise

from src.config import settings
from src.handlers import common, settings as settings_handlers, chat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db() -> None:
    await Tortoise.init(
        db_url=settings.DB_URL,
        modules={"models": ["src.database.models"]},
    )
    await Tortoise.generate_schemas()


async def main() -> None:
    await init_db()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # явные include_router, без автосканирования — см. README
    for module in (common, settings_handlers, chat):
        dp.include_router(module.router)

    logger.info("Бот запускается (муляж-провайдеры, эхо-ответы)...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
