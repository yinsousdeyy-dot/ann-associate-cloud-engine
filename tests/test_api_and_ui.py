import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.db import DatabaseAdapter
from app.main import app, db, settings, tg


class TestApiAndUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(cls.tmpdir.name) / 'test_api_firm.db'}"
        os.environ["GOOGLE_DRIVE_ENABLED"] = "false"
        os.environ["DEMO_TOOLS_ENABLED"] = "true"
        os.environ["QR_MAX_BACKDATE_HOURS"] = "72"
        os.environ["WEBHOOK_SHARED_SECRET"] = "test-firm-secret-12345"
        os.environ["DASHBOARD_ACCESS_TOKEN"] = "test-dashboard-token-12345"
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-tg-secret-12345"

        cls.settings = load_settings()
        cls.db = DatabaseAdapter(cls.settings)
        cls.db.init_schema_and_seed_rbac()

        import app.main as main_module
        main_module.settings = cls.settings
        main_module.db = cls.db
        main_module.tg = tg
        tg.db = cls.db
        tg.settings = cls.settings

        cls.client = TestClient(app)
        cls.dash = {"X-Firm-Secret": cls.settings.dashboard_access_token}
        cls.hook = {"X-Firm-Secret": cls.settings.webhook_shared_secret}
        cls.scan_day = (datetime.now(cls.settings.tz) - timedelta(days=1)).strftime("%Y-%m-%d")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("DEMO_TOOLS_ENABLED", None)
        os.environ.pop("QR_MAX_BACKDATE_HOURS", None)
        cls.tmpdir.cleanup()

    def test_01_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("organization", data)
        self.assertIn("timestamp", data)

    def test_02_root_redirect(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/dashboard", resp.headers["location"])

    def test_03_dashboard_authentication(self):
        browser = TestClient(app)

        # No credential -> 403 sign-in page
        resp_no_token = browser.get("/dashboard")
        self.assertEqual(resp_no_token.status_code, 403)
        self.assertIn("Access token", resp_no_token.text)

        # Tokens in the URL are no longer accepted
        resp_url = browser.get(f"/dashboard?token={self.settings.dashboard_access_token}")
        self.assertEqual(resp_url.status_code, 403)

        # Wrong token on the form -> 403 and no session
        bad = browser.post("/dashboard/login", data={"token": "wrong"}, follow_redirects=False)
        self.assertEqual(bad.status_code, 403)
        self.assertNotIn("firm_session", bad.headers.get("set-cookie", ""))

        # Right token -> 303 with an HttpOnly session cookie, then the dashboard loads
        good = browser.post(
            "/dashboard/login", data={"token": self.settings.dashboard_access_token}, follow_redirects=False
        )
        self.assertEqual(good.status_code, 303)
        cookie = good.headers["set-cookie"].lower()
        self.assertIn("firm_session=", cookie)
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)

        resp_auth = browser.get("/dashboard")
        self.assertEqual(resp_auth.status_code, 200)
        self.assertIn("Operations hub", resp_auth.text)
        self.assertIn("Record a scan", resp_auth.text)
        self.assertIn("default-src 'self'", resp_auth.headers["content-security-policy"])

        # A session cookie alone cannot call a mutating endpoint; it also needs the CSRF header
        no_csrf = browser.post("/api/v1/simulate/telegram", json={"chat_id": "111111111", "command": "/start"})
        self.assertEqual(no_csrf.status_code, 403)
        with_csrf = browser.post(
            "/api/v1/simulate/telegram",
            json={"chat_id": "111111111", "command": "/start"},
            headers={"X-Firm-CSRF": "1"},
        )
        self.assertEqual(with_csrf.status_code, 200)

    def test_03b_protected_routes_reject_anonymous_requests(self):
        anon = TestClient(app)
        for path in (
            "/api/v1/data/overview",
            "/charts/survey_analytics_all.png",
            "/receipts/x.html",
            "/datasets/x.csv",
            "/backups/x.zip",
        ):
            self.assertEqual(anon.get(path).status_code, 403, path)
        for path in ("/api/v1/pipeline/run", "/api/v1/seed-sample-data"):
            self.assertEqual(anon.post(path).status_code, 401, path)
        self.assertEqual(anon.post("/api/v1/simulate/telegram", json={"chat_id": "1", "command": "/start"}).status_code, 403)
        self.assertEqual(anon.post("/webhooks/telegram", json={}).status_code, 401)

    def test_03c_path_traversal_is_rejected(self):
        for name in ("..%2Fsecret.zip", "a%5Cb.zip", "notes.txt"):
            resp = self.client.get(f"/backups/{name}", headers=self.dash)
            self.assertEqual(resp.status_code, 404, name)

    def test_04_seed_sample_data(self):
        resp = self.client.post(
            "/api/v1/seed-sample-data",
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "seeded")
        self.assertGreater(data["academy"]["ok"], 0)
        self.assertGreater(data["surveys"]["ok"], 0)
        self.assertGreater(data["ops"]["ok"], 0)

    def test_05_api_data_overview(self):
        resp = self.client.get("/api/v1/data/overview", headers=self.dash)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("kpi", data)
        self.assertGreater(data["kpi"]["invoice_count"], 0)
        self.assertGreater(data["kpi"]["survey_count"], 0)
        self.assertIn("invoices", data)
        self.assertIn("attendance", data)
        self.assertIn("surveys", data)

    def test_06_webhook_qr_scan_workflow(self):
        # 1. Unauthorized scan
        unauth_resp = self.client.post(
            "/webhooks/qr-scan",
            json={
                "employee_code": "EMP-001",
                "employee_name": "Test Associate",
                "role_type": "Employee",
                "department": "Corporate & Tax",
                "action": "CHECK_IN",
            },
            headers={"X-Firm-Secret": "wrong-secret"},
        )
        self.assertEqual(unauth_resp.status_code, 401)

        # 2. Check-in on time
        in_resp = self.client.post(
            "/webhooks/qr-scan",
            json={
                "employee_code": "EMP-TEST-99",
                "employee_name": "Senior Test Lawyer",
                "role_type": "Employee",
                "department": "Corporate & Tax",
                "action": "CHECK_IN",
                "scanned_at": f"{self.scan_day}T08:15:00+07:00",
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(in_resp.status_code, 200)
        self.assertEqual(in_resp.json()["status_flag"], "ON_TIME")

        # 3. Check-out
        out_resp = self.client.post(
            "/webhooks/qr-scan",
            json={
                "employee_code": "EMP-TEST-99",
                "employee_name": "Senior Test Lawyer",
                "role_type": "Employee",
                "department": "Corporate & Tax",
                "action": "CHECK_OUT",
                "scanned_at": f"{self.scan_day}T17:45:00+07:00",
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(out_resp.status_code, 200)
        self.assertGreater(out_resp.json()["hours_worked"], 9.0)

    def test_07_webhook_academy_and_receipt_generation(self):
        # Valid enrollment
        resp = self.client.post(
            "/webhooks/google-form/academy",
            json={
                "khmer_name": "លឹម គឹមស៊្រុន",
                "latin_name": "LIM KIMSROUN",
                "email": "kimsroun@firmtest.kh",
                "phone": "012 999 888",
                "course_title": "Legal AI Automation Masterclass",
                "payment_method": "ABA KHQR",
                "price_usd": 45.0,
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        receipt_no = data["record"]["receipt_no"]
        self.assertTrue(receipt_no.startswith("AA-"))
        receipt_path = Path(data["receipt_path"])
        self.assertTrue(receipt_path.exists())

        # Test viewing the receipt via GET /receipts/{name}
        r_resp = self.client.get(f"/receipts/{receipt_path.name}", headers=self.dash)
        self.assertEqual(r_resp.status_code, 200)
        self.assertIn("INVOICE", r_resp.text)
        self.assertIn("LIM KIMSROUN", r_resp.text)

        # Invalid enrollment -> Quarantined
        bad_resp = self.client.post(
            "/webhooks/google-form/academy",
            json={
                "khmer_name": "",
                "latin_name": "",
                "email": "not-valid-email",
                "phone": "123",
                "price_usd": -10.0,
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(bad_resp.status_code, 200)
        self.assertEqual(bad_resp.json()["status"], "quarantined")

    def test_08_webhook_surveys_and_low_rating_alert(self):
        resp = self.client.post(
            "/webhooks/google-form/surveys",
            json={
                "respondent_name": "Critical Client",
                "organization": "Cambodia Retail",
                "chamber": "EuroCham",
                "event_name": "Compliance Seminar 2026",
                "department": "Corporate & Tax",
                "rating": 2.0,
                "requested_topic": "Tax & Customs",
                "feedback": "Needs more written handouts.",
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["is_low_rating"])

    def test_09_webhook_client_ops_intake(self):
        resp = self.client.post(
            "/webhooks/google-form/ops",
            json={
                "client_name": "Phnom Penh Logistics Ltd",
                "email": "contact@pplogistics.kh",
                "phone": "077 123 456",
                "practice_area": "Corporate & Tax",
                "urgency": "High",
            },
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["record"]["phone_e164"], "+85577123456")

    def test_10_pipeline_run_and_bundle_download(self):
        resp = self.client.post(
            "/api/v1/pipeline/run",
            headers={"X-Firm-Secret": self.settings.webhook_shared_secret},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["backup_zip"].endswith(".zip"))

        # Test downloading the backup ZIP via GET /backups/{name}
        zip_resp = self.client.get(f"/backups/{data['backup_zip']}", headers=self.dash)
        self.assertEqual(zip_resp.status_code, 200)
        self.assertGreater(len(zip_resp.content), 1000)

    def test_11_telegram_simulator(self):
        # 1. Executive /start
        resp = self.client.post(
            "/api/v1/simulate/telegram",
            headers=self.dash,
            json={"chat_id": "111111111", "command": "/start"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["authorized"])
        self.assertIn("Welcome Bong Philen", data["message"])
        self.assertIsNotNone(data["reply_markup"])

        # 2. Executive /attendance
        att_resp = self.client.post(
            "/api/v1/simulate/telegram",
            headers=self.dash,
            json={"chat_id": "111111111", "command": "/attendance"},
        )
        self.assertEqual(att_resp.status_code, 200)
        self.assertIn("Live QR Work-Hour Report", att_resp.json()["message"])

        # 3. Supervisor trying /zip -> restricted!
        sup_zip = self.client.post(
            "/api/v1/simulate/telegram",
            headers=self.dash,
            json={"chat_id": "222222222", "command": "/zip"},
        )
        self.assertEqual(sup_zip.status_code, 200)
        self.assertIn("Access restricted", sup_zip.json()["message"])

        # 4. Unknown user -> access denied
        unauth_tg = self.client.post(
            "/api/v1/simulate/telegram",
            headers=self.dash,
            json={"chat_id": "999999999", "command": "/start"},
        )
        self.assertEqual(unauth_tg.status_code, 200)
        self.assertFalse(unauth_tg.json()["authorized"])

    def test_12_charts_serving(self):
        resp = self.client.get("/charts/survey_analytics_all.png", headers=self.dash)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/png")
        self.assertGreater(len(resp.content), 5000)


if __name__ == "__main__":
    unittest.main()
