"""Majburiy obuna tekshiruvi. Natija keshlanadi, xatoda foydalanuvchi bloklanmaydi."""
import asyncio
import logging

from aiogram import Bot
from cachetools import TTLCache

import store

log = logging.getLogger(__name__)

# (user_id, chat_id) -> obuna bo'lgan. 10 daqiqa. Sekundiga yuzlab so'rovda
# getChatMember ni Telegram limitidan oshirib yubormaslik uchun.
_ok: TTLCache = TTLCache(maxsize=300_000, ttl=600)
_TIMEOUT = 4.0


async def _check(bot: Bot, uid: int, ch: dict):
    key = (uid, ch["chat_id"])
    if key in _ok:
        return None
    try:
        m = await asyncio.wait_for(bot.get_chat_member(ch["chat_id"], uid), _TIMEOUT)
    except Exception as e:  # noqa: BLE001
        # Sekin kanal / bot admin emas / kanal o'chgan — userni to'smaymiz
        log.warning("getChatMember %s user=%s: %s", ch["chat_id"], uid, e)
        return None
    left = m.status in ("left", "kicked") or (m.status == "restricted" and not getattr(m, "is_member", True))
    if left:
        return ch
    _ok[key] = True
    return None


async def missing(bot: Bot, uid: int, anime_id: int) -> list[dict]:
    """Foydalanuvchi obuna bo'lmagan kanallar ro'yxati."""
    if store.is_admin(uid):
        return []
    chans = await store.channels_for(anime_id)
    if not chans:
        return []
    res = await asyncio.gather(*(_check(bot, uid, c) for c in chans))
    return [c for c in res if c]
