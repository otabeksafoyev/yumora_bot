import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, Message
from cachetools import TTLCache

import store

log = logging.getLogger(__name__)


class GateMiddleware(BaseMiddleware):
    """Ban + spamdan himoya + userni ro'yxatga olish. Bazaga faqat YANGI user uchun boradi."""

    def __init__(self) -> None:
        self._recent = TTLCache(maxsize=300_000, ttl=0.6)  # user boshiga ~0.6s da 1 ta hodisa

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)
        uid = user.id

        if uid in store.banned:
            return

        if not store.is_admin(uid):
            if uid in self._recent:
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer()
                    except Exception:  # noqa: BLE001
                        pass
                return
            self._recent[uid] = 1

        if isinstance(event, (Message, CallbackQuery, InlineQuery)):
            await store.register(uid)
        return await handler(event, data)
