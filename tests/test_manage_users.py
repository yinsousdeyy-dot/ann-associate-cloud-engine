import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_settings
from app.db import DatabaseAdapter
from app.manage_users import main
from app.services.telegram_service import TelegramRBACService


class TestManageUsers(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(self.tmpdir.name) / 'users.db'}"
        os.environ["ARTIFACTS_DIR"] = str(Path(self.tmpdir.name) / "artifacts")
        for key in ("DATABASE_URL", "ARTIFACTS_DIR"):
            self.addCleanup(os.environ.pop, key, None)
        # app.config loads .env on import; make sure tests never use the real bot token.
        self.addCleanup(os.environ.__setitem__, "TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        os.environ["TELEGRAM_BOT_TOKEN"] = ""
        self.addCleanup(self.tmpdir.cleanup)
        self.settings = load_settings()
        self.db = DatabaseAdapter(self.settings)
        self.db.init_schema_and_seed_rbac()
        self.tg = TelegramRBACService(self.db, self.settings)

    def test_add_update_and_disable(self):
        self.assertEqual(main(["add", "--name", "Test Exec", "--chat-id", "555000111", "--role", "executive"]), 0)
        user = self.tg.get_user("555000111")
        self.assertEqual((user["role"], user["department"]), ("executive", "ALL"))
        self.assertIn("invoices", user["subscriptions"])

        self.assertEqual(
            main(["add", "--name", "Test Sup", "--chat-id", "555000111", "--role", "supervisor", "--department", "Academy"]), 0
        )
        user = self.tg.get_user("555000111")
        self.assertEqual((user["full_name"], user["role"], user["department"]), ("Test Sup", "supervisor", "Academy"))

        self.assertEqual(main(["disable", "--chat-id", "555000111"]), 0)
        self.assertIsNone(self.tg.get_user("555000111"))

    def test_bad_input_is_rejected(self):
        self.assertEqual(main(["add", "--name", "X", "--chat-id", "not-a-number"]), 2)
        self.assertEqual(main(["add", "--name", "  ", "--chat-id", "555000222"]), 2)
        self.assertIsNone(self.tg.get_user("555000222"))
        self.assertEqual(main(["disable", "--chat-id", "999999999999"]), 1)

    def test_denied_reply_shows_the_chat_id(self):
        import asyncio

        res = asyncio.run(self.tg.handle_command("777888999", "/start"))
        self.assertFalse(res["authorized"])
        self.assertIn("777888999", res["message"])


if __name__ == "__main__":
    unittest.main()
