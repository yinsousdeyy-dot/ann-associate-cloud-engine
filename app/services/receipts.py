import html
import re
from pathlib import Path
from typing import Any

from app.config import AppSettings


def generate_a5_receipt_html(settings: AppSettings, rec: dict[str, Any]) -> Path:
    org = settings.firm_config["organization"]
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", str(rec["latin_name"])).strip("_") or "TRAINEE"
    out_file = settings.receipts_dir / f"{rec['receipt_no']}_{safe_name}.html"

    content = f'''<!DOCTYPE html>
<html lang="km"><head><meta charset="UTF-8">
<title>{html.escape(str(rec['receipt_no']))} - {html.escape(org['name_en'])}</title>
<style>
  @page {{ size: A5 landscape; margin: 8mm 10mm; }}
  body {{ font-family: 'Khmer OS Siemreap','Noto Sans Khmer','Segoe UI',Arial,sans-serif;
          font-size: 10pt; color: #1f2937; max-width: 210mm; margin: 12px auto; padding: 14px;
          border: 1px solid #d1d5db; position: relative; }}
  .hdr {{ display:flex; justify-content:space-between; border-bottom:2px solid #14532d; padding-bottom:6px; margin-bottom:10px; }}
  .km {{ font-size:13pt; font-weight:700; color:#14532d; }}
  .en {{ font-size:10pt; font-weight:700; color:#166534; }}
  .addr {{ font-size:8pt; text-align:right; color:#374151; line-height:1.4; }}
  .doc {{ text-align:center; font-size:11pt; font-weight:700; text-decoration:underline; margin:8px 0 10px 0; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:10px; font-size:9pt; }}
  .items th, .items td {{ border:1px solid #9ca3af; padding:5px 7px; }}
  .items th {{ background:#f0fdf4; color:#14532d; }}
  .num {{ text-align:right; }}
  .stamp {{ position:absolute; right:58mm; bottom:18mm; border:3px solid #1d4ed8; color:#1d4ed8;
            font-size:16pt; font-weight:800; padding:3px 12px; border-radius:4px;
            transform:rotate(-12deg); opacity:0.72; letter-spacing:2px; }}
  .ftr {{ display:flex; justify-content:space-between; font-size:8.2pt; }}
  @media print {{ body {{ border:none; margin:0; padding:0; }} }}
</style></head><body>
  <div class="hdr">
    <div><div class="km">{html.escape(org['name_km'])}</div><div class="en">{html.escape(org['name_en'])}</div></div>
    <div class="addr">{html.escape(org['address'])}<br>Tel: {html.escape(org['phone'])} | Web: {html.escape(org['website'])}</div>
  </div>
  <div class="doc">វិក្កយបត្រ និង បង្កាន់ដៃទទួលប្រាក់ / INVOICE &amp; PAYMENT RECEIPT</div>
  <table>
    <tr><td><strong>ឈ្មោះ / Name:</strong> {html.escape(str(rec['khmer_name']))} ({html.escape(str(rec['latin_name']))})</td>
        <td><strong>លេខបង្កាន់ដៃ / Receipt:</strong> {html.escape(str(rec['receipt_no']))}</td></tr>
    <tr><td><strong>ទូរស័ព្ទ / Phone:</strong> {html.escape(str(rec['phone_e164']))}</td>
        <td><strong>បង់ជា / Method:</strong> {html.escape(str(rec['payment_method']))} | {html.escape(str(rec['issued_at'])[:10])}</td></tr>
  </table>
  <table class="items">
    <thead><tr><th style="text-align:left;">បរិយាយ / Description</th><th style="width:18%;">USD</th><th style="width:22%;">KHR</th></tr></thead>
    <tbody><tr><td>{html.escape(str(rec['course_title']))}</td><td class="num"><strong>${float(rec['total_usd']):.2f}</strong></td><td class="num"><strong>{int(rec['total_khr']):,} ៛</strong></td></tr></tbody>
  </table>
  <div class="stamp">PAID</div>
  <div class="ftr">
    <div>សូមរក្សាបង្កាន់ដៃទុករហូតដល់ចប់វគ្គសិក្សា។ <strong>បង់ប្រាក់រួចមិនអាចដកវិញបានទេ។</strong><br>Issued: {html.escape(str(rec['issued_at']))}</div>
    <div style="text-align:center;"><strong>អ្នកទទួលប្រាក់ / Cashier</strong><div style="margin-top:22px;border-top:1px solid #374151;">Ann &amp; Associates</div></div>
  </div>
</body></html>'''
    out_file.write_text(content, encoding="utf-8")
    return out_file
