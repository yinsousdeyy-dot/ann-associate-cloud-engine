"""Server-rendered HTML for the operations hub and the sign-in page.

All styling lives in static/css/dashboard.css and all behaviour in static/js/dashboard.js. The CSP sent by
app/main.py forbids inline scripts, inline styles and inline event handlers, so none appear here.
Every value that reaches the page is escaped with html.escape.
"""
from html import escape
from typing import Any

from app.config import AppSettings
from app.models import MAX_PRICE_USD

DEPARTMENTS = [
    ("Corporate & Tax", "Corporate & Tax"),
    ("Litigation & Dispute", "Litigation & Dispute"),
    ("Academy", "Academy & Events"),
    ("IP & Technology", "IP & Technology"),
]
PRACTICE_AREAS = [
    ("Corporate & Tax", "Corporate & Tax"),
    ("Labor & Employment", "Labor & Employment"),
    ("Real Estate & Land", "Real Estate & Land"),
    ("Litigation & Dispute", "Litigation & Dispute"),
    ("IP & Technology", "IP & Technology"),
]
COURSES = [
    ("Double Your Productivity With AI", "Double Your Productivity With AI"),
    ("Compliance Talks 2026", "Compliance Talks 2026"),
    ("Corporate Tax Law Masterclass", "Corporate Tax Law Masterclass"),
    ("Cambodian Labor Law & NSSF Workshop", "Cambodian Labor Law & NSSF Workshop"),
]
PAYMENT_METHODS = [(m, m) for m in ("ABA KHQR", "Wing Bank", "Canadia Bank", "Cash USD/KHR")]
CHAMBERS = [(c, c) for c in ("EuroCham", "AmCham", "BritCham", "IBC", "Independent")]
TOPICS = [
    ("Tax & Customs", "Tax & Customs"),
    ("Corporate & M&A", "Corporate & M&A"),
    ("Labor & Employment", "Labor & Employment"),
    ("AI & Legal Tech", "AI & Legal Tech"),
    ("Real Estate & Land", "Real Estate & Land"),
]
URGENCIES = [
    ("Standard", "Standard (24 to 48 hours)"),
    ("High", "High (same day)"),
    ("Urgent", "Urgent (immediate)"),
]

LOGO = '<img src="/static/img/law-firm-logo.png" alt="Ann &amp; Associates Law Firm" width="960" height="180">'


def _field(fid: str, label: str, *, kind: str = "text", required: bool = True, hint: str = "", extra: str = "") -> str:
    desc = f' aria-describedby="{fid}-hint"' if hint else ""
    req = ' required aria-required="true"' if required else ""
    star = '<span class="req" aria-hidden="true">*</span>' if required else ""
    hint_html = f'<p class="field-hint" id="{fid}-hint">{escape(hint)}</p>' if hint else ""
    return (
        f'<div class="field"><label for="{fid}">{escape(label)}{star}</label>'
        f'<input id="{fid}" name="{fid}" type="{kind}"{req}{desc} {extra}>{hint_html}</div>'
    )


def _select(fid: str, label: str, options: list[tuple[str, str]]) -> str:
    opts = "".join(f'<option value="{escape(v)}">{escape(t)}</option>' for v, t in options)
    return f'<div class="field"><label for="{fid}">{escape(label)}</label><select id="{fid}" name="{fid}">{opts}</select></div>'


def _table(tid: str, caption: str, heads: list[tuple[str, str]], loading: str) -> str:
    ths = "".join(f'<th scope="col"{" class=\"num\"" if cls == "num" else ""}>{escape(h)}</th>' for h, cls in heads)
    return (
        f'<div class="table-wrap" tabindex="0" role="region" aria-label="{escape(caption)}">'
        f'<table class="data" id="{tid}"><caption class="sr-only">{escape(caption)}</caption>'
        f'<thead><tr>{ths}</tr></thead>'
        f'<tbody><tr><td class="empty" colspan="{len(heads)}">{escape(loading)}</td></tr></tbody></table></div>'
    )


def _form_foot(button: str) -> str:
    return (
        f'<div class="form-actions"><button type="submit" class="btn">{escape(button)}</button>'
        '<p class="form-status" role="status" aria-live="polite"></p></div>'
    )


def _panel(pid: str, title: str, intro: str, body: str) -> str:
    return (
        f'<section class="panel" id="{pid}" aria-labelledby="{pid}-title" hidden>'
        f'<header class="panel-head"><h2 id="{pid}-title" tabindex="-1">{escape(title)}</h2><p>{escape(intro)}</p></header>'
        f"{body}</section>"
    )


def render_login_html(settings: AppSettings, error: str = "", unconfigured: bool = False) -> str:
    org = escape(settings.firm_config["organization"]["name_en"].title())
    if unconfigured:
        inner = (
            '<div class="gate-msg is-info" role="alert">Sign-in is not set up on this server. '
            "Set DASHBOARD_ACCESS_TOKEN and WEBHOOK_SHARED_SECRET in the server environment, then restart the service.</div>"
        )
    else:
        msg = f'<div class="gate-msg" role="alert">{escape(error)}</div>' if error else ""
        inner = (
            f"{msg}"
            '<form method="post" action="/dashboard/login">'
            '<div class="field"><label for="token">Access token</label>'
            '<input id="token" name="token" type="password" autocomplete="current-password" required autofocus '
            'aria-describedby="token-hint"><p class="field-hint" id="token-hint">The token is set by the firm administrator.</p></div>'
            '<button type="submit" class="btn">Sign in</button></form>'
        )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>Sign in - {org}</title>"
        '<link rel="stylesheet" href="/static/css/dashboard.css"></head><body>'
        f'<main class="gate"><div class="gate-card">{LOGO}<h1>Operations hub</h1>'
        f"<p>Restricted to authorised staff of {org}.</p>{inner}</div></main></body></html>"
    )


def render_dashboard_html(settings: AppSettings, kpi: dict[str, Any]) -> str:
    org = settings.firm_config["organization"]
    name = escape(org["name_en"].title())
    fx = int(org["currency_fx_khr"])
    rev = float(kpi.get("revenue_usd", 0.0))
    khr = int(kpi.get("revenue_khr", 0))
    inv = int(kpi.get("invoice_count", 0))
    sv = int(kpi.get("survey_count", 0))
    avg = float(kpi.get("avg_rating", 0.0))
    scans = int(kpi.get("scans_today", 0))
    quarantined = int(kpi.get("quarantine_count", 0))
    db_label = "PostgreSQL" if settings.database_url.startswith("postgres") else "SQLite"
    demo = settings.demo_tools_enabled

    nav = [
        ("Overview", [("overview", "Overview")]),
        (
            "Operations",
            [("attendance", "Attendance"), ("academy", "Academy invoices"), ("surveys", "Client surveys"), ("intake", "Client intake")],
        ),
        ("Records", [("quarantine", "Quarantine"), ("vault", "Vault and exports"), ("console", "Telegram console")]),
    ]
    nav_html = ""
    for label, items in nav:
        buttons = ""
        for pid, text in items:
            count = ""
            if pid == "quarantine":
                alert = " is-alert" if quarantined else ""
                count = f'<span class="nav-count{alert}" id="nav-quarantine">{quarantined}</span>'
            buttons += f'<li><button type="button" class="nav-item" data-panel="{pid}"><span>{escape(text)}</span>{count}</button></li>'
        nav_html += (
            f'<div class="nav-group"><p class="nav-label" id="nav-{escape(label.lower())}">{escape(label)}</p>'
            f'<ul class="nav-list" aria-labelledby="nav-{escape(label.lower())}">{buttons}</ul></div>'
        )

    overview = (
        '<dl class="figures">'
        '<div class="figure"><dt>Academy revenue</dt><dd>'
        f'<span class="figure-value" id="fig-revenue">${rev:,.2f}</span>'
        f'<span class="figure-note" id="fig-revenue-note">{khr:,} KHR across {inv} invoices</span></dd></div>'
        '<div class="figure"><dt>Client satisfaction</dt><dd>'
        f'<span class="figure-value" id="fig-rating">{f"{avg:.1f} / 5" if sv else "None yet"}</span>'
        f'<span class="figure-note" id="fig-rating-note">{sv} survey responses</span></dd></div>'
        '<div class="figure"><dt>Staff scanned in today</dt><dd>'
        f'<span class="figure-value" id="fig-scans">{scans}</span>'
        '<span class="figure-note">Employees and interns</span></dd></div>'
        '<div class="figure"><dt>Records in quarantine</dt><dd>'
        f'<span class="figure-value{" is-alert" if quarantined else ""}" id="fig-quarantine">{quarantined}</span>'
        '<span class="figure-note">Rejected submissions to review</span></dd></div></dl>'
        '<div class="card-head"><h3>Analytics</h3>'
        '<button type="button" class="btn btn-secondary btn-sm" id="btn-charts">Refresh charts</button></div>'
        '<div class="charts">'
        '<figure class="chart"><img id="img-survey" src="/charts/survey_analytics_all.png" width="1920" height="832" '
        'alt="Bar charts of survey responses by requested topic and by chamber, with average ratings">'
        '<figcaption>Survey responses by topic and chamber</figcaption></figure>'
        '<figure class="chart"><img id="img-revenue" src="/charts/firm_revenue_attendance.png" width="1725" height="690" '
        'alt="Pie chart of Academy revenue by payment channel and bar chart of today\'s attendance by status">'
        '<figcaption>Academy revenue by channel and attendance today</figcaption></figure></div>'
        '<div class="card"><div class="card-head"><h3>Latest invoices</h3>'
        '<button type="button" class="btn btn-secondary btn-sm" data-panel="academy">All invoices</button></div>'
        + _table(
            "tbl-recent",
            "Latest Academy invoices",
            [("Receipt", ""), ("Trainee", ""), ("Course", ""), ("Amount", "num"), ("Issued", ""), ("Receipt file", "")],
            "Loading invoices.",
        )
        + "</div>"
    )

    attendance = (
        '<form class="card" id="form-scan" aria-labelledby="scan-title">'
        '<div class="card-head"><h3 id="scan-title">Record a scan</h3>'
        '<p class="card-note">Fields marked * are required.</p></div><div class="form-grid">'
        + _field("scan-code", "Staff code", hint="For example EMP-001 or INT-001.", extra='maxlength="32" autocomplete="off"')
        + _field("scan-name", "Full name", extra='maxlength="120" autocomplete="off"')
        + _select("scan-role", "Role", [("Employee", "Employee"), ("Intern", "Intern")])
        + _select("scan-dept", "Department", DEPARTMENTS)
        + _select("scan-action", "Action", [("CHECK_IN", "Check in"), ("CHECK_OUT", "Check out")])
        + "</div>"
        + _form_foot("Record scan")
        + "</form>"
        '<div class="card"><div class="card-head"><h3>Today\'s roster</h3></div>'
        + _table(
            "tbl-attendance",
            "Staff attendance today",
            [("Code", ""), ("Name", ""), ("Role", ""), ("Department", ""), ("In", ""), ("Out", ""), ("Hours", "num"), ("Status", "")],
            "Loading roster.",
        )
        + "</div>"
    )

    academy = (
        '<form class="card" id="form-academy" aria-labelledby="academy-form-title">'
        '<div class="card-head"><h3 id="academy-form-title">Enrol a trainee and issue a receipt</h3>'
        '<p class="card-note">Fields marked * are required.</p></div><div class="form-grid">'
        + _field("ac-km", "Name in Khmer", extra='lang="km" maxlength="120" autocomplete="off"')
        + _field("ac-en", "Name in Latin letters", extra='maxlength="120" autocomplete="off"')
        + _field("ac-email", "Email", kind="email", extra='maxlength="254" autocomplete="off"')
        + _field("ac-phone", "Phone (Cambodia)", kind="tel", hint="For example 012 345 678.", extra='maxlength="20" autocomplete="off"')
        + _select("ac-course", "Course", COURSES)
        + _select("ac-method", "Payment method", PAYMENT_METHODS)
        + _field("ac-price", "Fee (USD)", kind="number", extra=f'min="0" max="{MAX_PRICE_USD:g}" step="0.01" inputmode="decimal"')
        + '<div class="field"><label for="ac-khr">Fee in KHR</label><input id="ac-khr" type="text" readonly aria-describedby="ac-khr-hint">'
        f'<p class="field-hint" id="ac-khr-hint">Calculated at {fx:,} KHR per USD.</p></div>'
        "</div>" + _form_foot("Issue receipt") + "</form>"
        '<div class="card"><div class="card-head"><h3>All invoices</h3></div>'
        + _table(
            "tbl-invoices",
            "Academy invoices",
            [("Receipt", ""), ("Trainee", ""), ("Course", ""), ("USD", "num"), ("KHR", "num"), ("Method", ""), ("Issued", ""), ("Receipt file", "")],
            "Loading invoices.",
        )
        + "</div>"
    )

    surveys = (
        '<form class="card" id="form-survey" aria-labelledby="survey-form-title">'
        '<div class="card-head"><h3 id="survey-form-title">Record client feedback</h3>'
        '<p class="card-note">Ratings below the alert threshold notify the firm\'s Telegram subscribers.</p></div><div class="form-grid">'
        + _field("sv-name", "Respondent name", extra='maxlength="120" autocomplete="off"')
        + _field("sv-org", "Organisation", required=False, extra='maxlength="160" autocomplete="off"')
        + _select("sv-chamber", "Chamber or network", CHAMBERS)
        + _field("sv-event", "Event", extra='maxlength="160" autocomplete="off"')
        + _select("sv-dept", "Department", DEPARTMENTS)
        + _field("sv-rating", "Rating (1 to 5)", kind="number", extra='min="1" max="5" step="0.1" inputmode="decimal"')
        + _select("sv-topic", "Requested topic", TOPICS)
        + _field("sv-feedback", "Written feedback", required=False, extra='maxlength="1000" autocomplete="off"')
        + "</div>" + _form_foot("Record feedback") + "</form>"
        '<div class="card"><div class="card-head"><h3>Survey responses</h3></div>'
        + _table(
            "tbl-surveys",
            "Survey responses",
            [("Respondent", ""), ("Organisation", ""), ("Chamber", ""), ("Event", ""), ("Topic", ""), ("Rating", ""), ("Feedback", ""), ("Recorded", "")],
            "Loading responses.",
        )
        + "</div>"
    )

    intake = (
        '<form class="card" id="form-ops" aria-labelledby="ops-form-title">'
        '<div class="card-head"><h3 id="ops-form-title">Record a consultation request</h3>'
        '<p class="card-note">Fields marked * are required.</p></div><div class="form-grid">'
        + _field("ops-name", "Client or company", extra='maxlength="160" autocomplete="off"')
        + _field("ops-email", "Email", kind="email", extra='maxlength="254" autocomplete="off"')
        + _field("ops-phone", "Phone (Cambodia)", kind="tel", hint="For example 077 889 900.", extra='maxlength="20" autocomplete="off"')
        + _select("ops-area", "Practice area", PRACTICE_AREAS)
        + _select("ops-urgency", "Urgency", URGENCIES)
        + "</div>" + _form_foot("Record request") + "</form>"
        '<div class="card"><div class="card-head"><h3>Client intake</h3></div>'
        + _table(
            "tbl-ops",
            "Client intake requests",
            [("Client", ""), ("Email", ""), ("Phone", ""), ("Practice area", ""), ("Urgency", ""), ("Received", "")],
            "Loading requests.",
        )
        + "</div>"
    )

    quarantine = (
        '<div class="card"><div class="card-head"><h3>Rejected submissions</h3>'
        '<p class="card-note">Newest 50 records</p></div>'
        + _table(
            "tbl-quarantine",
            "Quarantined submissions",
            [("ID", ""), ("Source", ""), ("Reason", ""), ("Submitted data", ""), ("Logged", "")],
            "Loading records.",
        )
        + "</div>"
    )

    vault = (
        '<div class="card"><div class="card-head"><h3>Backups</h3>'
        '<button type="button" class="btn btn-sm" id="btn-backup">Create backup now</button></div>'
        '<p class="card-note" id="backup-status" role="status" aria-live="polite"></p>'
        '<h4 class="subhead">Verified archives</h4><ul class="file-list" id="list-backups"></ul>'
        '<h4 class="subhead">CSV datasets</h4><ul class="file-list" id="list-datasets"></ul></div>'
        '<div class="card"><div class="card-head"><h3>Sync history</h3></div>'
        + _table(
            "tbl-runs",
            "Sync and backup history",
            [("Run", ""), ("Time", ""), ("Source", ""), ("Result", ""), ("Invoices", "num"), ("Revenue", "num"), ("Surveys", "num"), ("Scans", "num"), ("Quarantined", "num"), ("Backup", "")],
            "Loading history.",
        )
        + "</div>"
    )

    console = (
        '<div class="console"><div class="card"><div class="field"><label for="tg-user">Act as</label>'
        '<select id="tg-user"><option value="999999999">Unregistered account (access denied)</option></select></div>'
        '<p class="field-hint">Commands run with that person\'s permissions. Nothing is sent to Telegram.</p>'
        '<div class="console-commands" role="group" aria-label="Bot commands">'
        + "".join(
            f'<button type="button" class="btn btn-secondary btn-sm" data-cmd="{c}">{c}</button>'
            for c in ("/start", "/survey", "/invoices", "/attendance", "/csv", "/zip", "/health", "/run")
        )
        + '</div></div><div class="bubble-wrap"><div class="bubble" id="tg-out" role="status" aria-live="polite">'
        "Choose a person and a command. The reply appears here as it would in Telegram.</div>"
        '<p class="bubble-attach" id="tg-attach"></p><div class="keyboard" id="tg-keys"></div></div></div>'
    )

    panels = (
        _panel("overview", "Overview", "Revenue, client feedback, attendance and data quality.", overview)
        + _panel("attendance", "Attendance", "Record QR scans by hand and review who is in today.", attendance)
        + _panel("academy", "Academy invoices", "Enrol trainees and issue bilingual A5 receipts.", academy)
        + _panel("surveys", "Client surveys", "Seminar and client feedback with automatic low-rating alerts.", surveys)
        + _panel("intake", "Client intake", "Consultation requests from SMEs and start-ups.", intake)
        + _panel("quarantine", "Quarantine", "Submissions rejected for bad emails, phone numbers, prices or missing names.", quarantine)
        + _panel("vault", "Vault and exports", "CRC-verified backup archives, clean CSV datasets and sync history.", vault)
        + _panel("console", "Telegram console", "Try the role-based Telegram bot without leaving the dashboard.", console)
    )

    demo_btn = '<button type="button" class="btn btn-gold btn-sm" id="btn-demo">Load sample data</button>' if demo else ""

    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>Operations hub - {name}</title>"
        '<link rel="stylesheet" href="/static/css/dashboard.css"></head>'
        f'<body data-fx="{fx}" data-demo="{"true" if demo else "false"}">'
        '<a class="skip-link" href="#main">Skip to content</a><div class="app">'
        f'<aside class="sidebar"><div class="brand">{LOGO}<p class="brand-sub">Operations hub</p></div>'
        f'<nav aria-label="Sections"><div class="nav-groups">{nav_html}</div></nav>'
        '<div class="sidebar-foot"><form method="post" action="/dashboard/logout">'
        '<button type="submit" class="btn btn-secondary btn-sm">Sign out</button></form></div></aside>'
        '<div class="main"><header class="topbar">'
        f'<p class="topbar-meta">Time zone <strong>{escape(settings.timezone_name)}</strong> &middot; '
        f'Database <strong>{db_label}</strong> &middot; Updated <strong id="updated-at">now</strong></p>'
        f'<div class="topbar-actions">{demo_btn}'
        '<button type="button" class="btn btn-secondary btn-sm" id="btn-refresh">Refresh</button>'
        '<button type="button" class="btn btn-sm" id="btn-sync">Run sync and backup</button></div></header>'
        f'<main class="content" id="main"><h1 class="sr-only">{name} operations hub</h1>{panels}</main></div></div>'
        '<div class="toast" id="toast" role="status" aria-live="polite" hidden></div>'
        '<script src="/static/js/dashboard.js" defer></script></body></html>'
    )
