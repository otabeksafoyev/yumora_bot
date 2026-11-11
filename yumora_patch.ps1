# Yumora bot patch: inline poster-miniatyuralar + havola orqali karta
# Ishga tushirish (bot papkasida, masalan C:\yumoribot):
#   powershell -ExecutionPolicy Bypass -File .\yumora_patch.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\main.py") -or -not (Test-Path ".\handlers\admin.py")) {
    Write-Host "XATO: skriptni bot papkasiga (main.py yonidagi) qo'ying." -ForegroundColor Red; exit 1
}
$store = Get-Content ".\store.py" -Raw -Encoding UTF8
if ($store -notmatch "def has_perm") {
    Write-Host "XATO: sizda admin-huquqlar versiyasi yo'q. Avval oxirgi to'liq animebot.zip ni oching." -ForegroundColor Red; exit 1
}
$cfg = Get-Content ".\config.py" -Raw -Encoding UTF8
if ($cfg -match "IMGBB_API_KEY") {
    Write-Host "Patch allaqachon qo'llangan. Hech narsa o'zgartirilmadi." -ForegroundColor Yellow; exit 0
}

function Save-File([string]$Path, [string]$Text) {
    $full = Join-Path (Get-Location) $Path
    $dir = Split-Path $full
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText($full, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ("  OK  " + $Path) -ForegroundColor Green
}

Write-Host "Patch qo'llanmoqda..." -ForegroundColor Cyan

Save-File 'config.py' @'
import os

from dotenv import load_dotenv

load_dotenv()


def _ints(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_IDS = _ints(os.getenv("ADMIN_IDS", ""))
UPLOAD_CHANNEL_ID = int(os.getenv("UPLOAD_CHANNEL_ID", "0") or 0)
START_PHOTO = os.getenv("START_PHOTO", "").strip() or None
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "15") or 15)

# Telegram broadcast chegarasi ~30 xabar/soniya. 25 — xavfsiz qiymat.
BROADCAST_RATE = int(os.getenv("BROADCAST_RATE", "25") or 25)

# Inline qidiruvdagi poster-miniatyuralar uchun (https://api.imgbb.com — bepul kalit). Bo'sh bo'lsa rasm chiqmaydi.
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "").strip()
'@

Save-File '.env.example' @'
BOT_TOKEN=123456:ABC
DATABASE_URL=postgresql://user:pass@host:5432/dbname
# Vergul bilan ajratilgan admin ID lar
ADMIN_IDS=123456789
# Ixtiyoriy: shu kanalga video tashlansa avtomatik qism saqlanadi (caption: id:kod  qism:5)
UPLOAD_CHANNEL_ID=0
# Ixtiyoriy: /start dagi rasm (file_id yoki URL)
START_PHOTO=
# Baza pooli (Railway Postgres uchun 10-15 yetadi)
DB_POOL_MAX=15
# Inline qidiruvda poster chiqishi uchun ImgBB kaliti (https://api.imgbb.com)
IMGBB_API_KEY=
'@

Save-File 'db.py' @'
"""PostgreSQL (asyncpg) — ORM yo'q, faqat tez va oddiy so'rovlar."""
import logging

import asyncpg

log = logging.getLogger(__name__)
pool: asyncpg.Pool

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id       BIGINT PRIMARY KEY,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
    banned      BOOLEAN NOT NULL DEFAULT FALSE,
    blocked     BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS animes (
    id             SERIAL PRIMARY KEY,
    code           TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    poster_file_id TEXT,
    trailer_file_id TEXT,
    genres         TEXT[] NOT NULL DEFAULT '{}',
    views          BIGINT NOT NULL DEFAULT 0,
    rating_sum     INT NOT NULL DEFAULT 0,
    rating_count   INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE animes ADD COLUMN IF NOT EXISTS trailer_file_id TEXT;
ALTER TABLE animes ADD COLUMN IF NOT EXISTS thumb_url TEXT;
ALTER TABLE animes ADD COLUMN IF NOT EXISTS genres TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE animes ADD COLUMN IF NOT EXISTS rating_sum INT NOT NULL DEFAULT 0;
ALTER TABLE animes ADD COLUMN IF NOT EXISTS rating_count INT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS ratings (
    anime_id INT NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    user_id  BIGINT NOT NULL,
    score    SMALLINT NOT NULL,
    PRIMARY KEY (anime_id, user_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS episodes (
    anime_id INT NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    number   INT NOT NULL,
    file_id  TEXT NOT NULL,
    PRIMARY KEY (anime_id, number)
);
CREATE TABLE IF NOT EXISTS channels (
    id       SERIAL PRIMARY KEY,
    chat_id  BIGINT NOT NULL,
    url      TEXT NOT NULL,
    title    TEXT NOT NULL,
    anime_id INT REFERENCES animes(id) ON DELETE CASCADE,  -- NULL = hamma anime uchun
    kind     TEXT NOT NULL DEFAULT 'sub',                   -- sub = majburiy obuna, news = e'lon kanali
    UNIQUE (chat_id, anime_id)
);
ALTER TABLE channels ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'sub';
CREATE TABLE IF NOT EXISTS admins (tg_id BIGINT PRIMARY KEY, perms TEXT[] NOT NULL DEFAULT '{}');
ALTER TABLE admins ADD COLUMN IF NOT EXISTS perms TEXT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS animes_views_idx ON animes (views DESC);
"""


def _dsn(url: str) -> str:
    url = url.strip()
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    return url


async def init(url: str, max_size: int = 15) -> None:
    global pool
    pool = await asyncpg.create_pool(
        _dsn(url),
        min_size=2,
        max_size=max_size,
        command_timeout=20,
        max_inactive_connection_lifetime=300,
    )
    async with pool.acquire() as c:
        await c.execute(SCHEMA)
        try:  # nomi bo'yicha tez qidiruv uchun (ruxsat bo'lmasa — oddiy ILIKE ishlayveradi)
            await c.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            await c.execute(
                "CREATE INDEX IF NOT EXISTS animes_title_trgm ON animes USING gin (title gin_trgm_ops)"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("pg_trgm yoqilmadi (%s) — qidiruv sekinroq bo'ladi", e)


async def close() -> None:
    await pool.close()


# ── users ───────────────────────────────────────────────────
async def all_user_ids() -> set[int]:
    return {r["tg_id"] for r in await pool.fetch("SELECT tg_id FROM users")}


async def banned_ids() -> set[int]:
    return {r["tg_id"] for r in await pool.fetch("SELECT tg_id FROM users WHERE banned")}


async def admins_map() -> dict[int, set[str]]:
    return {r["tg_id"]: set(r["perms"]) for r in await pool.fetch("SELECT tg_id, perms FROM admins")}


async def add_user(uid: int) -> None:
    await pool.execute("INSERT INTO users (tg_id) VALUES ($1) ON CONFLICT DO NOTHING", uid)


async def touch_users(ids: list[int]) -> None:
    await pool.execute(
        "UPDATE users SET last_active = now(), blocked = FALSE WHERE tg_id = ANY($1::bigint[])", ids
    )


async def mark_blocked(ids: list[int]) -> None:
    await pool.execute("UPDATE users SET blocked = TRUE WHERE tg_id = ANY($1::bigint[])", ids)


async def set_banned(uid: int, value: bool) -> None:
    await pool.execute(
        "INSERT INTO users (tg_id, banned) VALUES ($1, $2) "
        "ON CONFLICT (tg_id) DO UPDATE SET banned = $2",
        uid,
        value,
    )


async def user_ids_after(last: int, limit: int) -> list[int]:
    rows = await pool.fetch(
        "SELECT tg_id FROM users WHERE tg_id > $1 AND NOT blocked AND NOT banned "
        "ORDER BY tg_id LIMIT $2",
        last,
        limit,
    )
    return [r["tg_id"] for r in rows]


async def set_admin_perms(uid: int, perms: list[str]) -> None:
    await pool.execute(
        "INSERT INTO admins (tg_id, perms) VALUES ($1, $2) "
        "ON CONFLICT (tg_id) DO UPDATE SET perms = EXCLUDED.perms", uid, perms)


async def del_admin(uid: int) -> None:
    await pool.execute("DELETE FROM admins WHERE tg_id = $1", uid)


# ── animes / episodes ───────────────────────────────────────
async def anime_by_code(code: str):
    r = await pool.fetchrow("SELECT * FROM animes WHERE code = $1", code)
    return dict(r) if r else None


async def anime_by_id(aid: int):
    r = await pool.fetchrow("SELECT * FROM animes WHERE id = $1", aid)
    return dict(r) if r else None


async def add_anime(code: str, title: str, genres: list[str], poster: str | None, trailer: str | None) -> int:
    return await pool.fetchval(
        "INSERT INTO animes (code, title, genres, poster_file_id, trailer_file_id) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING id",
        code, title, genres, poster, trailer,
    )


_EDITABLE = {"title", "genres", "poster_file_id", "trailer_file_id", "thumb_url"}


async def update_anime(aid: int, field: str, value) -> None:
    if field not in _EDITABLE:
        raise ValueError(field)
    await pool.execute(f"UPDATE animes SET {field} = $1 WHERE id = $2", value, aid)


async def animes_without_thumb() -> list[dict]:
    rows = await pool.fetch(
        "SELECT id, poster_file_id FROM animes WHERE poster_file_id IS NOT NULL AND thumb_url IS NULL ORDER BY id")
    return [dict(r) for r in rows]


async def delete_anime(aid: int) -> None:
    await pool.execute("DELETE FROM animes WHERE id = $1", aid)


async def rate(aid: int, uid: int, score: int):
    """Birinchi marta baho bergan bo'lsa (sum, count) qaytaradi, aks holda None."""
    return await pool.fetchrow(
        "WITH ins AS (INSERT INTO ratings (anime_id, user_id, score) VALUES ($1, $2, $3) "
        "ON CONFLICT DO NOTHING RETURNING 1) "
        "UPDATE animes SET rating_sum = rating_sum + $3, rating_count = rating_count + 1 "
        "WHERE id = $1 AND EXISTS (SELECT 1 FROM ins) RETURNING rating_sum, rating_count",
        aid, uid, score,
    )


async def user_rating(aid: int, uid: int):
    return await pool.fetchval("SELECT score FROM ratings WHERE anime_id=$1 AND user_id=$2", aid, uid)


async def episodes_of(aid: int) -> dict[int, str]:
    rows = await pool.fetch("SELECT number, file_id FROM episodes WHERE anime_id = $1", aid)
    return {r["number"]: r["file_id"] for r in rows}


async def set_episode(aid: int, number: int, file_id: str) -> None:
    await pool.execute(
        "INSERT INTO episodes (anime_id, number, file_id) VALUES ($1, $2, $3) "
        "ON CONFLICT (anime_id, number) DO UPDATE SET file_id = EXCLUDED.file_id",
        aid,
        number,
        file_id,
    )


async def delete_episode(aid: int, number: int) -> bool:
    return (await pool.execute("DELETE FROM episodes WHERE anime_id=$1 AND number=$2", aid, number)).endswith("1")


async def max_episode(aid: int) -> int:
    return await pool.fetchval("SELECT COALESCE(MAX(number), 0) FROM episodes WHERE anime_id = $1", aid)


async def add_views(ids: list[int], counts: list[int]) -> None:
    await pool.execute(
        "UPDATE animes a SET views = a.views + v.c "
        "FROM unnest($1::int[], $2::int[]) AS v(id, c) WHERE a.id = v.id",
        ids,
        counts,
    )


def _like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_COLS = (
    "id, code, title, poster_file_id, thumb_url, genres, views, rating_sum, rating_count, "
    "(SELECT COUNT(*) FROM episodes e WHERE e.anime_id = animes.id) AS eps"
)


async def search(q: str, limit: int = 20) -> list[dict]:
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM animes WHERE title ILIKE '%' || $1 || '%' "
        "OR array_to_string(genres, ' ') ILIKE '%' || $1 || '%' ORDER BY views DESC LIMIT $2",
        _like(q), limit,
    )
    return [dict(r) for r in rows]


async def top(limit: int = 20) -> list[dict]:
    rows = await pool.fetch(f"SELECT {_COLS} FROM animes ORDER BY views DESC, id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def by_genre(genre: str, limit: int, offset: int) -> list[dict]:
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM animes WHERE $1 = ANY(genres) ORDER BY views DESC, title LIMIT $2 OFFSET $3",
        genre, limit, offset,
    )
    return [dict(r) for r in rows]


async def genres(limit: int = 40) -> list[tuple[str, int]]:
    rows = await pool.fetch(
        "SELECT g, COUNT(*) AS n FROM animes, unnest(genres) g GROUP BY g ORDER BY n DESC, g LIMIT $1", limit
    )
    return [(r["g"], r["n"]) for r in rows]


async def get_setting(key: str):
    return await pool.fetchval("SELECT value FROM settings WHERE key = $1", key)


async def set_setting(key: str, value: str | None) -> None:
    await pool.execute(
        "INSERT INTO settings (key, value) VALUES ($1, $2) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", key, value,
    )


async def dump() -> dict:
    return {
        "animes": [dict(r) for r in await pool.fetch("SELECT * FROM animes ORDER BY id")],
        "episodes": [dict(r) for r in await pool.fetch("SELECT * FROM episodes ORDER BY anime_id, number")],
        "channels": [dict(r) for r in await pool.fetch("SELECT * FROM channels ORDER BY id")],
        "settings": [dict(r) for r in await pool.fetch("SELECT * FROM settings")],
    }


async def stats() -> dict:
    r = await pool.fetchrow(
        "SELECT (SELECT COUNT(*) FROM users) AS users,"
        " (SELECT COUNT(*) FROM users WHERE last_active > now() - interval '1 day') AS day,"
        " (SELECT COUNT(*) FROM users WHERE blocked) AS blocked,"
        " (SELECT COUNT(*) FROM animes) AS animes,"
        " (SELECT COUNT(*) FROM episodes) AS episodes,"
        " (SELECT COALESCE(SUM(views), 0) FROM animes) AS views"
    )
    return dict(r)


# ── channels ────────────────────────────────────────────────
async def channels() -> list[dict]:
    return [dict(r) for r in await pool.fetch("SELECT * FROM channels ORDER BY id")]


async def add_channel(chat_id: int, url: str, title: str, anime_id: int | None, kind: str = "sub") -> None:
    await pool.execute(
        "DELETE FROM channels WHERE chat_id = $1 AND anime_id IS NOT DISTINCT FROM $2", chat_id, anime_id
    )
    await pool.execute(
        "INSERT INTO channels (chat_id, url, title, anime_id, kind) VALUES ($1, $2, $3, $4, $5)",
        chat_id, url, title, anime_id, kind,
    )


async def delete_channel(cid: int) -> None:
    await pool.execute("DELETE FROM channels WHERE id = $1", cid)
'@

Save-File 'store.py' @'
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
'@

Save-File 'thumbs.py' @'
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
'@

Save-File 'handlers/inline.py' @'

from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

import keyboards as kb
import store
from handlers.user import avg_of

router = Router()


def _result(a: dict, default_thumb) -> InlineQueryResultArticle:
    """Kaworai uslubidagi ro'yxat qatori: poster + sarlavha + 2 qator tavsif.

    Tanlanganda chatga anime HAVOLASI yuboriladi. Botning o'z chatida bot uni ko'rib,
    havolani o'chiradi va to'liq kartani (poster + tugmalar) chiqaradi; boshqa chatda esa
    bu bosiladigan havola bo'lib, do'stlarga ulashishga yaraydi.
    """
    genres = a["genres"]
    icon = kb.genre_emoji(genres[0]) if genres else "🎬"
    desc = (f"⭐ {avg_of(a):.1f}  •  📺 {a['eps']} qism  •  👁 {a['views']}\n"
            f"🎭 {' • '.join(genres[:4]) or '—'}")
    kwargs = {}
    thumb = a.get("thumb_url") or default_thumb
    if thumb:
        kwargs["thumbnail_url"] = thumb
        kwargs["thumbnail_width"] = 200
        kwargs["thumbnail_height"] = 280
    return InlineQueryResultArticle(
        id=str(a["id"]),
        title=f"{icon} {a['title']}",
        description=desc,
        input_message_content=InputTextMessageContent(message_text=kb.start_link(a["code"])),
        **kwargs,
    )


@router.inline_query()
async def inline(q: InlineQuery):
    text = q.query.strip()
    if not text:
        items = await store.top(20)
    elif len(text) < 2:
        items = []
    else:
        items = await store.search(text)  # nom YOKI janr bo'yicha
    dt = await store.default_thumb()
    # Natija hammaga bir xil -> Telegram o'zi ham keshlaydi
    await q.answer([_result(a, dt) for a in items], cache_time=30, is_personal=False)
'@

Save-File 'handlers/user.py' @'
import asyncio
import html
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import CallbackQuery, Message

import config
import keyboards as kb
import store
import subs

router = Router()
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
LINK_RE = re.compile(r"t\.me/[A-Za-z0-9_]+\?start=([A-Za-z0-9_-]{1,64})")
DIV = "✨━━━━━━━━━━━━✨"
EFFECT_CONFETTI = "5046509860389126442"  # Telegram xabar effekti (faqat shaxsiy chatda)
PAGE_SIZE = 10
_bg: set[asyncio.Task] = set()


def esc(s) -> str:
    return html.escape(str(s or ""))


def fire(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def greeting() -> str:
    h = (datetime.utcnow() + timedelta(hours=5)).hour  # O'zbekiston vaqti
    if 5 <= h < 11:
        return "🌅 Xayrli tong"
    if 11 <= h < 17:
        return "☀️ Xayrli kun"
    if 17 <= h < 22:
        return "🌆 Xayrli kech"
    return "🌙 Xayrli tun"


def stars(avg: float) -> str:
    f = int(round(max(0.0, min(avg, 10.0)) / 10 * 5))
    return "⭐" * f + "☆" * (5 - f)


def bar(done: int, total: int, width: int = 8) -> str:
    if total <= 0:
        return "⬜" * width
    f = max(1, int(round(done / total * width))) if done > 0 else 0
    return "🟩" * f + "⬜" * (width - f)


def avg_of(a: dict) -> float:
    return a["rating_sum"] / a["rating_count"] if a["rating_count"] else 0.0


def protect(uid: int) -> bool:
    return not store.is_admin(uid)


async def poster_of(a: dict):
    return a.get("poster_file_id") or await store.default_poster()


async def show(c: CallbackQuery, text: str, markup) -> None:
    """Matnli xabar bo'lsa tahrirlaydi, rasm/video bo'lsa yangi xabar yuboradi."""
    if c.message.text:
        try:
            await c.message.edit_text(text, reply_markup=markup)
            return
        except Exception:  # noqa: BLE001
            pass
    await c.message.answer(text, reply_markup=markup)


# ── asosiy menyu ────────────────────────────────────────────
async def send_home(m: Message, user, effect: bool = False) -> None:
    name = esc(user.first_name) if user and user.first_name else "do'st"
    text = (f"<b>{greeting()}, {name}!</b> 🎉 Bugun nima ko'ramiz?\n{DIV}\n"
            f"🎌 <b>Yumora TV</b> — Anime & Dorama\n🍿 Yoqimli tomosha!")
    photo = config.START_PHOTO or await store.default_poster()
    fx = {"message_effect_id": EFFECT_CONFETTI} if effect else {}
    for extra in ([fx, {}] if fx else [{}]):
        try:
            if photo:
                await m.answer_photo(photo, caption=text, reply_markup=kb.home_kb(), **extra)
            else:
                await m.answer(text, reply_markup=kb.home_kb(), **extra)
            return
        except Exception:  # noqa: BLE001
            continue
    await m.answer(text, reply_markup=kb.home_kb())


# ── kartochka ───────────────────────────────────────────────
def card_text(a: dict, eps_count: int) -> str:
    cnt = a["rating_count"]
    return (f"🎬 <b>{esc(a['title'])}</b>\n{DIV}\n"
            f"🎭 <b>Janr:</b> {esc(', '.join(a['genres']) or '—')}\n"
            f"{stars(avg_of(a))} <b>{avg_of(a):.1f}</b>  •  👥 {cnt} ovoz\n"
            f"📺 <b>Qismlar:</b> {eps_count}\n🆔 <code>{a['code']}</code>")


async def send_card(bot: Bot, chat_id: int, a: dict, uid: int) -> None:
    eps = await store.episodes(a["id"])
    text = card_text(a, len(eps.numbers))
    markup = kb.card_kb(a, bool(eps.numbers))
    pc = protect(uid)
    try:
        if a.get("trailer_file_id"):
            await bot.send_video(chat_id, a["trailer_file_id"], caption=text, reply_markup=markup, protect_content=pc)
            return
        poster = await poster_of(a)
        if poster:
            await bot.send_photo(chat_id, poster, caption=text, reply_markup=markup, protect_content=pc)
            return
    except Exception:  # noqa: BLE001
        pass
    await bot.send_message(chat_id, text, reply_markup=markup)


# ── qism yuborish ───────────────────────────────────────────
def ep_caption(a: dict, n: int, numbers: list[int]) -> str:
    total = numbers[-1] if numbers else n
    return f"▶️ <b>{esc(a['title'])}</b>  •  {n}-qism\n🎞 {bar(n, total)} {n}/{total} qism"


async def _strip(msg: Message) -> None:
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


async def play(bot: Bot, uid: int, chat_id: int, a: dict, number: int | None, old: Message | None = None) -> None:
    """Qismni YANGI xabar sifatida yuboradi — oldingi video joyida qoladi."""
    eps = await store.episodes(a["id"])
    if not eps.numbers:
        await bot.send_message(chat_id, "⏳ Qismlar hali qo'shilmagan.")
        return
    if number not in eps.files:
        number = eps.numbers[0]

    miss = await subs.missing(bot, uid, a["id"])
    if miss:
        await bot.send_message(
            chat_id, "🔔 <b>Davom etish uchun kanallarga obuna bo'ling</b>, so'ng «✅ Tekshirish» ni bosing:",
            reply_markup=kb.sub_kb(miss, a["id"], number))
        return

    store.hit(a["id"])
    await bot.send_video(chat_id, eps.files[number], caption=ep_caption(a, number, eps.numbers),
                         reply_markup=kb.episodes_kb(a, eps.numbers, number), protect_content=protect(uid))
    if old is not None and old.video is not None:
        fire(_strip(old))  # eski videodagi tugmalar olinadi, video o'zi qoladi


async def open_payload(m: Message, bot: Bot, payload: str) -> bool:
    payload = payload.strip().lower()
    number = None
    if "_" in payload:
        payload, _, tail = payload.partition("_")
        number = int(tail) if tail.isdigit() else None
    if not CODE_RE.match(payload):
        return False
    a = await store.anime_by_code(payload)
    if not a:
        return False
    if number:
        await play(bot, m.from_user.id, m.chat.id, a, number)
    else:
        await send_card(bot, m.chat.id, a, m.from_user.id)
    return True


@router.message(CommandStart())
async def start(m: Message, bot: Bot):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1] != "home":
        if await open_payload(m, bot, parts[1]):
            return
        await m.answer("🤷 Bu ID bo'yicha hech narsa topilmadi.")
    await send_home(m, m.from_user, effect=True)


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def text_search(m: Message, bot: Bot):
    q = m.text.strip()
    link = LINK_RE.search(q)
    if link:  # inline natijadan kelgan havola: o'chirib, kartani chiqaramiz
        try:
            await m.delete()
        except Exception:  # noqa: BLE001
            pass
        if not await open_payload(m, bot, link.group(1)):
            await m.answer("🤷 Bu ID bo'yicha hech narsa topilmadi.")
        return
    if await open_payload(m, bot, q):
        return
    if len(q) < 2:
        return await m.answer("✏️ Kamida 2 ta harf yozing.")
    items = await store.search(q)
    if not items:
        return await m.answer("🤷 Hech narsa topilmadi. Boshqacha yozib ko'ring yoki janr bo'yicha qidiring.",
                              reply_markup=kb.back_home())
    await m.answer("🔎 <b>Natijalar:</b>", reply_markup=kb.list_kb(items, 0, False, "x"))


# ── menyu / ro'yxatlar / janr ───────────────────────────────
@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "edge")
async def edge(c: CallbackQuery):
    await c.answer("📄 Bu oxirgi sahifa")


@router.callback_query(F.data == "noep")
async def noep(c: CallbackQuery):
    await c.answer("⏳ Qismlar tez orada qo'shiladi", show_alert=True)


@router.callback_query(F.data == "menu")
async def menu(c: CallbackQuery):
    await c.answer()
    await send_home(c.message, c.from_user)


@router.callback_query(F.data == "help")
async def help_(c: CallbackQuery):
    await c.answer()
    await show(c, f"💡 <b>Qo'llanma</b>\n{DIV}\n"
                  "🔍 Anime nomini yoki ID sini yozing\n"
                  "🔎 «Janr bo'yicha qidirish» tugmasidan foydalaning\n"
                  "▶️ Qismni bossangiz video pastdan yuboriladi, oldingisi joyida qoladi\n"
                  "⭐ Yoqqan animega baho bering\n"
                  "📤 Do'stlaringizga ulashing", kb.back_home())


@router.callback_query(F.data == "gen")
async def genres(c: CallbackQuery):
    await c.answer()
    gl = await store.genres()
    if not gl:
        return await show(c, "⏳ Hozircha janrlar yo'q.", kb.back_home())
    await show(c, "🔎 <b>Janrni tanlang:</b>", kb.genres_kb(gl))


@router.callback_query(F.data.startswith("gn:"))
async def by_genre(c: CallbackQuery):
    _, g, page = c.data.rsplit(":", 2)
    page = int(page)
    await c.answer()
    items = await store.by_genre(g, page, PAGE_SIZE)
    has_next = len(items) > PAGE_SIZE
    await show(c, f"{kb.genre_emoji(g)} <b>{esc(g)}</b>", kb.list_kb(items[:PAGE_SIZE], page, has_next, f"gn:{g}",
                                                    ("◀️ Janrlar", "gen")))


@router.callback_query(F.data == "top")
async def top(c: CallbackQuery):
    await c.answer()
    items = await store.top(10)
    await show(c, "🔥 <b>Eng mashhur</b>", kb.list_kb(items, 0, False, "x"))


# ── kartochka / qismlar ─────────────────────────────────────
async def _anime(c: CallbackQuery, aid: str):
    a = await store.anime_by_id(int(aid))
    if not a:
        await c.answer("Topilmadi", show_alert=True)
    return a


@router.callback_query(F.data.startswith("a:"))
async def open_card(c: CallbackQuery, bot: Bot):
    await c.answer()
    a = await _anime(c, c.data.split(":")[1])
    if a:
        await send_card(bot, c.message.chat.id, a, c.from_user.id)


@router.callback_query(F.data.startswith("w:"))
async def watch_first(c: CallbackQuery, bot: Bot):
    await c.answer()
    a = await _anime(c, c.data.split(":")[1])
    if a:
        await play(bot, c.from_user.id, c.message.chat.id, a, None)


@router.callback_query(F.data.startswith("l:"))
async def episode_list(c: CallbackQuery):
    await c.answer()
    a = await _anime(c, c.data.split(":")[1])
    if not a:
        return
    eps = await store.episodes(a["id"])
    if not eps.numbers:
        return await c.answer("⏳ Qismlar yo'q", show_alert=True)
    await c.message.answer(f"📋 <b>{esc(a['title'])}</b>\n👇 Qismni tanlang:", reply_markup=kb.episodes_kb(a, eps.numbers, None, 0))


@router.callback_query(F.data.startswith("p:"))
async def play_cb(c: CallbackQuery, bot: Bot):
    _, aid, n = c.data.split(":")
    await c.answer()
    a = await store.anime_by_id(int(aid))
    if a:
        await play(bot, c.from_user.id, c.message.chat.id, a, int(n), old=c.message)


@router.callback_query(F.data.startswith("g:"))
async def page_cb(c: CallbackQuery):
    _, aid, page, cur = c.data.split(":")
    await c.answer()
    a = await store.anime_by_id(int(aid))
    eps = await store.episodes(int(aid))
    if a and eps.numbers:
        try:
            await c.message.edit_reply_markup(
                reply_markup=kb.episodes_kb(a, eps.numbers, int(cur) or None, int(page)))
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("c:"))
async def check_cb(c: CallbackQuery, bot: Bot):
    _, aid, n = c.data.split(":")
    a = await store.anime_by_id(int(aid))
    if not a:
        return await c.answer()
    if await subs.missing(bot, c.from_user.id, a["id"]):
        return await c.answer("❗ Hali hamma kanalga obuna bo'lmadingiz", show_alert=True)
    await c.answer("✅")
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await play(bot, c.from_user.id, c.message.chat.id, a, int(n))


# ── baho berish ─────────────────────────────────────────────
@router.callback_query(F.data.startswith("rt:"))
async def rate_start(c: CallbackQuery):
    import db
    aid = int(c.data.split(":")[1])
    old = await db.user_rating(aid, c.from_user.id)
    if old:
        return await c.answer(f"✅ Siz allaqachon baho bergansiz: {old}/10", show_alert=True)
    await c.answer()
    await c.message.answer("⭐ <b>Anime uchun baho bering (1-10):</b>\n\n😕 1 = Yomon  |  😐 5 = O'rtacha  |  🤩 10 = A'lo",
                           reply_markup=kb.rate_kb(aid))


@router.callback_query(F.data.startswith("rs:"))
async def rate_set(c: CallbackQuery):
    import db
    _, aid, score = c.data.split(":")
    aid, score = int(aid), int(score)
    if not 1 <= score <= 10:
        return await c.answer()
    row = await db.rate(aid, c.from_user.id, score)
    if row is None:
        return await c.answer("✅ Siz allaqachon baho bergansiz", show_alert=True)
    a = await store.anime_by_id(aid)
    if a:
        store.forget(a)
    avg = row["rating_sum"] / row["rating_count"]
    try:
        await c.message.edit_text(
            f"🎉 <b>Baho qabul qilindi!</b>\n\n🎬 <b>{esc(a['title']) if a else ''}</b>\n"
            f"⭐ Sizning bahoyingiz: <b>{score}/10</b>\n📊 O'rtacha reyting: <b>{avg:.1f}/10</b>",
            reply_markup=kb.back_home())
    except Exception:  # noqa: BLE001
        pass
    await c.answer(f"🤩 {score}/10 — Rahmat!", show_alert=True)


@router.callback_query(F.data == "rc")
async def rate_cancel(c: CallbackQuery):
    await c.answer()
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass
'@

Save-File 'handlers/admin.py' @'
import asyncio
import datetime as dt
import io
import json
import re
import zipfile

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Kb,
    KeyboardButton as KBtn,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import broadcast
import config
import db
import keyboards as kbd
import store
import thumbs
from handlers.user import CODE_RE, card_text, esc, fire, send_card

router = Router()
panel = Router()  # panel tugmalari — holat (FSM) ishlovchilaridan OLDIN tekshiriladi


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.is_admin(u.id))


class Perm(BaseFilter):
    """Adminning ma'lum huquqi bor-yo'qligini tekshiradi ('owner' — faqat asosiy admin)."""

    def __init__(self, key: str):
        self.key = key

    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.has_perm(u.id, self.key))


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
panel.message.filter(IsAdmin())
router.channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)

# ── tugma yozuvlari ─────────────────────────────────────────
B_ADD = "🆕 Anime qo'shish"
B_EPS = "🎞 Qism qo'shish"
B_MANAGE = "🛠 Anime boshqaruv"
B_CHANS = "📢 Kanallar"
B_CAST = "📣 Xabar yuborish"
B_STATS = "📊 Statistika"
B_BACKUP = "💾 Baza zaxira"
B_POSTER = "🖼 Standart poster"
B_ADMINS = "👑 Adminlar"
B_EXIT = "🚪 Chiqish"
B_CANCEL = "❌ Bekor qilish"
B_DONE = "✅ Tayyor"

# (tugma, huquq kaliti). Admin faqat o'ziga berilgan tugmalarni ko'radi.
BUTTONS = [(B_ADD, "add"), (B_EPS, "eps"), (B_MANAGE, "manage"), (B_CHANS, "chans"),
           (B_CAST, "cast"), (B_STATS, "stats"), (B_BACKUP, "backup"), (B_POSTER, "poster"),
           (B_ADMINS, "owner")]

# Yangi admin uchun belgilanadigan huquqlar
PERMS = [
    ("add", "🆕 Anime qo'shish"),
    ("eps", "🎞 Qism qo'shish"),
    ("manage", "🛠 Boshqaruv (tahrirlash / o'chirish)"),
    ("chans", "📢 Kanallar"),
    ("cast", "📣 Xabar yuborish"),
    ("stats", "📊 Statistika"),
    ("backup", "💾 Baza zaxira"),
    ("poster", "🖼 Standart poster"),
    ("ban", "🚫 Ban / Unban"),
]
PERM_LABEL = dict(PERMS)


def admin_kb(uid: int) -> ReplyKeyboardMarkup:
    shown = [t for t, p in BUTTONS if store.has_perm(uid, p)] + [B_EXIT]
    rows = [shown[i:i + 2] for i in range(0, len(shown), 2)]
    return ReplyKeyboardMarkup(keyboard=[[KBtn(text=t) for t in r] for r in rows],
                               resize_keyboard=True, is_persistent=True)


def flow_kb(done: bool = False) -> ReplyKeyboardMarkup:
    rows = ([[KBtn(text=B_DONE)]] if done else []) + [[KBtn(text=B_CANCEL)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def panel_text(uid: int) -> str:
    role = "OWNER 👑" if uid in config.ADMIN_IDS else "ADMIN 🛡"
    return (
        f"✨ <b>Yumora Admin Panel</b> ✨\nRol: <b>{role}</b>\n\n"
        "📖 <b>Qo'llanma:</b>\n"
        "🆕 <b>Anime qo'shish</b> — ID → nom → janr → poster/treyler, so'ng qismlar avtomatik\n"
        "🎞 <b>Qism qo'shish</b> — anime ID sini yozing, videolarni tashlang\n"
        "🛠 <b>Anime boshqaruv</b> — ID bo'yicha: tahrirlash, o'chirish, yuborish\n"
        "📢 <b>Kanallar</b> — majburiy obuna va news kanallar\n"
        "🖼 <b>Standart poster</b> — posteri yo'q animelar uchun rasm\n"
        "👑 <b>Adminlar</b> — yangi admin va uning huquqlari\n\n"
        "⚡️ /anime <code>ID</code> — boshqaruvni to'g'ridan-to'g'ri ochish\n🖼 /thumbs — eski animelar uchun inline rasmlarni tayyorlash\n"
        "🚫 /ban <code>id</code> · /unban <code>id</code> · 🗑 /delep <code>ID qism</code> · ⏹ /stopcast"
    )


class AddAnime(StatesGroup):
    code = State()
    title = State()
    genres = State()
    media = State()


class Pick(StatesGroup):
    q = State()


class AddEps(StatesGroup):
    up = State()


class EditF(StatesGroup):
    v = State()


class DelEp(StatesGroup):
    n = State()


class AddChan(StatesGroup):
    wait = State()


class Cast(StatesGroup):
    wait = State()


class SetPoster(StatesGroup):
    wait = State()


class NewAdmin(StatesGroup):
    id = State()


def parse_genres(text: str) -> list[str]:
    out: list[str] = []
    for p in re.split(r"[,;\n]+", text):
        p = p.strip()[:24]
        if p:
            p = p[:1].upper() + p[1:]
            if p.lower() not in [x.lower() for x in out]:
                out.append(p)
    return out[:8]


def parse_ep(caption: str | None):
    c = (caption or "").strip().lower()
    if c.isdigit():
        return int(c)
    m = re.search(r"(\d{1,4})\s*-?\s*qism", c) or re.search(r"qism\s*:?\s*(\d{1,4})", c)
    return int(m.group(1)) if m else None


# ═══ PANEL TUGMALARI (har birida huquq tekshiriladi) ═══════════
@panel.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(panel_text(m.from_user.id), reply_markup=admin_kb(m.from_user.id))


@panel.message(F.text == B_CANCEL)
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Bekor qilindi.", reply_markup=admin_kb(m.from_user.id))


@panel.message(F.text == B_EXIT)
async def leave(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🚪 Admin paneldan chiqdingiz. Qaytish: /admin", reply_markup=ReplyKeyboardRemove())


@panel.message(F.text == B_ADD, Perm("add"))
async def add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddAnime.code)
    await m.answer("🆔 <b>Anime ID</b> yozing — lotin harf, raqam va «-»\nMasalan: <code>naruto-1</code>",
                   reply_markup=flow_kb())


@panel.message(F.text == B_EPS, Perm("eps"))
async def eps_entry(m: Message, state: FSMContext):
    await ask_id(m, state, "eps")


@panel.message(F.text == B_MANAGE, Perm("manage"))
async def manage_entry(m: Message, state: FSMContext):
    await ask_id(m, state, "manage")


@panel.message(Command("anime"), Perm("manage"))
async def anime_cmd(m: Message, state: FSMContext):
    p = (m.text or "").split()
    a = await db.anime_by_code(p[1].lower()) if len(p) > 1 else None
    if not a:
        return await m.answer("🆔 Foydalanish: /anime <code>ID</code>")
    await state.clear()
    await show_manage(m, a["id"])


@panel.message(F.text == B_POSTER, Perm("poster"))
async def poster_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SetPoster.wait)
    has = await store.default_poster()
    await m.answer(f"🖼 <b>Standart poster</b> — posteri yo'q animelar uchun qidiruvda ko'rinadi.\n"
                   f"Hozir: <b>{'✅ o‘rnatilgan' if has else '❌ yo‘q'}</b>\n\n👇 Yangi rasmni yuboring:",
                   reply_markup=flow_kb())


@panel.message(F.text == B_CHANS, Perm("chans"))
async def chans_entry(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await chan_list()
    await m.answer(text, reply_markup=kb)


@panel.message(F.text == B_CAST, Perm("cast"))
async def cast_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Cast.wait)
    await m.answer("📣 Yuboriladigan xabarni jo'nating (matn / rasm / video — hammasi bo'ladi):",
                   reply_markup=flow_kb())


@panel.message(F.text == B_STATS, Perm("stats"))
async def stats(m: Message, state: FSMContext):
    await state.clear()
    s = await db.stats()
    top = await db.top(5)
    t = "\n".join(f"{i}. {esc(a['title'])} — 👁 {a['views']}" for i, a in enumerate(top, 1)) or "—"
    await m.answer(
        f"📊 <b>Statistika</b>\n\n👥 Userlar: <b>{s['users']}</b>\n"
        f"☀️ 24 soatda faol: <b>{s['day']}</b>\n🚫 Botni bloklagan: <b>{s['blocked']}</b>\n"
        f"🎬 Anime: <b>{s['animes']}</b>\n📺 Qism: <b>{s['episodes']}</b>\n👁 Ko'rishlar: <b>{s['views']}</b>\n\n"
        f"🏆 Top 5:\n{t}")


@panel.message(F.text == B_BACKUP, Perm("backup"))
async def backup(m: Message, state: FSMContext):
    await state.clear()
    js = json.dumps(await db.dump(), default=str, ensure_ascii=False, indent=1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", js)
    name = f"yumora_backup_{dt.date.today()}.zip"
    await m.answer_document(BufferedInputFile(buf.getvalue(), filename=name), caption="💾 Baza zaxira (JSON, ZIP)")


# ═══ 👑 ADMINLAR (faqat asosiy admin) ══════════════════════════
async def admins_view() -> tuple[str, Kb]:
    rows = []
    lines = []
    for uid, perms in sorted(store.db_admins.items()):
        lines.append(f"🛡 <code>{uid}</code> — {len(perms)} ta huquq")
        rows.append([Btn(text=f"⚙️ {uid} • {len(perms)} huquq", callback_data=f"adm:e:{uid}")])
    rows.append([Btn(text="➕ Admin qo'shish", callback_data="adm:new")])
    text = "👑 <b>Adminlar</b>\n\n" + ("\n".join(lines) or "Hozircha qo'shimcha admin yo'q.")
    return text, Kb(inline_keyboard=rows)


def perm_kb(uid: int) -> Kb:
    have = store.db_admins.get(uid, set())
    rows = [[Btn(text=("✅ " if k in have else "⬜ ") + label, callback_data=f"adm:t:{uid}:{k}")]
            for k, label in PERMS]
    rows.append([Btn(text="✅ Hammasini berish", callback_data=f"adm:all:{uid}"),
                 Btn(text="🧹 Tozalash", callback_data=f"adm:none:{uid}")])
    rows.append([Btn(text="🗑 Adminlikdan olish", callback_data=f"adm:del:{uid}"),
                 Btn(text="◀️ Orqaga", callback_data="adm:list")])
    return Kb(inline_keyboard=rows)


def perm_text(uid: int) -> str:
    return (f"🛡 <b>Admin</b> <code>{uid}</code>\n\n"
            "Nimalarni qila olishini belgilang (bosib yoqing/o'chiring).\n"
            "O'zgarish darhol kuchga kiradi.")


@panel.message(F.text == B_ADMINS, Perm("owner"))
async def admins_entry(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await admins_view()
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:list", Perm("owner"))
async def adm_list(c: CallbackQuery):
    await c.answer()
    text, kb = await admins_view()
    await c.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:new", Perm("owner"))
async def adm_new(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(NewAdmin.id)
    await c.message.answer("🆔 Yangi adminning <b>Telegram ID</b> sini yozing (faqat raqam).\n"
                           "<i>ID ni @userinfobot orqali bilish mumkin.</i>", reply_markup=flow_kb())


@router.message(NewAdmin.id, F.text, Perm("owner"))
async def adm_new_id(m: Message, state: FSMContext, bot: Bot):
    t = m.text.strip()
    if not t.isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    uid = int(t)
    if uid in config.ADMIN_IDS:
        return await m.answer("👑 Bu asosiy admin — unga hamma huquq berilgan. Boshqa ID yozing:")
    if uid not in store.db_admins:
        await db.set_admin_perms(uid, [])
        store.db_admins[uid] = set()
    await state.clear()
    await m.answer(f"✅ Admin qo'shildi: <code>{uid}</code>", reply_markup=admin_kb(m.from_user.id))
    await m.answer(perm_text(uid), reply_markup=perm_kb(uid))
    try:
        await bot.send_message(uid, "🎉 Siz admin etib tayinlandingiz! Panelni ochish: /admin")
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("adm:e:"), Perm("owner"))
async def adm_edit(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    await c.answer()
    await c.message.edit_text(perm_text(uid), reply_markup=perm_kb(uid))


async def _save_perms(uid: int, perms: set[str]) -> None:
    store.db_admins[uid] = perms
    await db.set_admin_perms(uid, sorted(perms))


@router.callback_query(F.data.startswith("adm:t:"), Perm("owner"))
async def adm_toggle(c: CallbackQuery):
    _, _, uid, key = c.data.split(":")
    uid = int(uid)
    if key not in PERM_LABEL or uid not in store.db_admins:
        return await c.answer()
    perms = set(store.db_admins[uid])
    perms.symmetric_difference_update({key})
    await _save_perms(uid, perms)
    await c.answer(("✅ Berildi: " if key in perms else "⬜ Olindi: ") + PERM_LABEL[key])
    await c.message.edit_reply_markup(reply_markup=perm_kb(uid))


@router.callback_query(F.data.startswith(("adm:all:", "adm:none:")), Perm("owner"))
async def adm_all(c: CallbackQuery):
    _, mode, uid = c.data.split(":")
    uid = int(uid)
    if uid not in store.db_admins:
        return await c.answer()
    await _save_perms(uid, set(PERM_LABEL) if mode == "all" else set())
    await c.answer("✅ Saqlandi")
    await c.message.edit_reply_markup(reply_markup=perm_kb(uid))


@router.callback_query(F.data.startswith("adm:del:"), Perm("owner"))
async def adm_del(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    await db.del_admin(uid)
    store.db_admins.pop(uid, None)
    await c.answer("🗑 Adminlikdan olindi")
    text, kb = await admins_view()
    await c.message.edit_text(text, reply_markup=kb)


# ═══ 🆕 ANIME QO'SHISH ═════════════════════════════════════════
@router.message(AddAnime.code, F.text)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    if not CODE_RE.match(code):
        return await m.answer("❗ Faqat a-z, 0-9 va «-». Qayta yozing:")
    if await db.anime_by_code(code):
        return await m.answer("❗ Bu ID band. Boshqasini yozing:")
    await state.update_data(code=code)
    await state.set_state(AddAnime.title)
    await m.answer("🎬 <b>Anime nomi:</b>")


@router.message(AddAnime.title, F.text)
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:200])
    await state.set_state(AddAnime.genres)
    await m.answer("🎭 <b>Janr(lar)</b> — vergul bilan yozing:\n"
                   "<i>Action, Romance, Comedy, Fantasy, Drama, Horror, Slice of Life, Sci-Fi, Sports, "
                   "Mystery, Supernatural, Mecha</i>")


@router.message(AddAnime.genres, F.text)
async def add_genres(m: Message, state: FSMContext):
    g = parse_genres(m.text)
    if not g:
        return await m.answer("❗ Kamida bitta janr yozing:")
    await state.update_data(genres=g)
    await state.set_state(AddAnime.media)
    await m.answer("🖼 <b>Poster (rasm)</b> yoki 🎥 <b>treyler (video)</b> yuboring.\n"
                   "Ikkalasidan kamida bittasi shart; xohlasangiz ikkalasini ham yuboring, so'ng «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await m.answer("✅ Poster qabul qilindi! Treyler ham yuborishingiz mumkin yoki «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.video)
async def add_trailer(m: Message, state: FSMContext):
    await state.update_data(trailer=m.video.file_id)
    await m.answer("✅ Treyler qabul qilindi! Poster ham yuborishingiz mumkin yoki «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.text == B_DONE)
async def add_finish(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if not (d.get("poster") or d.get("trailer")):
        return await m.answer("❗ Poster yoki treyler — kamida bittasi kerak. Rasm yoki video yuboring.")
    try:
        aid = await db.add_anime(d["code"], d["title"], d["genres"], d.get("poster"), d.get("trailer"))
    except Exception as e:  # noqa: BLE001
        await state.clear()
        return await m.answer(f"❗ Xato: {esc(e)}", reply_markup=admin_kb(m.from_user.id))
    store.invalidate_anime()
    if d.get("poster"):
        fire(thumbs.thumb_for_anime(bot, aid, d["poster"]))  # inline uchun rasm URL (fonda)
    note = ""
    if not d.get("poster") and not await store.default_poster():
        note = ("\n\n⚠️ Poster yo'q va standart poster ham o'rnatilmagan — qidiruvda rasm chiqmaydi. "
                "«🖼 Standart poster» orqali rasm yuklang.")
    await state.clear()
    await m.answer(f"🎉 <b>{esc(d['title'])}</b> qo'shildi!{note}", reply_markup=admin_kb(m.from_user.id))
    await start_upload(m, state, aid, new=True)


# ═══ 🆔 ID BO'YICHA TANLASH (qism qo'shish / boshqaruv) ════════
async def ask_id(m: Message, state: FSMContext, action: str):
    await state.clear()
    await state.set_state(Pick.q)
    await state.update_data(action=action)
    await m.answer("🆔 <b>Anime ID</b> sini yozing:\n<i>Masalan: <code>naruto-1</code></i>", reply_markup=flow_kb())


@router.message(Pick.q, F.text)
async def pick_id(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    a = await db.anime_by_code(code) if CODE_RE.match(code) else None
    if not a:
        return await m.answer("🤷 Bunday ID yo'q. Qayta yozing yoki «❌ Bekor qilish».")
    act = (await state.get_data()).get("action", "manage")
    if act == "eps":
        return await start_upload(m, state, a["id"])
    await state.clear()
    await m.answer("🛠 Anime boshqaruv", reply_markup=admin_kb(m.from_user.id))
    await show_manage(m, a["id"])


# ═══ 🎞 QISMLARNI AVTOMATIK QO'SHISH ═══════════════════════════
async def start_upload(m: Message, state: FSMContext, aid: int, new: bool = False):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("❗ Anime topilmadi")
    last = await db.max_episode(aid)
    await state.clear()
    await state.set_state(AddEps.up)
    await state.update_data(aid=aid, last=0, cnt=0, new=new)
    await m.answer(
        f"🎞 <b>{esc(a['title'])}</b>  🆔 <code>{a['code']}</code>\nHozir <b>{last}</b> ta qism bor.\n\n"
        f"📥 Videolarni ketma-ket yuboring — qismlar <b>avtomatik {last + 1}-dan</b> raqamlanadi.\n"
        "✏️ Boshqa raqam kerak bo'lsa, sarlavhaga yozing (masalan «12» yoki «12-qism»).\n"
        "Tugagach «✅ Tayyor» ni bosing.", reply_markup=flow_kb(True))


_locks: dict[int, asyncio.Lock] = {}


@router.message(AddEps.up, F.video)
async def ep_video(m: Message, state: FSMContext):
    lock = _locks.setdefault(m.from_user.id, asyncio.Lock())
    async with lock:  # ketma-ket kelgan videolar raqamlari to'qnashmasligi uchun
        d = await state.get_data()
        n = parse_ep(m.caption) or max(d.get("last", 0), await db.max_episode(d["aid"])) + 1
        await db.set_episode(d["aid"], n, m.video.file_id)
        await state.update_data(last=n, cnt=d.get("cnt", 0) + 1)
    await m.reply(f"✅ {n}-qism saqlandi")


@router.message(AddEps.up, F.document)
async def ep_doc(m: Message):
    await m.answer("❗ Fayl emas, «video» sifatida yuboring.")


@router.message(AddEps.up, F.text == B_DONE)
async def ep_done(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    store.invalidate_anime()
    await m.answer(f"🎉 Tayyor! <b>{d.get('cnt', 0)}</b> ta qism qo'shildi.", reply_markup=admin_kb(m.from_user.id))
    if d.get("new") and await store.news_channels():
        await m.answer("📣 News kanalga e'lon qilaymi?", reply_markup=Kb(inline_keyboard=[[
            Btn(text="📣 E'lon qilish", callback_data=f"nw:{d['aid']}"), Btn(text="❌ Yo'q", callback_data="ad:no")]]))


# ═══ 🛠 ANIME BOSHQARUV (ID bo'yicha) ══════════════════════════
async def show_manage(m: Message, aid: int):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("❗ Topilmadi")
    n = await db.max_episode(aid)
    avg = a["rating_sum"] / a["rating_count"] if a["rating_count"] else 0
    text = (f"🎬 <b>{esc(a['title'])}</b>\n🆔 <code>{a['code']}</code>\n🎭 {esc(', '.join(a['genres']) or '—')}\n"
            f"📺 Oxirgi qism: {n}  •  👁 {a['views']}  •  ⭐ {avg:.1f} ({a['rating_count']})\n"
            f"🖼 Poster: {'✅' if a['poster_file_id'] else '❌'}  •  🎥 Treyler: {'✅' if a['trailer_file_id'] else '❌'}")
    rows = [
        [Btn(text="✏️ Nom", callback_data=f"am:{aid}:title"), Btn(text="🎭 Janr", callback_data=f"am:{aid}:genres")],
        [Btn(text="🖼 Poster", callback_data=f"am:{aid}:poster_file_id"),
         Btn(text="🎥 Treyler", callback_data=f"am:{aid}:trailer_file_id")],
        [Btn(text="🎞 Qism qo'shish", callback_data=f"am:{aid}:eps"),
         Btn(text="🗑 Qism o'chirish", callback_data=f"am:{aid}:delep")],
        [Btn(text="👁 Ko'rish (yuborish)", callback_data=f"am:{aid}:show"),
         Btn(text="📣 News e'lon", callback_data=f"nw:{aid}")],
        [Btn(text="🗑 Animeni o'chirish", callback_data=f"am:{aid}:del")],
    ]
    await m.answer(text, reply_markup=Kb(inline_keyboard=rows))


PROMPTS = {
    "title": "✏️ Yangi <b>nom</b>ni yozing:",
    "genres": "🎭 Yangi <b>janr</b>larni vergul bilan yozing:",
    "poster_file_id": "🖼 Yangi <b>poster</b> rasmini yuboring:",
    "trailer_file_id": "🎥 Yangi <b>treyler</b> videosini yuboring:",
}


@router.callback_query(F.data.startswith("am:"), Perm("manage"))
async def manage_cb(c: CallbackQuery, state: FSMContext, bot: Bot):
    _, aid, act = c.data.split(":")
    aid = int(aid)
    await c.answer()
    if act in PROMPTS:
        await state.clear()
        await state.set_state(EditF.v)
        await state.update_data(aid=aid, field=act)
        return await c.message.answer(PROMPTS[act], reply_markup=flow_kb())
    if act == "eps":
        return await start_upload(c.message, state, aid)
    if act == "delep":
        await state.clear()
        await state.set_state(DelEp.n)
        await state.update_data(aid=aid)
        return await c.message.answer("🗑 O'chiriladigan <b>qism raqami</b>ni yozing:", reply_markup=flow_kb())
    if act == "show":
        a = await db.anime_by_id(aid)
        if a:
            await send_card(bot, c.message.chat.id, a, c.from_user.id)
        return
    if act == "del":
        a = await db.anime_by_id(aid)
        return await c.message.answer(
            f"⚠️ Rostdan <b>{esc(a['title'] if a else aid)}</b> va barcha qismlarini o'chirasizmi?",
            reply_markup=Kb(inline_keyboard=[[Btn(text="✅ Ha, o'chir", callback_data=f"ad:dely:{aid}"),
                                              Btn(text="❌ Yo'q", callback_data="ad:no")]]))


@router.message(EditF.v)
async def edit_value(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    f, aid = d["field"], d["aid"]
    if f == "title" and m.text:
        val = m.text.strip()[:200]
    elif f == "genres" and m.text:
        val = parse_genres(m.text)
        if not val:
            return await m.answer("❗ Kamida bitta janr yozing:")
    elif f == "poster_file_id" and m.photo:
        val = m.photo[-1].file_id
    elif f == "trailer_file_id" and m.video:
        val = m.video.file_id
    else:
        return await m.answer("❗ Noto'g'ri turdagi xabar. " + PROMPTS[f])
    await db.update_anime(aid, f, val)
    if f == "poster_file_id":
        await db.update_anime(aid, "thumb_url", None)
        fire(thumbs.thumb_for_anime(bot, aid, val))
    store.invalidate_anime()
    await state.clear()
    await m.answer("✅ Yangilandi!", reply_markup=admin_kb(m.from_user.id))


@router.message(DelEp.n, F.text)
async def delep_value(m: Message, state: FSMContext):
    d = await state.get_data()
    if not m.text.strip().isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    ok = await db.delete_episode(d["aid"], int(m.text))
    store.invalidate_anime()
    await state.clear()
    await m.answer("✅ O'chirildi." if ok else "🤷 Bunday qism yo'q.", reply_markup=admin_kb(m.from_user.id))


@router.callback_query(F.data.startswith("ad:dely:"), Perm("manage"))
async def del_yes(c: CallbackQuery):
    await db.delete_anime(int(c.data.split(":")[2]))
    store.invalidate_anime()
    await c.answer("🗑 O'chirildi")
    await c.message.edit_text("✅ Anime o'chirildi.")


@router.callback_query(F.data == "ad:no")
async def no(c: CallbackQuery):
    await c.answer()
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("delep"), Perm("manage"))
async def delep_cmd(m: Message):
    p = (m.text or "").split()
    if len(p) != 3 or not p[2].isdigit():
        return await m.answer("🗑 Foydalanish: /delep <code>ID qism</code>")
    a = await db.anime_by_code(p[1].lower())
    if not a:
        return await m.answer("🤷 Bunday ID yo'q")
    ok = await db.delete_episode(a["id"], int(p[2]))
    store.invalidate_anime()
    await m.answer("✅ O'chirildi" if ok else "🤷 Bunday qism yo'q")


# ═══ 📣 NEWS E'LON ═════════════════════════════════════════════
async def post_news(bot: Bot, aid: int) -> int:
    a = await db.anime_by_id(aid)
    chans = await store.news_channels()
    if not a or not chans:
        return 0
    eps = await store.episodes(aid)
    text = card_text(a, len(eps.numbers))
    markup = Kb(inline_keyboard=[[Btn(text="▶️ Tomosha qilish", url=kbd.start_link(a["code"]))]])
    poster = a["poster_file_id"] or await store.default_poster()
    ok = 0
    for ch in chans:
        try:
            if a["trailer_file_id"]:
                await bot.send_video(ch["chat_id"], a["trailer_file_id"], caption=text, reply_markup=markup)
            elif poster:
                await bot.send_photo(ch["chat_id"], poster, caption=text, reply_markup=markup)
            else:
                await bot.send_message(ch["chat_id"], text, reply_markup=markup)
            ok += 1
        except Exception:  # noqa: BLE001
            pass
    return ok


@router.callback_query(F.data.startswith("nw:"))
async def news_cb(c: CallbackQuery, bot: Bot):
    await c.answer()
    sent = await post_news(bot, int(c.data.split(":")[1]))
    await c.message.answer(f"📣 News kanalga yuborildi ✅" if sent else "❗ News kanal yo'q yoki yuborib bo'lmadi (📢 Kanallar).")


@panel.message(Command("thumbs"), Perm("poster"))
async def thumbs_cmd(m: Message, bot: Bot):
    if not config.IMGBB_API_KEY:
        return await m.answer("⚠️ <code>IMGBB_API_KEY</code> kiritilmagan. .env ga qo'shing (https://api.imgbb.com).")
    await m.answer("🖼 Inline rasmlar tayyorlanmoqda… Tugagach xabar beraman.")

    async def job():
        done, total = await thumbs.backfill(bot)
        await bot.send_message(m.chat.id, f"✅ Inline rasmlar tayyor: <b>{done}</b> / {total}")

    fire(job())


# ═══ 🖼 STANDART POSTER ════════════════════════════════════════
@router.message(SetPoster.wait, F.photo)
async def poster_set(m: Message, state: FSMContext, bot: Bot):
    fid = m.photo[-1].file_id
    url = await thumbs.make_thumb(bot, fid)
    await store.set_default_poster(fid, url)
    await state.clear()
    note = ""
    if not config.IMGBB_API_KEY:
        note = "\n\n⚠️ <code>IMGBB_API_KEY</code> kiritilmagan — inline qidiruvda rasm chiqmaydi."
    elif not url:
        note = "\n\n⚠️ Inline uchun rasm yuklanmadi (ImgBB). Keyinroq qayta urinib ko'ring."
    await m.answer(f"✅ Standart poster o'rnatildi!{note}", reply_markup=admin_kb(m.from_user.id))


# ═══ 📢 KANALLAR ═══════════════════════════════════════════════
async def chan_list() -> tuple[str, Kb]:
    rows = await db.channels()
    lines = []
    for c in rows:
        kind = "majburiy" if c["kind"] == "sub" else "news"
        scope = "" if c["anime_id"] is None else f" • anime #{c['anime_id']}"
        lines.append(f"{c['id']}. {esc(c['title'])} ({kind}{scope})")
    text = "📢 <b>Kanallar</b>\n\n" + ("\n".join(lines) or "Hozircha yo'q")
    kb_rows = [[Btn(text=f"🗑 {c['id']}. {c['title']}"[:50], callback_data=f"ad:chdel:{c['id']}")] for c in rows]
    kb_rows.append([Btn(text="➕ Majburiy kanal", callback_data="ad:chadd:sub"),
                    Btn(text="➕ News kanal", callback_data="ad:chadd:news")])
    return text, Kb(inline_keyboard=kb_rows)


@router.callback_query(F.data.startswith("ad:chadd:"), Perm("chans"))
async def chan_add_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(AddChan.wait)
    await state.update_data(kind=c.data.split(":")[2])
    await c.message.answer(
        "📢 Kanalni yuboring (bot kanalda <b>ADMIN</b> bo'lishi shart):\n\n"
        "• ochiq: <code>@kanal</code>\n"
        "• yopiq: <code>-100123456789 https://t.me/+invite</code>\n\n"
        "Faqat bitta anime uchun bo'lsa — 2-qatorga anime ID sini yozing.", reply_markup=flow_kb())


@router.message(AddChan.wait, F.text)
async def chan_add(m: Message, state: FSMContext, bot: Bot):
    lines = [x.strip() for x in m.text.strip().splitlines() if x.strip()]
    parts = lines[0].split()
    anime_id = None
    if len(lines) > 1:
        a = await db.anime_by_code(lines[1].lower())
        if not a:
            return await m.answer("🤷 Bunday anime ID yo'q. Qayta yuboring yoki «❌ Bekor qilish».")
        anime_id = a["id"]
    try:
        chat = await bot.get_chat(parts[0] if parts[0].startswith("@") else int(parts[0]))
        url = parts[1] if len(parts) > 1 else (f"https://t.me/{chat.username}" if chat.username else None)
        if not url:
            return await m.answer("❗ Yopiq kanal uchun invite link ham yozing.")
    except Exception as e:  # noqa: BLE001
        return await m.answer(f"❗ Topilmadi: {esc(e)}\nQayta yuboring yoki «❌ Bekor qilish».")
    kind = (await state.get_data()).get("kind", "sub")
    await db.add_channel(chat.id, url, chat.title or str(chat.id), anime_id, kind)
    store.invalidate_channels()
    await state.clear()
    await m.answer(f"✅ Qo'shildi: {esc(chat.title or '')}", reply_markup=admin_kb(m.from_user.id))


@router.callback_query(F.data.startswith("ad:chdel:"), Perm("chans"))
async def chan_del(c: CallbackQuery):
    await db.delete_channel(int(c.data.split(":")[2]))
    store.invalidate_channels()
    await c.answer("🗑 O'chirildi")
    text, kb = await chan_list()
    await c.message.edit_text(text, reply_markup=kb)


# ═══ 📣 XABAR YUBORISH ═════════════════════════════════════════
@router.message(Cast.wait)
async def cast_got(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✅ Xabar qabul qilindi.", reply_markup=admin_kb(m.from_user.id))
    await m.reply("📣 Shu xabarni hamma foydalanuvchiga yuboraymi?", reply_markup=Kb(inline_keyboard=[[
        Btn(text="✅ Yuborish", callback_data=f"ad:castgo:{m.chat.id}:{m.message_id}"),
        Btn(text="❌ Yo'q", callback_data="ad:no")]]))


@router.callback_query(F.data.startswith("ad:castgo:"), Perm("cast"))
async def cast_go(c: CallbackQuery, bot: Bot):
    _, _, chat, mid = c.data.split(":")
    await c.answer("🚀 Boshlandi")
    await c.message.delete()
    asyncio.create_task(broadcast.run(bot, c.message.chat.id, int(chat), int(mid)))


@router.message(Command("stopcast"), Perm("cast"))
async def stopcast(m: Message):
    broadcast.state["stop"] = True
    await m.answer("⏹ To'xtatilmoqda…")


# ═══ kanalga tashlab yuklash: caption "id:kod" va "qism:N" ═════
@router.channel_post(F.video, F.caption)
async def channel_upload(m: Message):
    code = re.search(r"id:\s*([a-z0-9-]+)", m.caption, re.I)
    num = re.search(r"qism:\s*(\d+)", m.caption, re.I)
    if not (code and num):
        return
    a = await db.anime_by_code(code.group(1).lower())
    if a:
        await db.set_episode(a["id"], int(num.group(1)), m.video.file_id)
        store.invalidate_anime()


# ═══ 🚫 BAN ════════════════════════════════════════════════════
def _arg_id(m: Message):
    p = (m.text or "").split()
    return int(p[1]) if len(p) > 1 and p[1].lstrip("-").isdigit() else None


@router.message(Command("ban"), Perm("ban"))
async def ban(m: Message):
    uid = _arg_id(m)
    if uid is None or store.is_admin(uid):
        return await m.answer("🚫 Foydalanish: /ban <code>user_id</code>")
    await db.set_banned(uid, True)
    store.banned.add(uid)
    await m.answer(f"🚫 {uid} bloklandi")


@router.message(Command("unban"), Perm("ban"))
async def unban(m: Message):
    uid = _arg_id(m)
    if uid is None:
        return await m.answer("✅ Foydalanish: /unban <code>user_id</code>")
    await db.set_banned(uid, False)
    store.banned.discard(uid)
    await m.answer(f"✅ {uid} blokdan chiqdi")
'@

Save-File 'README.md' @'
# Yumora TV bot

aiogram 3 + PostgreSQL (asyncpg). Rangli emoji dizayn.

## Ishga tushirish
1. `cp .env.example .env` → BOT_TOKEN, DATABASE_URL, ADMIN_IDS (asosiy adminlar)
2. `pip install -r requirements.txt`
3. `python main.py` (jadvallar o'zi yaratiladi / eski baza o'zi yangilanadi)

## Foydalanuvchi
- /start: salom + rasm + konfetti effekti, 🔎 Janr bo'yicha qidirish, 🔥 Eng mashhur, 🔍 Nom bo'yicha (inline), 💡 Yordam
- Kartochka: janr, ⭐ reyting, 📺 qismlar, ▶️ 1-qismdan tomosha, 📋 Qismlar ro'yxati, 📤 Ulashish, ⭐ Baho berish
- Qism bosilsa video PASTDAN yangi xabar bo'lib keladi, oldingi video joyida qoladi
- Havola: `t.me/bot?start=ID` (kartochka), `ID_5` (5-qismdan)
- Inline (`@bot ...`): poster-miniatyurali ro'yxat (sarlavha + ⭐ reyting, 📺 qism, 🎭 janr). Tanlansa bot havolani o'chirib, to'liq kartani chiqaradi.
  Poster-miniatyuralar uchun `.env` ga `IMGBB_API_KEY` kerak (https://api.imgbb.com, bepul). Eski animelar uchun bir marta `/thumbs`.

## Admin (/admin) — hammasi ID orqali
- 🆕 Anime qo'shish: ID → nom → janr → poster YOKI treyler → videolarni tashlang (qism raqami avtomatik)
- 🎞 Qism qo'shish: anime ID → videolarni tashlang
- 🛠 Anime boshqaruv: anime ID → ✏️ nom, 🎭 janr, 🖼 poster, 🎥 treyler, 🎞 qism qo'shish, 🗑 qism o'chirish,
  👁 ko'rish (yuborish), 📣 news e'lon, 🗑 animeni o'chirish. Tezkor: `/anime ID`
- 👑 Adminlar (faqat asosiy admin): admin Telegram ID si → huquqlarni bosib belgilash (✅/⬜):
  anime qo'shish, qism qo'shish, boshqaruv, kanallar, xabar yuborish, statistika, zaxira, standart poster, ban.
  Admin faqat o'ziga berilgan tugmalarni ko'radi; o'zgarish darhol kuchga kiradi.
- 📢 Kanallar, 🖼 Standart poster, 📣 Xabar yuborish, 📊 Statistika, 💾 Baza zaxira
- Har bir jarayonda ❌ Bekor qilish
'@


# .env GitHub'ga tushib ketmasligi uchun
if (-not (Test-Path ".gitignore")) {
    Save-File ".gitignore" ".env`n__pycache__/`n*.pyc`n"
} else {
    $gi = Get-Content ".gitignore" -Raw
    if ($gi -notmatch '(?m)^\.env\s*$') { Add-Content ".gitignore" "`n.env"; Write-Host "  OK  .gitignore (.env qo'shildi)" -ForegroundColor Green }
}

Write-Host ""
Write-Host "Tayyor. Endi:" -ForegroundColor Cyan
Write-Host "  git add ."
Write-Host "  git commit -m `"Inline miniatyuralar va havola orqali karta`""
Write-Host "  git push"
Write-Host "Railway > Variables ga IMGBB_API_KEY qo'shing, deploydan keyin botda /thumbs yozing."
