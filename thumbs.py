"""Inline qidiruv uchun poster-miniatyuralar: Telegram file_id -> ImgBB -> doimiy https URL.

Inline natijadagi rasm faqat ochiq URL bo'lishi mumkin (file_id ishlamaydi), shuning uchun poster
qo'yilganda u bir marta ImgBB ga yuklanadi va URL bazada saqlanadi.
"""
import asyncio
import base64
import logging

import aiohttp
from aiogram import Bot

import config
import db
import store

log = logging.getLogger(__name__)
IMGBB_URL = "https://api.imgbb.com/1/upload"


async def _upload(data: bytes) -> str | None:
    payload = {"key": config.IMGBB_API_KEY, "image": base64.b64encode(data).decode()}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(IMGBB_URL, data=payload) as r:
                if r.status != 200:
                    log.warning("ImgBB status=%s", r.status)
                    return None
                js = await r.json()
                d = js.get("data") or {}
                return (js.get("success") and (d.get("display_url") or d.get("url"))) or None
    except Exception as e:  # noqa: BLE001
        log.warning("ImgBB xato: %s", e)
        return None


async def make_thumb(bot: Bot, file_id: str) -> str | None:
    """Telegramdagi rasmni ImgBB ga yuklab, URL qaytaradi (kalit yo'q/xato bo'lsa None)."""
    if not config.IMGBB_API_KEY:
        return None
    try:
        buf = await bot.download(file_id)
        return await _upload(buf.getvalue())
    except Exception as e:  # noqa: BLE001
        log.warning("thumb yuklab olinmadi: %s", e)
        return None


async def thumb_for_anime(bot: Bot, aid: int, file_id: str) -> None:
    url = await make_thumb(bot, file_id)
    if url:
        await db.update_anime(aid, "thumb_url", url)
        store.invalidate_anime()


async def backfill(bot: Bot) -> tuple[int, int]:
    """Posteri bor, lekin miniatyurasi yo'q animelar uchun URL yaratadi. (muvaffaqiyatli, jami)"""
    rows = await db.animes_without_thumb()
    done = 0
    for r in rows:
        url = await make_thumb(bot, r["poster_file_id"])
        if url:
            await db.update_anime(r["id"], "thumb_url", url)
            done += 1
        await asyncio.sleep(0.3)
    store.invalidate_anime()
    return done, len(rows)
