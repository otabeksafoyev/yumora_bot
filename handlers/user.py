import html
import re

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InputMediaVideo, Message

import config
import keyboards as kb
import store
import subs

router = Router()
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def esc(s: str) -> str:
    return html.escape(s or "")


def caption(anime: dict, n: int) -> str:
    return f"🎬 <b>{esc(anime['title'])}</b>\n{n}-qism"


async def send_home(m: Message) -> None:
    st = await store.stats()
    text = f"🎌 <b>Anime bot</b>\n\n👥 Foydalanuvchilar: <b>{st['users']}</b>\n\nAnime nomini yozing yoki kodini yuboring."
    if config.START_PHOTO:
        try:
            await m.answer_photo(config.START_PHOTO, caption=text, reply_markup=kb.home_kb())
            return
        except Exception:  # noqa: BLE001
            pass
    await m.answer(text, reply_markup=kb.home_kb())


async def play(bot: Bot, user_id: int, chat_id: int, anime: dict, number: int | None,
               edit: Message | None = None) -> None:
    """Qismni yuboradi (obunani tekshirib). edit berilsa — shu xabar videosini almashtiradi."""
    eps = await store.episodes(anime["id"])
    if not eps.numbers:
        text = f"🎬 <b>{esc(anime['title'])}</b>\n\nQismlar tez orada yuklanadi."
        if anime.get("poster_file_id"):
            await bot.send_photo(chat_id, anime["poster_file_id"], caption=text)
        else:
            await bot.send_message(chat_id, text)
        return
    if number not in eps.files:
        number = eps.numbers[0]

    miss = await subs.missing(bot, user_id, anime["id"])
    if miss:
        await bot.send_message(
            chat_id,
            "🌟 Davom etish uchun quyidagi kanallarga obuna bo'ling, so'ng «Tekshirish» ni bosing:",
            reply_markup=kb.sub_kb(miss, anime["id"], number),
        )
        return

    store.hit(anime["id"])
    markup = kb.episodes_kb(anime["id"], eps.numbers, number)
    cap = caption(anime, number)
    if edit is not None:
        try:
            await edit.edit_media(
                InputMediaVideo(media=eps.files[number], caption=cap), reply_markup=markup
            )
            return
        except Exception as e:  # noqa: BLE001
            if "not modified" in str(e).lower():
                return
    await bot.send_video(chat_id, eps.files[number], caption=cap, reply_markup=markup)


async def open_by_payload(m: Message, bot: Bot, payload: str) -> bool:
    payload = payload.strip().lower()
    number = None
    if "_" in payload:
        payload, _, tail = payload.partition("_")
        number = int(tail) if tail.isdigit() else None
    if not CODE_RE.match(payload):
        return False
    anime = await store.anime_by_code(payload)
    if not anime:
        return False
    await play(bot, m.from_user.id, m.chat.id, anime, number)
    return True


@router.message(CommandStart())
async def start(m: Message, bot: Bot):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1] != "home":
        if await open_by_payload(m, bot, parts[1]):
            return
        await m.answer("❌ Anime topilmadi.")
    await send_home(m)


@router.message(F.text & ~F.text.startswith("/"))
async def text_search(m: Message, bot: Bot):
    q = m.text.strip()
    if await open_by_payload(m, bot, q):
        return
    if len(q) < 2:
        return await m.answer("Kamida 2 ta harf yozing.")
    items = await store.search(q)
    if not items:
        return await m.answer("❌ Hech narsa topilmadi. Boshqacha yozib ko'ring.")
    await m.answer(f"🔎 Topildi: {len(items)} ta", reply_markup=kb.results_kb(items))


@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "top")
async def top(c: CallbackQuery):
    await c.answer()
    items = await store.top(10)
    if items:
        await c.message.answer("🔥 Eng ko'p ko'rilganlar:", reply_markup=kb.results_kb(items))


@router.callback_query(F.data.startswith("a:"))
async def open_anime(c: CallbackQuery, bot: Bot):
    await c.answer()
    anime = await store.anime_by_id(int(c.data.split(":")[1]))
    if anime:
        await play(bot, c.from_user.id, c.message.chat.id, anime, None)


@router.callback_query(F.data.startswith("p:"))
async def play_cb(c: CallbackQuery, bot: Bot):
    _, aid, n = c.data.split(":")
    await c.answer()
    anime = await store.anime_by_id(int(aid))
    if anime:
        await play(bot, c.from_user.id, c.message.chat.id, anime, int(n), edit=c.message)


@router.callback_query(F.data.startswith("g:"))
async def page_cb(c: CallbackQuery):
    _, aid, page, cur = c.data.split(":")
    await c.answer()
    eps = await store.episodes(int(aid))
    if eps.numbers:
        try:
            await c.message.edit_reply_markup(
                reply_markup=kb.episodes_kb(int(aid), eps.numbers, int(cur), int(page))
            )
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("c:"))
async def check_cb(c: CallbackQuery, bot: Bot):
    _, aid, n = c.data.split(":")
    anime = await store.anime_by_id(int(aid))
    if not anime:
        return await c.answer()
    miss = await subs.missing(bot, c.from_user.id, anime["id"])
    if miss:
        return await c.answer("❌ Hali hamma kanalga obuna bo'lmadingiz", show_alert=True)
    await c.answer("✅")
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await play(bot, c.from_user.id, c.message.chat.id, anime, int(n))
