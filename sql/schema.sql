-- Ann & Associates Law Firm & Academy
-- Shared Managed Cloud PostgreSQL Schema (Production)
-- Wanted to import extension 
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- use generate_uuid_v4()


CREATE TABLE IF NOT EXISTS telegram_users_rbac (
    user_id SERIAL PRIMARY KEY,
    full_name TEXT NOT NULL,
    telegram_chat_id TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('executive', 'supervisor', 'admin')),
    department TEXT NOT NULL DEFAULT 'ALL',
    subscriptions_json TEXT NOT NULL DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academy_invoices (
    id SERIAL PRIMARY KEY,
    receipt_no TEXT UNIQUE NOT NULL,
    khmer_name TEXT NOT NULL,
    latin_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    course_title TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    total_usd NUMERIC(10, 2) NOT NULL,
    total_khr INTEGER NOT NULL,
    issued_at TEXT NOT NULL,
    UNIQUE(email, course_title)
);

CREATE TABLE IF NOT EXISTS firm_surveys (
    survey_id SERIAL PRIMARY KEY,
    respondent_name TEXT NOT NULL,
    organization TEXT NOT NULL,
    chamber TEXT NOT NULL,
    event_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'Academy',
    rating NUMERIC(3, 2) NOT NULL,
    requested_topic TEXT NOT NULL,
    feedback TEXT,
    loaded_at TEXT NOT NULL,
    UNIQUE(respondent_name, event_name)
);

CREATE TABLE IF NOT EXISTS client_ops_intake (
    intake_id SERIAL PRIMARY KEY,
    client_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone_e164 TEXT NOT NULL,
    practice_area TEXT NOT NULL,
    urgency TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    UNIQUE(email, practice_area)
);

CREATE TABLE IF NOT EXISTS employee_work_hours (
    scan_id SERIAL PRIMARY KEY,
    employee_code TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    role_type TEXT NOT NULL CHECK (role_type IN ('Employee', 'Intern')),
    department TEXT NOT NULL,
    work_date TEXT NOT NULL,
    check_in_at TEXT,
    check_out_at TEXT,
    hours_worked NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    status_flag TEXT NOT NULL DEFAULT 'ON_TIME',
    updated_at TEXT NOT NULL,
    UNIQUE(employee_code, work_date)
);

CREATE TABLE IF NOT EXISTS quarantine_logs (
    quarantine_id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    rejection_reason TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    UNIQUE(category, raw_payload, rejection_reason)
);

CREATE TABLE IF NOT EXISTS pipeline_run_logs (
    run_id SERIAL PRIMARY KEY,
    run_timestamp TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    status TEXT NOT NULL,
    invoice_count INTEGER NOT NULL,
    invoice_revenue_usd NUMERIC(12, 2) NOT NULL,
    survey_count INTEGER NOT NULL,
    survey_avg_rating NUMERIC(4, 2) NOT NULL,
    ops_count INTEGER NOT NULL,
    active_scans_today INTEGER NOT NULL,
    quarantine_count INTEGER NOT NULL,
    backup_file TEXT NOT NULL
);
