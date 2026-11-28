"""Manage who can use the Telegram bot.

    python -m app.manage_users list
    python -m app.manage_users add --name "Bong Philen" --chat-id 123456789 --role executive
    python -m app.manage_users disable --chat-id 111111111 222222222

`add` creates the user or updates an existing one with the same chat id. Subscriptions default to
those of the first user with the same role in config/rbac_seed.json. Roles: executive and admin see
every department, supervisor sees one (--department). A person finds their chat id by messaging the
bot: the access-denied reply shows it.
"""
import argparse
import json
import re
import sys
from datetime import datetime

from app.config import load_settings
from app.db import DatabaseAdapter

ROLES = ("executive", "supervisor", "admin")
CHAT_ID = re.compile(r"^-?\d{5,20}$")


def _default_subscriptions(settings, role: str) -> list[str]:
    if not settings.rbac_seed_path.exists():
        return []
    seed = json.loads(settings.rbac_seed_path.read_text(encoding="utf-8-sig"))
    return next((u.get("subscriptions", []) for u in seed.get("users", []) if u["role"] == role), [])


def _flag(db: DatabaseAdapter, on: bool):
    return on if db.is_postgres else int(on)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage_users", description="Manage Telegram bot users.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show all users")
    add = sub.add_parser("add", help="add or update a user")
    add.add_argument("--name", required=True)
    add.add_argument("--chat-id", required=True)
    add.add_argument("--role", choices=ROLES, default="executive")
    add.add_argument("--department", default="ALL", help='"ALL" or one department, e.g. "Corporate & Tax"')
    off = sub.add_parser("disable", help="turn off one or more users")
    off.add_argument("--chat-id", nargs="+", required=True)
    args = parser.parse_args(argv)

    settings = load_settings()
    db = DatabaseAdapter(settings)
    db.init_schema_and_seed_rbac()
    now = datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")

    with db.connection() as conn:
        if args.cmd == "list":
            for r in db.fetch_all(conn, "SELECT * FROM telegram_users_rbac ORDER BY user_id"):
                state = "active" if r["is_active"] else "DISABLED"
                print(f"{r['telegram_chat_id']:>12}  {state:<8}  {r['role']:<10}  {r['department']:<16}  {r['full_name']}")
            return 0

        if args.cmd == "add":
            chat_id = args.chat_id.strip()
            if not CHAT_ID.match(chat_id):
                print(f"Invalid chat id {chat_id!r}: expected digits only, for example 1162163336.", file=sys.stderr)
                return 2
            if not args.name.strip():
                print("Name must not be empty.", file=sys.stderr)
                return 2
            db.execute(
                conn,
                """
                INSERT INTO telegram_users_rbac (
                    full_name, telegram_chat_id, role, department, subscriptions_json, is_active, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (telegram_chat_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role,
                    department = EXCLUDED.department,
                    subscriptions_json = EXCLUDED.subscriptions_json,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    args.name.strip(), chat_id, args.role, args.department.strip() or "ALL",
                    json.dumps(_default_subscriptions(settings, args.role)), _flag(db, True), now,
                ),
            )
            print(f"Saved {args.name.strip()} ({args.role}, {args.department}) as chat {chat_id}.")
            return 0

        missing = 0
        for chat_id in args.chat_id:
            cur = db.execute(
                conn,
                "UPDATE telegram_users_rbac SET is_active = %s, updated_at = %s WHERE telegram_chat_id = %s",
                (_flag(db, False), now, chat_id.strip()),
            )
            if cur.rowcount:
                print(f"Disabled {chat_id}.")
            else:
                print(f"No user with chat id {chat_id}.", file=sys.stderr)
                missing += 1
        return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
