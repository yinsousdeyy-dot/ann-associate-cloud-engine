import json
import logging
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.db import DatabaseAdapter
from app.services.backups import create_verified_zip_bundle, export_clean_csv
from app.services.charts import generate_revenue_and_attendance_chart, generate_survey_chart

logger = logging.getLogger("telegram_service")

# When set, send_* record the reply in `last_dispatched` but never call the Telegram API.
dry_run: ContextVar[bool] = ContextVar("telegram_dry_run", default=False)


class TelegramRBACService:
    def __init__(self, db: DatabaseAdapter, settings: AppSettings):
        self.db = db
        self.settings = settings
        self.token = settings.telegram_bot_token
        self.last_dispatched: dict[str, Any] | None = None

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
        self.last_dispatched = {
            "type": "message",
            "chat_id": str(chat_id),
            "text": text,
            "reply_markup": reply_markup,
            "timestamp": datetime.now(self.settings.tz).isoformat(),
        }
        if not self.enabled or dry_run.get():
            return True  # Recorded in last_dispatched only
        import httpx
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text[:4000]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self._url("sendMessage"), json=payload)
                return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to send Telegram message to {chat_id}: {exc}")
            return False

    async def send_photo(self, chat_id: str, photo_path: Path, caption: str) -> bool:
        self.last_dispatched = {
            "type": "photo",
            "chat_id": str(chat_id),
            "photo": photo_path.name if photo_path else None,
            "caption": caption,
            "timestamp": datetime.now(self.settings.tz).isoformat(),
        }
        if not self.enabled or dry_run.get() or not photo_path.exists():
            return True if photo_path and photo_path.exists() else False
        import httpx
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                with open(photo_path, "rb") as f:
                    resp = await client.post(
                        self._url("sendPhoto"),
                        data={"chat_id": str(chat_id), "caption": caption[:1020]},
                        files={"photo": (photo_path.name, f, "image/png")},
                    )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to send Telegram photo to {chat_id}: {exc}")
            return False

    async def send_document(self, chat_id: str, file_path: Path, caption: str) -> bool:
        self.last_dispatched = {
            "type": "document",
            "chat_id": str(chat_id),
            "document": file_path.name if file_path else None,
            "caption": caption,
            "timestamp": datetime.now(self.settings.tz).isoformat(),
        }
        if not self.enabled or dry_run.get() or not file_path.exists():
            return True if file_path and file_path.exists() else False
        import httpx
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        self._url("sendDocument"),
                        data={"chat_id": str(chat_id), "caption": caption[:1020]},
                        files={"document": (file_path.name, f, "application/octet-stream")},
                    )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning(f"Failed to send Telegram document to {chat_id}: {exc}")
            return False

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
            msg = (
                "Access denied. Authorized Ann & Associates personnel only (BAKC RBAC).\n"
                f"Your chat ID is {chat_id}. Send it to the firm administrator to request access."
            )
            await self.send_message(chat_id, msg)
            return {"authorized": False, "message": msg}

        role = user["role"]
        dept = user["department"]
        kb = self.keyboard_for_role(role)

        # Normalize action (strip @bot_name if present)
        if action.startswith("/"):
            action = action.split("@")[0]

        if action in ("/start", "/menu"):
            msg = (
                f"ANN & ASSOCIATES LAW FIRM & ACADEMY\n"
                f"Welcome {user['full_name']} ({role.upper()} | Scope: {dept})\n\n"
                f"Select a real-time report or download below:"
            )
            await self.send_message(chat_id, msg, reply_markup=kb)
            return {"authorized": True, "action": "menu", "message": msg}

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
            cnt_val = stats["cnt"] if stats else 0
            avg_val = stats["avg_r"] if stats else 0.0
            caption = f"Survey Intelligence ({dept}) — {cnt_val} Responses | Avg {avg_val}/5.0"
            await self.send_photo(chat_id, chart, caption)
            fb_msg = f"Latest Client Feedback:\n\n{fb_lines}"
            await self.send_message(chat_id, fb_msg, reply_markup=kb)
            return {"authorized": True, "action": "survey", "message": f"{caption}\n\n{fb_msg}", "photo": chart.name}

        if action in ("/invoices", "btn_invoices"):
            fx = int(self.settings.firm_config["organization"]["currency_fx_khr"])
            chart = generate_revenue_and_attendance_chart(self.db, self.settings)
            with self.db.connection() as conn:
                tot = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_usd),0) AS rev FROM academy_invoices")
            rev = float(tot["rev"]) if tot else 0.0
            cnt = tot["cnt"] if tot else 0
            caption = f"ANN & ASSOCIATES ACADEMY\nInvoices Issued: {cnt}\nTotal Revenue: ${rev:,.2f} ({int(rev * fx):,} KHR)"
            await self.send_photo(chat_id, chart, caption)
            await self.send_message(chat_id, "Choose next action:", reply_markup=kb)
            return {"authorized": True, "action": "invoices", "message": caption, "photo": chart.name}

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
            msg = f"Live QR Work-Hour Report ({today} | {dept}):\n\n{lines}"
            await self.send_message(chat_id, msg, reply_markup=kb)
            return {"authorized": True, "action": "attendance", "message": msg}

        if action in ("btn_csv_surveys", "/csv"):
            csv_file = export_clean_csv(self.db, self.settings, "surveys", dept)
            msg = f"Clean Survey Dataset ({dept})"
            await self.send_document(chat_id, csv_file, msg)
            return {"authorized": True, "action": "csv_surveys", "message": msg, "document": csv_file.name}

        if action == "btn_csv_attendance":
            csv_file = export_clean_csv(self.db, self.settings, "work_hours", dept)
            msg = f"Clean Work-Hours Dataset ({dept})"
            await self.send_document(chat_id, csv_file, msg)
            return {"authorized": True, "action": "csv_attendance", "message": msg, "document": csv_file.name}

        if action in ("/zip", "btn_zip"):
            if role not in ("executive", "admin"):
                msg = "Access restricted: Verified ZIP downloads require Executive or Admin authorization."
                await self.send_message(chat_id, msg, reply_markup=kb)
                return {"authorized": True, "action": "restricted", "message": msg}
            bundle = create_verified_zip_bundle(self.db, self.settings)
            msg = f"Verified Firm Backup ZIP ({bundle['size_kb']} KB)\nVault: {bundle['drive_status']}"
            await self.send_document(chat_id, bundle["zip_path"], msg)
            return {"authorized": True, "action": "zip", "message": msg, "document": bundle["zip_name"]}

        if action in ("/health", "btn_health"):
            if role not in ("executive", "admin"):
                msg = "Access restricted: Health audits require Executive or Admin authorization."
                await self.send_message(chat_id, msg, reply_markup=kb)
                return {"authorized": True, "action": "restricted", "message": msg}
            with self.db.connection() as conn:
                q = self.db.fetch_one(conn, "SELECT COUNT(*) AS cnt FROM quarantine_logs")
                last = self.db.fetch_one(conn, "SELECT * FROM pipeline_run_logs ORDER BY run_id DESC LIMIT 1")
            q_cnt = q["cnt"] if q else 0
            last_txt = f"Run #{last['run_id']} ({last['run_timestamp']}) — {last['status']} | Backup: {last['backup_file']}" if last else "No scheduled runs yet."
            msg = f"Cloud Engine Health & Quarantine Status\n• Engine DB: {'Cloud PostgreSQL' if self.db.is_postgres else 'Local SQLite'}\n• Quarantined Rows: {q_cnt}\n• Latest Run: {last_txt}"
            await self.send_message(chat_id, msg, reply_markup=kb)
            return {"authorized": True, "action": "health", "message": msg}

        if action in ("/run", "btn_run_sync"):
            if role not in ("executive", "admin"):
                msg = "Access restricted: Cloud Sync trigger requires Executive or Admin authorization."
                await self.send_message(chat_id, msg, reply_markup=kb)
                return {"authorized": True, "action": "restricted", "message": msg}
            chart = generate_survey_chart(self.db, self.settings, "ALL")
            generate_revenue_and_attendance_chart(self.db, self.settings)
            bundle = create_verified_zip_bundle(self.db, self.settings)
            msg = f"Cloud Sync Complete! Verified ZIP: {bundle['zip_name']} ({bundle['size_kb']} KB)"
            await self.send_photo(chat_id, chart, msg)
            await self.send_message(chat_id, "Ready for next command:", reply_markup=kb)
            return {"authorized": True, "action": "run_sync", "message": msg, "photo": chart.name, "document": bundle["zip_name"]}

        msg = "Use the role menu buttons below:"
        await self.send_message(chat_id, msg, reply_markup=kb)
        return {"authorized": True, "action": "fallback", "message": msg}
