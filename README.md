# Yumora TV bot

aiogram 3 + PostgreSQL (asyncpg). Dizayn Kaworai uslubida (matn belgilari ᐅ ๏ ✧ ★ ⌂, emojisiz).

## Ishga tushirish
1. `cp .env.example .env` → BOT_TOKEN, DATABASE_URL, ADMIN_IDS
2. `pip install -r requirements.txt`
3. `python main.py` (jadvallar o'zi yaratiladi / eski baza o'zi yangilanadi)

## Foydalanuvchi
- /start: salom + rasm, ⌕ Janr bo'yicha qidirish, Barcha animelar, Eng mashhur, Nom bo'yicha qidirish (inline), Yordam
- Anime kartochkasi: treyler (yoki poster), janr, ★ reyting, qismlar soni, ᐅ 1-qismdan tomosha, ≡ Qismlar ro'yxati, ↗ Ulashish, ★ Baho berish
- Qism bosilsa video PASTDAN yangi xabar bo'lib keladi, oldingi video joyida qoladi
- Inline: `@bot nom` yoki `@bot janr` — poster bilan (poster yo'q bo'lsa admin qo'ygan standart rasm)
- Havola: `t.me/bot?start=kod` (kartochka), `kod_5` (5-qismdan)

## Admin (/admin) — pastdagi tugmalar, har bir jarayonda «✕ Bekor qilish»
- + Anime qo'shish: ID → nom → janr → poster YOKI treyler (kamida bittasi) → videolarni tashlang
- ⊙ Qism qo'shish: animeni tanlang, videolarni ketma-ket tashlang — raqam AVTOMATIK (sarlavhada «12» yoki «12-qism» bo'lsa shu raqam)
- ≡ Anime boshqaruv: nom, janr, poster, treyler, qism o'chirish, anime o'chirish, news e'lon
- ᐅ Kanallar: majburiy obuna (hamma yoki bitta anime uchun) va news kanallar
- ▣ Standart poster: posteri yo'q animelar uchun qidiruvdagi rasm (BIR MARTA yuklab qo'ying)
- ᐅ Xabar yuborish, ◈ Statistika, ≡ Baza zaxira (ZIP/JSON)
- /ban /unban /delep /addadmin /deladmin /stopcast
- UPLOAD_CHANNEL_ID: kanalga video + caption `id:kod qism:5` tashlansa avtomat saqlanadi

## 200k user uchun
Kesh + single-flight, ko'rishlar va faollik batch bilan yoziladi, user/ban xotirada, obuna natijasi keshlanadi,
antispam, flood-wait avtomatik, broadcast 25 xabar/s. Issiq yo'l bazaga murojaat qilmaydi.
