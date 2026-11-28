import base64
import csv
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart


def export_clean_csv(db: DatabaseAdapter, settings: AppSettings, dataset_name: str, department: str = "ALL") -> Path:
    stamp = datetime.now(settings.tz).strftime("%Y%m%d")
    dept_suffix = department.lower().replace(" ", "_").replace("&", "and")
    out_path = settings.datasets_dir / f"{dataset_name}_{dept_suffix}_{stamp}.csv"

    queries = {
        "invoices": (
            "SELECT receipt_no, khmer_name, latin_name, email, phone_e164, course_title, payment_method, total_usd, total_khr, issued_at FROM academy_invoices ORDER BY id DESC",
            (),
        ),
        "surveys": (
            "SELECT respondent_name, organization, chamber, event_name, department, rating, requested_topic, feedback, loaded_at FROM firm_surveys ORDER BY survey_id DESC"
            if department == "ALL"
            else "SELECT respondent_name, organization, chamber, event_name, department, rating, requested_topic, feedback, loaded_at FROM firm_surveys WHERE department = %s ORDER BY survey_id DESC",
            () if department == "ALL" else (department,),
        ),
        "work_hours": (
            "SELECT employee_code, employee_name, role_type, department, work_date, check_in_at, check_out_at, hours_worked, status_flag FROM employee_work_hours ORDER BY work_date DESC, scan_id DESC"
            if department == "ALL"
            else "SELECT employee_code, employee_name, role_type, department, work_date, check_in_at, check_out_at, hours_worked, status_flag FROM employee_work_hours WHERE department = %s ORDER BY work_date DESC, scan_id DESC",
            () if department == "ALL" else (department,),
        ),
        "ops": (
            "SELECT client_name, email, phone_e164, practice_area, urgency, loaded_at FROM client_ops_intake ORDER BY intake_id DESC",
            (),
        ),
    }
    sql, params = queries[dataset_name]

    with db.connection() as conn:
        rows = db.fetch_all(conn, sql, params)

    if rows:
        fieldnames = list(rows[0].keys())
    else:
        fieldnames = ["notice"]
        rows = [{"notice": f"No records available in {dataset_name}"}]

    with open(out_path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def upload_file_to_google_drive(settings: AppSettings, file_path: Path, folder_id: str) -> str:
    """Uploads a verified ZIP backup or dataset to Firm Google Drive via Service Account API."""
    if not settings.google_drive_enabled or not settings.google_service_account_json_b64 or not folder_id:
        return "Local Cloud Container Vault (Google Drive API disabled)"

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        sa_info = json.loads(base64.b64decode(settings.google_service_account_json_b64).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        metadata = {"name": file_path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(file_path), resumable=True)
        uploaded = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,  # Required for Google Workspace Shared Drives
            )
            .execute()
        )
        return f"Uploaded to Firm Google Drive ({uploaded.get('webViewLink', 'OK')})"
    except Exception as exc:
        return f"Local Vault Saved (Drive Upload Skipped: {exc})"


def create_verified_zip_bundle(db: DatabaseAdapter, settings: AppSettings) -> dict[str, Any]:
    '''Exports clean CSV datasets + A5 receipts + PNG charts into a CRC-verified ZIP archive.'''
    stamp = datetime.now(settings.tz).strftime("%Y%m%d_%H%M%S")
    zip_path = settings.backups_dir / f"ann_firm_vault_{stamp}.zip"

    # Ensure charts exist before bundling
    if not list(settings.charts_dir.glob("*.png")):
        generate_survey_chart(db, settings, "ALL")
        generate_revenue_and_attendance_chart(db, settings)

    csv_files = [
        export_clean_csv(db, settings, name, "ALL")
        for name in ("invoices", "surveys", "work_hours", "ops")
    ]

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for cf in csv_files:
            zf.write(cf, arcname=f"datasets/{cf.name}")
        for receipt in settings.receipts_dir.glob("*.html"):
            zf.write(receipt, arcname=f"receipts_a5/{receipt.name}")
        for chart in settings.charts_dir.glob("*.png"):
            zf.write(chart, arcname=f"charts/{chart.name}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad_file = zf.testzip()
        if bad_file is not None:
            raise RuntimeError(f"ZIP CRC verification failed on: {bad_file}")

    retention = int(settings.firm_config["alerts"]["backup_retention_days"])
    for old_zip in sorted(settings.backups_dir.glob("ann_firm_vault_*.zip"), reverse=True)[retention:]:
        old_zip.unlink(missing_ok=True)

    drive_status = upload_file_to_google_drive(settings, zip_path, settings.google_drive_vault_folder_id)
    return {
        "zip_path": zip_path,
        "zip_name": zip_path.name,
        "size_kb": round(zip_path.stat().st_size / 1024.0, 2),
        "drive_status": drive_status,
    }
