import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.config import load_settings
from app.db import DatabaseAdapter
from app.services.backups import create_verified_zip_bundle, export_clean_csv
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart
from app.services.ingestion import (
    ingest_csv_file,
    ingest_qr_work_hour_scan,
    ingest_survey_record,
    normalize_phone_kh,
)
from app.services.telegram_service import TelegramRBACService


class TestAnnAssociatesCloudEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(self.tmpdir.name) / 'test_firm.db'}"
        self.settings = load_settings()
        self.db = DatabaseAdapter(self.settings)
        self.db.init_schema_and_seed_rbac()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_phone_e164_normalization(self):
        self.assertEqual(normalize_phone_kh("012 345 678"), "+85512345678")
        self.assertEqual(normalize_phone_kh("855719834433"), "+855719834433")
        self.assertIsNone(normalize_phone_kh("1234"))

    def test_multi_category_ingestion_and_quarantine_idempotency(self):
        ac_res = ingest_csv_file(self.db, self.settings, "academy", self.settings.root_dir / "sample_data" / "academy_sample.csv")
        self.assertEqual(ac_res, {"ok": 2, "quarantined": 1})

        ingest_csv_file(self.db, self.settings, "academy", self.settings.root_dir / "sample_data" / "academy_sample.csv")
        with self.db.connection() as conn:
            q_cnt = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")["cnt"]
            inv_cnt = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM academy_invoices")["cnt"]
        self.assertEqual(q_cnt, 1)
        self.assertEqual(inv_cnt, 2)

    def test_qr_work_hour_scan_and_rbac_routing(self):
        in_res = ingest_qr_work_hour_scan(
            self.db, self.settings,
            {
                "employee_code": "INT-001",
                "employee_name": "Data & Web Intern",
                "role_type": "Intern",
                "department": "Corporate & Tax",
                "action": "CHECK_IN",
                "scanned_at": "2026-11-20T08:55:00+07:00",
            },
        )
        self.assertEqual(in_res["status_flag"], "LATE")

        out_res = ingest_qr_work_hour_scan(
            self.db, self.settings,
            {
                "employee_code": "INT-001",
                "employee_name": "Data & Web Intern",
                "role_type": "Intern",
                "department": "Corporate & Tax",
                "action": "CHECK_OUT",
                "scanned_at": "2026-11-20T17:35:00+07:00",
            },
        )
        self.assertGreater(out_res["hours_worked"], 8.5)

        tg = TelegramRBACService(self.db, self.settings)
        late_targets = tg.resolve_recipients("late_scan_alerts")
        self.assertEqual([u["full_name"] for u in late_targets], ["Bong Philen"])

        dept_targets = tg.resolve_recipients("team_work_hours", department="Corporate & Tax")
        self.assertEqual([u["full_name"] for u in dept_targets], ["Corporate & Tax Supervisor"])

    def test_charts_csv_and_verified_zip_bundle(self):
        ingest_csv_file(self.db, self.settings, "academy", self.settings.root_dir / "sample_data" / "academy_sample.csv")
        ingest_csv_file(self.db, self.settings, "surveys", self.settings.root_dir / "sample_data" / "surveys_sample.csv")
        ingest_csv_file(self.db, self.settings, "ops", self.settings.root_dir / "sample_data" / "ops_sample.csv")

        low = ingest_survey_record(
            self.db, self.settings,
            {
                "respondent_name": "Test Client",
                "organization": "Acme KH",
                "chamber": "EuroCham",
                "event_name": "Compliance Talks 2026",
                "department": "Corporate & Tax",
                "rating": 2.5,
                "requested_topic": "Tax & Customs",
                "feedback": "Audio was quiet in back row.",
            },
        )
        self.assertTrue(low["is_low_rating"])

        chart1 = generate_survey_chart(self.db, self.settings, "ALL")
        chart2 = generate_revenue_and_attendance_chart(self.db, self.settings)
        self.assertTrue(chart1.exists() and chart1.stat().st_size > 5000)
        self.assertTrue(chart2.exists() and chart2.stat().st_size > 5000)

        csv_out = export_clean_csv(self.db, self.settings, "surveys", "ALL")
        self.assertTrue(csv_out.exists())

        bundle = create_verified_zip_bundle(self.db, self.settings)
        self.assertTrue(bundle["zip_path"].exists())
        with zipfile.ZipFile(bundle["zip_path"], "r") as zf:
            self.assertIsNone(zf.testzip())
            names = zf.namelist()
            self.assertTrue(any(n.startswith("datasets/") for n in names))
            self.assertTrue(any(n.startswith("receipts_a5/") for n in names))
            self.assertTrue(any(n.startswith("charts/") for n in names))


if __name__ == "__main__":
    unittest.main()
