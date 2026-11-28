"""Authentication for every protected route.

Credentials:
- Dashboard pages, data and downloads: an HttpOnly session cookie issued by POST /dashboard/login,
  or an X-Firm-Secret header carrying the dashboard token (scripts, monitoring).
- Ingest webhooks and actions: X-Firm-Secret carrying the webhook secret or the dashboard token,
  or a dashboard session plus the X-Firm-CSRF header (the dashboard's own forms).
- A secret that is empty or still a `replace_with_*` placeholder rejects the request when
  APP_ENV is production (the default). Only APP_ENV=development/dev/local/test leaves it open.
Tokens are never accepted in the URL, so they stay out of logs, history and referrers.
"""
import hashlib
import hmac
import time

from fastapi import HTTPException, Request, Response

from app.config import AppSettings

SESSION_COOKIE = "firm_session"
CSRF_HEADER = "x-firm-csrf"
SESSION_MAX_AGE = 12 * 60 * 60
NOT_CONFIGURED = "Authentication is not configured on the server. Set the secrets in .env."

LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 8
_failures: dict[str, list[float]] = {}


def _recent_failures(client: str) -> list[float]:
    cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
    recent = [t for t in _failures.get(client, []) if t > cutoff]
    if recent:
        _failures[client] = recent
    else:
        _failures.pop(client, None)
    return recent


def login_blocked(client: str) -> bool:
    return len(_recent_failures(client)) >= LOGIN_MAX_FAILURES


def login_failed(client: str) -> None:
    _failures[client] = _recent_failures(client) + [time.monotonic()]


def login_ok(client: str) -> None:
    _failures.pop(client, None)


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def is_configured(secret: str) -> bool:
    return bool(secret) and "replace_with" not in secret


def _same(supplied: str | None, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied.encode(), expected.encode())


def session_value(settings: AppSettings) -> str:
    key = settings.dashboard_access_token.encode()
    return hmac.new(key, b"firm-dashboard-session-v1", hashlib.sha256).hexdigest()


def token_valid(settings: AppSettings, supplied: str | None) -> bool:
    return is_configured(settings.dashboard_access_token) and _same(supplied, settings.dashboard_access_token)


def set_session_cookie(response: Response, settings: AppSettings, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_value(settings),
        max_age=SESSION_MAX_AGE,
        path="/",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _credential(settings: AppSettings, request: Request) -> str | None:
    expected = settings.dashboard_access_token
    if _same(request.headers.get("x-firm-secret"), expected):
        return "header"
    if _same(request.cookies.get(SESSION_COOKIE), session_value(settings)):
        return "session"
    return None


def dashboard_state(settings: AppSettings, request: Request) -> str:
    """Returns "ok", "denied" or "unconfigured" for the HTML dashboard."""
    if not is_configured(settings.dashboard_access_token):
        return "unconfigured" if settings.is_production else "ok"
    return "ok" if _credential(settings, request) else "denied"


def require_dashboard(settings: AppSettings, request: Request, *, mutating: bool = False) -> None:
    if not is_configured(settings.dashboard_access_token):
        if settings.is_production:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return
    via = _credential(settings, request)
    if via is None:
        raise HTTPException(status_code=403, detail="Unauthorized")
    if mutating and via == "session" and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Missing CSRF header")


def require_ingest(settings: AppSettings, request: Request, x_firm_secret: str | None) -> None:
    accepted = [s for s in (settings.webhook_shared_secret, settings.dashboard_access_token) if is_configured(s)]
    if not accepted:
        if settings.is_production:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return
    if any([_same(x_firm_secret, s) for s in accepted]):
        return
    if (
        is_configured(settings.dashboard_access_token)
        and _credential(settings, request) == "session"
        and request.headers.get(CSRF_HEADER) == "1"
    ):
        return
    raise HTTPException(status_code=401, detail="Invalid or missing credentials")


def require_telegram_secret(settings: AppSettings, supplied: str | None) -> None:
    expected = settings.telegram_webhook_secret
    if not is_configured(expected):
        if settings.is_production:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return
    if not _same(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")
