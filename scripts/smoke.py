from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def configure_isolated_runtime(root: Path) -> None:
    os.environ["BTC_RESEARCH_DISABLE_BACKGROUND_TASKS"] = "1"
    os.environ["BTC_RESEARCH_DB"] = str(root / "smoke.duckdb")
    os.environ["BTC_RESEARCH_RUNTIME_FILE"] = str(root / "runtime.json")


async def run_smoke() -> dict[str, object]:
    import httpx

    with tempfile.TemporaryDirectory(prefix="btc-research-smoke-") as temp_dir:
        root = Path(temp_dir)
        configure_isolated_runtime(root)

        from app.main import app, database, service

        database.initialize()
        service.load_metric_names()
        service.refresh_overview_cache()
        service.start_refresh = lambda: True  # type: ignore[method-assign]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8789",
        ) as client:
            paths = [
                "/api/health",
                "/api/overview",
                "/api/sources",
                "/manifest.webmanifest",
                "/icon.svg",
                "/sw.js",
                "/LICENSE",
                "/",
            ]
            routes = []
            for path in paths:
                response = await client.get(path)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"{path} returned {response.status_code}: {response.text[:200]}"
                    )
                routes.append(
                    {
                        "path": path,
                        "status": response.status_code,
                        "contentType": response.headers.get("content-type"),
                    }
                )

            health_response = await client.get("/api/health")
            health = health_response.json()
            if health.get("status") != "ok" or health.get("version") != "0.1.0":
                raise RuntimeError("Unexpected health payload.")
            if health.get("license") != "AGPL-3.0-only":
                raise RuntimeError("Unexpected software license metadata.")
            if "no-store" not in health_response.headers.get("cache-control", ""):
                raise RuntimeError("API Cache-Control header is missing no-store.")
            if health_response.headers.get("x-content-type-options") != "nosniff":
                raise RuntimeError("Security headers are missing.")

            cross_origin = await client.post(
                "/api/refresh",
                headers={"Origin": "https://malicious.example"},
            )
            if cross_origin.status_code != 403:
                raise RuntimeError("Cross-origin write was not rejected.")

            same_origin = await client.post(
                "/api/refresh",
                headers={"Origin": "http://127.0.0.1:8789"},
            )
            if same_origin.status_code != 202:
                raise RuntimeError("Same-origin refresh request was rejected.")

            return {
                "routes": routes,
                "crossOriginWrite": cross_origin.status_code,
                "sameOriginWrite": same_origin.status_code,
            }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_smoke()), ensure_ascii=False, indent=2))
