# Yumora TV bot

aiogram 3 + PostgreSQL (asyncpg). Rangli emoji dizayn.

## Ishga tushirish
1. `cp .env.example .env` → BOT_TOKEN, DATABASE_URL, ADMIN_IDS (asosiy adminlar)
2. `pip install -r requirements.txt`
3. `python main.py` (jadvallar o'zi yaratiladi / eski baza o'zi yangilanadi)

## Foydalanuvchi
- /start: salom + rasm + konfetti effekti, 🔎 Janr bo'yicha qidirish, 🔥 Eng mashhur, 🔍 Nom bo'yicha (inline), 💡 Yordam
- Kartochka: janr, ⭐ reyting, 📺 qismlar, ▶️ 1-qismdan tomosha, 📋 Qismlar ro'yxati, 📤 Ulashish, ⭐ Baho berish
- Qism bosilsa video PASTDAN yangi xabar bo'lib keladi, oldingi video joyida qoladi
- Havola: `t.me/bot?start=ID` (kartochka), `ID_5` (5-qismdan)
- Inline (`@bot ...`): poster-miniatyurali ro'yxat (sarlavha + ⭐ reyting, 📺 qism, 🎭 janr). Tanlansa bot havolani o'chirib, to'liq kartani chiqaradi.
  Poster-miniatyuralar uchun `.env` ga `IMGBB_API_KEY` kerak (https://api.imgbb.com, bepul). Eski animelar uchun bir marta `/thumbs`.

## Admin (/admin) — hammasi ID orqali
- 🆕 Anime qo'shish: ID → nom → janr → poster YOKI treyler → videolarni tashlang (qism raqami avtomatik)
- 🎞 Qism qo'shish: anime ID → videolarni tashlang
- 🛠 Anime boshqaruv: anime ID → ✏️ nom, 🎭 janr, 🖼 poster, 🎥 treyler, 🎞 qism qo'shish, 🗑 qism o'chirish,
  👁 ko'rish (yuborish), 📣 news e'lon, 🗑 animeni o'chirish. Tezkor: `/anime ID`
- 👑 Adminlar (faqat asosiy admin): admin Telegram ID si → huquqlarni bosib belgilash (✅/⬜):
  anime qo'shish, qism qo'shish, boshqaruv, kanallar, xabar yuborish, statistika, zaxira, standart poster, ban.
  Admin faqat o'ziga berilgan tugmalarni ko'radi; o'zgarish darhol kuchga kiradi.
- 📢 Kanallar, 🖼 Standart poster, 📣 Xabar yuborish, 📊 Statistika, 💾 Baza zaxira
- Har bir jarayonda ❌ Bekor qilish