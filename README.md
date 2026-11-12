# Anime bot (oddiy, 200k user uchun)

aiogram 3 + PostgreSQL (asyncpg). Teg, mood, reyting, tavsif, yil, status — YO'Q.
Faqat: nom, kod, poster (ixtiyoriy), qismlar.

## Ishga tushirish
1. `cp .env.example .env` va to'ldiring (BOT_TOKEN, DATABASE_URL, ADMIN_IDS)
2. `pip install -r requirements.txt`
3. `python main.py` (Railway: start command shu, jadvallar o'zi yaratiladi)

## Foydalanuvchi
- Anime nomini yozadi / kodini yozadi / `t.me/bot?start=kod` / `kod_5` (5-qismdan)
- Inline: `@bot nom` (poster bilan chiqadi)
- Qism tugmalari 20 tadan sahifalanadi, qism almashganda xabar tahrirlanadi (yangi xabar yo'q)

## Admin (/admin)
- ➕ Anime: kod → nom → poster → darhol videolarni ketma-ket tashlang (/done)
- 🎞 Qismlar: mavjud animega qism qo'shish (sarlavhada raqam bo'lsa shu raqam)
- /delep kod qism · 🗑 anime o'chirish
- 📢 Kanallar: hamma anime uchun yoki bitta anime uchun (2-qatorga kod)
- 📣 Xabar yuborish (matn/rasm/video), /stopcast
- /ban /unban, /addadmin /deladmin, 📊 statistika
- UPLOAD_CHANNEL_ID: kanalga video + caption `id:kod` `qism:5` tashlansa avtomat saqlanadi

## Nega qotmaydi
- Issiq yo'l (start → qism → qism almashtirish) bazaga murojaat qilmaydi: anime/qismlar TTL keshda
- Single-flight: kesh eskirganda 2000 ta parallel so'rovga 1 ta SQL
- Ko'rishlar va "oxirgi faollik" xotirada yig'ilib, 15 soniyada bitta UPDATE bilan yoziladi
- User/ban/admin tekshiruvi xotiradagi set (200k user startda 0.1s da yuklanadi)
- Obuna tekshiruvi: natija 10 daqiqa keshlanadi, timeout 4s, xatoda user to'silmaydi
- Antispam: user boshiga 0.6s, flood-wait bo'lsa avtomatik kutib qayta uradi
- Broadcast: 25 xabar/s (Telegram chegarasi ~30), bloklaganlar avtomatik belgilanadi
  (200k user ≈ 2.2 soat, fonda ishlaydi, bot javob berishda davom etadi)
- Qidiruv: pg_trgm indeks

## Cheklov
Bitta jarayon (polling). Bir vaqtda 1000+ so'rov/s bo'lsa — webhook + kuchliroq server kerak.
