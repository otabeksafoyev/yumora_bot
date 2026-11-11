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

import store

router = Router()


def _result(a: dict):
    link = f"https://t.me/{store.BOT_USERNAME}?start={a['code']}"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Tomosha qilish", url=link)]]
    )
    title = a["title"]
    desc = f"📼 {a['eps']} qism • 👁 {a['views']}"
    text = f"🎬 <b>{html.escape(title)}</b>\n📼 {a['eps']} qism"
    if a.get("poster_file_id"):
        return InlineQueryResultCachedPhoto(
            id=str(a["id"]), photo_file_id=a["poster_file_id"], title=title,
            description=desc, caption=text, reply_markup=markup,
        )
    return InlineQueryResultArticle(
        id=str(a["id"]), title=title, description=desc,
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
        items = await store.search(text)
    # Natija hammaga bir xil -> Telegram o'zi ham keshlaydi
    await q.answer([_result(a) for a in items], cache_time=30, is_personal=False)
