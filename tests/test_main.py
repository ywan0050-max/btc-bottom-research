from starlette.requests import Request

from app.config import APP_VERSION
from app.main import (
    app,
    health,
    host_is_allowed,
    require_loopback_client,
    require_same_origin_request,
)


def make_request(host: str, origin: str | None = None) -> Request:
    headers = [] if origin is None else [(b"origin", origin.encode("ascii"))]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/references/cvdd",
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8765),
            "client": (host, 54321),
        }
    )


def test_cvdd_write_allows_loopback_clients() -> None:
    require_loopback_client(make_request("127.0.0.1"))
    require_loopback_client(make_request("::1"))


def test_cvdd_write_rejects_lan_clients() -> None:
    try:
        require_loopback_client(make_request("192.168.1.50"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("LAN client should not be allowed to write CVDD references")


def test_health_exposes_application_version() -> None:
    assert app.version == APP_VERSION
    assert health()["version"] == APP_VERSION


def test_write_origin_allows_same_origin_or_non_browser_clients() -> None:
    require_same_origin_request(make_request("127.0.0.1"))
    require_same_origin_request(
        make_request("127.0.0.1", "http://127.0.0.1:8765")
    )


def test_write_origin_rejects_cross_origin_browser_requests() -> None:
    try:
        require_same_origin_request(
            make_request("127.0.0.1", "https://malicious.example")
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("Cross-origin browser writes should be rejected")


def test_host_policy_allows_local_lan_and_tailscale_addresses() -> None:
    assert host_is_allowed("localhost")
    assert host_is_allowed("127.0.0.1")
    assert host_is_allowed("::1")
    assert host_is_allowed("192.168.1.31")
    assert host_is_allowed("10.0.0.2")
    assert host_is_allowed("100.64.0.10")


def test_host_policy_rejects_public_or_arbitrary_hostnames() -> None:
    assert not host_is_allowed(None)
    assert not host_is_allowed("research.example.com")
    assert not host_is_allowed("8.8.8.8")
    assert not host_is_allowed("203.0.113.10")
    assert not host_is_allowed("0.0.0.0")
