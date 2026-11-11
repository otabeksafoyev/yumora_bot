import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

import config
import db
import store
from handlers import admin, inline, user
from middlewares import GateMiddleware
from session import RobustSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


async def on_error(event: ErrorEvent):
    log.exception("handler xatosi", exc_info=event.exception)
    cq = event.update.callback_query
    if cq:
        try:
            await cq.answer("Xatolik, qayta urinib ko'ring", show_alert=False)
        except Exception:  # noqa: BLE001
            pass
    return True


async def main() -> None:
    await db.init(config.DATABASE_URL, config.DB_POOL_MAX)
    await store.load_initial()

    bot = Bot(config.BOT_TOKEN, session=RobustSession(),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    store.BOT_USERNAME = (await bot.get_me()).username

    dp = Dispatcher(storage=MemoryStorage())
    gate = GateMiddleware()
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.inline_query.outer_middleware(gate)
    dp.errors.register(on_error)
    dp.include_routers(admin.panel, admin.router, inline.router, user.router)  # admin birinchi: FSM holatlari ustun

    flusher = asyncio.create_task(store.flush_loop())
    try:
        await bot.delete_webhook()
        await dp.start_polling(
            bot, allowed_updates=["message", "callback_query", "inline_query", "channel_post"]
        )
    finally:
        flusher.cancel()
        try:
            await store.flush()
        finally:
            await bot.session.close()
            await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
