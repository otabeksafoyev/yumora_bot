from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb

PAGE = 20
ROW = 5


def episodes_kb(anime_id: int, numbers: list[int], current: int, page: int | None = None) -> Kb:
    pages = max(1, -(-len(numbers) // PAGE))
    if page is None:
        page = numbers.index(current) // PAGE if current in numbers else 0
    page = max(0, min(page, pages - 1))
    chunk = numbers[page * PAGE : (page + 1) * PAGE]

    rows, row = [], []
    for n in chunk:
        row.append(Btn(text=f"▶️ {n}" if n == current else str(n), callback_data=f"p:{anime_id}:{n}"))
        if len(row) == ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Btn(text="⬅️", callback_data=f"g:{anime_id}:{page - 1}:{current}"))
        nav.append(Btn(text=f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(Btn(text="➡️", callback_data=f"g:{anime_id}:{page + 1}:{current}"))
        rows.append(nav)
    rows.append([Btn(text="🔍 Qidirish", switch_inline_query_current_chat="")])
    return Kb(inline_keyboard=rows)


def sub_kb(channels: list[dict], anime_id: int, number: int) -> Kb:
    rows = [[Btn(text=f"📢 {c['title']}", url=c["url"])] for c in channels]
    rows.append([Btn(text="✅ Tekshirish", callback_data=f"c:{anime_id}:{number}")])
    return Kb(inline_keyboard=rows)


def results_kb(items: list[dict]) -> Kb:
    return Kb(inline_keyboard=[[Btn(text=f"🎬 {a['title']}"[:60], callback_data=f"a:{a['id']}")] for a in items])


def home_kb() -> Kb:
    return Kb(
        inline_keyboard=[
            [Btn(text="🔍 Anime qidirish", switch_inline_query_current_chat="")],
            [Btn(text="🔥 Eng ko'p ko'rilganlar", callback_data="top")],
        ]
    )
