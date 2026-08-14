import socket
from argparse import Namespace
from pathlib import Path

import pytest

import run
from run import select_port


def test_select_port_skips_an_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied = listener.getsockname()[1]
        assert select_port(occupied) != occupied


def test_select_port_strict_rejects_an_occupied_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("0.0.0.0", 0))
        occupied = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match="already in use"):
            select_port(occupied, strict=True)


def test_select_port_rejects_invalid_port() -> None:
    with pytest.raises(ValueError, match="between 1"):
        select_port(70000)


def test_select_port_continues_after_the_preferred_range(monkeypatch) -> None:
    monkeypatch.setattr(run, "port_is_available", lambda port: port == 8796)
    assert select_port() == 8796


def test_main_uses_environment_port_and_writes_actual_runtime(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    runtime_path = tmp_path / "runtime.json"
    selected: dict[str, object] = {}
    monkeypatch.setenv("BTC_RESEARCH_PORT", "8788")
    monkeypatch.setattr(
        run,
        "parse_args",
        lambda: Namespace(port=None, host="0.0.0.0", strict_port=False, reload=False),
    )
    monkeypatch.setattr(
        run,
        "select_port",
        lambda requested, strict: selected.update(
            {"requested": requested, "strict": strict}
        )
        or 8789,
    )
    monkeypatch.setattr(run, "discover_lan_ip", lambda: "192.168.50.10")
    monkeypatch.setattr(run, "RUNTIME_PATH", runtime_path)
    monkeypatch.setattr(
        run.uvicorn,
        "run",
        lambda *args, **kwargs: selected.update({"uvicorn": (args, kwargs)}),
    )

    run.main()

    runtime = runtime_path.read_text(encoding="utf-8")
    assert selected["requested"] == 8788
    assert selected["strict"] is False
    assert '"port": 8789' in runtime
    assert '"host": "0.0.0.0"' in runtime
    assert '"localUrl": "http://127.0.0.1:8789"' in runtime
    assert '"lanUrl": "http://192.168.50.10:8789"' in runtime
    assert selected["uvicorn"][1]["host"] == "0.0.0.0"  # type: ignore[index]
    assert selected["uvicorn"][1]["port"] == 8789  # type: ignore[index]
    output = capsys.readouterr().out
    assert "8788" in output
    assert "8789" in output
    assert "http://127.0.0.1:8789" in output


def test_main_reports_invalid_environment_port_cleanly(monkeypatch) -> None:
    monkeypatch.setenv("BTC_RESEARCH_PORT", "not-a-port")
    monkeypatch.setattr(
        run,
        "parse_args",
        lambda: Namespace(port=None, host="0.0.0.0", strict_port=False, reload=False),
    )
    with pytest.raises(SystemExit, match="must be an integer"):
        run.main()
