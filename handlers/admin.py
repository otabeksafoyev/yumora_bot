import asyncio
import re

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb, Message

import broadcast
import config
import db
import store
from handlers.user import CODE_RE, esc

router = Router()


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.is_admin(u.id))


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
router.channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)


class AddAnime(StatesGroup):
    code = State()
    title = State()
    poster = State()


class AddEps(StatesGroup):
    code = State()
    upload = State()


class DelAnime(StatesGroup):
    code = State()


class AddChan(StatesGroup):
    wait = State()


class Cast(StatesGroup):
    wait = State()


PANEL = Kb(inline_keyboard=[
    [Btn(text="➕ Anime", callback_data="ad:anime"), Btn(text="🎞 Qismlar", callback_data="ad:eps")],
    [Btn(text="🗑 Anime o'chirish", callback_data="ad:del"), Btn(text="📢 Kanallar", callback_data="ad:chans")],
    [Btn(text="📣 Xabar yuborish", callback_data="ad:cast"), Btn(text="📊 Statistika", callback_data="ad:stats")],
])


@router.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "⚙️ <b>Admin panel</b>\n\n"
        "/ban id · /unban id · /delep kod qism\n/addadmin id · /deladmin id · /stopcast",
        reply_markup=PANEL,
    )


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.")


@router.message(Command("done"))
async def done(m: Message, state: FSMContext):
    await state.clear()
    store.invalidate_anime()
    await m.answer("✅ Tayyor.")


# ── anime qo'shish ──────────────────────────────────────────
@router.callback_query(F.data == "ad:anime")
async def a1(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(AddAnime.code)
    await c.message.answer("Anime KODI (lotin harf/raqam/«-», masalan: naruto-1):")


@router.message(AddAnime.code, F.text)
async def a2(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    if not CODE_RE.match(code):
        return await m.answer("❌ Faqat a-z, 0-9 va «-». Qayta yozing:")
    if await db.anime_by_code(code):
        return await m.answer("❌ Bu kod band. Boshqasini yozing:")
    await state.update_data(code=code)
    await state.set_state(AddAnime.title)
    await m.answer("Anime NOMI:")


@router.message(AddAnime.title, F.text)
async def a3(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:200])
    await state.set_state(AddAnime.poster)
    await m.answer("Poster rasmini yuboring (yoki /skip):")


async def _finish_anime(m: Message, state: FSMContext, poster: str | None):
    d = await state.get_data()
    try:
        aid = await db.add_anime(d["code"], d["title"], poster)
    except Exception as e:  # noqa: BLE001
        await state.clear()
        return await m.answer(f"❌ Xato: {e}")
    store.invalidate_anime()
    await state.set_state(AddEps.upload)
    await state.update_data(aid=aid)
    await m.answer(
        f"✅ <b>{esc(d['title'])}</b> qo'shildi. Kod: <code>{d['code']}</code>\n\n"
        "Endi videolarni ketma-ket yuboring (1-qismdan). Raqam sarlavhada yozilgan bo'lsa shu raqam olinadi.\n"
        "Tugatish: /done"
    )


@router.message(AddAnime.poster, F.photo)
async def a4(m: Message, state: FSMContext):
    await _finish_anime(m, state, m.photo[-1].file_id)


@router.message(AddAnime.poster, Command("skip"))
async def a5(m: Message, state: FSMContext):
    await _finish_anime(m, state, None)


# ── qismlar ─────────────────────────────────────────────────
@router.callback_query(F.data == "ad:eps")
async def e1(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(AddEps.code)
    await c.message.answer("Qaysi anime kodiga qism qo'shamiz?")


@router.message(AddEps.code, F.text)
async def e2(m: Message, state: FSMContext):
    a = await db.anime_by_code(m.text.strip().lower())
    if not a:
        return await m.answer("❌ Topilmadi. Qayta yozing yoki /cancel")
    await state.set_state(AddEps.upload)
    await state.update_data(aid=a["id"])
    last = await db.max_episode(a["id"])
    await m.answer(f"<b>{esc(a['title'])}</b>: hozir {last} ta qism bor. Videolarni yuboring ({last + 1}-dan). Tugatish: /done")


_locks: dict[int, asyncio.Lock] = {}


@router.message(AddEps.upload, F.video)
async def e3(m: Message, state: FSMContext):
    lock = _locks.setdefault(m.from_user.id, asyncio.Lock())
    async with lock:  # ketma-ket kelgan videolar raqamlari to'qnashmasligi uchun
        d = await state.get_data()
        cap = (m.caption or "").strip()
        if cap.isdigit():
            n = int(cap)
        else:
            n = max(d.get("last", 0), await db.max_episode(d["aid"])) + 1
        await db.set_episode(d["aid"], n, m.video.file_id)
        await state.update_data(last=n)
    await m.reply(f"✅ {n}-qism")


@router.message(AddEps.upload, F.document)
async def e4(m: Message):
    await m.answer("⚠️ Fayl emas, «video» sifatida yuboring.")


@router.message(Command("delep"))
async def delep(m: Message):
    p = (m.text or "").split()
    if len(p) != 3 or not p[2].isdigit():
        return await m.answer("Foydalanish: /delep kod qism")
    a = await db.anime_by_code(p[1].lower())
    if not a:
        return await m.answer("❌ Anime topilmadi")
    ok = await db.delete_episode(a["id"], int(p[2]))
    store.invalidate_anime()
    await m.answer("✅ O'chirildi" if ok else "❌ Bunday qism yo'q")


# kanalga tashlab yuklash: caption "id:kod" va "qism:N"
@router.channel_post(F.video, F.caption)
async def channel_upload(m: Message, bot: Bot):
    code = re.search(r"id:\s*([a-z0-9-]+)", m.caption, re.I)
    num = re.search(r"qism:\s*(\d+)", m.caption, re.I)
    if not (code and num):
        return
    a = await db.anime_by_code(code.group(1).lower())
    if a:
        await db.set_episode(a["id"], int(num.group(1)), m.video.file_id)
        store.invalidate_anime()


# ── o'chirish ───────────────────────────────────────────────
@router.callback_query(F.data == "ad:del")
async def d1(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(DelAnime.code)
    await c.message.answer("O'chiriladigan anime kodi:")


@router.message(DelAnime.code, F.text)
async def d2(m: Message, state: FSMContext):
    a = await db.anime_by_code(m.text.strip().lower())
    await state.clear()
    if not a:
        return await m.answer("❌ Topilmadi")
    await m.answer(
        f"Rostdan <b>{esc(a['title'])}</b> va barcha qismlarini o'chirasizmi?",
        reply_markup=Kb(inline_keyboard=[[Btn(text="Ha, o'chir", callback_data=f"ad:dely:{a['id']}"),
                                          Btn(text="Yo'q", callback_data="ad:no")]]),
    )


@router.callback_query(F.data.startswith("ad:dely:"))
async def d3(c: CallbackQuery):
    await db.delete_anime(int(c.data.split(":")[2]))
    store.invalidate_anime()
    await c.answer("O'chirildi")
    await c.message.edit_text("✅ O'chirildi")


@router.callback_query(F.data == "ad:no")
async def d4(c: CallbackQuery):
    await c.answer()
    await c.message.delete()


# ── majburiy kanallar ───────────────────────────────────────
async def _chan_list() -> tuple[str, Kb]:
    rows = await db.channels()
    text = "📢 <b>Majburiy kanallar</b>\n\n" + ("\n".join(
        f"{c['id']}. {esc(c['title'])} " + ("(hamma anime)" if c["anime_id"] is None else f"(anime #{c['anime_id']})")
        for c in rows) or "Hozircha yo'q")
    kbd = [[Btn(text=f"🗑 {c['id']}. {c['title']}"[:50], callback_data=f"ad:chdel:{c['id']}")] for c in rows]
    kbd.append([Btn(text="➕ Qo'shish", callback_data="ad:chadd")])
    return text, Kb(inline_keyboard=kbd)


@router.callback_query(F.data == "ad:chans")
async def c1(c: CallbackQuery):
    await c.answer()
    text, kbd = await _chan_list()
    await c.message.answer(text, reply_markup=kbd)


@router.callback_query(F.data == "ad:chadd")
async def c2(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(AddChan.wait)
    await c.message.answer(
        "Kanalni yuboring (bot kanalda ADMIN bo'lishi shart):\n\n"
        "• ochiq kanal: <code>@kanal</code>\n"
        "• yopiq kanal: <code>-100123456789 https://t.me/+invite</code>\n\n"
        "Faqat bitta anime uchun bo'lsa — 2-qatorga anime kodini yozing."
    )


@router.message(AddChan.wait, F.text)
async def c3(m: Message, state: FSMContext, bot: Bot):
    lines = [x.strip() for x in m.text.strip().splitlines() if x.strip()]
    parts = lines[0].split()
    anime_id = None
    if len(lines) > 1:
        a = await db.anime_by_code(lines[1].lower())
        if not a:
            return await m.answer("❌ Anime kodi topilmadi. Qayta yuboring yoki /cancel")
        anime_id = a["id"]
    try:
        ident = parts[0] if parts[0].startswith("@") else int(parts[0])
        chat = await bot.get_chat(ident)
        url = parts[1] if len(parts) > 1 else (f"https://t.me/{chat.username}" if chat.username else None)
        if not url:
            return await m.answer("❌ Yopiq kanal uchun invite link ham yozing.")
    except Exception as e:  # noqa: BLE001
        return await m.answer(f"❌ Topilmadi: {e}\nQayta yuboring yoki /cancel")
    await db.add_channel(chat.id, url, chat.title or str(chat.id), anime_id)
    store.invalidate_channels()
    await state.clear()
    await m.answer(f"✅ Qo'shildi: {esc(chat.title or '')}")


@router.callback_query(F.data.startswith("ad:chdel:"))
async def c4(c: CallbackQuery):
    await db.delete_channel(int(c.data.split(":")[2]))
    store.invalidate_channels()
    await c.answer("O'chirildi")
    text, kbd = await _chan_list()
    await c.message.edit_text(text, reply_markup=kbd)


# ── xabar yuborish ──────────────────────────────────────────
@router.callback_query(F.data == "ad:cast")
async def b1(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.set_state(Cast.wait)
    await c.message.answer("Yuboriladigan xabarni jo'nating (matn/rasm/video — hammasi bo'ladi). Bekor: /cancel")


@router.message(Cast.wait)
async def b2(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "Shu xabarni hamma foydalanuvchiga yuboraymi?",
        reply_markup=Kb(inline_keyboard=[[Btn(text="✅ Yuborish", callback_data=f"ad:castgo:{m.chat.id}:{m.message_id}"),
                                          Btn(text="❌ Yo'q", callback_data="ad:no")]]),
    )


@router.callback_query(F.data.startswith("ad:castgo:"))
async def b3(c: CallbackQuery, bot: Bot):
    _, _, chat, mid = c.data.split(":")
    await c.answer("Boshlandi")
    await c.message.delete()
    asyncio.create_task(broadcast.run(bot, c.message.chat.id, int(chat), int(mid)))


@router.message(Command("stopcast"))
async def stopcast(m: Message):
    broadcast.state["stop"] = True
    await m.answer("To'xtatilmoqda…")


# ── statistika / ban / adminlar ─────────────────────────────
@router.callback_query(F.data == "ad:stats")
async def s1(c: CallbackQuery):
    await c.answer()
    s = await db.stats()
    top = await db.top(5)
    t = "\n".join(f"{i}. {esc(a['title'])} — {a['views']}" for i, a in enumerate(top, 1)) or "—"
    await c.message.answer(
        f"📊 <b>Statistika</b>\n\n👥 Userlar: {s['users']}\n🟢 24 soatda faol: {s['day']}\n"
        f"🚫 Botni bloklagan: {s['blocked']}\n🎬 Anime: {s['animes']}\n📼 Qism: {s['episodes']}\n"
        f"👁 Ko'rishlar: {s['views']}\n\n🔥 Top 5:\n{t}"
    )


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
    await m.answer(f"🚫 {uid} bloklandi")


@router.message(Command("unban"))
async def unban(m: Message):
    uid = _arg_id(m)
    if uid is None:
        return await m.answer("Foydalanish: /unban user_id")
    await db.set_banned(uid, False)
    store.banned.discard(uid)
    await m.answer(f"✅ {uid} blokdan chiqdi")


@router.message(Command("addadmin"))
async def addadmin(m: Message):
    uid = _arg_id(m)
    if m.from_user.id not in config.ADMIN_IDS or uid is None:
        return await m.answer("Faqat asosiy admin: /addadmin user_id")
    await db.add_admin(uid)
    store.db_admins.add(uid)
    await m.answer(f"✅ {uid} admin")


@router.message(Command("deladmin"))
async def deladmin(m: Message):
    uid = _arg_id(m)
    if m.from_user.id not in config.ADMIN_IDS or uid is None:
        return await m.answer("Faqat asosiy admin: /deladmin user_id")
    await db.del_admin(uid)
    store.db_admins.discard(uid)
    await m.answer(f"✅ {uid} adminlikdan olindi")
