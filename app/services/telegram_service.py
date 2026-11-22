import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.backups import create_verified_zip_bundle, export_clean_csv
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart


class TelegramRBACService:
    def __init__(self, db: DatabaseAdapter, settings: AppSettings):
        self.db = db
        self.settings = settings
        self.token = settings.telegram_bot_token

    @property
    def enabled(self) -> bool:
        return bool(self.token and "replace_with" not in self.token)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def get_user(self, chat_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = self.db.fetch_one(
                conn,
                "SELECT * FROM telegram_users_rbac WHERE telegram_chat_id = %s",
                (str(chat_id),),
            )
        if not row or not row.get("is_active"):
            return None
        row["subscriptions"] = json.loads(row.get("subscriptions_json") or "[]")
        return row

    def resolve_recipients(self, subscription: str, department: str | None = None) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            rows = self.db.fetch_all(conn, "SELECT * FROM telegram_users_rbac")
        matched = []
        for r in rows:
            if not r.get("is_active"):
                continue
            subs = json.loads(r.get("subscriptions_json") or "[]")
            if subscription not in subs:
                continue
            if department and r["department"] != "ALL" and r["department"].lower() != department.lower():
                continue
            r["subscriptions"] = subs
            matched.append(r)
        return matched

    def keyboard_for_role(self, role: str) -> dict[str, Any]:
        if role == "executive":
            return {
                "inline_keyboard": [
                    [{"text": "Survey Chart & Insights", "callback_data": "btn_survey"}],
                    [
                        {"text": "Academy Invoices & Rev", "callback_data": "btn_invoices"},
                        {"text": "Work-Hour Scan Report", "callback_data": "btn_attendance"},
                    ],
                    [
                        {"text": "Download Clean CSVs", "callback_data": "btn_csv_surveys"},
                        {"text": "Download Verified ZIP", "callback_data": "btn_zip"},
                    ],
                    [{"text": "Run Cloud Sync & Refresh", "callback_data": "btn_run_sync"}],
                ]
            }
        if role == "supervisor":
            return {
                "inline_keyboard": [
                    [{"text": "Dept Survey Chart", "callback_data": "btn_survey"}],
                    [
                        {"text": "Team Work-Hour Scans", "callback_data": "btn_attendance"},
                        {"text": "Team Attendance CSV", "callback_data": "btn_csv_attendance"},
                    ],
                ]
            }
        return {
            "inline_keyboard": [
                [
                    {"text": "Cloud Health & Quarantine", "callback_data": "btn_health"},
                    {"text": "Download Verified ZIP", "callback_data": "btn_zip"},
                ],
                [{"text": "Trigger Full Cloud Sync", "callback_data": "btn_run_sync"}],
            ]
        }

    async def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
        if not self.enabled:
            return False
        import httpx
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text[:4000]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(self._url("sendMessage"), json=payload)
            return resp.status_code == 200

    async def send_photo(self, chat_id: str, photo_path: Path, caption: str) -> bool:
        if not self.enabled or not photo_path.exists():
            return False
        import httpx
        async with httpx.AsyncClient(timeout=25) as client:
            with open(photo_path, "rb") as f:
                resp = await client.post(
                    self._url("sendPhoto"),
                    data={"chat_id": str(chat_id), "caption": caption[:1020]},
                    files={"photo": (photo_path.name, f, "image/png")},
                )
            return resp.status_code == 200

    async def send_document(self, chat_id: str, file_path: Path, caption: str) -> bool:
        if not self.enabled or not file_path.exists():
            return False
        import httpx
        async with httpx.AsyncClient(timeout=35) as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    self._url("sendDocument"),
                    data={"chat_id": str(chat_id), "caption": caption[:1020]},
                    files={"document": (file_path.name, f, "application/octet-stream")},
                )
            return resp.status_code == 200

    async def notify_subscription(self, subscription: str, text: str, department: str | None = None, photo_path: Path | None = None) -> int:
        recipients = self.resolve_recipients(subscription, department)
        sent = 0
        for r in recipients:
            cid = r["telegram_chat_id"]
            ok = await (self.send_photo(cid, photo_path, text) if photo_path else self.send_message(cid, text))
            if ok:
                sent += 1
        return sent

    async def handle_command(self, chat_id: str, action: str) -> dict[str, Any]:
        user = self.get_user(chat_id)
        if not user:
            await self.send_message(chat_id, "Access denied. Authorized Ann & Associates personnel only (BAKC RBAC).")
            return {"authorized": False}

        role = user["role"]
        dept = user["department"]
        kb = self.keyboard_for_role(role)

        if action in ("/start", "/menu"):
            await self.send_message(
                chat_id,
                f"ANN & ASSOCIATES LAW FIRM & ACADEMY\n"
                f"Welcome {user['full_name']} ({role.upper()} | Scope: {dept})\n\n"
                f"Select a real-time report or download below:",
                reply_markup=kb,
            )
            return {"authorized": True, "action": "menu"}

        if action in ("/survey", "btn_survey"):
            chart = generate_survey_chart(self.db, self.settings, dept)
            with self.db.connection() as conn:
                if dept == "ALL":
                    stats = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating),2),0) AS avg_r FROM firm_surveys")
                    fb = self.db.fetch_all(conn, "SELECT respondent_name, chamber, rating, feedback FROM firm_surveys WHERE feedback != '' ORDER BY survey_id DESC LIMIT 3")
                else:
                    stats = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating),2),0) AS avg_r FROM firm_surveys WHERE department = %s", (dept,))
                    fb = self.db.fetch_all(conn, "SELECT respondent_name, chamber, rating, feedback FROM firm_surveys WHERE department = %s AND feedback != '' ORDER BY survey_id DESC LIMIT 3", (dept,))
            fb_lines = "\n".join(f"• {r['respondent_name']} ({r['chamber']}, {r['rating']}/5): \"{r['feedback']}\"" for r in fb) or "• No written feedback yet."
            await self.send_photo(
                chat_id, chart,
                f"Survey Intelligence ({dept}) — {stats['cnt']} Responses | Avg {stats['avg_r']}/5.0",
            )
            await self.send_message(chat_id, f"Latest Client Feedback:\n\n{fb_lines}", reply_markup=kb)
            return {"authorized": True, "action": "survey"}

        if action in ("/invoices", "btn_invoices"):
            fx = int(self.settings.firm_config["organization"]["currency_fx_khr"])
            chart = generate_revenue_and_attendance_chart(self.db, self.settings)
            with self.db.connection() as conn:
                tot = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_usd),0) AS rev FROM academy_invoices")
            rev = float(tot["rev"])
            await self.send_photo(
                chat_id, chart,
                f"ANN & ASSOCIATES ACADEMY\nInvoices Issued: {tot['cnt']}\nTotal Revenue: ${rev:,.2f} ({int(rev * fx):,} KHR)",
            )
            await self.send_message(chat_id, "Choose next action:", reply_markup=kb)
            return {"authorized": True, "action": "invoices"}

        if action in ("/attendance", "btn_attendance"):
            today = datetime.now(self.settings.tz).strftime("%Y-%m-%d")
            with self.db.connection() as conn:
                if dept == "ALL":
                    rows = self.db.fetch_all(conn, "SELECT employee_name, role_type, department, check_in_at, check_out_at, hours_worked, status_flag FROM employee_work_hours WHERE work_date = %s ORDER BY check_in_at ASC", (today,))
                else:
                    rows = self.db.fetch_all(conn, "SELECT employee_name, role_type, department, check_in_at, check_out_at, hours_worked, status_flag FROM employee_work_hours WHERE work_date = %s AND department = %s ORDER BY check_in_at ASC", (today, dept))
            lines = "\n".join(
                f"• {r['employee_name']} ({r['role_type']} - {r['department']}): In {(r['check_in_at'] or '-')[-8:]} | Out {(r['check_out_at'] or 'Active')[-8:]} | {r['hours_worked']}h [{r['status_flag']}]"
                for r in rows
            ) or "• No QR scans recorded yet today."
            await self.send_message(chat_id, f"Live QR Work-Hour Report ({today} | {dept}):\n\n{lines}", reply_markup=kb)
            return {"authorized": True, "action": "attendance"}

        if action in ("btn_csv_surveys", "/csv"):
            csv_file = export_clean_csv(self.db, self.settings, "surveys", dept)
            await self.send_document(chat_id, csv_file, f"Clean Survey Dataset ({dept})")
            return {"authorized": True, "action": "csv_surveys"}

        if action == "btn_csv_attendance":
            csv_file = export_clean_csv(self.db, self.settings, "work_hours", dept)
            await self.send_document(chat_id, csv_file, f"Clean Work-Hours Dataset ({dept})")
            return {"authorized": True, "action": "csv_attendance"}

        if action in ("/zip", "btn_zip") and role in ("executive", "admin"):
            bundle = create_verified_zip_bundle(self.db, self.settings)
            await self.send_document(
                chat_id, bundle["zip_path"],
                f"Verified Firm Backup ZIP ({bundle['size_kb']} KB)\nVault: {bundle['drive_status']}",
            )
            return {"authorized": True, "action": "zip"}

        if action in ("/health", "btn_health") and role in ("executive", "admin"):
            with self.db.connection() as conn:
                q = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")
                last = self.db.fetch_one(conn, "SELECT * FROM pipeline_run_logs ORDER BY run_id DESC LIMIT 1")
            last_txt = f"Run #{last['run_id']} ({last['run_timestamp']}) — {last['status']} | Backup: {last['backup_file']}" if last else "No scheduled runs yet."
            await self.send_message(
                chat_id,
                f"Cloud Engine Health & Quarantine Status\n• Engine DB: {'Cloud PostgreSQL' if self.db.is_postgres else 'Local SQLite'}\n• Quarantined Rows: {q['cnt']}\n• Latest Run: {last_txt}",
                reply_markup=kb,
            )
            return {"authorized": True, "action": "health"}

        if action in ("/run", "btn_run_sync") and role in ("executive", "admin"):
            chart = generate_survey_chart(self.db, self.settings, "ALL")
            generate_revenue_and_attendance_chart(self.db, self.settings)
            bundle = create_verified_zip_bundle(self.db, self.settings)
            await self.send_photo(chat_id, chart, f"Cloud Sync Complete! Verified ZIP: {bundle['zip_name']} ({bundle['size_kb']} KB)")
            await self.send_message(chat_id, "Ready for next command:", reply_markup=kb)
            return {"authorized": True, "action": "run_sync"}

        await self.send_message(chat_id, "Use the role menu buttons below:", reply_markup=kb)
        return {"authorized": True, "action": "fallback"}
