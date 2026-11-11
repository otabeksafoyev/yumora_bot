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
from handlers.user import CODE_RE, card_text, esc

router = Router()
panel = Router()  # panel tugmalari — holat (FSM) ishlovchilaridan OLDIN tekshiriladi


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.is_admin(u.id))


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
panel.message.filter(IsAdmin())
router.channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)

# ── tugma yozuvlari ─────────────────────────────────────────
B_ADD = "+ Anime qo'shish"
B_EPS = "⊙ Qism qo'shish"
B_MANAGE = "≡ Anime boshqaruv"
B_CHANS = "ᐅ Kanallar"
B_CAST = "ᐅ Xabar yuborish"
B_STATS = "◈ Statistika"
B_BACKUP = "≡ Baza zaxira"
B_POSTER = "▣ Standart poster"
B_EXIT = "⌂ Chiqish"
B_CANCEL = "✕ Bekor qilish"
B_DONE = "✓ Tayyor"


def admin_kb() -> ReplyKeyboardMarkup:
    rows = [[B_ADD, B_EPS], [B_MANAGE, B_CHANS], [B_CAST, B_STATS], [B_BACKUP, B_POSTER], [B_EXIT]]
    return ReplyKeyboardMarkup(keyboard=[[KBtn(text=t) for t in r] for r in rows],
                               resize_keyboard=True, is_persistent=True)


def flow_kb(done: bool = False) -> ReplyKeyboardMarkup:
    rows = ([[KBtn(text=B_DONE)]] if done else []) + [[KBtn(text=B_CANCEL)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


PANEL_TEXT = (
    "✱ <b>Yumora Admin Panel</b>\nRol: OWNER\n\n"
    "# Qo'llanma:\n"
    "• <b>+ Anime qo'shish</b> — ID → nom → janr → poster/treyler, so'ng qismlar avtomatik\n"
    "• <b>⊙ Qism qo'shish</b> — animeni tanlang, videolarni tashlang, raqam o'zi qo'yiladi\n"
    "• <b>≡ Anime boshqaruv</b> — nom, janr, poster, treyler, qism o'chirish, o'chirish\n"
    "• <b>ᐅ Kanallar</b> — majburiy obuna va news kanallar\n"
    "• <b>▣ Standart poster</b> — posteri yo'q animelar uchun qidiruvdagi rasm\n\n"
    "/ban id · /unban id · /delep kod qism · /addadmin id · /deladmin id · /stopcast"
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


# ── kirish / bekor / chiqish ────────────────────────────────
@panel.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(PANEL_TEXT, reply_markup=admin_kb())


@panel.message(F.text == B_CANCEL)
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✕ Bekor qilindi.", reply_markup=admin_kb())


@panel.message(F.text == B_EXIT)
async def leave(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("⌂ Admin paneldan chiqdingiz. Qaytish: /admin", reply_markup=ReplyKeyboardRemove())


# ── + Anime qo'shish ────────────────────────────────────────
@panel.message(F.text == B_ADD)
async def add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddAnime.code)
    await m.answer("№ <b>Anime ID (kod)</b> yozing — lotin harf, raqam va «-»\nMasalan: <code>naruto-1</code>",
                   reply_markup=flow_kb())


@router.message(AddAnime.code, F.text)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    if not CODE_RE.match(code):
        return await m.answer("! Faqat a-z, 0-9 va «-». Qayta yozing:")
    if await db.anime_by_code(code):
        return await m.answer("! Bu ID band. Boshqasini yozing:")
    await state.update_data(code=code)
    await state.set_state(AddAnime.title)
    await m.answer("๏ <b>Anime nomi:</b>")


@router.message(AddAnime.title, F.text)
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:200])
    await state.set_state(AddAnime.genres)
    await m.answer("⌕ <b>Janr(lar)</b> — vergul bilan yozing:\n"
                   "<i>Action, Romance, Comedy, Fantasy, Drama, Horror, Slice of Life, Sci-Fi, Sports, "
                   "Mystery, Supernatural, Mecha</i>")


@router.message(AddAnime.genres, F.text)
async def add_genres(m: Message, state: FSMContext):
    g = parse_genres(m.text)
    if not g:
        return await m.answer("! Kamida bitta janr yozing:")
    await state.update_data(genres=g)
    await state.set_state(AddAnime.media)
    await m.answer("▣ <b>Poster (rasm)</b> yoki <b>treyler (video)</b> yuboring.\n"
                   "Ikkalasidan kamida bittasi shart; xohlasangiz ikkalasini ham yuboring, so'ng «✓ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await m.answer("✓ Poster qabul qilindi. Treyler ham yuborishingiz mumkin yoki «✓ Tayyor».", reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.video)
async def add_trailer(m: Message, state: FSMContext):
    await state.update_data(trailer=m.video.file_id)
    await m.answer("✓ Treyler qabul qilindi. Poster ham yuborishingiz mumkin yoki «✓ Tayyor».", reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.text == B_DONE)
async def add_finish(m: Message, state: FSMContext):
    d = await state.get_data()
    if not (d.get("poster") or d.get("trailer")):
        return await m.answer("! Poster yoki treyler — kamida bittasi kerak. Rasm yoki video yuboring.")
    try:
        aid = await db.add_anime(d["code"], d["title"], d["genres"], d.get("poster"), d.get("trailer"))
    except Exception as e:  # noqa: BLE001
        await state.clear()
        return await m.answer(f"! Xato: {esc(e)}", reply_markup=admin_kb())
    store.invalidate_anime()
    note = ""
    if not d.get("poster") and not await store.default_poster():
        note = "\n\n! Poster yo'q va standart poster ham o'rnatilmagan — qidiruvda rasm chiqmaydi. «▣ Standart poster» orqali rasm yuklang."
    await state.clear()
    await m.answer(f"✓ <b>{esc(d['title'])}</b> qo'shildi.{note}", reply_markup=admin_kb())
    await start_upload(m, state, aid, new=True)


# ── anime tanlash (qism qo'shish / boshqaruv) ───────────────
async def ask_pick(m: Message, state: FSMContext, action: str):
    await state.clear()
    await state.set_state(Pick.q)
    await state.update_data(action=action)
    recent = await db.recent(8)
    rows = [[Btn(text=f"๏ {a['title']}"[:60], callback_data=f"pk:{a['id']}")] for a in recent]
    await m.answer("⌕ <b>Anime ID (kod) yoki nomini yozing</b>" + (", yoki oxirgilardan tanlang:" if rows else ":"),
                   reply_markup=flow_kb())
    if rows:
        await m.answer("Oxirgi qo'shilganlar:", reply_markup=Kb(inline_keyboard=rows))


@panel.message(F.text == B_EPS)
async def eps_entry(m: Message, state: FSMContext):
    await ask_pick(m, state, "eps")


@panel.message(F.text == B_MANAGE)
async def manage_entry(m: Message, state: FSMContext):
    await ask_pick(m, state, "manage")


@router.message(Pick.q, F.text)
async def pick_text(m: Message, state: FSMContext):
    q = m.text.strip()
    a = await db.anime_by_code(q.lower()) if CODE_RE.match(q.lower()) else None
    if a:
        return await go(m, state, a["id"])
    items = await db.search(q, 10)
    if not items:
        return await m.answer("⌕ Topilmadi. Qayta yozing yoki «✕ Bekor qilish».")
    await m.answer("⌕ Topilganlar:", reply_markup=Kb(inline_keyboard=[
        [Btn(text=f"๏ {a['title']}"[:60], callback_data=f"pk:{a['id']}")] for a in items]))


@router.callback_query(F.data.startswith("pk:"))
async def pick_cb(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await go(c.message, state, int(c.data.split(":")[1]))


async def go(m: Message, state: FSMContext, aid: int):
    act = (await state.get_data()).get("action", "manage")
    if act == "eps":
        return await start_upload(m, state, aid)
    await state.clear()
    await m.answer("≡ Anime boshqaruv", reply_markup=admin_kb())
    await show_manage(m, aid)


# ── qismlarni avtomatik qo'shish ────────────────────────────
async def start_upload(m: Message, state: FSMContext, aid: int, new: bool = False):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("! Anime topilmadi", reply_markup=admin_kb())
    last = await db.max_episode(aid)
    await state.clear()
    await state.set_state(AddEps.up)
    await state.update_data(aid=aid, last=0, cnt=0, new=new)
    await m.answer(
        f"⊙ <b>{esc(a['title'])}</b>\nHozir <b>{last}</b> ta qism bor.\n\n"
        f"Videolarni ketma-ket yuboring — qismlar <b>avtomatik {last + 1}-dan</b> raqamlanadi.\n"
        "Boshqa raqam kerak bo'lsa, sarlavhaga yozing (masalan «12» yoki «12-qism»).\n"
        "Tugagach «✓ Tayyor» ni bosing.", reply_markup=flow_kb(True))


_locks: dict[int, asyncio.Lock] = {}


@router.message(AddEps.up, F.video)
async def ep_video(m: Message, state: FSMContext):
    lock = _locks.setdefault(m.from_user.id, asyncio.Lock())
    async with lock:  # ketma-ket kelgan videolar raqamlari to'qnashmasligi uchun
        d = await state.get_data()
        n = parse_ep(m.caption) or max(d.get("last", 0), await db.max_episode(d["aid"])) + 1
        await db.set_episode(d["aid"], n, m.video.file_id)
        await state.update_data(last=n, cnt=d.get("cnt", 0) + 1)
    await m.reply(f"✓ {n}-qism saqlandi")


@router.message(AddEps.up, F.document)
async def ep_doc(m: Message):
    await m.answer("! Fayl emas, «video» sifatida yuboring.")


@router.message(AddEps.up, F.text == B_DONE)
async def ep_done(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    store.invalidate_anime()
    await m.answer(f"✓ Tayyor. <b>{d.get('cnt', 0)}</b> ta qism qo'shildi.", reply_markup=admin_kb())
    if d.get("new") and await store.news_channels():
        await m.answer("ᐅ News kanalga e'lon qilaymi?", reply_markup=Kb(inline_keyboard=[[
            Btn(text="ᐅ E'lon qilish", callback_data=f"am:{d['aid']}:news"), Btn(text="✕ Yo'q", callback_data="ad:no")]]))


# ── anime boshqaruv ─────────────────────────────────────────
async def show_manage(m: Message, aid: int):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("! Topilmadi")
    n = await db.max_episode(aid)
    avg = a["rating_sum"] / a["rating_count"] if a["rating_count"] else 0
    text = (f"๏ <b>{esc(a['title'])}</b>\n№ <code>{a['code']}</code>\n⌕ {esc(', '.join(a['genres']) or '—')}\n"
            f"≡ Oxirgi qism: {n}  •  ◉ {a['views']} ko'rish  •  ★ {avg:.1f} ({a['rating_count']})\n"
            f"▣ Poster: {'bor' if a['poster_file_id'] else 'yo‘q'}  •  Treyler: {'bor' if a['trailer_file_id'] else 'yo‘q'}")
    rows = [
        [Btn(text="✎ Nom", callback_data=f"am:{aid}:title"), Btn(text="✎ Janr", callback_data=f"am:{aid}:genres")],
        [Btn(text="▣ Poster", callback_data=f"am:{aid}:poster_file_id"),
         Btn(text="▣ Treyler", callback_data=f"am:{aid}:trailer_file_id")],
        [Btn(text="⊙ Qism qo'shish", callback_data=f"am:{aid}:eps"),
         Btn(text="✕ Qism o'chirish", callback_data=f"am:{aid}:delep")],
        [Btn(text="ᐅ News e'lon", callback_data=f"am:{aid}:news"),
         Btn(text="✕ Anime o'chirish", callback_data=f"am:{aid}:del")],
    ]
    await m.answer(text, reply_markup=Kb(inline_keyboard=rows))


PROMPTS = {
    "title": "✎ Yangi <b>nom</b>ni yozing:",
    "genres": "✎ Yangi <b>janr</b>larni vergul bilan yozing:",
    "poster_file_id": "▣ Yangi <b>poster</b> rasmini yuboring:",
    "trailer_file_id": "▣ Yangi <b>treyler</b> videosini yuboring:",
}


@router.callback_query(F.data.startswith("am:"))
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
        return await c.message.answer("✕ O'chiriladigan <b>qism raqami</b>ni yozing:", reply_markup=flow_kb())
    if act == "news":
        sent = await post_news(bot, aid)
        return await c.message.answer(f"✓ {sent} ta news kanalga yuborildi." if sent else "! News kanal yo'q yoki yuborilmadi (ᐅ Kanallar).")
    if act == "del":
        a = await db.anime_by_id(aid)
        return await c.message.answer(
            f"✕ Rostdan <b>{esc(a['title'] if a else aid)}</b> va barcha qismlarini o'chirasizmi?",
            reply_markup=Kb(inline_keyboard=[[Btn(text="✓ Ha, o'chir", callback_data=f"ad:dely:{aid}"),
                                              Btn(text="✕ Yo'q", callback_data="ad:no")]]))


@router.message(EditF.v)
async def edit_value(m: Message, state: FSMContext):
    d = await state.get_data()
    f, aid = d["field"], d["aid"]
    if f == "title" and m.text:
        val = m.text.strip()[:200]
    elif f == "genres" and m.text:
        val = parse_genres(m.text)
        if not val:
            return await m.answer("! Kamida bitta janr yozing:")
    elif f == "poster_file_id" and m.photo:
        val = m.photo[-1].file_id
    elif f == "trailer_file_id" and m.video:
        val = m.video.file_id
    else:
        return await m.answer("! Noto'g'ri turdagi xabar. " + PROMPTS[f])
    await db.update_anime(aid, f, val)
    store.invalidate_anime()
    await state.clear()
    await m.answer("✓ Yangilandi.", reply_markup=admin_kb())


@router.message(DelEp.n, F.text)
async def delep_value(m: Message, state: FSMContext):
    d = await state.get_data()
    if not m.text.strip().isdigit():
        return await m.answer("! Faqat raqam yozing:")
    ok = await db.delete_episode(d["aid"], int(m.text))
    store.invalidate_anime()
    await state.clear()
    await m.answer("✓ O'chirildi." if ok else "! Bunday qism yo'q.", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("ad:dely:"))
async def del_yes(c: CallbackQuery):
    await db.delete_anime(int(c.data.split(":")[2]))
    store.invalidate_anime()
    await c.answer("O'chirildi")
    await c.message.edit_text("✓ Anime o'chirildi.")


@router.callback_query(F.data == "ad:no")
async def no(c: CallbackQuery):
    await c.answer()
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("delep"))
async def delep_cmd(m: Message):
    p = (m.text or "").split()
    if len(p) != 3 or not p[2].isdigit():
        return await m.answer("Foydalanish: /delep kod qism")
    a = await db.anime_by_code(p[1].lower())
    if not a:
        return await m.answer("! Anime topilmadi")
    ok = await db.delete_episode(a["id"], int(p[2]))
    store.invalidate_anime()
    await m.answer("✓ O'chirildi" if ok else "! Bunday qism yo'q")


# ── news e'lon ──────────────────────────────────────────────
async def post_news(bot: Bot, aid: int) -> int:
    a = await db.anime_by_id(aid)
    chans = await store.news_channels()
    if not a or not chans:
        return 0
    eps = await store.episodes(aid)
    text = card_text({**a}, len(eps.numbers))
    markup = Kb(inline_keyboard=[[Btn(text="ᐅ Tomosha qilish", url=kbd.start_link(a["code"]))]])
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


# ── standart poster ─────────────────────────────────────────
@panel.message(F.text == B_POSTER)
async def poster_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SetPoster.wait)
    has = await store.default_poster()
    await m.answer(f"▣ <b>Standart poster</b> — posteri yo'q animelar uchun qidiruvda ko'rinadi.\n"
                   f"Hozir: <b>{'o‘rnatilgan' if has else 'yo‘q'}</b>\n\nYangi rasmni yuboring:", reply_markup=flow_kb())


@router.message(SetPoster.wait, F.photo)
async def poster_set(m: Message, state: FSMContext):
    await store.set_default_poster(m.photo[-1].file_id)
    await state.clear()
    await m.answer("✓ Standart poster o'rnatildi.", reply_markup=admin_kb())


# ── kanallar ────────────────────────────────────────────────
async def chan_list() -> tuple[str, Kb]:
    rows = await db.channels()
    lines = []
    for c in rows:
        kind = "majburiy" if c["kind"] == "sub" else "news"
        scope = "" if c["anime_id"] is None else f" • anime #{c['anime_id']}"
        lines.append(f"{c['id']}. {esc(c['title'])} ({kind}{scope})")
    text = "ᐅ <b>Kanallar</b>\n\n" + ("\n".join(lines) or "Hozircha yo'q")
    kb_rows = [[Btn(text=f"✕ {c['id']}. {c['title']}"[:50], callback_data=f"ad:chdel:{c['id']}")] for c in rows]
    kb_rows.append([Btn(text="+ Majburiy kanal", callback_data="ad:chadd:sub"),
                    Btn(text="+ News kanal", callback_data="ad:chadd:news")])
    return text, Kb(inline_keyboard=kb_rows)


@panel.message(F.text == B_CHANS)
async def chans_entry(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await chan_list()
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("ad:chadd:"))
async def chan_add_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(AddChan.wait)
    await state.update_data(kind=c.data.split(":")[2])
    await c.message.answer(
        "ᐅ Kanalni yuboring (bot kanalda <b>ADMIN</b> bo'lishi shart):\n\n"
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
            return await m.answer("! Anime ID topilmadi. Qayta yuboring yoki «✕ Bekor qilish».")
        anime_id = a["id"]
    try:
        chat = await bot.get_chat(parts[0] if parts[0].startswith("@") else int(parts[0]))
        url = parts[1] if len(parts) > 1 else (f"https://t.me/{chat.username}" if chat.username else None)
        if not url:
            return await m.answer("! Yopiq kanal uchun invite link ham yozing.")
    except Exception as e:  # noqa: BLE001
        return await m.answer(f"! Topilmadi: {esc(e)}\nQayta yuboring yoki «✕ Bekor qilish».")
    kind = (await state.get_data()).get("kind", "sub")
    await db.add_channel(chat.id, url, chat.title or str(chat.id), anime_id, kind)
    store.invalidate_channels()
    await state.clear()
    await m.answer(f"✓ Qo'shildi: {esc(chat.title or '')}", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("ad:chdel:"))
async def chan_del(c: CallbackQuery):
    await db.delete_channel(int(c.data.split(":")[2]))
    store.invalidate_channels()
    await c.answer("O'chirildi")
    text, kb = await chan_list()
    await c.message.edit_text(text, reply_markup=kb)


# ── xabar yuborish ──────────────────────────────────────────
@panel.message(F.text == B_CAST)
async def cast_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Cast.wait)
    await m.answer("ᐅ Yuboriladigan xabarni jo'nating (matn / rasm / video — hammasi bo'ladi):", reply_markup=flow_kb())


@router.message(Cast.wait)
async def cast_got(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✓ Xabar qabul qilindi.", reply_markup=admin_kb())
    await m.reply("Shu xabarni hamma foydalanuvchiga yuboraymi?", reply_markup=Kb(inline_keyboard=[[
        Btn(text="✓ Yuborish", callback_data=f"ad:castgo:{m.chat.id}:{m.message_id}"),
        Btn(text="✕ Yo'q", callback_data="ad:no")]]))


@router.callback_query(F.data.startswith("ad:castgo:"))
async def cast_go(c: CallbackQuery, bot: Bot):
    _, _, chat, mid = c.data.split(":")
    await c.answer("Boshlandi")
    await c.message.delete()
    asyncio.create_task(broadcast.run(bot, c.message.chat.id, int(chat), int(mid)))


@router.message(Command("stopcast"))
async def stopcast(m: Message):
    broadcast.state["stop"] = True
    await m.answer("To'xtatilmoqda…")


# ── statistika / zaxira ─────────────────────────────────────
@panel.message(F.text == B_STATS)
async def stats(m: Message, state: FSMContext):
    await state.clear()
    s = await db.stats()
    top = await db.top(5)
    t = "\n".join(f"{i}. {esc(a['title'])} — {a['views']}" for i, a in enumerate(top, 1)) or "—"
    await m.answer(
        f"◈ <b>Statistika</b>\n\n◉ Userlar: <b>{s['users']}</b>\n● Hozir online: <b>{store.online_count}</b>\n"
        f"☼ 24 soatda faol: <b>{s['day']}</b>\n✕ Botni bloklagan: <b>{s['blocked']}</b>\n"
        f"๏ Anime: <b>{s['animes']}</b>\n≡ Qism: <b>{s['episodes']}</b>\n◉ Ko'rishlar: <b>{s['views']}</b>\n\n"
        f"★ Top 5:\n{t}")


@panel.message(F.text == B_BACKUP)
async def backup(m: Message, state: FSMContext):
    await state.clear()
    js = json.dumps(await db.dump(), default=str, ensure_ascii=False, indent=1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", js)
    name = f"yumora_backup_{dt.date.today()}.zip"
    await m.answer_document(BufferedInputFile(buf.getvalue(), filename=name), caption="≡ Baza zaxira (JSON, ZIP)")


# ── kanalga tashlab yuklash: caption "id:kod" va "qism:N" ──
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


# ── ban / adminlar ──────────────────────────────────────────
def _arg_id(m: Message):
    p = (m.text or "").split()
    return int(p[1]) if len(p) > 1 and p[1].lstrip("-").isdigit() else None


@router.message(Command("ban"))
async def ban(m: Message):
    uid = _arg_id(m)
    if uid is None or store.is_admin(uid):
        return await m.answer("Foydalanish: /ban user_id")
    await db.set_banned(uid, True)
    store.banned.add(uid)
    await m.answer(f"✕ {uid} bloklandi")


@router.message(Command("unban"))
async def unban(m: Message):
    uid = _arg_id(m)
    if uid is None:
        return await m.answer("Foydalanish: /unban user_id")
    await db.set_banned(uid, False)
    store.banned.discard(uid)
    await m.answer(f"✓ {uid} blokdan chiqdi")


@router.message(Command("addadmin"))
async def addadmin(m: Message):
    uid = _arg_id(m)
    if m.from_user.id not in config.ADMIN_IDS or uid is None:
        return await m.answer("Faqat asosiy admin: /addadmin user_id")
    await db.add_admin(uid)
    store.db_admins.add(uid)
    await m.answer(f"✓ {uid} admin")


@router.message(Command("deladmin"))
async def deladmin(m: Message):
    uid = _arg_id(m)
    if m.from_user.id not in config.ADMIN_IDS or uid is None:
        return await m.answer("Faqat asosiy admin: /deladmin user_id")
    await db.del_admin(uid)
    store.db_admins.discard(uid)
    await m.answer(f"✓ {uid} adminlikdan olindi")
