import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.config import AppSettings

SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS telegram_users_rbac (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    telegram_chat_id TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('executive', 'supervisor', 'admin')),
    department TEXT NOT NULL DEFAULT 'ALL',
    subscriptions_json TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS academy_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no TEXT UNIQUE NOT NULL,
    khmer_name TEXT NOT NULL,
    latin_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    course_title TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    total_usd REAL NOT NULL,
    total_khr INTEGER NOT NULL,
    issued_at TEXT NOT NULL,
    UNIQUE(email, course_title)
);

CREATE TABLE IF NOT EXISTS firm_surveys (
    survey_id INTEGER PRIMARY KEY AUTOINCREMENT,
    respondent_name TEXT NOT NULL,
    organization TEXT NOT NULL,
    chamber TEXT NOT NULL,
    event_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'Academy',
    rating REAL NOT NULL,
    requested_topic TEXT NOT NULL,
    feedback TEXT,
    loaded_at TEXT NOT NULL,
    UNIQUE(respondent_name, event_name)
);

CREATE TABLE IF NOT EXISTS client_ops_intake (
    intake_id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    practice_area TEXT NOT NULL,
    urgency TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    UNIQUE(email, practice_area)
);

CREATE TABLE IF NOT EXISTS employee_work_hours (
    scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    role_type TEXT NOT NULL CHECK (role_type IN ('Employee', 'Intern')),
    department TEXT NOT NULL,
    work_date TEXT NOT NULL,
    check_in_at TEXT,
    check_out_at TEXT,
    hours_worked REAL NOT NULL DEFAULT 0.0,
    status_flag TEXT NOT NULL DEFAULT 'ON_TIME',
    updated_at TEXT NOT NULL,
    UNIQUE(employee_code, work_date)
);

CREATE TABLE IF NOT EXISTS quarantine_logs (
    quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    rejection_reason TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    UNIQUE(category, raw_payload, rejection_reason)
);

CREATE TABLE IF NOT EXISTS pipeline_run_logs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    invoice_count INTEGER NOT NULL,
    invoice_revenue_usd REAL NOT NULL,
    survey_count INTEGER NOT NULL,
    survey_avg_rating REAL NOT NULL,
    ops_count INTEGER NOT NULL,
    active_scans_today INTEGER NOT NULL,
    quarantine_count INTEGER NOT NULL,
    backup_file TEXT NOT NULL
);
'''


class DatabaseAdapter:
    '''Unified DB layer: Managed Cloud PostgreSQL (psycopg) in prod, SQLite for local tests.'''

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.url = settings.database_url
        self.is_postgres = self.url.startswith("postgresql://") or self.url.startswith("postgres://")

    def _sqlite_path(self) -> Path:
        raw = self.url.replace("sqlite:///", "", 1)
        p = Path(raw)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self.is_postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self.url, row_factory=dict_row)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self._sqlite_path())
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def adapt_sql(self, sql: str) -> str:
        if self.is_postgres:
            return sql
        return sql.replace("%s", "?")

    def execute(self, conn: Any, sql: str, params: tuple = ()) -> Any:
        cur = conn.cursor()
        cur.execute(self.adapt_sql(sql), params)
        return cur

    def fetch_all(self, conn: Any, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cur = self.execute(conn, sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def fetch_one(self, conn: Any, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cur = self.execute(conn, sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def init_schema_and_seed_rbac(self) -> None:
        with self.connection() as conn:
            if self.is_postgres:
                schema_sql = (self.settings.root_dir / "sql" / "schema.sql").read_text(encoding="utf-8")
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
            else:
                conn.executescript(SQLITE_SCHEMA)

            if self.settings.rbac_seed_path.exists():
                seed = json.loads(self.settings.rbac_seed_path.read_text(encoding="utf-8-sig"))
                now_str = datetime.now(self.settings.tz).strftime("%Y-%m-%d %H:%M:%S")
                for u in seed.get("users", []):
                    self.execute(
                        conn,
                        '''
                        INSERT INTO telegram_users_rbac (
                            full_name, telegram_chat_id, role, department, subscriptions_json, is_active, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (telegram_chat_id) DO NOTHING
                        ''',
                        (
                            u["full_name"],
                            str(u["telegram_chat_id"]),
                            u["role"],
                            u.get("department", "ALL"),
                            json.dumps(u.get("subscriptions", [])),
                            True if self.is_postgres else (1 if u.get("is_active", True) else 0),
                            now_str,
                        ),
                    )
