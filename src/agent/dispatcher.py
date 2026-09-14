"""API-side persisted pending discovery; a wakeup is never the source of truth."""
import asyncio
from datetime import UTC, datetime

from .coordinator import Coordinator
from .runtime import run_invocation
from .tools.client import TrustedTransport


class Dispatcher:
    def __init__(self, app, *, model_factory=None, http_transport=None, runner=None):
        self.app = app
        self.wake = asyncio.Event()
        self.model_factory = model_factory
        self.http_transport = http_transport(app) if callable(http_transport) else http_transport
        self.runner = runner or run_invocation
        self.last_error = None

    def pending(self):
        settings = self.app.state.api_settings
        with self.app.state.store_factory(settings.store_path) as store:
            rows = store.db.execute("SELECT id FROM invocations WHERE status='PENDING' OR "
                "(status='RUNNING' AND json_extract(record_json,'$.lease_expires_at')<=?) ORDER BY rowid LIMIT 8",
                (datetime.now(UTC).isoformat(),)).fetchall()
            result = []
            for row in rows:
                if Coordinator(store).finalize_exhaustion(row[0]):
                    continue
                result.append(row[0])
            return result

    async def run(self):
        self.wake.set()
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=10)
            except TimeoutError:
                pass
            self.wake.clear()
            # The Store and its thread are closed before any HTTP/provider work.
            try:
                pending = await asyncio.to_thread(self.pending)
            except Exception:  # noqa: BLE001 - failed discovery is retried without provider work
                self.last_error = "DISCOVERY_UNAVAILABLE"
                continue
            for invocation_id in pending:
                settings = self.app.state.api_settings
                try:
                    await self.runner(TrustedTransport(settings.origin, settings.service_token, invocation_id),
                        model_factory=self.model_factory,
                        http_transport=self.http_transport)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - safe process status; saved journals retain exact bounded outcomes
                    self.last_error = "INVOCATION_UNFINISHED"
