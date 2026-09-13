"""Explicit pytest plugin: install fail-closed guards before importing application tests.

Run with PYTHONPATH=tests and python -m pytest -p offline_guard. No application runtime
imports this module. Tests may replace constructors with their own bounded fakes.
"""
import socket
import sys


def blocked(*args, **kwargs):
    raise AssertionError("Offline test blocked a model/AWS/network constructor")


_connect = socket.socket.connect


def guarded_connect(self, address):
    # Windows' stdlib socketpair uses a private loopback connect for asyncio wakeups.
    caller = sys._getframe(1)
    if caller.f_code.co_filename == socket.__file__ and caller.f_code.co_name == "_fallback_socketpair":
        return _connect(self, address)
    return blocked()


socket.create_connection = blocked
socket.socket.connect = guarded_connect
socket.socket.connect_ex = blocked

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
