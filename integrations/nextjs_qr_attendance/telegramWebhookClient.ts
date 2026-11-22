/**
 * Drop into: D:\lawfirm-attendee-system\qr-scan-attendance-v2\src\server\notifications\cloudEngineClient.ts
 * Fires immediately after Prisma writes an Employee/Intern QR scan.
 */

export interface QRScanWebhookPayload {
  employee_code: string;
  employee_name: string;
  role_type: "Employee" | "Intern";
  department: string;
  action: "CHECK_IN" | "CHECK_OUT";
  scanned_at?: string;
}

export async function pushQRScanToCloudEngine(payload: QRScanWebhookPayload): Promise<void> {
  const baseUrl = process.env.ANN_CLOUD_ENGINE_URL;
  const secret = process.env.ANN_CLOUD_WEBHOOK_SECRET;

  if (!baseUrl || !secret) {
    console.warn("[CloudEngine] ANN_CLOUD_ENGINE_URL or ANN_CLOUD_WEBHOOK_SECRET missing; skipping live alert.");
    return;
  }

  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, "")}/webhooks/qr-scan`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Firm-Secret": secret,
      },
      body: JSON.stringify({
        ...payload,
        scanned_at: payload.scanned_at ?? new Date().toISOString(),
      }),
      signal: AbortSignal.timeout(8000),
    });

    if (!res.ok) {
      console.error(`[CloudEngine] Webhook returned ${res.status}: ${await res.text()}`);
    }
  } catch (err) {
    console.error("[CloudEngine] Failed to push QR scan alert:", err);
  }
}
