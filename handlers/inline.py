
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
