"""UPLOAD_CHANNEL_ID kanali bilan ishlash.

1) KANALDAN BOTGA: kanalga video tashlansa va sarlavhada anime ID + qism raqami bo'lsa,
   bot uni avtomatik shu animega qo'shadi (botda 11 qism bo'lsa va kanalga 12-qism tashlansa — 12-qism qo'shiladi).
2) BOTDAN KANALGA: admin botga qism yuklaganda bot har bir videoni kanalga ham
   "id: .. / qism: .." sarlavhasi bilan birma-bir nusxalaydi (zaxira va qayta tiklash uchun).

Sarlavha formatlari (hammasi bo'ladi):
    id: 32            32 12
    qism: 12          naruto-1 12-qism
"""
import asyncio
import logging
import re
import time

from aiogram import Bot, F, Router
from aiogram.types import Message

import config
import db
import store

log = logging.getLogger(__name__)
router = Router()
router.channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)
router.edited_channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)

# "id: 32", "ID=naruto-1", "id 32" (lekin "idea", "video" emas)
ID_RE = re.compile(r"(?<![a-z0-9])id(?:\s*[:=#]\s*|\s+)([a-z0-9][a-z0-9-]{0,40})", re.I)
EP_RE1 = re.compile(r"(?<![a-z0-9])qism\s*[:=#\-]?\s*(\d{1,4})", re.I)
EP_RE2 = re.compile(r"(?<!\d)(\d{1,4})\s*-?\s*qism", re.I)
PAIR_RE = re.compile(r"^\s*([a-z0-9][a-z0-9-]{0,40})[\s,|/]+(\d{1,4})\s*(?:-?\s*qism)?\s*$", re.I)


def parse_caption(caption: str | None):
    """(anime_id, qism_raqami) yoki None."""
    if not caption:
        return None
    m = PAIR_RE.match(caption)
    if m:
        return m.group(1).lower(), int(m.group(2))
    i = ID_RE.search(caption)
    e = EP_RE1.search(caption) or EP_RE2.search(caption)
    if i and e:
        return i.group(1).lower(), int(e.group(1))
    return None


_last_warn = 0.0


async def _warn(bot: Bot, text: str) -> None:
    """Asosiy adminlarga qisqa xabar (15 soniyada ko'pi bilan bitta — ommaviy yuklashda spam bo'lmasin)."""
    global _last_warn
    log.warning("kanal: %s", text)
    if time.monotonic() - _last_warn < 15:
        return
    _last_warn = time.monotonic()
    for uid in config.ADMIN_IDS:
        try:
            await bot.send_message(uid, f"⚠️ <b>Yuklash kanali:</b> {text}")
        except Exception:  # noqa: BLE001
            pass


@router.channel_post(F.video)
@router.edited_channel_post(F.video)
async def ingest(m: Message, bot: Bot):
    parsed = parse_caption(m.caption)
    if not parsed:
        return await _warn(bot, "videoda anime ID va qism topilmadi. Sarlavhaga <code>id: 32</code> va "
                                "<code>qism: 12</code> yozing (yoki <code>32 12</code>). Post tahrirlansa ham qabul qilinadi.")
    code, n = parsed
    a = await db.anime_by_code(code)
    if not a:
        return await _warn(bot, f"<code>{code}</code> ID li anime botda yo'q ({n}-qism qo'shilmadi).")
    await db.set_episode(a["id"], n, m.video.file_id)
    store.invalidate_anime()
    log.info("kanaldan qo'shildi: %s %s-qism", code, n)


# ── botdan kanalga nusxalash (birma-bir, flood-wait'siz) ─────
_queue: asyncio.Queue = asyncio.Queue()


def mirror(code: str, title: str, n: int, file_id: str) -> None:
    if config.UPLOAD_CHANNEL_ID:
        _queue.put_nowait((code, title, n, file_id))


async def mirror_worker(bot: Bot) -> None:
    while True:
        code, title, n, fid = await _queue.get()
        try:
            await bot.send_video(config.UPLOAD_CHANNEL_ID, fid, caption=f"🎬 {title}\nid: {code}\nqism: {n}")
        except Exception as e:  # noqa: BLE001
            log.warning("kanalga nusxalanmadi (%s %s-qism): %s", code, n, e)
        await asyncio.sleep(3)  # kanalga ~20 post/daqiqa chegarasiga mos
