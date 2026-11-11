import html

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent,
)

import keyboards as kb
import store
from handlers.user import avg_of

router = Router()


def _result(a: dict, default_poster):
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Tomosha qilish", url=kb.start_link(a["code"]))]]
    )
    genres = " • ".join(a["genres"][:4]) or "—"
    desc = f"⭐ {avg_of(a):.1f}  •  📺 {a['eps']} qism\n🎭 {genres}"
    text = f"🎬 <b>{html.escape(a['title'])}</b>\n🎭 {html.escape(genres)}\n⭐ {avg_of(a):.1f}  •  📺 {a['eps']} qism"
    poster = a.get("poster_file_id") or default_poster  # poster yo'q bo'lsa — admin qo'ygan standart rasm
    if poster:
        return InlineQueryResultCachedPhoto(
            id=str(a["id"]), photo_file_id=poster, title=a["title"],
            description=desc, caption=text, reply_markup=markup,
        )
    return InlineQueryResultArticle(
        id=str(a["id"]), title=a["title"], description=desc,
        input_message_content=InputTextMessageContent(message_text=text), reply_markup=markup,
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
    dp = await store.default_poster()
    # Natija hammaga bir xil -> Telegram o'zi ham keshlaydi
    await q.answer([_result(a, dp) for a in items], cache_time=30, is_personal=False)
