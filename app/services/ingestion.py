import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.receipts import generate_a5_receipt_html

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def normalize_phone_kh(raw_phone: str) -> str | None:
    digits = re.sub(r"[^\d]", "", str(raw_phone or "").strip())
    if digits.startswith("0"):
        digits = "+855" + digits[1:]
    elif digits.startswith("855"):
        digits = "+" + digits
    elif len(digits) >= 8:
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
        (category, json.dumps(payload, ensure_ascii=False, sort_keys=True), reason, now_str),
    )


def ingest_academy_record(db: DatabaseAdapter, settings: AppSettings, raw: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(settings.tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
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
        if usd < 0:
            raise ValueError
        khr = int(round(usd * fx))
    except (ValueError, TypeError):
        errors.append("Invalid price_usd")
        usd, khr = 0.0, 0

    with db.connection() as conn:
        if errors:
            reason = "; ".join(errors)
            log_quarantine(db, conn, "academy", raw, reason, now_str)
            return {"status": "quarantined", "reason": reason}

        existing = db.fetch_one(
            conn,
            "SELECT receipt_no FROM academy_invoices WHERE email = %s AND course_title = %s",
            (email, course),
        )
        if existing:
            receipt_no = existing["receipt_no"]
        else:
            cnt_row = db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM academy_invoices")
            next_num = int(cnt_row["cnt"]) + 1 if cnt_row else 1
            receipt_no = f"AA-{now.year}-{next_num:03d}"

        db.execute(
            conn,
            '''
            INSERT INTO academy_invoices (
                receipt_no, khmer_name, latin_name, email, phone_e164,
                course_title, payment_method, total_usd, total_khr, issued_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email, course_title) DO UPDATE SET
                khmer_name = EXCLUDED.khmer_name,
                latin_name = EXCLUDED.latin_name,
                phone_e164 = EXCLUDED.phone_e164,
                payment_method = EXCLUDED.payment_method,
                total_usd = EXCLUDED.total_usd,
                total_khr = EXCLUDED.total_khr,
                issued_at = EXCLUDED.issued_at
            ''',
            (receipt_no, km, en, email, phone, course, method, usd, khr, now_str),
        )

    rec = {
        "receipt_no": receipt_no,
        "khmer_name": km,
        "latin_name": en,
        "email": email,
        "phone_e164": phone,
        "course_title": course,
        "payment_method": method,
        "total_usd": usd,
        "total_khr": khr,
        "issued_at": now_str,
    }
    receipt_path = generate_a5_receipt_html(settings, rec)
    return {"status": "ok", "record": rec, "receipt_path": str(receipt_path)}


def ingest_survey_record(db: DatabaseAdapter, settings: AppSettings, raw: dict[str, Any]) -> dict[str, Any]:
    now_str = datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")
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
    except (ValueError, TypeError):
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
    now_str = datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")
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


def ingest_qr_work_hour_scan(db: DatabaseAdapter, settings: AppSettings, scan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(settings.tz)
    if scan.get("scanned_at"):
        try:
            parsed = datetime.fromisoformat(str(scan["scanned_at"]).replace("Z", "+00:00"))
            now = parsed.astimezone(settings.tz) if parsed.tzinfo else parsed.replace(tzinfo=settings.tz)
        except ValueError:
            pass

    work_date = now.strftime("%Y-%m-%d")
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
    att_cfg = settings.firm_config["attendance"]
    start_cutoff_mins = att_cfg["work_start_hour"] * 60 + att_cfg["work_start_minute"] + att_cfg["late_grace_minutes"]
    end_cutoff_mins = att_cfg["work_end_hour"] * 60 + att_cfg["work_end_minute"]
    now_mins = now.hour * 60 + now.minute

    emp_code = str(scan["employee_code"]).strip()
    emp_name = str(scan["employee_name"]).strip()
    role_type = str(scan.get("role_type") or "Employee").strip()
    dept = str(scan.get("department") or "Corporate & Tax").strip()
    action = str(scan["action"]).upper()

    with db.connection() as conn:
        existing = db.fetch_one(
            conn,
            "SELECT * FROM employee_work_hours WHERE employee_code = %s AND work_date = %s",
            (emp_code, work_date),
        )

        check_in_at = existing["check_in_at"] if existing else None
        check_out_at = existing["check_out_at"] if existing else None
        hours_worked = float(existing["hours_worked"]) if existing else 0.0
        status_flag = existing["status_flag"] if existing else "ON_TIME"

        if action == "CHECK_IN":
            if not check_in_at:
                check_in_at = ts_str
                status_flag = "LATE" if now_mins > start_cutoff_mins else "ON_TIME"
        elif action == "CHECK_OUT":
            check_out_at = ts_str
            if check_in_at:
                t_in = datetime.strptime(check_in_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=settings.tz)
                diff_hrs = max(0.0, (now - t_in).total_seconds() / 3600.0)
                hours_worked = round(diff_hrs, 2)
            if now_mins < end_cutoff_mins and status_flag != "LATE":
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
            if res["status"] == "ok":
                ok_count += 1
            else:
                q_count += 1
    return {"ok": ok_count, "quarantined": q_count}
