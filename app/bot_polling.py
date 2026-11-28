'''Run `python -m app.bot_polling` if hosting on a firm VPS without an HTTPS webhook domain.'''
import asyncio
import httpx

from app.config import load_settings
from app.db import DatabaseAdapter
from app.services.telegram_service import TelegramRBACService


async def main():
    settings = load_settings()
    db = DatabaseAdapter(settings)
    db.init_schema_and_seed_rbac()
    tg = TelegramRBACService(db, settings)
    if not tg.enabled:
        print("[ERROR] Configure TELEGRAM_BOT_TOKEN in .env first.")
        return

    print("[LIVE] Ann & Associates Cloud Telegram Bot (Polling Mode) listening...")
    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            try:
                resp = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates",
                    params={"offset": offset, "timeout": 25},
                )
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    if "message" in upd and "text" in upd["message"]:
                        chat_id = str(upd["message"]["chat"]["id"])
                        raw_text = upd["message"]["text"].strip()
                        cmd = raw_text.split("@")[0].lower() if raw_text.startswith("/") else raw_text.lower()
                        await tg.handle_command(chat_id, cmd)
                    elif "callback_query" in upd:
                        cb = upd["callback_query"]
                        cb_msg = cb.get("message") or {}
                        chat_id = str(cb_msg.get("chat", {}).get("id") or cb.get("from", {}).get("id"))
                        try:
                            await client.post(
                                f"https://api.telegram.org/bot{settings.telegram_bot_token}/answerCallbackQuery",
                                json={"callback_query_id": cb["id"]},
                            )
                        except Exception:
                            pass
                        await tg.handle_command(chat_id, cb.get("data", ""))
            except Exception as exc:
                print(f"[WARN] Polling error (retrying in 5s): {exc}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
