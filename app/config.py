import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppSettings:
    root_dir: Path
    artifacts_dir: Path
    receipts_dir: Path
    charts_dir: Path
    datasets_dir: Path
    backups_dir: Path
    database_url: str
    timezone_name: str
    tz: ZoneInfo
    webhook_shared_secret: str
    dashboard_access_token: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    public_base_url: str
    google_drive_enabled: bool
    google_service_account_json_b64: str
    google_drive_bronze_folder_id: str
    google_drive_vault_folder_id: str
    firm_config: dict[str, Any]
    rbac_seed_path: Path
    app_env: str = "production"
    demo_tools_enabled: bool = False
    qr_max_backdate_hours: float = 24.0

    @property
    def is_production(self) -> bool:
        return self.app_env not in ("development", "dev", "local", "test")

    def ensure_dirs(self) -> None:
        for d in (
            self.artifacts_dir,
            self.receipts_dir,
            self.charts_dir,
            self.datasets_dir,
            self.backups_dir,
            self.root_dir / "data",
        ):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(root: Path = ROOT_DIR) -> AppSettings:
    cfg_path = root / "config" / "settings.json"
    firm_cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    tz_name = os.getenv("TIMEZONE", "Asia/Phnom_Penh")
    artifacts_dir = Path(os.getenv("ARTIFACTS_DIR") or root / "artifacts")

    settings = AppSettings(
        root_dir=root,
        artifacts_dir=artifacts_dir,
        receipts_dir=artifacts_dir / "receipts_a5",
        charts_dir=artifacts_dir / "charts",
        datasets_dir=artifacts_dir / "datasets",
        backups_dir=artifacts_dir / "backups",
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{(root / 'data' / 'ann_firm_local.db').as_posix()}"),
        timezone_name=tz_name,
        tz=ZoneInfo(tz_name),
        webhook_shared_secret=os.getenv("WEBHOOK_SHARED_SECRET", ""),
        dashboard_access_token=os.getenv("DASHBOARD_ACCESS_TOKEN", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        google_drive_enabled=os.getenv("GOOGLE_DRIVE_ENABLED", "false").lower() == "true",
        google_service_account_json_b64=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", ""),
        google_drive_bronze_folder_id=os.getenv("GOOGLE_DRIVE_BRONZE_FOLDER_ID", ""),
        google_drive_vault_folder_id=os.getenv("GOOGLE_DRIVE_VAULT_FOLDER_ID", ""),
        firm_config=firm_cfg,
        rbac_seed_path=root / "config" / "rbac_seed.json",
        app_env=os.getenv("APP_ENV", "production").strip().lower(),
        demo_tools_enabled=os.getenv("DEMO_TOOLS_ENABLED", "false").strip().lower() == "true",
        qr_max_backdate_hours=float(os.getenv("QR_MAX_BACKDATE_HOURS", "24")),
    )
    settings.ensure_dirs()
    return settings
