"""The entry point of the server: the address has to be free before it starts."""

import socket

import pytest

from coderagent.web.server import check_address


def test_a_free_address_is_accepted():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    check_address("127.0.0.1", port)


def test_a_port_that_is_taken_is_reported(capsys):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]

        with pytest.raises(SystemExit):
            check_address("127.0.0.1", port)

    assert "cannot listen on 127.0.0.1:" in capsys.readouterr().err
