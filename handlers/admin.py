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
import thumbs
from handlers.user import CODE_RE, card_text, esc, fire, send_card

router = Router()
panel = Router()  # panel tugmalari — holat (FSM) ishlovchilaridan OLDIN tekshiriladi


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.is_admin(u.id))


class Perm(BaseFilter):
    """Adminning ma'lum huquqi bor-yo'qligini tekshiradi ('owner' — faqat asosiy admin)."""

    def __init__(self, key: str):
        self.key = key

    async def __call__(self, event) -> bool:
        u = event.from_user
        return bool(u and store.has_perm(u.id, self.key))


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())
panel.message.filter(IsAdmin())
router.channel_post.filter(F.chat.id == config.UPLOAD_CHANNEL_ID)

# ── tugma yozuvlari ─────────────────────────────────────────
B_ADD = "🆕 Anime qo'shish"
B_EPS = "🎞 Qism qo'shish"
B_MANAGE = "🛠 Anime boshqaruv"
B_CHANS = "📢 Kanallar"
B_CAST = "📣 Xabar yuborish"
B_STATS = "📊 Statistika"
B_BACKUP = "💾 Baza zaxira"
B_POSTER = "🖼 Standart poster"
B_ADMINS = "👑 Adminlar"
B_EXIT = "🚪 Chiqish"
B_CANCEL = "❌ Bekor qilish"
B_DONE = "✅ Tayyor"

# (tugma, huquq kaliti). Admin faqat o'ziga berilgan tugmalarni ko'radi.
BUTTONS = [(B_ADD, "add"), (B_EPS, "eps"), (B_MANAGE, "manage"), (B_CHANS, "chans"),
           (B_CAST, "cast"), (B_STATS, "stats"), (B_BACKUP, "backup"), (B_POSTER, "poster"),
           (B_ADMINS, "owner")]

# Yangi admin uchun belgilanadigan huquqlar
PERMS = [
    ("add", "🆕 Anime qo'shish"),
    ("eps", "🎞 Qism qo'shish"),
    ("manage", "🛠 Boshqaruv (tahrirlash / o'chirish)"),
    ("chans", "📢 Kanallar"),
    ("cast", "📣 Xabar yuborish"),
    ("stats", "📊 Statistika"),
    ("backup", "💾 Baza zaxira"),
    ("poster", "🖼 Standart poster"),
    ("ban", "🚫 Ban / Unban"),
]
PERM_LABEL = dict(PERMS)


def admin_kb(uid: int) -> ReplyKeyboardMarkup:
    shown = [t for t, p in BUTTONS if store.has_perm(uid, p)] + [B_EXIT]
    rows = [shown[i:i + 2] for i in range(0, len(shown), 2)]
    return ReplyKeyboardMarkup(keyboard=[[KBtn(text=t) for t in r] for r in rows],
                               resize_keyboard=True, is_persistent=True)


def flow_kb(done: bool = False) -> ReplyKeyboardMarkup:
    rows = ([[KBtn(text=B_DONE)]] if done else []) + [[KBtn(text=B_CANCEL)]]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def panel_text(uid: int) -> str:
    role = "OWNER 👑" if uid in config.ADMIN_IDS else "ADMIN 🛡"
    return (
        f"✨ <b>Yumora Admin Panel</b> ✨\nRol: <b>{role}</b>\n\n"
        "📖 <b>Qo'llanma:</b>\n"
        "🆕 <b>Anime qo'shish</b> — ID → nom → janr → poster/treyler, so'ng qismlar avtomatik\n"
        "🎞 <b>Qism qo'shish</b> — anime ID sini yozing, videolarni tashlang\n"
        "🛠 <b>Anime boshqaruv</b> — ID bo'yicha: tahrirlash, o'chirish, yuborish\n"
        "📢 <b>Kanallar</b> — majburiy obuna va news kanallar\n"
        "🖼 <b>Standart poster</b> — posteri yo'q animelar uchun rasm\n"
        "👑 <b>Adminlar</b> — yangi admin va uning huquqlari\n\n"
        "⚡️ /anime <code>ID</code> — boshqaruvni to'g'ridan-to'g'ri ochish\n🖼 /thumbs — eski animelar uchun inline rasmlarni tayyorlash\n"
        "🚫 /ban <code>id</code> · /unban <code>id</code> · 🗑 /delep <code>ID qism</code> · ⏹ /stopcast"
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


class NewAdmin(StatesGroup):
    id = State()


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


# ═══ PANEL TUGMALARI (har birida huquq tekshiriladi) ═══════════
@panel.message(Command("admin"))
async def admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(panel_text(m.from_user.id), reply_markup=admin_kb(m.from_user.id))


@panel.message(F.text == B_CANCEL)
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❌ Bekor qilindi.", reply_markup=admin_kb(m.from_user.id))


@panel.message(F.text == B_EXIT)
async def leave(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🚪 Admin paneldan chiqdingiz. Qaytish: /admin", reply_markup=ReplyKeyboardRemove())


@panel.message(F.text == B_ADD, Perm("add"))
async def add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddAnime.code)
    await m.answer("🆔 <b>Anime ID</b> yozing — lotin harf, raqam va «-»\nMasalan: <code>naruto-1</code>",
                   reply_markup=flow_kb())


@panel.message(F.text == B_EPS, Perm("eps"))
async def eps_entry(m: Message, state: FSMContext):
    await ask_id(m, state, "eps")


@panel.message(F.text == B_MANAGE, Perm("manage"))
async def manage_entry(m: Message, state: FSMContext):
    await ask_id(m, state, "manage")


@panel.message(Command("anime"), Perm("manage"))
async def anime_cmd(m: Message, state: FSMContext):
    p = (m.text or "").split()
    a = await db.anime_by_code(p[1].lower()) if len(p) > 1 else None
    if not a:
        return await m.answer("🆔 Foydalanish: /anime <code>ID</code>")
    await state.clear()
    await show_manage(m, a["id"])


@panel.message(F.text == B_POSTER, Perm("poster"))
async def poster_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SetPoster.wait)
    has = await store.default_poster()
    await m.answer(f"🖼 <b>Standart poster</b> — posteri yo'q animelar uchun qidiruvda ko'rinadi.\n"
                   f"Hozir: <b>{'✅ o‘rnatilgan' if has else '❌ yo‘q'}</b>\n\n👇 Yangi rasmni yuboring:",
                   reply_markup=flow_kb())


@panel.message(F.text == B_CHANS, Perm("chans"))
async def chans_entry(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await chan_list()
    await m.answer(text, reply_markup=kb)


@panel.message(F.text == B_CAST, Perm("cast"))
async def cast_entry(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Cast.wait)
    await m.answer("📣 Yuboriladigan xabarni jo'nating (matn / rasm / video — hammasi bo'ladi):",
                   reply_markup=flow_kb())


@panel.message(F.text == B_STATS, Perm("stats"))
async def stats(m: Message, state: FSMContext):
    await state.clear()
    s = await db.stats()
    top = await db.top(5)
    t = "\n".join(f"{i}. {esc(a['title'])} — 👁 {a['views']}" for i, a in enumerate(top, 1)) or "—"
    await m.answer(
        f"📊 <b>Statistika</b>\n\n👥 Userlar: <b>{s['users']}</b>\n"
        f"☀️ 24 soatda faol: <b>{s['day']}</b>\n🚫 Botni bloklagan: <b>{s['blocked']}</b>\n"
        f"🎬 Anime: <b>{s['animes']}</b>\n📺 Qism: <b>{s['episodes']}</b>\n👁 Ko'rishlar: <b>{s['views']}</b>\n\n"
        f"🏆 Top 5:\n{t}")


@panel.message(F.text == B_BACKUP, Perm("backup"))
async def backup(m: Message, state: FSMContext):
    await state.clear()
    js = json.dumps(await db.dump(), default=str, ensure_ascii=False, indent=1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backup.json", js)
    name = f"yumora_backup_{dt.date.today()}.zip"
    await m.answer_document(BufferedInputFile(buf.getvalue(), filename=name), caption="💾 Baza zaxira (JSON, ZIP)")


# ═══ 👑 ADMINLAR (faqat asosiy admin) ══════════════════════════
async def admins_view() -> tuple[str, Kb]:
    rows = []
    lines = []
    for uid, perms in sorted(store.db_admins.items()):
        lines.append(f"🛡 <code>{uid}</code> — {len(perms)} ta huquq")
        rows.append([Btn(text=f"⚙️ {uid} • {len(perms)} huquq", callback_data=f"adm:e:{uid}")])
    rows.append([Btn(text="➕ Admin qo'shish", callback_data="adm:new")])
    text = "👑 <b>Adminlar</b>\n\n" + ("\n".join(lines) or "Hozircha qo'shimcha admin yo'q.")
    return text, Kb(inline_keyboard=rows)


def perm_kb(uid: int) -> Kb:
    have = store.db_admins.get(uid, set())
    rows = [[Btn(text=("✅ " if k in have else "⬜ ") + label, callback_data=f"adm:t:{uid}:{k}")]
            for k, label in PERMS]
    rows.append([Btn(text="✅ Hammasini berish", callback_data=f"adm:all:{uid}"),
                 Btn(text="🧹 Tozalash", callback_data=f"adm:none:{uid}")])
    rows.append([Btn(text="🗑 Adminlikdan olish", callback_data=f"adm:del:{uid}"),
                 Btn(text="◀️ Orqaga", callback_data="adm:list")])
    return Kb(inline_keyboard=rows)


def perm_text(uid: int) -> str:
    return (f"🛡 <b>Admin</b> <code>{uid}</code>\n\n"
            "Nimalarni qila olishini belgilang (bosib yoqing/o'chiring).\n"
            "O'zgarish darhol kuchga kiradi.")


@panel.message(F.text == B_ADMINS, Perm("owner"))
async def admins_entry(m: Message, state: FSMContext):
    await state.clear()
    text, kb = await admins_view()
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:list", Perm("owner"))
async def adm_list(c: CallbackQuery):
    await c.answer()
    text, kb = await admins_view()
    await c.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "adm:new", Perm("owner"))
async def adm_new(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(NewAdmin.id)
    await c.message.answer("🆔 Yangi adminning <b>Telegram ID</b> sini yozing (faqat raqam).\n"
                           "<i>ID ni @userinfobot orqali bilish mumkin.</i>", reply_markup=flow_kb())


@router.message(NewAdmin.id, F.text, Perm("owner"))
async def adm_new_id(m: Message, state: FSMContext, bot: Bot):
    t = m.text.strip()
    if not t.isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    uid = int(t)
    if uid in config.ADMIN_IDS:
        return await m.answer("👑 Bu asosiy admin — unga hamma huquq berilgan. Boshqa ID yozing:")
    if uid not in store.db_admins:
        await db.set_admin_perms(uid, [])
        store.db_admins[uid] = set()
    await state.clear()
    await m.answer(f"✅ Admin qo'shildi: <code>{uid}</code>", reply_markup=admin_kb(m.from_user.id))
    await m.answer(perm_text(uid), reply_markup=perm_kb(uid))
    try:
        await bot.send_message(uid, "🎉 Siz admin etib tayinlandingiz! Panelni ochish: /admin")
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("adm:e:"), Perm("owner"))
async def adm_edit(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    await c.answer()
    await c.message.edit_text(perm_text(uid), reply_markup=perm_kb(uid))


async def _save_perms(uid: int, perms: set[str]) -> None:
    store.db_admins[uid] = perms
    await db.set_admin_perms(uid, sorted(perms))


@router.callback_query(F.data.startswith("adm:t:"), Perm("owner"))
async def adm_toggle(c: CallbackQuery):
    _, _, uid, key = c.data.split(":")
    uid = int(uid)
    if key not in PERM_LABEL or uid not in store.db_admins:
        return await c.answer()
    perms = set(store.db_admins[uid])
    perms.symmetric_difference_update({key})
    await _save_perms(uid, perms)
    await c.answer(("✅ Berildi: " if key in perms else "⬜ Olindi: ") + PERM_LABEL[key])
    await c.message.edit_reply_markup(reply_markup=perm_kb(uid))


@router.callback_query(F.data.startswith(("adm:all:", "adm:none:")), Perm("owner"))
async def adm_all(c: CallbackQuery):
    _, mode, uid = c.data.split(":")
    uid = int(uid)
    if uid not in store.db_admins:
        return await c.answer()
    await _save_perms(uid, set(PERM_LABEL) if mode == "all" else set())
    await c.answer("✅ Saqlandi")
    await c.message.edit_reply_markup(reply_markup=perm_kb(uid))


@router.callback_query(F.data.startswith("adm:del:"), Perm("owner"))
async def adm_del(c: CallbackQuery):
    uid = int(c.data.split(":")[2])
    await db.del_admin(uid)
    store.db_admins.pop(uid, None)
    await c.answer("🗑 Adminlikdan olindi")
    text, kb = await admins_view()
    await c.message.edit_text(text, reply_markup=kb)


# ═══ 🆕 ANIME QO'SHISH ═════════════════════════════════════════
@router.message(AddAnime.code, F.text)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    if not CODE_RE.match(code):
        return await m.answer("❗ Faqat a-z, 0-9 va «-». Qayta yozing:")
    if await db.anime_by_code(code):
        return await m.answer("❗ Bu ID band. Boshqasini yozing:")
    await state.update_data(code=code)
    await state.set_state(AddAnime.title)
    await m.answer("🎬 <b>Anime nomi:</b>")


@router.message(AddAnime.title, F.text)
async def add_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:200])
    await state.set_state(AddAnime.genres)
    await m.answer("🎭 <b>Janr(lar)</b> — vergul bilan yozing:\n"
                   "<i>Action, Romance, Comedy, Fantasy, Drama, Horror, Slice of Life, Sci-Fi, Sports, "
                   "Mystery, Supernatural, Mecha</i>")


@router.message(AddAnime.genres, F.text)
async def add_genres(m: Message, state: FSMContext):
    g = parse_genres(m.text)
    if not g:
        return await m.answer("❗ Kamida bitta janr yozing:")
    await state.update_data(genres=g)
    await state.set_state(AddAnime.media)
    await m.answer("🖼 <b>Poster (rasm)</b> yoki 🎥 <b>treyler (video)</b> yuboring.\n"
                   "Ikkalasidan kamida bittasi shart; xohlasangiz ikkalasini ham yuboring, so'ng «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await m.answer("✅ Poster qabul qilindi! Treyler ham yuborishingiz mumkin yoki «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.video)
async def add_trailer(m: Message, state: FSMContext):
    await state.update_data(trailer=m.video.file_id)
    await m.answer("✅ Treyler qabul qilindi! Poster ham yuborishingiz mumkin yoki «✅ Tayyor».",
                   reply_markup=flow_kb(True))


@router.message(AddAnime.media, F.text == B_DONE)
async def add_finish(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if not (d.get("poster") or d.get("trailer")):
        return await m.answer("❗ Poster yoki treyler — kamida bittasi kerak. Rasm yoki video yuboring.")
    try:
        aid = await db.add_anime(d["code"], d["title"], d["genres"], d.get("poster"), d.get("trailer"))
    except Exception as e:  # noqa: BLE001
        await state.clear()
        return await m.answer(f"❗ Xato: {esc(e)}", reply_markup=admin_kb(m.from_user.id))
    store.invalidate_anime()
    if d.get("poster"):
        fire(thumbs.thumb_for_anime(bot, aid, d["poster"]))  # inline uchun rasm URL (fonda)
    note = ""
    if not d.get("poster") and not await store.default_poster():
        note = ("\n\n⚠️ Poster yo'q va standart poster ham o'rnatilmagan — qidiruvda rasm chiqmaydi. "
                "«🖼 Standart poster» orqali rasm yuklang.")
    await state.clear()
    await m.answer(f"🎉 <b>{esc(d['title'])}</b> qo'shildi!{note}", reply_markup=admin_kb(m.from_user.id))
    await start_upload(m, state, aid, new=True)


# ═══ 🆔 ID BO'YICHA TANLASH (qism qo'shish / boshqaruv) ════════
async def ask_id(m: Message, state: FSMContext, action: str):
    await state.clear()
    await state.set_state(Pick.q)
    await state.update_data(action=action)
    await m.answer("🆔 <b>Anime ID</b> sini yozing:\n<i>Masalan: <code>naruto-1</code></i>", reply_markup=flow_kb())


@router.message(Pick.q, F.text)
async def pick_id(m: Message, state: FSMContext):
    code = m.text.strip().lower()
    a = await db.anime_by_code(code) if CODE_RE.match(code) else None
    if not a:
        return await m.answer("🤷 Bunday ID yo'q. Qayta yozing yoki «❌ Bekor qilish».")
    act = (await state.get_data()).get("action", "manage")
    if act == "eps":
        return await start_upload(m, state, a["id"])
    await state.clear()
    await m.answer("🛠 Anime boshqaruv", reply_markup=admin_kb(m.from_user.id))
    await show_manage(m, a["id"])


# ═══ 🎞 QISMLARNI AVTOMATIK QO'SHISH ═══════════════════════════
async def start_upload(m: Message, state: FSMContext, aid: int, new: bool = False):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("❗ Anime topilmadi")
    last = await db.max_episode(aid)
    await state.clear()
    await state.set_state(AddEps.up)
    await state.update_data(aid=aid, last=0, cnt=0, new=new)
    await m.answer(
        f"🎞 <b>{esc(a['title'])}</b>  🆔 <code>{a['code']}</code>\nHozir <b>{last}</b> ta qism bor.\n\n"
        f"📥 Videolarni ketma-ket yuboring — qismlar <b>avtomatik {last + 1}-dan</b> raqamlanadi.\n"
        "✏️ Boshqa raqam kerak bo'lsa, sarlavhaga yozing (masalan «12» yoki «12-qism»).\n"
        "Tugagach «✅ Tayyor» ni bosing.", reply_markup=flow_kb(True))


_locks: dict[int, asyncio.Lock] = {}


@router.message(AddEps.up, F.video)
async def ep_video(m: Message, state: FSMContext):
    lock = _locks.setdefault(m.from_user.id, asyncio.Lock())
    async with lock:  # ketma-ket kelgan videolar raqamlari to'qnashmasligi uchun
        d = await state.get_data()
        n = parse_ep(m.caption) or max(d.get("last", 0), await db.max_episode(d["aid"])) + 1
        await db.set_episode(d["aid"], n, m.video.file_id)
        await state.update_data(last=n, cnt=d.get("cnt", 0) + 1)
    await m.reply(f"✅ {n}-qism saqlandi")


@router.message(AddEps.up, F.document)
async def ep_doc(m: Message):
    await m.answer("❗ Fayl emas, «video» sifatida yuboring.")


@router.message(AddEps.up, F.text == B_DONE)
async def ep_done(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    store.invalidate_anime()
    await m.answer(f"🎉 Tayyor! <b>{d.get('cnt', 0)}</b> ta qism qo'shildi.", reply_markup=admin_kb(m.from_user.id))
    if d.get("new") and await store.news_channels():
        await m.answer("📣 News kanalga e'lon qilaymi?", reply_markup=Kb(inline_keyboard=[[
            Btn(text="📣 E'lon qilish", callback_data=f"nw:{d['aid']}"), Btn(text="❌ Yo'q", callback_data="ad:no")]]))


# ═══ 🛠 ANIME BOSHQARUV (ID bo'yicha) ══════════════════════════
async def show_manage(m: Message, aid: int):
    a = await db.anime_by_id(aid)
    if not a:
        return await m.answer("❗ Topilmadi")
    n = await db.max_episode(aid)
    avg = a["rating_sum"] / a["rating_count"] if a["rating_count"] else 0
    text = (f"🎬 <b>{esc(a['title'])}</b>\n🆔 <code>{a['code']}</code>\n🎭 {esc(', '.join(a['genres']) or '—')}\n"
            f"📺 Oxirgi qism: {n}  •  👁 {a['views']}  •  ⭐ {avg:.1f} ({a['rating_count']})\n"
            f"🖼 Poster: {'✅' if a['poster_file_id'] else '❌'}  •  🎥 Treyler: {'✅' if a['trailer_file_id'] else '❌'}")
    rows = [
        [Btn(text="✏️ Nom", callback_data=f"am:{aid}:title"), Btn(text="🎭 Janr", callback_data=f"am:{aid}:genres")],
        [Btn(text="🖼 Poster", callback_data=f"am:{aid}:poster_file_id"),
         Btn(text="🎥 Treyler", callback_data=f"am:{aid}:trailer_file_id")],
        [Btn(text="🎞 Qism qo'shish", callback_data=f"am:{aid}:eps"),
         Btn(text="🗑 Qism o'chirish", callback_data=f"am:{aid}:delep")],
        [Btn(text="👁 Ko'rish (yuborish)", callback_data=f"am:{aid}:show"),
         Btn(text="📣 News e'lon", callback_data=f"nw:{aid}")],
        [Btn(text="🗑 Animeni o'chirish", callback_data=f"am:{aid}:del")],
    ]
    await m.answer(text, reply_markup=Kb(inline_keyboard=rows))


PROMPTS = {
    "title": "✏️ Yangi <b>nom</b>ni yozing:",
    "genres": "🎭 Yangi <b>janr</b>larni vergul bilan yozing:",
    "poster_file_id": "🖼 Yangi <b>poster</b> rasmini yuboring:",
    "trailer_file_id": "🎥 Yangi <b>treyler</b> videosini yuboring:",
}


@router.callback_query(F.data.startswith("am:"), Perm("manage"))
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
        return await c.message.answer("🗑 O'chiriladigan <b>qism raqami</b>ni yozing:", reply_markup=flow_kb())
    if act == "show":
        a = await db.anime_by_id(aid)
        if a:
            await send_card(bot, c.message.chat.id, a, c.from_user.id)
        return
    if act == "del":
        a = await db.anime_by_id(aid)
        return await c.message.answer(
            f"⚠️ Rostdan <b>{esc(a['title'] if a else aid)}</b> va barcha qismlarini o'chirasizmi?",
            reply_markup=Kb(inline_keyboard=[[Btn(text="✅ Ha, o'chir", callback_data=f"ad:dely:{aid}"),
                                              Btn(text="❌ Yo'q", callback_data="ad:no")]]))


@router.message(EditF.v)
async def edit_value(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    f, aid = d["field"], d["aid"]
    if f == "title" and m.text:
        val = m.text.strip()[:200]
    elif f == "genres" and m.text:
        val = parse_genres(m.text)
        if not val:
            return await m.answer("❗ Kamida bitta janr yozing:")
    elif f == "poster_file_id" and m.photo:
        val = m.photo[-1].file_id
    elif f == "trailer_file_id" and m.video:
        val = m.video.file_id
    else:
        return await m.answer("❗ Noto'g'ri turdagi xabar. " + PROMPTS[f])
    await db.update_anime(aid, f, val)
    if f == "poster_file_id":
        await db.update_anime(aid, "thumb_url", None)
        fire(thumbs.thumb_for_anime(bot, aid, val))
    store.invalidate_anime()
    await state.clear()
    await m.answer("✅ Yangilandi!", reply_markup=admin_kb(m.from_user.id))


@router.message(DelEp.n, F.text)
async def delep_value(m: Message, state: FSMContext):
    d = await state.get_data()
    if not m.text.strip().isdigit():
        return await m.answer("❗ Faqat raqam yozing:")
    ok = await db.delete_episode(d["aid"], int(m.text))
    store.invalidate_anime()
    await state.clear()
    await m.answer("✅ O'chirildi." if ok else "🤷 Bunday qism yo'q.", reply_markup=admin_kb(m.from_user.id))


@router.callback_query(F.data.startswith("ad:dely:"), Perm("manage"))
async def del_yes(c: CallbackQuery):
    await db.delete_anime(int(c.data.split(":")[2]))
    store.invalidate_anime()
    await c.answer("🗑 O'chirildi")
    await c.message.edit_text("✅ Anime o'chirildi.")


@router.callback_query(F.data == "ad:no")
async def no(c: CallbackQuery):
    await c.answer()
    try:
        await c.message.delete()
    except Exception:  # noqa: BLE001
        pass


@router.message(Command("delep"), Perm("manage"))
async def delep_cmd(m: Message):
    p = (m.text or "").split()
    if len(p) != 3 or not p[2].isdigit():
        return await m.answer("🗑 Foydalanish: /delep <code>ID qism</code>")
    a = await db.anime_by_code(p[1].lower())
    if not a:
        return await m.answer("🤷 Bunday ID yo'q")
    ok = await db.delete_episode(a["id"], int(p[2]))
    store.invalidate_anime()
    await m.answer("✅ O'chirildi" if ok else "🤷 Bunday qism yo'q")


# ═══ 📣 NEWS E'LON ═════════════════════════════════════════════
async def post_news(bot: Bot, aid: int) -> int:
    a = await db.anime_by_id(aid)
    chans = await store.news_channels()
    if not a or not chans:
        return 0
    eps = await store.episodes(aid)
    text = card_text(a, len(eps.numbers))
    markup = Kb(inline_keyboard=[[Btn(text="▶️ Tomosha qilish", url=kbd.start_link(a["code"]))]])
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


@router.callback_query(F.data.startswith("nw:"))
async def news_cb(c: CallbackQuery, bot: Bot):
    await c.answer()
    sent = await post_news(bot, int(c.data.split(":")[1]))
    await c.message.answer(f"📣 News kanalga yuborildi ✅" if sent else "❗ News kanal yo'q yoki yuborib bo'lmadi (📢 Kanallar).")


@panel.message(Command("thumbs"), Perm("poster"))
async def thumbs_cmd(m: Message, bot: Bot):
    if not config.IMGBB_API_KEY:
        return await m.answer("⚠️ <code>IMGBB_API_KEY</code> kiritilmagan. .env ga qo'shing (https://api.imgbb.com).")
    await m.answer("🖼 Inline rasmlar tayyorlanmoqda… Tugagach xabar beraman.")

    async def job():
        done, total = await thumbs.backfill(bot)
        await bot.send_message(m.chat.id, f"✅ Inline rasmlar tayyor: <b>{done}</b> / {total}")

    fire(job())


# ═══ 🖼 STANDART POSTER ════════════════════════════════════════
@router.message(SetPoster.wait, F.photo)
async def poster_set(m: Message, state: FSMContext, bot: Bot):
    fid = m.photo[-1].file_id
    url = await thumbs.make_thumb(bot, fid)
    await store.set_default_poster(fid, url)
    await state.clear()
    note = ""
    if not config.IMGBB_API_KEY:
        note = "\n\n⚠️ <code>IMGBB_API_KEY</code> kiritilmagan — inline qidiruvda rasm chiqmaydi."
    elif not url:
        note = "\n\n⚠️ Inline uchun rasm yuklanmadi (ImgBB). Keyinroq qayta urinib ko'ring."
    await m.answer(f"✅ Standart poster o'rnatildi!{note}", reply_markup=admin_kb(m.from_user.id))


# ═══ 📢 KANALLAR ═══════════════════════════════════════════════
async def chan_list() -> tuple[str, Kb]:
    rows = await db.channels()
    lines = []
    for c in rows:
        kind = "majburiy" if c["kind"] == "sub" else "news"
        scope = "" if c["anime_id"] is None else f" • anime #{c['anime_id']}"
        lines.append(f"{c['id']}. {esc(c['title'])} ({kind}{scope})")
    text = "📢 <b>Kanallar</b>\n\n" + ("\n".join(lines) or "Hozircha yo'q")
    kb_rows = [[Btn(text=f"🗑 {c['id']}. {c['title']}"[:50], callback_data=f"ad:chdel:{c['id']}")] for c in rows]
    kb_rows.append([Btn(text="➕ Majburiy kanal", callback_data="ad:chadd:sub"),
                    Btn(text="➕ News kanal", callback_data="ad:chadd:news")])
    return text, Kb(inline_keyboard=kb_rows)


@router.callback_query(F.data.startswith("ad:chadd:"), Perm("chans"))
async def chan_add_start(c: CallbackQuery, state: FSMContext):
    await c.answer()
    await state.clear()
    await state.set_state(AddChan.wait)
    await state.update_data(kind=c.data.split(":")[2])
    await c.message.answer(
        "📢 Kanalni yuboring (bot kanalda <b>ADMIN</b> bo'lishi shart):\n\n"
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
            return await m.answer("🤷 Bunday anime ID yo'q. Qayta yuboring yoki «❌ Bekor qilish».")
        anime_id = a["id"]
    try:
        chat = await bot.get_chat(parts[0] if parts[0].startswith("@") else int(parts[0]))
        url = parts[1] if len(parts) > 1 else (f"https://t.me/{chat.username}" if chat.username else None)
        if not url:
            return await m.answer("❗ Yopiq kanal uchun invite link ham yozing.")
    except Exception as e:  # noqa: BLE001
        return await m.answer(f"❗ Topilmadi: {esc(e)}\nQayta yuboring yoki «❌ Bekor qilish».")
    kind = (await state.get_data()).get("kind", "sub")
    await db.add_channel(chat.id, url, chat.title or str(chat.id), anime_id, kind)
    store.invalidate_channels()
    await state.clear()
    await m.answer(f"✅ Qo'shildi: {esc(chat.title or '')}", reply_markup=admin_kb(m.from_user.id))


@router.callback_query(F.data.startswith("ad:chdel:"), Perm("chans"))
async def chan_del(c: CallbackQuery):
    await db.delete_channel(int(c.data.split(":")[2]))
    store.invalidate_channels()
    await c.answer("🗑 O'chirildi")
    text, kb = await chan_list()
    await c.message.edit_text(text, reply_markup=kb)


# ═══ 📣 XABAR YUBORISH ═════════════════════════════════════════
@router.message(Cast.wait)
async def cast_got(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✅ Xabar qabul qilindi.", reply_markup=admin_kb(m.from_user.id))
    await m.reply("📣 Shu xabarni hamma foydalanuvchiga yuboraymi?", reply_markup=Kb(inline_keyboard=[[
        Btn(text="✅ Yuborish", callback_data=f"ad:castgo:{m.chat.id}:{m.message_id}"),
        Btn(text="❌ Yo'q", callback_data="ad:no")]]))


@router.callback_query(F.data.startswith("ad:castgo:"), Perm("cast"))
async def cast_go(c: CallbackQuery, bot: Bot):
    _, _, chat, mid = c.data.split(":")
    await c.answer("🚀 Boshlandi")
    await c.message.delete()
    asyncio.create_task(broadcast.run(bot, c.message.chat.id, int(chat), int(mid)))


@router.message(Command("stopcast"), Perm("cast"))
async def stopcast(m: Message):
    broadcast.state["stop"] = True
    await m.answer("⏹ To'xtatilmoqda…")


# ═══ kanalga tashlab yuklash: caption "id:kod" va "qism:N" ═════
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


# ═══ 🚫 BAN ════════════════════════════════════════════════════
def _arg_id(m: Message):
    p = (m.text or "").split()
    return int(p[1]) if len(p) > 1 and p[1].lstrip("-").isdigit() else None


@router.message(Command("ban"), Perm("ban"))
async def ban(m: Message):
    uid = _arg_id(m)
    if uid is None or store.is_admin(uid):
        return await m.answer("🚫 Foydalanish: /ban <code>user_id</code>")
    await db.set_banned(uid, True)
    store.banned.add(uid)
    await m.answer(f"🚫 {uid} bloklandi")


@router.message(Command("unban"), Perm("ban"))
async def unban(m: Message):
    uid = _arg_id(m)
    if uid is None:
        return await m.answer("✅ Foydalanish: /unban <code>user_id</code>")
    await db.set_banned(uid, False)
    store.banned.discard(uid)
    await m.answer(f"✅ {uid} blokdan chiqdi")