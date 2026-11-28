import base64
import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import AppSettings

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "img" / "law-firm-logo-receipt.png"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")


def generate_a5_receipt_html(settings: AppSettings, rec: dict[str, Any]) -> Path:
    org = settings.firm_config["organization"]
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", str(rec["latin_name"])).strip("_") or "TRAINEE"
    out_file = settings.receipts_dir / f"{rec['receipt_no']}_{safe_name}.html"
    esc = lambda v: html.escape(str(v))  # noqa: E731
    logo = _logo_data_uri()
    logo_html = f'<img class="logo" src="{logo}" alt="{esc(org["name_en"])}">' if logo else f'<div class="en">{esc(org["name_en"])}</div>'

    content = f'''<!DOCTYPE html>
<html lang="km"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(rec['receipt_no'])} - {esc(org['name_en'])}</title>
<style>
  @page {{ size: A5 landscape; margin: 8mm 10mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Khmer OS Siemreap','Noto Sans Khmer','Segoe UI',Arial,sans-serif; font-size: 10pt; color: #0f1b33;
          max-width: 210mm; margin: 12px auto; padding: 14px 16px; border: 1px solid #cdc7ba; position: relative; background: #fff; }}
  .hdr {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; border-bottom: 2px solid #b8893a;
          padding-bottom: 8px; margin-bottom: 10px; }}
  .logo {{ display: block; width: 62mm; max-width: 100%; height: auto; }}
  .en {{ font-size: 11pt; font-weight: 700; color: #1b2a49; }}
  .km {{ font-size: 9pt; color: #3d4a5f; margin-top: 3px; }}
  .addr {{ font-size: 8pt; text-align: right; color: #3d4a5f; line-height: 1.45; }}
  .doc {{ text-align: center; font-size: 11pt; font-weight: 700; color: #1b2a49; letter-spacing: 0.04em; margin: 8px 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; font-size: 9pt; }}
  .meta td {{ padding: 3px 0; vertical-align: top; }}
  .items th, .items td {{ border: 1px solid #cdc7ba; padding: 6px 8px; }}
  .items th {{ background: #f6efe0; color: #1b2a49; text-align: left; }}
  .num {{ text-align: right; white-space: nowrap; }}
  .stamp {{ position: absolute; right: 56mm; bottom: 17mm; border: 3px solid #1b2a49; color: #1b2a49; font-size: 16pt;
            font-weight: 800; padding: 3px 12px; border-radius: 4px; transform: rotate(-12deg); opacity: 0.7; letter-spacing: 2px; }}
  .ftr {{ display: flex; justify-content: space-between; gap: 12px; font-size: 8.2pt; color: #3d4a5f; }}
  .sign {{ text-align: center; min-width: 48mm; }}
  .sign div {{ margin-top: 22px; border-top: 1px solid #3d4a5f; padding-top: 2px; }}
  @media print {{ body {{ border: none; margin: 0; padding: 0; }} }}
</style></head><body>
  <div class="hdr">
    <div>{logo_html}<div class="km">{esc(org['name_km'])}</div></div>
    <div class="addr">{esc(org['address'])}<br>Tel: {esc(org['phone'])} | Web: {esc(org['website'])}</div>
  </div>
  <div class="doc">វិក្កយបត្រ និង បង្កាន់ដៃទទួលប្រាក់ / INVOICE &amp; PAYMENT RECEIPT</div>
  <table class="meta">
    <tr><td><strong>ឈ្មោះ / Name:</strong> {esc(rec['khmer_name'])} ({esc(rec['latin_name'])})</td>
        <td><strong>លេខបង្កាន់ដៃ / Receipt:</strong> {esc(rec['receipt_no'])}</td></tr>
    <tr><td><strong>ទូរស័ព្ទ / Phone:</strong> {esc(rec['phone_e164'])}</td>
        <td><strong>បង់ជា / Method:</strong> {esc(rec['payment_method'])} | {esc(str(rec['issued_at'])[:10])}</td></tr>
  </table>
  <table class="items">
    <thead><tr><th>បរិយាយ / Description</th><th class="num" style="width:18%;">USD</th><th class="num" style="width:22%;">KHR</th></tr></thead>
    <tbody><tr><td>{esc(rec['course_title'])}</td><td class="num"><strong>${float(rec['total_usd']):.2f}</strong></td><td class="num"><strong>{int(rec['total_khr']):,} ៛</strong></td></tr></tbody>
  </table>
  <div class="stamp">PAID</div>
  <div class="ftr">
    <div>សូមរក្សាបង្កាន់ដៃទុករហូតដល់ចប់វគ្គសិក្សា។ <strong>បង់ប្រាក់រួចមិនអាចដកវិញបានទេ។</strong><br>Issued: {esc(rec['issued_at'])}</div>
    <div class="sign"><strong>អ្នកទទួលប្រាក់ / Cashier</strong><div>Ann &amp; Associates</div></div>
  </div>
</body></html>'''
    out_file.write_text(content, encoding="utf-8")
    return out_file
