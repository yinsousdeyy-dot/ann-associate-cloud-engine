# Ann & Associates Law Firm & Academy — Cloud Automation & Distributed Telegram Engine

Production-ready, firm-owned cloud architecture unifying:
1. **Real-Time Producers:** Google Forms (`surveys`, `academy`, `ops`), Next.js QR Attendance App (`qr-scan-attendance-v2`), and Firm Cloud Drive.
2. **Firm Cloud Subscription:** Managed Cloud PostgreSQL + Always-On FastAPI Cloud Engine (webhooks, Matplotlib PNG charts, bilingual A5 USD/KHR receipts, clean CSV datasets, verified ZIP vault, and scheduled daily reports in `Asia/Phnom_Penh`).
3. **Distributed Role-Based Telegram Ops:** Dedicated mobile control center tailored for **Bong Philen** (Executive), **Distributed Supervisors** (department-scoped), and **IT & Data Admin** (quarantine & cloud health).

## Quick Start (Docker Compose — Local or Firm VPS)
```bash
cp .env.example .env
# Edit .env with firm Telegram Bot Token, secrets, and real chat IDs in config/rbac_seed.json
docker compose up -d --build
curl http://localhost:8080/health
```

## this is not current available
## Deploy to Google Cloud Run (Recommended for Google Workspace Firms)
```bash
gcloud run deploy ann-associates-cloud-engine \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --set-env-vars TIMEZONE=Asia/Phnom_Penh
```

Register the Telegram Webhook once deployed:
```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://<YOUR_CLOUD_RUN_URL>/webhooks/telegram","secret_token":"<TELEGRAM_WEBHOOK_SECRET>"}'
```
