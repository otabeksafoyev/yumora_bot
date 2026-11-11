from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb

import store

GRID = 4  # bir qatorda
PER = 8  # bir sahifada qism soni

GENRE_EMOJI = {
    "action": "⚔️", "romance": "💕", "comedy": "😂", "fantasy": "🧙", "drama": "🎭", "horror": "👻",
    "slice of life": "🌸", "sci-fi": "🚀", "sports": "⚽", "mystery": "🕵️", "supernatural": "🔮",
    "mecha": "🤖", "adventure": "🗺️", "isekai": "🌀", "shounen": "🔥", "shoujo": "🌷", "thriller": "😱",
    "school": "🎒", "music": "🎵", "magic": "✨", "psychological": "🧠", "historical": "🏯",
    "martial arts": "🥋", "military": "🪖", "harem": "💘", "ecchi": "🙈", "josei": "🌹", "seinen": "🍷",
}


def genre_emoji(g: str) -> str:
    return GENRE_EMOJI.get(g.lower(), "🎬")


def share_url(code: str) -> str:
    return f"https://t.me/share/url?url=https://t.me/{store.BOT_USERNAME}%3Fstart%3D{code}"


def start_link(code: str, n: int | None = None) -> str:
    return f"https://t.me/{store.BOT_USERNAME}?start={code}" + (f"_{n}" if n else "")


def home_kb() -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="🔎 Janr bo'yicha qidirish", callback_data="gen")],
        [Btn(text="🔥 Eng mashhur", callback_data="top"),
         Btn(text="🔍 Nom bo'yicha", switch_inline_query_current_chat="")],
        [Btn(text="💡 Yordam / Qo'llanma", callback_data="help")],
    ])


def back_home() -> Kb:
    return Kb(inline_keyboard=[[Btn(text="🏠 Asosiy menyu", callback_data="menu")]])


def card_kb(a: dict, has_eps: bool) -> Kb:
    rows = []
    if has_eps:
        rows.append([Btn(text="▶️ 1-qismdan tomosha qilish", callback_data=f"w:{a['id']}")])
        rows.append([Btn(text="📋 Qismlar ro'yxati", callback_data=f"l:{a['id']}")])
    else:
        rows.append([Btn(text="⏳ Qismlar hali qo'shilmagan", callback_data="noep")])
    rows.append([Btn(text="📤 Ulashish", url=share_url(a["code"])),
                 Btn(text="⭐ Baho berish", callback_data=f"rt:{a['id']}")])
    rows.append([Btn(text="🏠 Asosiy menyu", callback_data="menu")])
    return Kb(inline_keyboard=rows)


def episodes_kb(a: dict, numbers: list[int], current: int | None, page: int | None = None) -> Kb:
    pages = max(1, -(-len(numbers) // PER))
    if page is None:
        page = numbers.index(current) // PER if current in numbers else 0
    page = max(0, min(page, pages - 1))
    chunk = numbers[page * PER:(page + 1) * PER]
    cur = current or 0

    rows, row = [], []
    for n in chunk:
        row.append(Btn(text=f"▶️ {n}" if n == current else str(n), callback_data=f"p:{a['id']}:{n}"))
        if len(row) == GRID:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if pages > 1:
        prev_cb = f"g:{a['id']}:{page - 1}:{cur}" if page > 0 else "edge"
        next_cb = f"g:{a['id']}:{page + 1}:{cur}" if page < pages - 1 else "edge"
        rows.append([Btn(text="◀️ Oldingi", callback_data=prev_cb),
                     Btn(text=f"📄 {page + 1} / {pages}", callback_data="noop"),
                     Btn(text="Keyingi ▶️", callback_data=next_cb)])
    rows.append([Btn(text="📤 Ulashish", url=share_url(a["code"]))])
    rows.append([Btn(text="🏠 Menu", callback_data="menu"), Btn(text="⭐ Baho berish", callback_data=f"rt:{a['id']}")])
    return Kb(inline_keyboard=rows)


def sub_kb(channels: list[dict], anime_id: int, number: int) -> Kb:
    rows = [[Btn(text=f"📢 {c['title']}", url=c["url"])] for c in channels]
    rows.append([Btn(text="✅ Tekshirish", callback_data=f"c:{anime_id}:{number}")])
    return Kb(inline_keyboard=rows)


def list_kb(items: list[dict], page: int, has_next: bool, prefix: str, back: tuple[str, str] | None = None) -> Kb:
    """prefix: 'gn:Action' -> sahifa tugmalari `{prefix}:{page}`"""
    rows = [[Btn(text=f"🎬 {a['title']}"[:60], callback_data=f"a:{a['id']}")] for a in items]
    if page > 0 or has_next:
        nav = []
        if page > 0:
            nav.append(Btn(text="◀️ Oldingi", callback_data=f"{prefix}:{page - 1}"))
        nav.append(Btn(text=f"📄 {page + 1}", callback_data="noop"))
        if has_next:
            nav.append(Btn(text="Keyingi ▶️", callback_data=f"{prefix}:{page + 1}"))
        rows.append(nav)
    if back:
        rows.append([Btn(text=back[0], callback_data=back[1])])
    rows.append([Btn(text="🏠 Asosiy menyu", callback_data="menu")])
    return Kb(inline_keyboard=rows)


def genres_kb(genres: list[tuple[str, int]]) -> Kb:
    rows, row = [], []
    for g, _n in genres:
        row.append(Btn(text=f"{genre_emoji(g)} {g}"[:30], callback_data=f"gn:{g}:0"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn(text="🔍 Nom bo'yicha izlash", switch_inline_query_current_chat="")])
    rows.append([Btn(text="🏠 Asosiy menyu", callback_data="menu")])
    return Kb(inline_keyboard=rows)


def rate_kb(aid: int) -> Kb:
    rows = [[Btn(text=str(i), callback_data=f"rs:{aid}:{i}") for i in range(s, s + 5)] for s in (1, 6)]
    rows.append([Btn(text="❌ Bekor", callback_data="rc")])
    return Kb(inline_keyboard=rows)
