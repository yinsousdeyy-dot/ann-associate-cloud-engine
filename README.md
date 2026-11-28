# Ann & Associates Law Firm & Academy — Cloud Automation & Distributed Telegram Engine

Production-ready, firm-owned cloud architecture unifying:
1. **Real-Time Producers:** Google Forms (`surveys`, `academy`, `ops`), Next.js QR Attendance App (`qr-scan-attendance-v2`), and Firm Cloud Drive.
2. **Firm Cloud Subscription:** Managed Cloud PostgreSQL + Always-On FastAPI Cloud Engine (webhooks, Matplotlib PNG charts, bilingual A5 USD/KHR receipts, clean CSV datasets, verified ZIP vault, and scheduled daily reports in `Asia/Phnom_Penh`).
3. **Interactive Operations Command Hub:** Modern, responsive 8-tab operations dashboard for live task execution (QR scans, course enrollments, client intake, quarantine auditing, and Telegram bot simulation).
4. **Distributed Role-Based Telegram Ops:** Dedicated mobile control center tailored for **Bong Philen** (Executive), **Distributed Supervisors** (department-scoped), and **IT & Data Admin** (quarantine & cloud health).

---

## Quick Start (Local Run with Interactive UI)

### 1. Run the Local Engine
```powershell
.\.venv\Scripts\python run.py
```
This automatically initializes the database schema, seeds RBAC users, ingests initial sample data if empty, and launches the server:
- **Operations Hub:** `http://localhost:8000/dashboard` (or visit `http://localhost:8000/`). Sign in with `DASHBOARD_ACCESS_TOKEN` from `.env`; it is entered on the sign-in form and never goes in the URL.
- **Health Endpoint:** `http://localhost:8000/health`

### 2. Run the Full Test Suite
```powershell
.\.venv\Scripts\pytest -v
```
All unit, integration, validation, and API tests will run and verify the core pipeline, webhook authentication, receipt generation, and Telegram RBAC commands.

---

## Real-Time Tasking in the Web UI

| Tab / Station | Real-Time Task Capability |
| :--- | :--- |
| **📊 Executive Hub** | Live KPIs (Academy revenue in USD & KHR, survey ratings, scans today, quarantined items), Matplotlib analytics charts, and recent invoices feed. |
| **⏱️ QR Attendance Station** | Check-In & Check-Out simulation for employees and interns with auto-calculated hours worked and status tags (`ON_TIME`, `LATE`, `EARLY_LEAVE`). |
| **🎓 Academy & Invoices** | Student enrollment with auto-calculated KHR conversions (4,000 KHR/USD), ABA KHQR tracking, and instant official **Bilingual A5 HTML Receipt** generator with direct view & print links. |
| **📋 Client Surveys** | Seminar and client feedback submission with auto-detection of low ratings (`< 3.5`) and immediate chart refreshes. |
| **⚖️ SME Legal Intake** | Corporate and startup legal consultation intake with E.164 phone normalization (`+855...`). |
| **🛡️ Quarantine Gate** | Real-time audit log of malformed/corrupted submissions (bad emails, invalid phones, negative prices) with raw JSON payload inspection. |
| **📦 Vault & Exports** | One-click CRC-verified ZIP archive bundle creation, direct ZIP download, and clean CSV dataset downloads. |
| **🤖 Telegram Bot Simulator** | Interactive mobile bot simulator allowing testing of commands (`/start`, `/survey`, `/invoices`, `/attendance`, `/csv`, `/zip`, `/health`, `/run`) across RBAC roles. |

---

## Docker Compose (Local or Firm VPS)
```bash
cp .env.example .env
# Edit .env with firm Telegram Bot Token, secrets, and real chat IDs in config/rbac_seed.json
docker compose up -d --build
curl http://localhost:8000/health
```

---

## Telegram Bot Polling Mode (Optional Local/VPS)
To run the Telegram bot without a public HTTPS webhook domain:
```powershell
.\.venv\Scripts\python -m app.bot_polling
```
