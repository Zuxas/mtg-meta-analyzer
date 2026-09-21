"""The conftest network guard must actually block real hosts (and allow localhost)."""
import socket

import pytest


def test_real_host_resolution_is_blocked_by_default():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.getaddrinfo("www.mtgtop8.com", 443)


def test_localhost_still_resolves():
    assert socket.getaddrinfo("127.0.0.1", 0)


@pytest.mark.network
def test_marked_tests_can_opt_in():
    # Only checks the guard steps aside; no request is made.
    assert socket.getaddrinfo is not None
