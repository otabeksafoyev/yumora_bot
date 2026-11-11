"""Ommaviy xabar: Telegram limiti (~30/s) ichida, flood-wait va bloklanganlarni hisobga olib."""
import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

import config
import db

log = logging.getLogger(__name__)
state = {"running": False, "stop": False}


async def _copy(bot: Bot, uid: int, from_chat: int, msg_id: int) -> str:
    for _ in range(3):
        try:
            await bot.copy_message(uid, from_chat, msg_id)
            return "ok"
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramForbiddenError:
            return "blocked"
        except TelegramBadRequest as e:
            return "blocked" if "chat not found" in str(e).lower() or "deactivated" in str(e).lower() else "failed"
        except Exception:  # noqa: BLE001
            return "failed"
    return "failed"


async def run(bot: Bot, admin_chat: int, from_chat: int, msg_id: int) -> None:
    if state["running"]:
        await bot.send_message(admin_chat, "⚠️ Boshqa xabar yuborilmoqda.")
        return
    state.update(running=True, stop=False)
    sent = blocked = failed = 0
    last, t_report = 0, time.monotonic()
    status = await bot.send_message(admin_chat, "📣 Yuborish boshlandi… (to'xtatish: /stopcast)")
    try:
        while not state["stop"]:
            ids = await db.user_ids_after(last, 1000)
            if not ids:
                break
            last = ids[-1]
            dead: list[int] = []
            for i in range(0, len(ids), config.BROADCAST_RATE):
                if state["stop"]:
                    break
                chunk = ids[i : i + config.BROADCAST_RATE]
                t0 = time.monotonic()
                res = await asyncio.gather(*(_copy(bot, u, from_chat, msg_id) for u in chunk))
                for u, r in zip(chunk, res):
                    if r == "ok":
                        sent += 1
                    elif r == "blocked":
                        blocked += 1
                        dead.append(u)
                    else:
                        failed += 1
                await asyncio.sleep(max(0.0, 1.0 - (time.monotonic() - t0)))
            if dead:
                await db.mark_blocked(dead)
            if time.monotonic() - t_report > 30:
                t_report = time.monotonic()
                try:
                    await status.edit_text(f"📣 Yuborildi: {sent} | bloklagan: {blocked} | xato: {failed}")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        state["running"] = False
    head = "⏹ To'xtatildi" if state["stop"] else "✅ Tugadi"
    await bot.send_message(admin_chat, f"{head}\n\nYetkazildi: {sent}\nBloklagan: {blocked}\nXato: {failed}")
