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
CREATE TABLE IF NOT EXISTS admins (tg_id BIGINT PRIMARY KEY);
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


async def admin_ids() -> set[int]:
    return {r["tg_id"] for r in await pool.fetch("SELECT tg_id FROM admins")}


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


async def add_admin(uid: int) -> None:
    await pool.execute("INSERT INTO admins VALUES ($1) ON CONFLICT DO NOTHING", uid)


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


_EDITABLE = {"title", "genres", "poster_file_id", "trailer_file_id"}


async def update_anime(aid: int, field: str, value) -> None:
    if field not in _EDITABLE:
        raise ValueError(field)
    await pool.execute(f"UPDATE animes SET {field} = $1 WHERE id = $2", value, aid)


async def recent(limit: int = 8) -> list[dict]:
    return [dict(r) for r in await pool.fetch("SELECT id, title FROM animes ORDER BY id DESC LIMIT $1", limit)]


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
    "id, code, title, poster_file_id, genres, views, rating_sum, rating_count, "
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


async def list_all(limit: int, offset: int) -> list[dict]:
    rows = await pool.fetch(f"SELECT {_COLS} FROM animes ORDER BY title LIMIT $1 OFFSET $2", limit, offset)
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
