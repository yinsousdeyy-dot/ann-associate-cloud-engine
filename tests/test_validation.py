import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.config import load_settings
from app.db import DatabaseAdapter
from app.services.ingestion import (
    ingest_academy_record,
    ingest_ops_record,
    ingest_qr_work_hour_scan,
    ingest_survey_record,
)


class TestValidationEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(self.tmpdir.name) / 'validation.db'}"
        os.environ["GOOGLE_DRIVE_ENABLED"] = "false"
        os.environ["ARTIFACTS_DIR"] = str(Path(self.tmpdir.name) / "artifacts")
        os.environ["QR_MAX_BACKDATE_HOURS"] = "24"
        for key in ("DATABASE_URL", "GOOGLE_DRIVE_ENABLED", "ARTIFACTS_DIR", "QR_MAX_BACKDATE_HOURS"):
            self.addCleanup(os.environ.pop, key, None)
        self.settings = load_settings()
        self.db = DatabaseAdapter(self.settings)
        self.db.init_schema_and_seed_rbac()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _count(self, table: str) -> int:
        with self.db.connection() as conn:
            return self.db.fetch_one(conn, f"SELECT COUNT(*) AS cnt FROM {table}")["cnt"]

    def _scan(self, action: str, when: datetime, code: str = "EMP-900") -> dict:
        return ingest_qr_work_hour_scan(
            self.db,
            self.settings,
            {
                "employee_code": code,
                "employee_name": "Edge Case",
                "role_type": "Employee",
                "department": "Corporate & Tax",
                "action": action,
                "scanned_at": when.isoformat(),
            },
        )

    def _academy(self, **overrides) -> dict:
        raw = {
            "khmer_name": "សុខា",
            "latin_name": "Sokha Dara",
            "email": "sokha@example.kh",
            "phone": "012 345 678",
            "course_title": "Compliance Talks 2026",
            "payment_method": "ABA KHQR",
            "price_usd": 45,
        }
        raw.update(overrides)
        return ingest_academy_record(self.db, self.settings, raw)

    # --- QR scans -------------------------------------------------------------------------------

    def test_scan_in_the_future_is_quarantined(self):
        now = datetime.now(self.settings.tz)
        res = self._scan("CHECK_IN", now + timedelta(hours=2))
        self.assertEqual(res["status"], "quarantined")
        self.assertIn("future", res["reason"])
        self.assertEqual(self._count("employee_work_hours"), 0)

    def test_scan_older_than_backdate_window_is_quarantined(self):
        res = self._scan("CHECK_IN", datetime.now(self.settings.tz) - timedelta(hours=30))
        self.assertEqual(res["status"], "quarantined")
        self.assertIn("old", res["reason"])

    def test_scan_with_unparseable_timestamp_is_quarantined(self):
        res = ingest_qr_work_hour_scan(
            self.db,
            self.settings,
            {"employee_code": "EMP-1", "employee_name": "X", "action": "CHECK_IN", "scanned_at": "yesterday-ish"},
        )
        self.assertEqual(res["status"], "quarantined")
        self.assertIn("ISO 8601", res["reason"])

    def test_scan_without_employee_identity_is_quarantined(self):
        res = ingest_qr_work_hour_scan(self.db, self.settings, {"employee_code": "", "employee_name": "", "action": "CHECK_IN"})
        self.assertEqual(res["status"], "quarantined")

    def test_checkout_without_checkin_is_quarantined(self):
        res = self._scan("CHECK_OUT", datetime.now(self.settings.tz) - timedelta(minutes=10))
        self.assertEqual(res["status"], "quarantined")
        self.assertIn("without a check-in", res["reason"])
        self.assertEqual(self._count("employee_work_hours"), 0)

    def test_second_checkout_for_the_same_shift_is_rejected(self):
        now = datetime.now(self.settings.tz)
        self.assertEqual(self._scan("CHECK_IN", now - timedelta(hours=3))["status"], "ok")
        first = self._scan("CHECK_OUT", now - timedelta(hours=1))
        self.assertEqual(first["status"], "ok")
        self.assertAlmostEqual(first["hours_worked"], 2.0, places=1)
        second = self._scan("CHECK_OUT", now - timedelta(minutes=5))
        self.assertEqual(second["status"], "quarantined")
        self.assertIn("Already checked out", second["reason"])

    def test_checkout_before_checkin_is_rejected(self):
        now = datetime.now(self.settings.tz)
        self.assertEqual(self._scan("CHECK_IN", now - timedelta(hours=1))["status"], "ok")
        res = self._scan("CHECK_OUT", now - timedelta(hours=2))
        self.assertEqual(res["status"], "quarantined")
        self.assertIn("earlier than the check-in", res["reason"])

    def test_repeated_checkin_does_not_move_the_original_time(self):
        now = datetime.now(self.settings.tz)
        first = self._scan("CHECK_IN", now - timedelta(hours=2))
        again = self._scan("CHECK_IN", now - timedelta(hours=1))
        self.assertEqual(again["status"], "ok")
        with self.db.connection() as conn:
            rows = self.db.fetch_all(conn, "SELECT check_in_at FROM employee_work_hours WHERE employee_code = %s", ("EMP-900",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["check_in_at"], first["timestamp"])

    def test_naive_timestamp_is_read_in_the_firm_timezone(self):
        now = datetime.now(self.settings.tz) - timedelta(hours=1)
        res = ingest_qr_work_hour_scan(
            self.db,
            self.settings,
            {
                "employee_code": "EMP-77",
                "employee_name": "Naive Clock",
                "action": "CHECK_IN",
                "scanned_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["timestamp"], now.strftime("%Y-%m-%d %H:%M:%S"))

    # --- Academy --------------------------------------------------------------------------------

    def test_academy_rejects_non_finite_negative_and_oversized_prices(self):
        for bad in (float("nan"), float("inf"), -1, 10000.01, "abc", None):
            res = self._academy(price_usd=bad, email=f"p{abs(hash(str(bad)))}@example.kh")
            self.assertEqual(res["status"], "quarantined", bad)
            self.assertIn("price_usd", res["reason"], bad)
        self.assertEqual(self._count("academy_invoices"), 0)

    def test_academy_accepts_a_free_course_and_the_price_ceiling(self):
        self.assertEqual(self._academy(price_usd=0, email="free@example.kh")["status"], "ok")
        self.assertEqual(self._academy(price_usd=10000, email="max@example.kh")["status"], "ok")

    def test_academy_duplicate_returns_the_original_invoice_unchanged(self):
        first = self._academy(price_usd=45)
        again = self._academy(price_usd=999)
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["record"]["receipt_no"], first["record"]["receipt_no"])
        self.assertEqual(again["record"]["total_usd"], 45.0)
        self.assertEqual(self._count("academy_invoices"), 1)

    def test_academy_email_is_case_insensitive_for_duplicates(self):
        self._academy(email="Mixed.Case@Example.KH")
        again = self._academy(email="mixed.case@example.kh")
        self.assertTrue(again["duplicate"])
        self.assertEqual(self._count("academy_invoices"), 1)

    def test_academy_accepts_google_form_capitalised_keys(self):
        res = ingest_academy_record(
            self.db,
            self.settings,
            {
                "Khmer_Name": "ចាន់",
                "Latin_Name": "chan",
                "Email": "chan@example.kh",
                "Phone": "+855 12 111 222",
                "Course_Title": "Compliance Talks 2026",
                "Payment_Method": "Wing Bank",
                "Price_USD": "30.50",
            },
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["record"]["latin_name"], "CHAN")
        self.assertEqual(res["record"]["total_usd"], 30.5)
        self.assertEqual(res["record"]["phone_e164"], "+85512111222")

    def test_receipt_escapes_markup_in_trainee_fields(self):
        res = self._academy(
            latin_name='<script>alert("x")</script>',
            course_title="<img src=x onerror=alert(1)>",
            email="xss@example.kh",
        )
        self.assertEqual(res["status"], "ok")
        html = Path(res["receipt_path"]).read_text(encoding="utf-8")
        self.assertNotIn("<SCRIPT>", html)
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x", html)

    def test_receipt_numbers_are_unique_and_sequential(self):
        numbers = [self._academy(email=f"n{i}@example.kh")["record"]["receipt_no"] for i in range(3)]
        self.assertEqual(len(set(numbers)), 3)
        self.assertEqual(numbers, sorted(numbers))

    # --- Surveys --------------------------------------------------------------------------------

    def _survey(self, **overrides) -> dict:
        raw = {"respondent_name": "Client A", "event_name": "Seminar", "rating": 4}
        raw.update(overrides)
        return ingest_survey_record(self.db, self.settings, raw)

    def test_survey_rating_bounds(self):
        for bad in (0, 0.99, 5.01, 6, -3, float("nan"), float("inf"), "five", None):
            res = self._survey(rating=bad, respondent_name=f"R{abs(hash(str(bad)))}")
            self.assertEqual(res["status"], "quarantined", bad)
        for good in (1, 1.0, 5, 5.0, "3.5"):
            res = self._survey(rating=good, respondent_name=f"G{good}")
            self.assertEqual(res["status"], "ok", good)

    def test_survey_replay_updates_instead_of_duplicating(self):
        self._survey(rating=2)
        again = self._survey(rating=5)
        self.assertEqual(again["status"], "ok")
        self.assertFalse(again["is_low_rating"])
        self.assertEqual(self._count("firm_surveys"), 1)
        with self.db.connection() as conn:
            self.assertEqual(float(self.db.fetch_one(conn, "SELECT rating FROM firm_surveys")["rating"]), 5.0)

    def test_survey_missing_respondent_is_quarantined(self):
        self.assertEqual(self._survey(respondent_name="  ")["status"], "quarantined")

    # --- Client intake --------------------------------------------------------------------------

    def test_ops_validation_and_replay(self):
        raw = {
            "client_name": "Mekong Foods",
            "email": "hello@mekong.kh",
            "phone": "077 123 456",
            "practice_area": "Labor & Employment",
            "urgency": "High",
        }
        self.assertEqual(ingest_ops_record(self.db, self.settings, raw)["status"], "ok")
        raw["urgency"] = "Urgent"
        self.assertEqual(ingest_ops_record(self.db, self.settings, raw)["status"], "ok")
        self.assertEqual(self._count("client_ops_intake"), 1)
        with self.db.connection() as conn:
            self.assertEqual(self.db.fetch_one(conn, "SELECT urgency FROM client_ops_intake")["urgency"], "Urgent")

        for patch in ({"email": "nope"}, {"phone": "12"}, {"client_name": ""}):
            bad = ingest_ops_record(self.db, self.settings, {**raw, **patch})
            self.assertEqual(bad["status"], "quarantined", patch)

    def test_identical_bad_payload_is_quarantined_once(self):
        for _ in range(3):
            self._academy(email="broken")
        self.assertEqual(self._count("quarantine_logs"), 1)


if __name__ == "__main__":
    unittest.main()
