"""Default pytest plugin: install fail-closed guards before importing application tests.

Run with PYTHONPATH=tests and python -m pytest -p offline_guard. No application runtime
imports this module. Tests may replace constructors with their own bounded fakes.
"""
import asyncio
import socket
import sys
from contextlib import contextmanager

import anyio


def blocked(*args, **kwargs):
    raise AssertionError("Offline test blocked a model/AWS/network constructor")


_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_create_connection = socket.create_connection
_getaddrinfo = socket.getaddrinfo
_loop_create_connection = asyncio.BaseEventLoop.create_connection
_loop_getaddrinfo = asyncio.BaseEventLoop.getaddrinfo
_anyio_connect_tcp = anyio.connect_tcp
_anyio_getaddrinfo = anyio.getaddrinfo
_allowed_loopback: tuple[str, int] | None = None


def guarded_connect(self, address):
    # Windows' stdlib socketpair uses a private loopback connect for asyncio wakeups.
    caller = sys._getframe(1)
    if caller.f_code.co_filename == socket.__file__ and caller.f_code.co_name == "_fallback_socketpair":
        return _connect(self, address)
    if _allowed_address(address):
        return _connect(self, address)
    return blocked()


def guarded_connect_ex(self, address):
    if _allowed_address(address):
        return _connect_ex(self, address)
    return blocked()


def _allowed_address(address):
    return (isinstance(address, tuple) and len(address) >= 2 and _allowed_loopback is not None
            and address[0] == _allowed_loopback[0] and address[1] == _allowed_loopback[1])


@contextmanager
def allow_literal_loopback(port: int, host: str = "127.0.0.1"):
    """Permit one exact allocated literal test endpoint, then restore deny-all."""
    if host not in {"127.0.0.1", "::1"} or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("only an allocated literal loopback address and port may be allowed")
    global _allowed_loopback
    previous = _allowed_loopback
    _allowed_loopback = (host, port)
    try:
        yield
    finally:
        _allowed_loopback = previous


async def guarded_anyio_connect_tcp(*args, **kwargs):
    host = kwargs.get("remote_host", args[0] if args else None)
    port = kwargs.get("remote_port", args[1] if len(args) > 1 else None)
    if not _allowed_address((host, port)):
        return blocked()
    return await _anyio_connect_tcp(*args, **kwargs)


async def guarded_anyio_getaddrinfo(host, port, *args, **kwargs):
    if not _allowed_address((host, port)):
        return blocked()
    return await _anyio_getaddrinfo(host, port, *args, **kwargs)


async def guarded_getaddrinfo(self, host, port, *args, **kwargs):
    if not _allowed_address((host, port)):
        return blocked()
    return await _loop_getaddrinfo(self, host, port, *args, **kwargs)


async def guarded_create_connection(self, protocol_factory, host=None, port=None, **kwargs):
    if kwargs.get("sock") is not None or not _allowed_address((host, port)):
        return blocked()
    return await _loop_create_connection(self, protocol_factory, host, port, **kwargs)


socket.create_connection = lambda address, *args, **kwargs: (
    _create_connection(address, *args, **kwargs) if _allowed_address(address) else blocked())
socket.getaddrinfo = lambda host, port, *args, **kwargs: (
    _getaddrinfo(host, port, *args, **kwargs) if _allowed_address((host, port)) else blocked())
socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
anyio.connect_tcp = guarded_anyio_connect_tcp
anyio.getaddrinfo = guarded_anyio_getaddrinfo
asyncio.BaseEventLoop.create_connection = guarded_create_connection
asyncio.BaseEventLoop.getaddrinfo = guarded_getaddrinfo

if sys.platform == "win32":
    from asyncio.proactor_events import BaseProactorEventLoop
    from asyncio.windows_events import IocpProactor

    _sock_connect = BaseProactorEventLoop.sock_connect
    _proactor_connect = IocpProactor.connect

    async def guarded_sock_connect(self, sock, address):
        if not _allowed_address(address):
            return blocked()
        return await _sock_connect(self, sock, address)

    def guarded_proactor_connect(self, sock, address):
        if not _allowed_address(address):
            return blocked()
        return _proactor_connect(self, sock, address)

    BaseProactorEventLoop.sock_connect = guarded_sock_connect
    IocpProactor.connect = guarded_proactor_connect

import boto3
import botocore.session
import strands
import strands.models

boto3.client = blocked
boto3.resource = blocked
boto3.session.Session.client = blocked
boto3.session.Session.resource = blocked
botocore.session.Session.create_client = blocked
boto3.Session = blocked
strands.Agent = blocked
strands.models.BedrockModel = blocked
