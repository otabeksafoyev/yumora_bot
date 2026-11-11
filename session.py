"""Telegram so'rovlari uchun sessiya: ulanishlar ko'p, flood-wait bo'lsa o'zi kutib qayta uradi."""
import asyncio
import logging

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter

log = logging.getLogger(__name__)


class RobustSession(AiohttpSession):
    def __init__(self) -> None:
        super().__init__(limit=300, timeout=60)

    async def make_request(self, bot, method, timeout=None):
        for attempt in range(3):
            try:
                return await super().make_request(bot, method, timeout)
            except TelegramRetryAfter as e:
                if attempt == 2:
                    raise
                wait = min(e.retry_after + 0.5, 30)
                log.warning("flood-wait %.1fs (%s)", wait, type(method).__name__)
                await asyncio.sleep(wait)
