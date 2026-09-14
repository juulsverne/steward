"""One HTTP-only sequential invocation runner; no SQLite or Store imports."""
import asyncio
import json
from dataclasses import asdict

from .core import build_agent, invoke_case
from .runtime_contracts import Claim
from .tools.durable import DurableLifecycle
from .tools.lifecycle import LifecycleError
from .tools.session import build_steward_tool_session


async def run_invocation(transport, *, model=None, model_factory=None, http_transport=None):
    async with build_steward_tool_session(transport, lifecycle_factory=DurableLifecycle,
                                          http_transport=http_transport) as session:
        lifecycle = session.client.lifecycle
        await lifecycle.acquire()
        lost = asyncio.Event()

        async def heartbeat():
            try:
                while True:
                    await asyncio.sleep(10)
                    value = await lifecycle.control("renew")
                    renewed = Claim.model_validate_json(json.dumps(value))
                    # Keep the original client monotonic clock anchor; renewal grants no execution time.
                    if renewed.deadline != lifecycle.claim.deadline:
                        raise LifecycleError("DEADLINE_CHANGED")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - coordinator refusal fences all later effects
                lost.set()

        pulse = asyncio.create_task(heartbeat())
        observations = asyncio.Queue(maxsize=40)
        loop = asyncio.get_running_loop()

        def observe_provider(value):
            def enqueue():
                if not observations.full():
                    observations.put_nowait(value)
            loop.call_soon_threadsafe(enqueue)

        async def persist_observations():
            while True:
                value = await observations.get()
                try:
                    await lifecycle.control("observe", nonce=f"sdk-{lifecycle.claim.fence}-{value.ordinal}",
                        kind="sdk_before_send", ordinal=value.ordinal,
                        observation_json=json.dumps({"outcome": "SDK_BEFORE_SEND", "result_json": json.dumps(asdict(value))}))
                finally:
                    observations.task_done()

        observer = asyncio.create_task(persist_observations())
        execution = None
        try:
            await lifecycle.recover_unresolved()
            if model is None and model_factory is not None:
                model = model_factory()
            agent = build_agent(session, model=model, lifecycle=lifecycle, provider_observer=observe_provider)
            execution = asyncio.create_task(invoke_case(agent))
            loss = asyncio.create_task(lost.wait())
            try:
                done, _ = await asyncio.wait((execution, loss), return_when=asyncio.FIRST_COMPLETED)
                if loss in done:
                    agent.cancel()
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    raise LifecycleError("LEASE_LOST")
                result = await execution
            finally:
                loss.cancel()
                await asyncio.gather(loss, return_exceptions=True)
            if result.interruption is not None:
                # A lost coordinator acknowledgment is unfinished work, even when the
                # lower-level tool safely returned an ERROR envelope to the SDK.
                return result
            status = "COMPLETED" if result.saved_stop in {"ISSUE_RESOLVED", "JOB_CANCELLED", "RESOLVED"} else "WAITING" if result.saved_stop else "ERROR"
            await lifecycle.control("complete", status=status, outcome=result.saved_stop or result.error_code or "MODEL_END_WITHOUT_SAVED_STOP")
            return result
        except asyncio.CancelledError:
            # Interruption leaves RUNNING + authentic unknown work for fenced takeover, not a fabricated failure.
            if execution is not None:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
            raise
        except LifecycleError:
            # A failed authorization/ack is unfinished, never permission to advance a model.
            raise
        finally:
            try:
                async with asyncio.timeout(1):
                    await observations.join()
            except TimeoutError:
                pass  # Unacknowledged observations are never described as durable or zero-cost.
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
