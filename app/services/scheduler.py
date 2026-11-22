from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.backups import create_verified_zip_bundle
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart
from app.services.telegram_service import TelegramRBACService


def build_scheduler(db: DatabaseAdapter, settings: AppSettings, tg: TelegramRBACService) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)

    async def morning_rollcall_job():
        today = datetime.now(settings.tz).strftime("%Y-%m-%d")
        with db.connection() as conn:
            rows = db.fetch_all(
                conn,
                "SELECT employee_name, role_type, department, check_in_at, status_flag "
                "FROM employee_work_hours WHERE work_date = %s ORDER BY check_in_at ASC",
                (today,),
            )
        on_time = sum(1 for r in rows if r["status_flag"] == "ON_TIME")
        late = sum(1 for r in rows if r["status_flag"] == "LATE")
        detail = "\n".join(
            f"• {r['employee_name']} ({r['role_type']}): {(r['check_in_at'] or '-')[-8:]} [{r['status_flag']}]"
            for r in rows
        ) or "• No QR check-ins recorded yet."

        msg = (
            f"GOOD MORNING — Ann & Associates 08:45 Roll-Call ({today})\n"
            f"Scanned In: {len(rows)} | On Time: {on_time} | Late: {late}\n\n{detail}"
        )
        await tg.notify_subscription("work_hours_summary", msg)

    async def evening_executive_wrapup_job():
        now_str = datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now(settings.tz).strftime("%Y-%m-%d")
        fx = int(settings.firm_config["organization"]["currency_fx_khr"])

        survey_chart = generate_survey_chart(db, settings, "ALL")
        generate_revenue_and_attendance_chart(db, settings)
        bundle = create_verified_zip_bundle(db, settings)

        with db.connection() as conn:
            inv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_usd),0) AS rev FROM academy_invoices")
            sv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating),2),0) AS avg_r FROM firm_surveys")
            ops = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM client_ops_intake")
            scans = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM employee_work_hours WHERE work_date = %s", (today,))
            q = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")

            db.execute(
                conn,
                '''
                INSERT INTO pipeline_run_logs (
                    run_timestamp, trigger_source, status, invoice_count, invoice_revenue_usd,
                    survey_count, survey_avg_rating, ops_count, active_scans_today, quarantine_count, backup_file
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    now_str, "cron_evening_wrapup", "SUCCESS",
                    int(inv["cnt"]), float(inv["rev"]), int(sv["cnt"]), float(sv["avg_r"]),
                    int(ops["cnt"]), int(scans["cnt"]), int(q["cnt"]), bundle["zip_name"],
                ),
            )

        rev = float(inv["rev"])
        caption = (
            f"ANN & ASSOCIATES — 17:30 Executive Daily Wrap-Up ({today})\n\n"
            f"• Survey Intelligence: {sv['cnt']} responses (Avg {sv['avg_r']}/5.0)\n"
            f"• Academy Invoices: {inv['cnt']} (${rev:,.2f} / {int(rev * fx):,} KHR)\n"
            f"• QR Work-Hour Scans Today: {scans['cnt']} staff/interns\n"
            f"• Verified Backup ZIP: {bundle['zip_name']} ({bundle['size_kb']} KB)\n"
            f"• Quarantined Rows: {q['cnt']}"
        )
        await tg.notify_subscription("daily_digest", caption, photo_path=survey_chart)

    m_hr, m_min = map(int, settings.firm_config["alerts"]["morning_rollcall_time"].split(":"))
    e_hr, e_min = map(int, settings.firm_config["alerts"]["evening_wrapup_time"].split(":"))

    scheduler.add_job(morning_rollcall_job, CronTrigger(day_of_week="mon-fri", hour=m_hr, minute=m_min, timezone=settings.tz))
    scheduler.add_job(evening_executive_wrapup_job, CronTrigger(day_of_week="mon-fri", hour=e_hr, minute=e_min, timezone=settings.tz))
    return scheduler
