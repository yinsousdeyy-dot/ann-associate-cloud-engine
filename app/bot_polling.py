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
                    parWams={"offset": offset, "timeout": 25},
                )
                data = resp.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    if "message" in upd and "text" in upd["message"]:
                        await tg.handle_command(str(upd["message"]["chat"]["id"]), upd["message"]["text"].strip().lower())
                    elif "callback_query" in upd:
                        cb = upd["callback_query"]
                        await client.post(
                            f"https://api.telegram.org/bot{settings.telegram_bot_token}/answerCallbackQuery",
                            json={"callback_query_id": cb["id"]},
                        )
                        await tg.handle_command(str(cb["message"]["chat"]["id"]), cb["data"])
            except Exception as exc:
                print(f"[WARN] Polling error (retrying in 5s): {exc}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
