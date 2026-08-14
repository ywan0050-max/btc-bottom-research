from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = "0.1.0"
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path(os.getenv("BTC_RESEARCH_DB", DATA_DIR / "research.duckdb"))
PARQUET_DIR = Path(os.getenv("BTC_RESEARCH_PARQUET_DIR", DATA_DIR / "parquet"))
RUNTIME_PATH = Path(os.getenv("BTC_RESEARCH_RUNTIME_FILE", PROJECT_ROOT / ".runtime.json"))
WEB_DIST = PROJECT_ROOT / "web" / "dist"

FAST_REFRESH_SECONDS = max(
    300, int(os.getenv("BTC_RESEARCH_DERIBIT_REFRESH_SECONDS", "900"))
)
ENABLE_DERIBIT = os.getenv("BTC_RESEARCH_ENABLE_DERIBIT", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SLOW_REFRESH_SECONDS = max(
    3600,
    int(
        os.getenv(
            "BTC_RESEARCH_SLOW_REFRESH_SECONDS",
            os.getenv("BTC_RESEARCH_REFRESH_SECONDS", "21600"),
        )
    ),
)
ARCHIVE_SECONDS = max(
    3600, int(os.getenv("BTC_RESEARCH_ARCHIVE_SECONDS", "86400"))
)
HTTP_TIMEOUT_SECONDS = float(os.getenv("BTC_RESEARCH_HTTP_TIMEOUT", "25"))
COLLECTOR_TIMEOUT_SECONDS = max(
    HTTP_TIMEOUT_SECONDS,
    float(os.getenv("BTC_RESEARCH_COLLECTOR_TIMEOUT", "45")),
)
USER_AGENT = "btc-bottom-research/0.1 (personal research)"
DISABLE_BACKGROUND_TASKS = os.getenv(
    "BTC_RESEARCH_DISABLE_BACKGROUND_TASKS", "0"
).strip().lower() in {"1", "true", "yes", "on"}
