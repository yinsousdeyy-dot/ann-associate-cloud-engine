"""Shared KPI queries and the sync-and-backup pipeline used by the API, the scheduler and Telegram."""
from datetime import datetime
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.backups import create_verified_zip_bundle
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart


def kpi_counts(db: DatabaseAdapter, settings: AppSettings) -> dict[str, Any]:
    today = datetime.now(settings.tz).strftime("%Y-%m-%d")
    fx = int(settings.firm_config["organization"]["currency_fx_khr"])
    with db.connection() as conn:
        inv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_usd),0) AS rev FROM academy_invoices")
        sv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating),2),0) AS avg_r FROM firm_surveys")
        ops = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM client_ops_intake")
        scans = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM employee_work_hours WHERE work_date = %s", (today,))
        quarantine = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")
    revenue = float(inv["rev"]) if inv else 0.0
    return {
        "invoice_count": int(inv["cnt"]) if inv else 0,
        "revenue_usd": revenue,
        "revenue_khr": int(revenue * fx),
        "survey_count": int(sv["cnt"]) if sv else 0,
        "avg_rating": float(sv["avg_r"]) if sv else 0.0,
        "ops_count": int(ops["cnt"]) if ops else 0,
        "scans_today": int(scans["cnt"]) if scans else 0,
        "quarantine_count": int(quarantine["cnt"]) if quarantine else 0,
    }


def _insert_run_log(db: DatabaseAdapter, settings: AppSettings, trigger: str, status: str, k: dict[str, Any], backup_file: str) -> None:
    now_str = datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")
    with db.connection() as conn:
        db.execute(
            conn,
            """
            INSERT INTO pipeline_run_logs (
                run_timestamp, trigger_source, status, invoice_count, invoice_revenue_usd,
                survey_count, survey_avg_rating, ops_count, active_scans_today, quarantine_count, backup_file
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                now_str, trigger, status, k["invoice_count"], k["revenue_usd"], k["survey_count"],
                k["avg_rating"], k["ops_count"], k["scans_today"], k["quarantine_count"], backup_file,
            ),
        )


def run_pipeline(db: DatabaseAdapter, settings: AppSettings, trigger: str) -> dict[str, Any]:
    """Regenerates both charts, builds the verified ZIP and records the run. Raises on failure after logging it."""
    try:
        survey_chart = generate_survey_chart(db, settings, "ALL")
        revenue_chart = generate_revenue_and_attendance_chart(db, settings)
        bundle = create_verified_zip_bundle(db, settings)
        counts = kpi_counts(db, settings)
        _insert_run_log(db, settings, trigger, "SUCCESS", counts, bundle["zip_name"])
    except Exception as exc:
        try:
            _insert_run_log(db, settings, trigger, f"FAILED: {type(exc).__name__}", kpi_counts(db, settings), "-")
        except Exception:
            pass
        raise
    return {"survey_chart": survey_chart, "revenue_chart": revenue_chart, "bundle": bundle, "counts": counts}
