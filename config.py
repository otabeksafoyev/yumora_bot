import os

from dotenv import load_dotenv

load_dotenv()


def _ints(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()}


BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_IDS = _ints(os.getenv("ADMIN_IDS", ""))
UPLOAD_CHANNEL_ID = int(os.getenv("UPLOAD_CHANNEL_ID", "0") or 0)
START_PHOTO = os.getenv("START_PHOTO", "").strip() or None
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "15") or 15)

# Telegram broadcast chegarasi ~30 xabar/soniya. 25 — xavfsiz qiymat.
BROADCAST_RATE = int(os.getenv("BROADCAST_RATE", "25") or 25)

# Inline qidiruvdagi poster-miniatyuralar uchun (https://api.imgbb.com — bepul kalit). Bo'sh bo'lsa rasm chiqmaydi.
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "").strip()
