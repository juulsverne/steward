"""Invocation-owned composition for Stage-B domain tool adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

import httpx

from .client import RequestLifecycle, StewardHttpClient, TrustedTransport
from .steward import OPERATIONS, StewardAgentTool


@dataclass
class InvocationToolSession:
    """One async-closeable client and its isolated domain tool registry."""

    client: StewardHttpClient
    tools: tuple[StewardAgentTool, ...]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.client.aclose()

    async def recover(self, logical_request_id: str) -> dict:
        """Trusted runner recovery only; not included in the model tool registry."""
        return await self.client.recover(logical_request_id)


def build_steward_tool_session(
    transport: TrustedTransport,
    *,
    lifecycle: RequestLifecycle | None = None,
    lifecycle_factory: Callable[[StewardHttpClient], RequestLifecycle] | None = None,
    deadline_at: float | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> InvocationToolSession:
    """Build isolated tools from trusted runner configuration, never model input.

    The default lifecycle is deliberately process-local pending B12's durable
    coordinator; callers that need persistence must inject B12's implementation.
    """
    client = StewardHttpClient(
        transport,
        lifecycle=lifecycle,
        lifecycle_factory=lifecycle_factory,
        deadline_at=deadline_at,
        http_transport=http_transport,
    )
    return InvocationToolSession(
        client=client, tools=tuple(StewardAgentTool(name, client) for name in OPERATIONS)
    )
