import csv
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.models import MAX_PRICE_USD
from app.services.receipts import generate_a5_receipt_html

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_SHIFT_HOURS = 16
RECEIPT_ATTEMPTS = 5


def normalize_phone_kh(raw_phone: str) -> str | None:
    digits = re.sub(r"[^\d]", "", str(raw_phone or "").strip())
    if digits.startswith("8550"):
        digits = "+855" + digits[4:]
    elif digits.startswith("855"):
        digits = "+" + digits
    elif digits.startswith("0"):
        digits = "+855" + digits[1:]
    elif len(digits) in (8, 9):
        digits = "+855" + digits
    else:
        return None
    return digits if re.match(r"^\+855\d{8,9}$", digits) else None


def log_quarantine(db: DatabaseAdapter, conn: Any, category: str, payload: dict[str, Any], reason: str, now_str: str) -> None:
    db.execute(
        conn,
        '''
        INSERT INTO quarantine_logs (category, raw_payload, rejection_reason, logged_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (category, raw_payload, rejection_reason) DO NOTHING
        ''',
        (category, json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), reason, now_str),
    )


def _invoice_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_no": row["receipt_no"],
        "khmer_name": row["khmer_name"],
        "latin_name": row["latin_name"],
        "email": row["email"],
        "phone_e164": row["phone_e164"],
        "course_title": row["course_title"],
        "payment_method": row["payment_method"],
        "total_usd": float(row["total_usd"]),
        "total_khr": int(row["total_khr"]),
        "issued_at": row["issued_at"],
    }


def ingest_academy_record(db: DatabaseAdapter, settings: AppSettings, raw: dict[str, Any]) -> dict[str, Any]:
    """Issues an invoice and receipt. An invoice is immutable once issued: re-submitting the same
    email and course returns the original record (duplicate=True) and changes nothing."""
    now = datetime.now(settings.tz)
    now_str = now.strftime(TS_FORMAT)
    fx = int(settings.firm_config["organization"]["currency_fx_khr"])

    km = str(raw.get("khmer_name") or raw.get("Khmer_Name") or "").strip()
    en = str(raw.get("latin_name") or raw.get("Latin_Name") or "").strip().upper()
    email = str(raw.get("email") or raw.get("Email") or "").strip().lower()
    phone = normalize_phone_kh(str(raw.get("phone") or raw.get("Phone") or ""))
    course = str(raw.get("course_title") or raw.get("Course_Title") or "Double Your Productivity With AI").strip()
    method = str(raw.get("payment_method") or raw.get("Payment_Method") or "ABA KHQR").strip()

    errors = []
    if not km or not en:
        errors.append("Missing Khmer or Latin name")
    if not EMAIL_RE.match(email):
        errors.append(f"Invalid email: {email}")
    if not phone:
        errors.append(f"Invalid Cambodia phone: {raw.get('phone') or raw.get('Phone') or ''}")
    try:
        usd = round(float(raw.get("price_usd") if "price_usd" in raw else raw.get("Price_USD", 0)), 2)
        if not math.isfinite(usd) or usd < 0 or usd > MAX_PRICE_USD:
            raise ValueError
        khr = int(round(usd * fx))
    except (ValueError, TypeError, OverflowError):
        errors.append(f"Invalid price_usd (must be between 0 and {MAX_PRICE_USD:g})")
        usd, khr = 0.0, 0

    if errors:
        reason = "; ".join(errors)
        with db.connection() as conn:
            log_quarantine(db, conn, "academy", raw, reason, now_str)
        return {"status": "quarantined", "reason": reason}

    rec: dict[str, Any] | None = None
    duplicate = False
    for _ in range(RECEIPT_ATTEMPTS):
        try:
            with db.connection() as conn:
                existing = db.fetch_one(
                    conn,
                    "SELECT * FROM academy_invoices WHERE email = %s AND course_title = %s",
                    (email, course),
                )
                if existing:
                    rec, duplicate = _invoice_record(existing), True
                else:
                    row = db.fetch_one(conn, "SELECT COALESCE(MAX(id), 0) AS max_id FROM academy_invoices")
                    next_num = int(row["max_id"]) + 1 if row else 1
                    receipt_no = f"AA-{now.year}-{next_num:03d}"
                    db.execute(
                        conn,
                        '''
                        INSERT INTO academy_invoices (
                            receipt_no, khmer_name, latin_name, email, phone_e164,
                            course_title, payment_method, total_usd, total_khr, issued_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        (receipt_no, km, en, email, phone, course, method, usd, khr, now_str),
                    )
                    rec = {
                        "receipt_no": receipt_no, "khmer_name": km, "latin_name": en, "email": email,
                        "phone_e164": phone, "course_title": course, "payment_method": method,
                        "total_usd": usd, "total_khr": khr, "issued_at": now_str,
                    }
            break
        except db.integrity_errors():
            # Another request took this receipt number or inserted the same invoice first. Re-read and retry.
            continue
    if rec is None:
        raise RuntimeError("Could not allocate a unique receipt number")

    receipt_path = generate_a5_receipt_html(settings, rec)
    return {"status": "ok", "duplicate": duplicate, "record": rec, "receipt_path": str(receipt_path)}


def ingest_survey_record(db: DatabaseAdapter, settings: AppSettings, raw: dict[str, Any]) -> dict[str, Any]:
    now_str = datetime.now(settings.tz).strftime(TS_FORMAT)
    name = str(raw.get("respondent_name") or raw.get("Respondent_Name") or "").strip()
    org = str(raw.get("organization") or raw.get("Organization") or "Independent").strip()
    chamber = str(raw.get("chamber") or raw.get("Chamber") or "Independent").strip()
    event = str(raw.get("event_name") or raw.get("Event_Name") or "General Firm Survey").strip()
    dept = str(raw.get("department") or raw.get("Department") or "Academy").strip()
    topic = str(raw.get("requested_topic") or raw.get("Requested_Topic") or "General Legal").strip()
    feedback = str(raw.get("feedback") or raw.get("Feedback") or "").strip()

    errors = []
    if not name:
        errors.append("Missing respondent_name")
    try:
        rating = round(float(raw.get("rating") if "rating" in raw else raw.get("Rating", 0)), 2)
        if not (1.0 <= rating <= 5.0):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        errors.append("Rating must be between 1.0 and 5.0")
        rating = 0.0

    with db.connection() as conn:
        if errors:
            reason = "; ".join(errors)
            log_quarantine(db, conn, "surveys", raw, reason, now_str)
            return {"status": "quarantined", "reason": reason}

        db.execute(
            conn,
            '''
            INSERT INTO firm_surveys (
                respondent_name, organization, chamber, event_name, department,
                rating, requested_topic, feedback, loaded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (respondent_name, event_name) DO UPDATE SET
                organization = EXCLUDED.organization,
                chamber = EXCLUDED.chamber,
                department = EXCLUDED.department,
                rating = EXCLUDED.rating,
                requested_topic = EXCLUDED.requested_topic,
                feedback = EXCLUDED.feedback,
                loaded_at = EXCLUDED.loaded_at
            ''',
            (name, org, chamber, event, dept, rating, topic, feedback, now_str),
        )

    low_threshold = float(settings.firm_config["alerts"]["low_survey_rating_threshold"])
    return {
        "status": "ok",
        "is_low_rating": rating < low_threshold,
        "record": {
            "respondent_name": name,
            "organization": org,
            "chamber": chamber,
            "event_name": event,
            "department": dept,
            "rating": rating,
            "requested_topic": topic,
            "feedback": feedback,
            "loaded_at": now_str,
        },
    }


def ingest_ops_record(db: DatabaseAdapter, settings: AppSettings, raw: dict[str, Any]) -> dict[str, Any]:
    now_str = datetime.now(settings.tz).strftime(TS_FORMAT)
    cname = str(raw.get("client_name") or raw.get("Client_Name") or "").strip()
    email = str(raw.get("email") or raw.get("Email") or "").strip().lower()
    phone = normalize_phone_kh(str(raw.get("phone") or raw.get("Phone") or ""))
    area = str(raw.get("practice_area") or raw.get("Practice_Area") or raw.get("Case_Category") or "Corporate & Tax").strip()
    urgency = str(raw.get("urgency") or raw.get("Urgency") or "Standard").strip()

    errors = []
    if not cname:
        errors.append("Missing client_name")
    if not EMAIL_RE.match(email):
        errors.append(f"Invalid email: {email}")
    if not phone:
        errors.append("Invalid Cambodia phone")

    with db.connection() as conn:
        if errors:
            reason = "; ".join(errors)
            log_quarantine(db, conn, "ops", raw, reason, now_str)
            return {"status": "quarantined", "reason": reason}

        db.execute(
            conn,
            '''
            INSERT INTO client_ops_intake (
                client_name, email, phone_e164, practice_area, urgency, loaded_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (email, practice_area) DO UPDATE SET
                client_name = EXCLUDED.client_name,
                phone_e164 = EXCLUDED.phone_e164,
                urgency = EXCLUDED.urgency,
                loaded_at = EXCLUDED.loaded_at
            ''',
            (cname, email, phone, area, urgency, now_str),
        )

    return {
        "status": "ok",
        "record": {
            "client_name": cname,
            "email": email,
            "phone_e164": phone,
            "practice_area": area,
            "urgency": urgency,
            "loaded_at": now_str,
        },
    }


def _reject_scan(db: DatabaseAdapter, conn: Any, scan: dict[str, Any], reason: str, ts_str: str) -> dict[str, Any]:
    log_quarantine(db, conn, "qr-scan", scan, reason, ts_str)
    return {"status": "quarantined", "reason": reason}


def ingest_qr_work_hour_scan(db: DatabaseAdapter, settings: AppSettings, scan: dict[str, Any]) -> dict[str, Any]:
    """Records a check-in or check-out.

    Rules: scanned_at must be a valid timestamp, at most five minutes ahead of the server clock and no older
    than QR_MAX_BACKDATE_HOURS. A check-out needs an open check-in, either today or from a shift that began
    within the last 16 hours (overnight shifts). A second check-out for the same shift is rejected."""
    real_now = datetime.now(settings.tz)
    now = real_now
    rejection = ""
    raw_ts = scan.get("scanned_at")
    if raw_ts:
        try:
            parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            now = parsed.astimezone(settings.tz) if parsed.tzinfo else parsed.replace(tzinfo=settings.tz)
            if now > real_now + timedelta(minutes=5):
                rejection = "scanned_at is in the future"
            elif now < real_now - timedelta(hours=settings.qr_max_backdate_hours):
                rejection = f"scanned_at is more than {settings.qr_max_backdate_hours:g} hours old"
        except ValueError:
            rejection = "scanned_at is not a valid ISO 8601 timestamp"

    emp_code = str(scan.get("employee_code") or "").strip()
    emp_name = str(scan.get("employee_name") or "").strip()
    role_type = str(scan.get("role_type") or "Employee").strip()
    dept = str(scan.get("department") or "Corporate & Tax").strip()
    action = str(scan.get("action") or "CHECK_IN").upper()
    if action not in ("CHECK_IN", "CHECK_OUT"):
        action = "CHECK_IN"
    if not rejection and (not emp_code or not emp_name):
        rejection = "Missing employee_code or employee_name"

    work_date = now.strftime("%Y-%m-%d")
    ts_str = now.strftime(TS_FORMAT)
    att_cfg = settings.firm_config["attendance"]
    start_cutoff_mins = att_cfg["work_start_hour"] * 60 + att_cfg["work_start_minute"] + att_cfg["late_grace_minutes"]
    end_cutoff_mins = att_cfg["work_end_hour"] * 60 + att_cfg["work_end_minute"]
    now_mins = now.hour * 60 + now.minute

    with db.connection() as conn:
        if rejection:
            return _reject_scan(db, conn, scan, rejection, real_now.strftime(TS_FORMAT))

        existing = db.fetch_one(
            conn,
            "SELECT * FROM employee_work_hours WHERE employee_code = %s AND work_date = %s",
            (emp_code, work_date),
        )

        if action == "CHECK_OUT" and not existing:
            prev_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            prev = db.fetch_one(
                conn,
                "SELECT * FROM employee_work_hours WHERE employee_code = %s AND work_date = %s",
                (emp_code, prev_date),
            )
            if prev and prev["check_in_at"] and not prev["check_out_at"]:
                started = datetime.strptime(prev["check_in_at"], TS_FORMAT).replace(tzinfo=settings.tz)
                if timedelta(0) <= now - started <= timedelta(hours=MAX_SHIFT_HOURS):
                    existing, work_date = prev, prev_date

        check_in_at = existing["check_in_at"] if existing else None
        check_out_at = existing["check_out_at"] if existing else None
        hours_worked = float(existing["hours_worked"]) if existing else 0.0
        status_flag = existing["status_flag"] if existing else "ON_TIME"

        if action == "CHECK_IN":
            if not check_in_at:
                check_in_at = ts_str
                status_flag = "LATE" if now_mins > start_cutoff_mins else "ON_TIME"
        else:
            if not check_in_at:
                return _reject_scan(db, conn, scan, "Check-out without a check-in for this shift", ts_str)
            if check_out_at:
                return _reject_scan(db, conn, scan, f"Already checked out at {check_out_at[11:16]}", ts_str)
            t_in = datetime.strptime(check_in_at, TS_FORMAT).replace(tzinfo=settings.tz)
            if now < t_in:
                return _reject_scan(db, conn, scan, "Check-out is earlier than the check-in", ts_str)
            check_out_at = ts_str
            hours_worked = round((now - t_in).total_seconds() / 3600.0, 2)
            same_day = work_date == now.strftime("%Y-%m-%d")
            if same_day and now_mins < end_cutoff_mins and status_flag != "LATE":
                status_flag = "EARLY_LEAVE"

        db.execute(
            conn,
            '''
            INSERT INTO employee_work_hours (
                employee_code, employee_name, role_type, department, work_date,
                check_in_at, check_out_at, hours_worked, status_flag, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (employee_code, work_date) DO UPDATE SET
                employee_name = EXCLUDED.employee_name,
                role_type = EXCLUDED.role_type,
                department = EXCLUDED.department,
                check_in_at = EXCLUDED.check_in_at,
                check_out_at = EXCLUDED.check_out_at,
                hours_worked = EXCLUDED.hours_worked,
                status_flag = EXCLUDED.status_flag,
                updated_at = EXCLUDED.updated_at
            ''',
            (emp_code, emp_name, role_type, dept, work_date, check_in_at, check_out_at, hours_worked, status_flag, ts_str),
        )

    return {
        "status": "ok",
        "action": action,
        "employee_code": emp_code,
        "employee_name": emp_name,
        "role_type": role_type,
        "department": dept,
        "work_date": work_date,
        "timestamp": ts_str,
        "hours_worked": hours_worked,
        "status_flag": status_flag,
    }


def ingest_csv_file(db: DatabaseAdapter, settings: AppSettings, category: str, csv_path: Path) -> dict[str, int]:
    ok_count, q_count = 0, 0
    handler = {
        "academy": ingest_academy_record,
        "surveys": ingest_survey_record,
        "ops": ingest_ops_record,
    }.get(category)
    if not handler or not csv_path.exists():
        return {"ok": 0, "quarantined": 0}

    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            res = handler(db, settings, row)
            if res.get("status") == "ok":
                ok_count += 1
            else:
                q_count += 1
    return {"ok": ok_count, "quarantined": q_count}
