from starlette.requests import Request

from app.main import require_loopback_client


def make_request(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/references/cvdd",
            "headers": [],
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
