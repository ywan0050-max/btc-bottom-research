import socket

import pytest

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
