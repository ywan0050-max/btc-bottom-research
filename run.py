from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import uvicorn

from app.config import RUNTIME_PATH


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT_START = 8765
DEFAULT_PORT_END = 8795
MAX_PORT = 65535


def port_is_available(port: int, host: str = "0.0.0.0") -> bool:
    probe_hosts = [host]
    if host == "0.0.0.0":
        probe_hosts.insert(0, "127.0.0.1")
    for probe_host in dict.fromkeys(probe_hosts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((probe_host, port))
            except OSError:
                return False
    return True


def select_port(requested: int | None = None, strict: bool = False) -> int:
    if requested is not None and not 1 <= requested <= MAX_PORT:
        raise ValueError(f"Port must be between 1 and {MAX_PORT}.")
    candidates: list[int] = []
    if requested:
        candidates.append(requested)
        if strict and not port_is_available(requested):
            raise RuntimeError(f"Requested port {requested} is already in use.")

    candidates.extend(range(DEFAULT_PORT_START, DEFAULT_PORT_END + 1))
    candidates.extend(range(DEFAULT_PORT_END + 1, MAX_PORT + 1))

    seen: set[int] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if port_is_available(candidate):
            return candidate
    raise RuntimeError("No free port was found in the configured port range.")


def discover_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            return str(probe.getsockname()[0])
    except OSError:
        try:
            addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
            return next(
                address[4][0]
                for address in addresses
                if not address[4][0].startswith("127.")
            )
        except (OSError, StopIteration):
            return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BTC Bottom Research Desk.")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--strict-port", action="store_true")
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env_port = os.getenv("BTC_RESEARCH_PORT")
    try:
        requested = args.port or (int(env_port) if env_port else None)
    except ValueError as exc:
        raise SystemExit("BTC_RESEARCH_PORT must be an integer.") from exc
    try:
        port = select_port(requested, strict=args.strict_port)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    lan_ip = discover_lan_ip()

    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{lan_ip}:{port}" if lan_ip else None
    runtime = {
        "port": port,
        "host": args.host,
        "localUrl": local_url,
        "lanUrl": lan_url,
        "startedAt": datetime.now(timezone.utc).isoformat(),
    }
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(
        json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if requested and requested != port:
        print(f"指定端口 {requested} 已被占用，已自动选择端口 {port}。", flush=True)
    print(f"本机地址：{local_url}", flush=True)
    if lan_url:
        print(f"局域网地址：{lan_url}", flush=True)
    else:
        print("局域网地址：未检测到可用的局域网 IPv4 地址", flush=True)
    print("按 Ctrl+C 停止服务。", flush=True)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=port,
        reload=args.reload,
        app_dir=str(PROJECT_ROOT),
        log_level="info",
    )


if __name__ == "__main__":
    main()
