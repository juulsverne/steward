"""Install real coordinator permits for pre-runtime cause/transaction regressions."""
from uuid import uuid4

from agent import contracts as c
from agent.coordinator import Coordinator
from agent.runtime_contracts import command_record
from agent.tools.protocol import build_command, operation_for


def permit_context(store, context, operation, **values):
    if context.runtime is not None:
        return context
    op = operation_for(operation)
    if op.revision:
        values[op.revision] = context.expected_revision
    command = build_command(operation, values)
    co = Coordinator(store)
    inv = store.get_invocation(context.invocation_id)
    claim = co.claim(inv.id, "test-owner", "test-claim") if inv.status == "PENDING" else co._claim(inv)
    for saved in co.requests(claim, unresolved_only=True):
        co.reconcile(claim, saved.id)
    state = co._state(inv.id)
    if state[2] == 0:
        co.execution(claim, f"authorize-{claim.fence}-model-1", "model", 1)
    ordinal = state[3] + 1
    co.execution(claim, f"authorize-{claim.fence}-tool-{ordinal}", "tool", ordinal,
                 details={"command": command_record(command).model_dump(mode="json")})
    saved = co.prepare(claim, f"model-{max(1, state[2])}-tool-{ordinal}", command)
    permit = co.begin(claim, saved.id, str(uuid4()))
    return context.model_copy(update={"operation": command.receipt_operation, "idempotency_key": saved.idempotency_key,
        "runtime": c.RuntimeAuthority(attempt_id=permit.id, owner=claim.owner, fence=claim.fence,
                                       command_json=saved.command.model_dump_json())})


def permit_headers(store, context, operation, **values):
    from test_api_auth import TOKEN
    bound = permit_context(store, context, operation, **values)
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Steward-Invocation-Id": bound.invocation_id,
        "X-Steward-Lease-Owner": bound.runtime.owner, "X-Steward-Fencing-Token": str(bound.runtime.fence),
        "X-Steward-Attempt-Id": bound.runtime.attempt_id, "Idempotency-Key": bound.idempotency_key}
    if bound.expected_revision is not None:
        headers["X-Steward-Expected-Revision"] = str(bound.expected_revision)
    return headers


def remove_runtime_tables_for_legacy_fixture(db):
    """Reconstruct an old-version fixture without leaving future schema7 tables."""
    for table in ("runtime_control_observations", "runtime_trace", "runtime_controls", "runtime_observations",
                  "runtime_attempts", "runtime_requests", "runtime_episodes", "runtime_state",
                  "intake_physical_observations"):
        db.execute(f"DROP TABLE {table}")
