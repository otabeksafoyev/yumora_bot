"""
Xotira keshi va buferlar — 200k foydalanuvchida bazaga yuk tushmasligi uchun.

Issiq yo'l (start -> qism ochish -> qism almashtirish) bazaga umuman murojaat qilmaydi:
  * anime va qismlar ro'yxati TTL keshda turadi;
  * "single-flight": kesh eskirganda 1000 ta user bir vaqtda kirsa ham bazaga 1 ta so'rov ketadi;
  * ko'rishlar soni va "oxirgi faollik" xotirada yig'ilib, har bir necha soniyada bitta so'rov bilan yoziladi;
  * userlar/banlar/adminlar to'plami xotirada (tekshiruv O(1)).
"""
import asyncio
import logging
import time
from collections import Counter
from typing import Awaitable, Callable, NamedTuple

from cachetools import TTLCache

import config
import db

log = logging.getLogger(__name__)

BOT_USERNAME = ""

# ── to'plamlar (startda bazadan yuklanadi) ──────────────────
known_users: set[int] = set()
banned: set[int] = set()
db_admins: dict[int, set] = {}

# ── yig'ilib boradigan buferlar ─────────────────────────────
_active_buf: set[int] = set()
_views_buf: Counter = Counter()

# ── keshlar ─────────────────────────────────────────────────
_anime_code: TTLCache = TTLCache(maxsize=5000, ttl=300)
_anime_id: TTLCache = TTLCache(maxsize=5000, ttl=300)
_eps: TTLCache = TTLCache(maxsize=800, ttl=120)
_lists: TTLCache = TTLCache(maxsize=3000, ttl=30)  # qidiruv/top natijalari
_misc: TTLCache = TTLCache(maxsize=50, ttl=60)  # stats, kanallar
_inflight: dict = {}


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS or uid in db_admins


def has_perm(uid: int, perm: str) -> bool:
    """Asosiy admin (ADMIN_IDS) hammasiga ega; qolganlar — o'zlariga berilgan huquqlar."""
    if uid in config.ADMIN_IDS:
        return True
    if perm == "owner":
        return False
    return perm in db_admins.get(uid, ())


async def _cached(cache: TTLCache, key, loader: Callable[[], Awaitable]):
    try:
        return cache[key]
    except KeyError:
        pass
    fk = (id(cache), key)
    fut = _inflight.get(fk)
    if fut is not None:
        return await asyncio.shield(fut)
    fut = asyncio.get_running_loop().create_future()
    fut.add_done_callback(lambda f: f.cancelled() or f.exception())
    _inflight[fk] = fut
    try:
        val = await loader()
        cache[key] = val
        fut.set_result(val)
        return val
    except BaseException as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _inflight.pop(fk, None)


async def load_initial() -> None:
    known_users.update(await db.all_user_ids())
    banned.update(await db.banned_ids())
    db_admins.update(await db.admins_map())
    log.info("yuklandi: users=%d banned=%d", len(known_users), len(banned))


# ── foydalanuvchi ───────────────────────────────────────────
async def register(uid: int) -> None:
    if uid not in known_users:
        known_users.add(uid)
        try:
            await db.add_user(uid)
        except Exception:
            known_users.discard(uid)
            raise
    _active_buf.add(uid)


# ── anime ───────────────────────────────────────────────────
async def anime_by_code(code: str):
    return await _cached(_anime_code, code, lambda: db.anime_by_code(code))


async def anime_by_id(aid: int):
    return await _cached(_anime_id, aid, lambda: db.anime_by_id(aid))


class Eps(NamedTuple):
    files: dict  # {qism_raqami: file_id}
    numbers: list  # tartiblangan raqamlar


async def episodes(aid: int) -> Eps:
    async def load():
        files = await db.episodes_of(aid)
        return Eps(files, sorted(files))

    return await _cached(_eps, aid, load)


def invalidate_anime() -> None:
    for c in (_anime_code, _anime_id, _eps, _lists):
        c.clear()
    _misc.pop("channels", None)


async def search(q: str) -> list[dict]:
    return await _cached(_lists, ("s", q), lambda: db.search(q, 20))


async def top(limit: int = 20) -> list[dict]:
    return await _cached(_lists, ("t", limit), lambda: db.top(limit))


async def stats() -> dict:
    return await _cached(_misc, "stats", db.stats)


async def channels_for(anime_id: int) -> list[dict]:
    allch = await _cached(_misc, "channels", db.channels)
    return [c for c in allch if c["kind"] == "sub" and (c["anime_id"] is None or c["anime_id"] == anime_id)]


async def news_channels() -> list[dict]:
    return [c for c in await _cached(_misc, "channels", db.channels) if c["kind"] == "news"]


async def genres() -> list:
    return await _cached(_lists, "genres", db.genres)


async def by_genre(genre: str, page: int, size: int) -> list[dict]:
    return await _cached(_lists, ("g", genre, page, size), lambda: db.by_genre(genre, size + 1, page * size))


async def default_poster():
    return await _cached(_misc, "default_poster", lambda: db.get_setting("default_poster"))


async def default_thumb():
    return await _cached(_misc, "default_thumb", lambda: db.get_setting("default_thumb"))


async def set_default_poster(file_id: str, thumb_url: str | None = None) -> None:
    await db.set_setting("default_poster", file_id)
    await db.set_setting("default_thumb", thumb_url)
    _misc.pop("default_poster", None)
    _misc.pop("default_thumb", None)
    invalidate_anime()


def forget(anime: dict) -> None:
    """Bitta anime keshini tozalash (masalan, baho berilgandan keyin)."""
    _anime_id.pop(anime["id"], None)
    _anime_code.pop(anime["code"], None)
    for k in [k for k in _lists if k != "genres"]:
        _lists.pop(k, None)


def invalidate_channels() -> None:
    _misc.pop("channels", None)


def hit(anime_id: int) -> None:
    _views_buf[anime_id] += 1


# ── fon ishi: buferlarni bazaga yozish ──────────────────────
async def flush() -> None:
    global _views_buf
    if _active_buf:
        ids = list(_active_buf)
        _active_buf.clear()
        for i in range(0, len(ids), 5000):
            await db.touch_users(ids[i : i + 5000])
    if _views_buf:
        buf, _views_buf = _views_buf, Counter()
        try:
            await db.add_views(list(buf.keys()), list(buf.values()))
        except Exception:
            _views_buf.update(buf)  # yozilmadi — keyingi safar qayta uriniladi
            raise


async def flush_loop(interval: float = 15.0) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await flush()
        except Exception:  # noqa: BLE001
            log.exception("flush xatosi")
