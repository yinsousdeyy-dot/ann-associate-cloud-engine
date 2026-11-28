import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import load_settings
from app.db import DatabaseAdapter
from app.models import (
    AcademyFormSubmission,
    ClientOpsSubmission,
    QRScanEvent,
    SurveyFormSubmission,
)
from app.security import (
    client_key,
    clear_session_cookie,
    dashboard_state,
    is_configured,
    login_blocked,
    login_failed,
    login_ok,
    require_dashboard,
    require_ingest,
    require_telegram_secret,
    set_session_cookie,
    token_valid,
)
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart
from app.services.ingestion import (
    ingest_academy_record,
    ingest_csv_file,
    ingest_ops_record,
    ingest_qr_work_hour_scan,
    ingest_survey_record,
)
from app.services.pipeline import kpi_counts, run_pipeline
from app.services.scheduler import build_scheduler
from app.services.telegram_service import TelegramRBACService, dry_run
from app.ui_template import render_dashboard_html, render_login_html

logger = logging.getLogger("ann_engine")

STATIC_DIR = Path(__file__).resolve().parent / "static"
CHART_MAX_AGE_SECONDS = 60

settings = load_settings()
db = DatabaseAdapter(settings)
tg = TelegramRBACService(db, settings)
scheduler = build_scheduler(db, settings, tg)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_schema_and_seed_rbac()
    if settings.is_production:
        missing = [
            name
            for name, value in (
                ("DASHBOARD_ACCESS_TOKEN", settings.dashboard_access_token),
                ("WEBHOOK_SHARED_SECRET", settings.webhook_shared_secret),
            )
            if not is_configured(value)
        ]
        if missing:
            logger.error(
                "APP_ENV=production and %s not set: protected routes will answer 503 until configured.",
                ", ".join(missing),
            )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Ann & Associates Cloud Automation & Telegram Ops Engine",
    version="2.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DASHBOARD_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
RECEIPT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if path.startswith("/receipts/"):
        response.headers["Content-Security-Policy"] = RECEIPT_CSP
    elif path.startswith("/dashboard"):
        response.headers["Content-Security-Policy"] = DASHBOARD_CSP
    if path.startswith(("/dashboard", "/api/", "/backups/", "/datasets/", "/receipts/")):
        response.headers["Cache-Control"] = "no-store"
    return response


# Authentication dependencies. They read the module-level `settings` at call time.
def dashboard_read(request: Request) -> None:
    require_dashboard(settings, request)


def dashboard_write(request: Request) -> None:
    require_dashboard(settings, request, mutating=True)


def ingest_auth(request: Request, x_firm_secret: str | None = Header(default=None)) -> None:
    require_ingest(settings, request, x_firm_secret)


class TelegramSimulateRequest(BaseModel):
    chat_id: str = Field(..., min_length=1, max_length=32)
    command: str = Field(..., min_length=1, max_length=64)


def safe_file(base: Path, name: str, suffix: str) -> Path:
    """Resolves `name` inside `base` or raises 404. Rejects separators, traversal and wrong extensions."""
    if (
        not name
        or name != Path(name).name
        or "\\" in name
        or Path(name).suffix.lower() != suffix
    ):
        raise HTTPException(status_code=404, detail="Not found")
    path = (base / name).resolve()
    if path.parent != base.resolve():
        raise HTTPException(status_code=404, detail="Not found")
    return path


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/health")
async def health_check(request: Request):
    body: dict[str, Any] = {
        "status": "healthy",
        "organization": settings.firm_config["organization"]["name_en"],
        "timestamp": datetime.now(settings.tz).isoformat(),
    }
    if dashboard_state(settings, request) == "ok":
        body["database_mode"] = "postgresql" if db.is_postgres else "sqlite"
        body["telegram_configured"] = tg.enabled
    return body


@app.post("/webhooks/qr-scan", dependencies=[Depends(ingest_auth)])
async def webhook_qr_scan(event: QRScanEvent):
    """Receives real-time Employee/Intern QR scans from the Next.js attendance app or the dashboard."""
    res = ingest_qr_work_hour_scan(db, settings, event.model_dump())

    if res.get("status") == "ok":
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
    else:
        await tg.notify_subscription("quarantine_alerts", f"QUARANTINE [qr-scan]: {res.get('reason', '')}")

    return res


@app.post("/webhooks/google-form/academy", dependencies=[Depends(ingest_auth)])
async def webhook_academy(sub: AcademyFormSubmission):
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


@app.post("/webhooks/google-form/surveys", dependencies=[Depends(ingest_auth)])
async def webhook_surveys(sub: SurveyFormSubmission):
    res = ingest_survey_record(db, settings, sub.model_dump())
    if res["status"] == "ok":
        rec = res["record"]
        if res["is_low_rating"]:
            chart_path = await run_in_threadpool(generate_survey_chart, db, settings, "ALL")
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


@app.post("/webhooks/google-form/ops", dependencies=[Depends(ingest_auth)])
async def webhook_ops(sub: ClientOpsSubmission):
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
    """Cloud webhook endpoint for the 24/7 Telegram bot (no polling overhead on Cloud Run / VPS)."""
    require_telegram_secret(settings, x_telegram_bot_api_secret_token)

    update: dict[str, Any] = await request.json()
    if "message" in update and "text" in update["message"]:
        chat_id = str(update["message"]["chat"]["id"])
        raw = update["message"]["text"].strip()
        cmd = raw.split("@")[0].lower() if raw.startswith("/") else raw.lower()
        return await tg.handle_command(chat_id, cmd)
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_msg = cb.get("message") or {}
        chat_id = str(cb_msg.get("chat", {}).get("id") or cb.get("from", {}).get("id"))
        return await tg.handle_command(chat_id, cb.get("data", ""))
    return {"ignored": True}


@app.post("/api/v1/pipeline/run", dependencies=[Depends(ingest_auth)])
async def trigger_cloud_sync():
    try:
        result = await run_in_threadpool(run_pipeline, db, settings, "api_manual_trigger")
    except Exception as exc:
        logger.exception("Manual pipeline run failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {type(exc).__name__}") from exc
    bundle = result["bundle"]
    return {
        "status": "completed",
        "survey_chart": result["survey_chart"].name,
        "revenue_chart": result["revenue_chart"].name,
        "backup_zip": bundle["zip_name"],
        "drive_status": bundle["drive_status"],
    }


@app.post("/api/v1/seed-sample-data", dependencies=[Depends(ingest_auth)])
async def seed_sample_data():
    """Loads sample_data/ into the live database. Only available when DEMO_TOOLS_ENABLED=true."""
    if not settings.demo_tools_enabled:
        raise HTTPException(status_code=404, detail="Demo tools are disabled")
    res_ac = ingest_csv_file(db, settings, "academy", settings.root_dir / "sample_data" / "academy_sample.csv")
    res_sv = ingest_csv_file(db, settings, "surveys", settings.root_dir / "sample_data" / "surveys_sample.csv")
    res_ops = ingest_csv_file(db, settings, "ops", settings.root_dir / "sample_data" / "ops_sample.csv")

    today_str = datetime.now(settings.tz).strftime("%Y-%m-%d")
    for code, name, role, stamp in (
        ("INT-001", "Data & Web Intern", "Intern", "08:25:00"),
        ("EMP-001", "Bong Philen (Partner)", "Employee", "08:15:00"),
    ):
        ingest_qr_work_hour_scan(db, settings, {
            "employee_code": code,
            "employee_name": name,
            "role_type": role,
            "department": "Corporate & Tax",
            "action": "CHECK_IN",
            "scanned_at": f"{today_str}T{stamp}+07:00",
        })

    await run_in_threadpool(generate_survey_chart, db, settings, "ALL")
    await run_in_threadpool(generate_revenue_and_attendance_chart, db, settings)
    return {"status": "seeded", "academy": res_ac, "surveys": res_sv, "ops": res_ops, "attendance_scans": 2}


@app.post("/api/v1/simulate/telegram", dependencies=[Depends(dashboard_write)])
async def simulate_telegram(req: TelegramSimulateRequest):
    """Runs a bot command as the given chat id and returns the reply. Nothing is sent to Telegram."""
    marker = dry_run.set(True)
    try:
        res = await tg.handle_command(req.chat_id, req.command)
    finally:
        dry_run.reset(marker)
    dispatched = tg.last_dispatched or {}
    return {
        "authorized": res.get("authorized", False),
        "action": res.get("action", ""),
        "message": res.get("message") or dispatched.get("text") or dispatched.get("caption") or "",
        "reply_markup": dispatched.get("reply_markup"),
        "photo": res.get("photo") or dispatched.get("photo"),
        "document": res.get("document") or dispatched.get("document"),
    }


@app.get("/api/v1/data/overview", dependencies=[Depends(dashboard_read)])
async def api_data_overview():
    """Live operational statistics and record feeds for the dashboard."""
    today = datetime.now(settings.tz).strftime("%Y-%m-%d")
    kpi = kpi_counts(db, settings)

    with db.connection() as conn:
        invoices = db.fetch_all(conn, "SELECT * FROM academy_invoices ORDER BY id DESC LIMIT 50")
        attendance = db.fetch_all(conn, "SELECT * FROM employee_work_hours WHERE work_date = %s ORDER BY check_in_at DESC", (today,))
        surveys = db.fetch_all(conn, "SELECT * FROM firm_surveys ORDER BY survey_id DESC LIMIT 50")
        ops = db.fetch_all(conn, "SELECT * FROM client_ops_intake ORDER BY intake_id DESC LIMIT 50")
        quarantine = db.fetch_all(conn, "SELECT * FROM quarantine_logs ORDER BY quarantine_id DESC LIMIT 50")
        runs = db.fetch_all(conn, "SELECT * FROM pipeline_run_logs ORDER BY run_id DESC LIMIT 20")
        bot_users = db.fetch_all(
            conn,
            "SELECT telegram_chat_id AS chat_id, full_name, role, department "
            "FROM telegram_users_rbac WHERE is_active = %s ORDER BY user_id",
            (True if db.is_postgres else 1,),
        )

    receipts_list = [f.name for f in sorted(settings.receipts_dir.glob("*.html"), reverse=True)[:200]]
    datasets_list = [f.name for f in sorted(settings.datasets_dir.glob("*.csv"), reverse=True)[:20]]
    backups_list = [
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024.0, 1)}
        for f in sorted(settings.backups_dir.glob("ann_firm_vault_*.zip"), reverse=True)[:10]
    ]

    return {
        "status": "healthy",
        "timestamp": datetime.now(settings.tz).isoformat(),
        "kpi": kpi,
        "invoices": invoices,
        "attendance": attendance,
        "surveys": surveys,
        "ops": ops,
        "quarantine": quarantine,
        "pipeline_runs": runs,
        "bot_users": bot_users,
        "receipts": receipts_list,
        "datasets": datasets_list,
        "backups": backups_list,
    }


def _chart_builders() -> dict[str, Any]:
    return {
        "survey_analytics_all.png": lambda: generate_survey_chart(db, settings, "ALL"),
        "firm_revenue_attendance.png": lambda: generate_revenue_and_attendance_chart(db, settings),
    }


@app.get("/charts/{chart_name}", dependencies=[Depends(dashboard_read)])
async def get_chart(chart_name: str, fresh: bool = False):
    path = safe_file(settings.charts_dir, chart_name, ".png")
    builder = _chart_builders().get(path.name)
    if builder:
        stale = fresh or not path.exists() or (time.time() - path.stat().st_mtime) > CHART_MAX_AGE_SECONDS
        if stale:
            await run_in_threadpool(builder)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(path, media_type="image/png")


@app.get("/receipts/{receipt_name}", dependencies=[Depends(dashboard_read)])
async def get_receipt(receipt_name: str):
    path = safe_file(settings.receipts_dir, receipt_name, ".html")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Receipt not found")
    return FileResponse(path, media_type="text/html")


@app.get("/datasets/{filename}", dependencies=[Depends(dashboard_read)])
async def get_dataset(filename: str):
    path = safe_file(settings.datasets_dir, filename, ".csv")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dataset not found")
    return FileResponse(path, media_type="text/csv", filename=path.name)


@app.get("/backups/{filename}", dependencies=[Depends(dashboard_read)])
async def get_backup(filename: str):
    path = safe_file(settings.backups_dir, filename, ".zip")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.get("/dashboard", response_class=HTMLResponse)
async def live_dashboard(request: Request):
    state = dashboard_state(settings, request)
    if state == "unconfigured":
        return HTMLResponse(render_login_html(settings, unconfigured=True), status_code=503)
    if state == "denied":
        return HTMLResponse(render_login_html(settings), status_code=403)

    kpi = await run_in_threadpool(kpi_counts, db, settings)
    return HTMLResponse(render_dashboard_html(settings, kpi))


@app.post("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login(request: Request):
    if settings.is_production and not is_configured(settings.dashboard_access_token):
        return HTMLResponse(render_login_html(settings, unconfigured=True), status_code=503)

    client = client_key(request)
    if login_blocked(client):
        return HTMLResponse(
            render_login_html(settings, error="Too many failed attempts. Wait five minutes and try again."),
            status_code=429,
        )

    raw = (await request.body())[:4096].decode("utf-8", "replace")
    supplied = parse_qs(raw).get("token", [""])[0]
    if is_configured(settings.dashboard_access_token) and not token_valid(settings, supplied):
        login_failed(client)
        return HTMLResponse(render_login_html(settings, error="That access token is not valid."), status_code=403)

    login_ok(client)
    response = RedirectResponse(url="/dashboard", status_code=303)
    if is_configured(settings.dashboard_access_token):
        set_session_cookie(response, settings, request)
    return response


@app.post("/dashboard/logout")
async def dashboard_logout():
    response = RedirectResponse(url="/dashboard", status_code=303)
    clear_session_cookie(response)
    return response
