import html
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.config import load_settings
from app.db import DatabaseAdapter
from app.models import (
    AcademyFormSubmission,
    ClientOpsSubmission,
    QRScanEvent,
    SurveyFormSubmission,
)
from app.services.backups import create_verified_zip_bundle
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart
from app.services.ingestion import (
    ingest_academy_record,
    ingest_ops_record,
    ingest_qr_work_hour_scan,
    ingest_survey_record,
)
from app.services.scheduler import build_scheduler
from app.services.telegram_service import TelegramRBACService

settings = load_settings()
db = DatabaseAdapter(settings)
tg = TelegramRBACService(db, settings)
scheduler = build_scheduler(db, settings, tg)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_schema_and_seed_rbac()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Ann & Associates Cloud Automation & Telegram Ops Engine",
    version="2.0.0",
    lifespan=lifespan,
)


def verify_webhook_secret(x_firm_secret: str | None) -> None:
    expected = settings.webhook_shared_secret
    if expected and "replace_with" not in expected and x_firm_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid X-Firm-Secret header")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "organization": settings.firm_config["organization"]["name_en"],
        "database_mode": "postgresql" if db.is_postgres else "sqlite",
        "telegram_configured": tg.enabled,
        "timestamp": datetime.now(settings.tz).isoformat(),
    }


@app.post("/webhooks/qr-scan")
async def webhook_qr_scan(event: QRScanEvent, x_firm_secret: str | None = Header(default=None)):
    '''Receives real-time Employee/Intern QR scans from Next.js qr-scan-attendance-v2.'''
    verify_webhook_secret(x_firm_secret)
    res = ingest_qr_work_hour_scan(db, settings, event.model_dump())

    badge = "LATE CHECK-IN" if res["status_flag"] == "LATE" else res["action"].replace("_", " ")
    hrs_line = f"\nHours Logged Today: {res['hours_worked']:.2f} hrs" if res["action"] == "CHECK_OUT" else ""
    msg = (
        f"[{badge}] Ann & Associates QR Attendance\n"
        f"Name: {res['employee_name']} ({res['role_type']})\n"
        f"Dept: {res['department']}\n"
        f"Time: {res['timestamp']}{hrs_line}"
    )

    await tg.notify_subscription("team_work_hours", msg, department=res["department"])
    if res["status_flag"] in ("LATE", "EARLY_LEAVE"):
        await tg.notify_subscription("late_scan_alerts", f"ALERT — {msg}")

    return res


@app.post("/webhooks/google-form/academy")
async def webhook_academy(sub: AcademyFormSubmission, x_firm_secret: str | None = Header(default=None)):
    verify_webhook_secret(x_firm_secret)
    res = ingest_academy_record(db, settings, sub.model_dump())
    if res["status"] == "ok":
        rec = res["record"]
        msg = (
            f"NEW ACADEMY INVOICE — {rec['receipt_no']}\n"
            f"Trainee: {rec['khmer_name']} ({rec['latin_name']})\n"
            f"Course: {rec['course_title']}\n"
            f"Amount: ${rec['total_usd']:,.2f} ({rec['total_khr']:,} KHR) via {rec['payment_method']}"
        )
        await tg.notify_subscription("invoices", msg)
    else:
        await tg.notify_subscription("quarantine_alerts", f"QUARANTINE [academy]: {res['reason']}")
    return res


@app.post("/webhooks/google-form/surveys")
async def webhook_surveys(sub: SurveyFormSubmission, x_firm_secret: str | None = Header(default=None)):
    verify_webhook_secret(x_firm_secret)
    res = ingest_survey_record(db, settings, sub.model_dump())
    if res["status"] == "ok":
        rec = res["record"]
        chart_path = generate_survey_chart(db, settings, "ALL")
        if res["is_low_rating"]:
            alert = (
                f"LOW SURVEY RATING ALERT ({rec['rating']}/5.0)\n"
                f"Respondent: {rec['respondent_name']} ({rec['organization']} / {rec['chamber']})\n"
                f"Event: {rec['event_name']}\n"
                f"Feedback: \"{rec['feedback']}\""
            )
            await tg.notify_subscription("low_survey_alerts", alert, photo_path=chart_path)
    else:
        await tg.notify_subscription("quarantine_alerts", f"QUARANTINE [surveys]: {res['reason']}")
    return res


@app.post("/webhooks/google-form/ops")
async def webhook_ops(sub: ClientOpsSubmission, x_firm_secret: str | None = Header(default=None)):
    verify_webhook_secret(x_firm_secret)
    res = ingest_ops_record(db, settings, sub.model_dump())
    if res["status"] == "ok":
        rec = res["record"]
        msg = (
            f"NEW SME/STARTUP LEGAL INTAKE\n"
            f"Client: {rec['client_name']} ({rec['phone_e164']})\n"
            f"Practice Area: {rec['practice_area']} | Urgency: {rec['urgency']}"
        )
        await tg.notify_subscription("invoices", msg)
    else:
        await tg.notify_subscription("quarantine_alerts", f"QUARANTINE [ops]: {res['reason']}")
    return res


@app.post("/webhooks/telegram")
async def webhook_telegram(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    '''Cloud Webhook endpoint for 24/7 Telegram Bot (zero polling overhead on Cloud Run / Azure).'''
    expected = settings.telegram_webhook_secret
    if expected and "replace_with" not in expected and x_telegram_bot_api_secret_token != expected:
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

    update: dict[str, Any] = await request.json()
    if "message" in update and "text" in update["message"]:
        chat_id = str(update["message"]["chat"]["id"])
        cmd = update["message"]["text"].strip().lower()
        return await tg.handle_command(chat_id, cmd)
    if "callback_query" in update:
        cb = update["callback_query"]
        chat_id = str(cb["message"]["chat"]["id"])
        return await tg.handle_command(chat_id, cb["data"])
    return {"ignored": True}


@app.post("/api/v1/pipeline/run")
async def trigger_cloud_sync(x_firm_secret: str | None = Header(default=None)):
    verify_webhook_secret(x_firm_secret)
    s_chart = generate_survey_chart(db, settings, "ALL")
    r_chart = generate_revenue_and_attendance_chart(db, settings)
    bundle = create_verified_zip_bundle(db, settings)
    return {
        "status": "completed",
        "survey_chart": s_chart.name,
        "revenue_chart": r_chart.name,
        "backup_zip": bundle["zip_name"],
        "drive_status": bundle["drive_status"],
    }


@app.get("/charts/{chart_name}")
async def get_chart(chart_name: str):
    path = settings.charts_dir / chart_name
    if not path.exists() or path.suffix != ".png":
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(path, media_type="image/png")


@app.get("/dashboard", response_class=HTMLResponse)
async def live_dashboard(token: str = Query(default="")):
    expected = settings.dashboard_access_token
    if expected and "replace_with" not in expected and token != expected:
        raise HTTPException(status_code=403, detail="Provide ?token=... to view firm dashboard")

    generate_survey_chart(db, settings, "ALL")
    generate_revenue_and_attendance_chart(db, settings)
    today = datetime.now(settings.tz).strftime("%Y-%m-%d")
    fx = int(settings.firm_config["organization"]["currency_fx_khr"])

    with db.connection() as conn:
        inv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_usd),0) AS rev FROM academy_invoices")
        sv = db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating),2),0) AS avg_r FROM firm_surveys")
        scans = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM employee_work_hours WHERE work_date = %s", (today,))
        q = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")

    rev = float(inv["rev"])
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Ann &amp; Associates — Cloud Executive Hub</title>
<style>
  body {{ font-family:'Segoe UI',Arial,sans-serif; background:#f1f5f9; color:#1e293b; margin:0; padding:24px; }}
  .wrap {{ max-width:1120px; margin:0 auto; }}
  .hero {{ background:linear-gradient(135deg,#14532d,#1e3a5f); color:#fff; padding:22px 26px; border-radius:12px; margin-bottom:18px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:18px; }}
  .card {{ background:#fff; border-radius:10px; padding:16px 18px; box-shadow:0 1px 4px rgba(0,0,0,.07); margin-bottom:18px; }}
  .val {{ font-size:24px; font-weight:700; color:#14532d; margin-top:4px; }}
  img {{ width:100%; border-radius:8px; border:1px solid #e2e8f0; }}
</style></head><body><div class="wrap">
  <div class="hero">
    <h1 style="margin:0;font-size:22px;">ANN &amp; ASSOCIATES LAW FIRM &amp; ACADEMY</h1>
    <div style="color:#dcfce7;margin-top:4px;">Cloud-Owned Real-Time Executive Hub | {html.escape(today)}</div>
  </div>
  <div class="kpis">
    <div class="card"><div>Academy Revenue</div><div class="val">${rev:,.2f}</div><div>{int(rev*fx):,} KHR | {inv['cnt']} Invoices</div></div>
    <div class="card"><div>Survey Rating</div><div class="val">{sv['avg_r']} / 5.0</div><div>{sv['cnt']} Chamber &amp; Event Responses</div></div>
    <div class="card"><div>QR Scans Today</div><div class="val">{scans['cnt']}</div><div>Employees &amp; Interns</div></div>
    <div class="card"><div>Quarantine Gate</div><div class="val" style="color:#1e3a5f;">{q['cnt']}</div><div>Isolated Bad Records</div></div>
  </div>
  <div class="card"><img src="/charts/survey_analytics_all.png" alt="Survey Analytics"></div>
  <div class="card"><img src="/charts/firm_revenue_attendance.png" alt="Revenue & Attendance"></div>
</div></body></html>'''
