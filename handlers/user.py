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
DIV = "✧───────✧"
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
        return "✧ Xayrli tong"
    if 11 <= h < 17:
        return "☼ Xayrli kun"
    if 17 <= h < 22:
        return "☾ Xayrli kech"
    return "☾ Xayrli tun"


def stars(avg: float) -> str:
    f = int(round(max(0.0, min(avg, 10.0)) / 10 * 5))
    return "★" * f + "☆" * (5 - f)


def bar(done: int, total: int, width: int = 8) -> str:
    if total <= 0:
        return "▱" * width
    f = max(1, int(round(done / total * width))) if done > 0 else 0
    return "▰" * f + "▱" * (width - f)


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
async def send_home(m: Message, user) -> None:
    name = esc(user.first_name) if user and user.first_name else ""
    text = (f"<b>{greeting()}, {name}!</b> Bugun nima ko'ramiz?\n{DIV}\n"
            f"<b>Yumora TV</b> — Anime & Dorama\n● {store.online_count or 1} kishi online")
    photo = config.START_PHOTO or await store.default_poster()
    if photo:
        try:
            await m.answer_photo(photo, caption=text, reply_markup=kb.home_kb())
            return
        except Exception:  # noqa: BLE001
            pass
    await m.answer(text, reply_markup=kb.home_kb())


# ── kartochka ───────────────────────────────────────────────
def card_text(a: dict, eps_count: int) -> str:
    cnt = a["rating_count"]
    return (f"๏ <b>{esc(a['title'])}</b>\n{DIV}\n"
            f"๏ {esc(', '.join(a['genres']) or '—')}\n"
            f"{stars(avg_of(a))} <b>{avg_of(a):.1f}</b>  •  ◉ {cnt} ovoz\n"
            f"≡ {eps_count} qism\n№ <code>{a['code']}</code>")


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
    return f"ᐅ <b>{esc(a['title'])}</b>  •  {n}-qism\n๏ {bar(n, total)} {n}/{total} qism"


async def _strip(msg: Message) -> None:
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


async def play(bot: Bot, uid: int, chat_id: int, a: dict, number: int | None, old: Message | None = None) -> None:
    """Qismni YANGI xabar sifatida yuboradi — oldingi video joyida qoladi."""
    eps = await store.episodes(a["id"])
    if not eps.numbers:
        await bot.send_message(chat_id, "◌ Qismlar hali qo'shilmagan.")
        return
    if number not in eps.files:
        number = eps.numbers[0]

    miss = await subs.missing(bot, uid, a["id"])
    if miss:
        await bot.send_message(
            chat_id, "ᐅ <b>Davom etish uchun kanallarga obuna bo'ling</b>, so'ng «Tekshirish» ni bosing:",
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
        await m.answer("⌕ Bu kod bo'yicha hech narsa topilmadi.")
    await send_home(m, m.from_user)


@router.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def text_search(m: Message, bot: Bot):
    q = m.text.strip()
    if await open_payload(m, bot, q):
        return
    if len(q) < 2:
        return await m.answer("⌕ Kamida 2 ta harf yozing.")
    items = await store.search(q)
    if not items:
        return await m.answer("⌕ Hech narsa topilmadi. Boshqacha yozib ko'ring yoki janr bo'yicha qidiring.",
                              reply_markup=kb.back_home())
    await m.answer(f"⌕ Topildi: <b>{len(items)}</b> ta", reply_markup=kb.list_kb(items, 0, False, "x"))


# ── menyu / ro'yxatlar / janr ───────────────────────────────
@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "edge")
async def edge(c: CallbackQuery):
    await c.answer("Bu chekka sahifa", show_alert=False)


@router.callback_query(F.data == "noep")
async def noep(c: CallbackQuery):
    await c.answer("Qismlar tez orada qo'shiladi", show_alert=True)


@router.callback_query(F.data == "menu")
async def menu(c: CallbackQuery):
    await c.answer()
    await send_home(c.message, c.from_user)


@router.callback_query(F.data == "help")
async def help_(c: CallbackQuery):
    await c.answer()
    await show(c, f"ⓘ <b>Qo'llanma</b>\n{DIV}\n"
                  "⌕ Anime nomini yoki kodini yozing\n"
                  "⌕ Janr bo'yicha qidirish tugmasidan foydalaning\n"
                  "ᐅ Qismni bossangiz video pastdan yuboriladi, oldingisi joyida qoladi\n"
                  "★ Anime tugagach baho bering\n"
                  "↗ Do'stlaringizga ulashing", kb.back_home())


@router.callback_query(F.data == "gen")
async def genres(c: CallbackQuery):
    await c.answer()
    gl = await store.genres()
    if not gl:
        return await show(c, "◌ Hozircha janrlar yo'q.", kb.back_home())
    await show(c, "⌕ <b>Janrni tanlang:</b>", kb.genres_kb(gl))


@router.callback_query(F.data.startswith("gn:"))
async def by_genre(c: CallbackQuery):
    _, g, page = c.data.rsplit(":", 2)
    page = int(page)
    await c.answer()
    items = await store.by_genre(g, page, PAGE_SIZE)
    has_next = len(items) > PAGE_SIZE
    await show(c, f"๏ <b>{esc(g)}</b>", kb.list_kb(items[:PAGE_SIZE], page, has_next, f"gn:{g}",
                                                    ("ᐊ Janrlar", "gen")))


@router.callback_query(F.data.startswith("ls:"))
async def list_all(c: CallbackQuery):
    page = int(c.data.split(":")[1])
    await c.answer()
    items = await store.list_all(page, PAGE_SIZE)
    if not items:
        return await show(c, "◌ Hozircha anime yo'q.", kb.back_home())
    await show(c, "๏ <b>Barcha animelar</b>", kb.list_kb(items[:PAGE_SIZE], page, len(items) > PAGE_SIZE, "ls"))


@router.callback_query(F.data == "top")
async def top(c: CallbackQuery):
    await c.answer()
    items = await store.top(10)
    await show(c, "★ <b>Eng mashhur</b>", kb.list_kb(items, 0, False, "x"))


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
        return await c.answer("Qismlar yo'q", show_alert=True)
    await c.message.answer(f"≡ <b>{esc(a['title'])}</b>\nQismni tanlang:", reply_markup=kb.episodes_kb(a, eps.numbers, None, 0))


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
        return await c.answer("Hali hamma kanalga obuna bo'lmadingiz", show_alert=True)
    await c.answer("✓")
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
        return await c.answer(f"✓ Siz allaqachon baho bergansiz: {old}/10", show_alert=True)
    await c.answer()
    await c.message.answer("★ <b>Anime uchun baho bering (1-10):</b>\n\n1 = Yomon  |  5 = O'rtacha  |  10 = A'lo",
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
        return await c.answer("✓ Siz allaqachon baho bergansiz", show_alert=True)
    a = await store.anime_by_id(aid)
    if a:
        store.forget(a)
    avg = row["rating_sum"] / row["rating_count"]
    try:
        await c.message.edit_text(
            f"✓ <b>Baho qabul qilindi!</b>\n\n๏ <b>{esc(a['title']) if a else ''}</b>\n"
            f"★ Sizning bahoyingiz: <b>{score}/10</b>\n◈ O'rtacha reyting: <b>{avg:.1f}/10</b>",
            reply_markup=kb.back_home())
    except Exception:  # noqa: BLE001
        pass
    await c.answer(f"★ {score}/10 — Rahmat!", show_alert=True)


@router.callback_query(F.data == "rc")
async def rate_cancel(c: CallbackQuery):
    await c.answer()
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass
