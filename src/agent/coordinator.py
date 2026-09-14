"""FastAPI-owned durable execution authority. Every method uses a short writer unit."""
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .runtime_contracts import (
    Claim,
    CommandRecord,
    LogicalRequest,
    RuntimeAttempt,
    command_record,
    restored_command,
)
from .tools.protocol import validated_envelope


class RuntimeConflict(RuntimeError):
    pass


def validate_effect(store, context):
    """Re-load authority inside the effect writer; direct non-invocation callers retain policy."""
    if context.invocation_id is None:
        if context.runtime is not None:
            raise RuntimeConflict("INVOCATION_REQUIRED")
        return
    authority = context.runtime
    if authority is None:
        raise RuntimeConflict("RUNTIME_PERMIT_REQUIRED")
    validate_transport(store, context.invocation_id, authority,
                       key=context.idempotency_key, operation=context.operation,
                       revision=context.expected_revision)


def validate_transport(store, invocation_id, authority, *, key=None, operation=None, revision=None):
    co = Coordinator(store)
    inv = store.get_invocation(invocation_id)
    state = co._state(invocation_id)
    if state is None or inv.lease_owner is None:
        raise RuntimeConflict("RUNTIME_PERMIT_REQUIRED")
    claim = co._claim(inv)
    if authority.owner != claim.owner or authority.fence != claim.fence:
        raise RuntimeConflict("FENCED")
    co.current(claim)
    row = store.db.execute("SELECT record_json FROM runtime_attempts WHERE id=?", (authority.attempt_id,)).fetchone()
    if row is None:
        raise RuntimeConflict("ATTEMPT_NOT_FOUND")
    attempt = RuntimeAttempt.model_validate_json(row[0])
    saved = co.load(claim, attempt.logical_request_id)
    if attempt.owner != claim.owner or attempt.fence != claim.fence or attempt.deadline <= co.clock():
        raise RuntimeConflict("FENCED")
    actual = CommandRecord.model_validate_json(authority.command_json)
    if actual != saved.command:
        raise RuntimeConflict("COMMAND_MISMATCH")
    command = restored_command(saved.command)
    if command.mutation and (key != saved.idempotency_key or operation != command.receipt_operation
                            or revision != command.expected_revision):
        raise RuntimeConflict("COMMAND_MISMATCH")


class Coordinator:
    def __init__(self, store, *, clock=None):
        self.store = store
        self.db = store.db
        self.clock = clock or getattr(store, "runtime_clock", None) or (lambda: datetime.now(UTC))

    def _state(self, invocation_id):
        return self.db.execute("SELECT episode,deadline,model_cycles,tool_requests FROM runtime_state "
                               "WHERE invocation_id=?", (invocation_id,)).fetchone()

    def _claim(self, invocation):
        state = self._state(invocation.id)
        return Claim(invocation_id=invocation.id, owner=invocation.lease_owner,
            fence=invocation.fencing_token, episode=state[0], deadline=datetime.fromisoformat(state[1]),
            server_time=self.clock(), model_cycles=state[2], tool_requests=state[3])

    def current(self, claim, *, allow_expired=False, allow_terminal=False):
        inv = self.store.get_invocation(claim.invocation_id)
        state = self._state(inv.id)
        if (inv.status not in ({"RUNNING", "ERROR"} if allow_terminal else {"RUNNING"}) or inv.lease_owner != claim.owner or inv.fencing_token != claim.fence
                or state is None or state[0] != claim.episode
                or datetime.fromisoformat(state[1]) != claim.deadline):
            raise RuntimeConflict("FENCED")
        if not allow_expired and (inv.lease_expires_at <= self.clock()
                or datetime.fromisoformat(state[1]) <= self.clock()):
            raise RuntimeConflict("DEADLINE_EXCEEDED")
        return inv

    def finalize_exhaustion(self, invocation_id):
        """Persist an exhausted interrupted run without granting another execution episode."""
        with self.store.transaction() as tx:
            inv = self.store.get_invocation(invocation_id)
            state = self._state(invocation_id)
            now = self.clock()
            if inv.status != "RUNNING" or not state or inv.lease_expires_at > now:
                return None
            reason = ("LIFETIME_LIMIT_EXHAUSTED" if state[2] >= 12 or state[3] >= 40 else
                      "EPISODES_EXHAUSTED" if state[0] >= 2 and datetime.fromisoformat(state[1]) <= now else None)
            if reason:
                tx.replace_invocation(inv.model_copy(update={"status": "ERROR", "error_code": reason,
                    "finished_at": now, "state_revision": inv.state_revision + 1}), inv.state_revision)
            return reason

    def claim(self, invocation_id, owner, nonce):
        exhausted = self.finalize_exhaustion(invocation_id)
        if exhausted:
            raise RuntimeConflict(exhausted)
        with self.store.transaction() as tx:
            inv = self.store.get_invocation(invocation_id)
            old = self.db.execute("SELECT result_json FROM runtime_controls WHERE invocation_id=? AND nonce=?",
                                  (invocation_id, nonce)).fetchone()
            if old:
                result = Claim.model_validate_json(old[0])
                if result.owner != owner:
                    raise RuntimeConflict("CONTROL_CONFLICT")
                self.current(result)
                return result
            if inv.status not in {"PENDING", "RUNNING"}:
                raise RuntimeConflict("INVOCATION_TERMINAL")
            now = self.clock()
            if inv.status == "RUNNING" and inv.lease_expires_at and inv.lease_expires_at > now:
                raise RuntimeConflict("CLAIM_BUSY")
            state = self._state(invocation_id)
            if state and (state[2] >= 12 or state[3] >= 40):
                raise RuntimeConflict("LIFETIME_LIMIT_EXHAUSTED")
            episode = state[0] if state else 0
            deadline = datetime.fromisoformat(state[1]) if state else now
            if deadline <= now:
                if episode >= 2:
                    raise RuntimeConflict("EPISODES_EXHAUSTED")
                episode += 1
                deadline = now + timedelta(seconds=120)
                self.db.execute("INSERT INTO runtime_episodes VALUES (?,?,?,?)",
                                (invocation_id, episode, now.isoformat(), deadline.isoformat()))
            if state:
                self.db.execute("UPDATE runtime_state SET episode=?,deadline=? WHERE invocation_id=?",
                                (episode, deadline.isoformat(), invocation_id))
            else:
                self.db.execute("INSERT INTO runtime_state VALUES (?,?,?,0,0)",
                                (invocation_id, episode, deadline.isoformat()))
            inv = inv.model_copy(update={"status": "RUNNING", "lease_owner": owner,
                "fencing_token": inv.fencing_token + 1, "lease_expires_at": min(now + timedelta(seconds=30), deadline),
                "started_at": inv.started_at or now, "state_revision": inv.state_revision + 1,
                "attempt_count": inv.attempt_count + 1})
            tx.replace_invocation(inv, inv.state_revision - 1)
            result = self._claim(inv)
            self.db.execute("INSERT INTO runtime_controls VALUES (?,?,?,?)",
                            (invocation_id, nonce, json.dumps({"owner": owner}), result.model_dump_json()))
            return result

    def renew(self, claim):
        with self.store.transaction() as tx:
            inv = self.current(claim)
            inv = inv.model_copy(update={"lease_expires_at": min(self.clock() + timedelta(seconds=30), claim.deadline),
                                         "state_revision": inv.state_revision + 1})
            tx.replace_invocation(inv, inv.state_revision - 1)
            return self._claim(inv)

    def prepare(self, claim, call_ref, command):
        with self.store.transaction():
            self.current(claim)
            row = self.db.execute("SELECT record_json FROM runtime_requests WHERE invocation_id=? AND call_ref=?",
                                  (claim.invocation_id, call_ref)).fetchone()
            record = command_record(command)
            if row:
                previous = LogicalRequest.model_validate_json(row[0])
                if previous.command != record:
                    raise RuntimeConflict("LOGICAL_REQUEST_CONFLICT")
                return previous
            if command.operation == "read_case_context":
                match = re.fullmatch(rf"host-{claim.fence}-(\d+)", call_ref)
                kind = "context"
            else:
                match = re.fullmatch(r"model-(\d+)-tool-(\d+)", call_ref)
                kind = "tool"
                if match and int(match[1]) != self._state(claim.invocation_id)[2]:
                    raise RuntimeConflict("MODEL_SEQUENCE_MISMATCH")
            if match is None:
                raise RuntimeConflict("CALL_IDENTITY_INVALID")
            ordinal = int(match[1] if kind == "context" else match[2])
            authorization = self.db.execute("SELECT record_json FROM runtime_trace WHERE invocation_id=? AND nonce=?",
                (claim.invocation_id, f"authorize-{claim.fence}-{kind}-{ordinal}")).fetchone()
            if authorization is None or (json.loads(authorization[0]).get("details") or {}).get("command") != record.model_dump(mode="json"):
                raise RuntimeConflict("COMMAND_NOT_AUTHORIZED")
            if self.db.execute("SELECT 1 FROM runtime_requests WHERE invocation_id=? AND "
                "json_extract(record_json,'$.terminal_json') IS NULL", (claim.invocation_id,)).fetchone():
                raise RuntimeConflict("PREVIOUS_REQUEST_UNRESOLVED")
            saved = LogicalRequest(id=str(uuid4()), invocation_id=claim.invocation_id,
                call_ref=call_ref, command=record, idempotency_key=str(uuid4()) if command.mutation else None,
                deadline=claim.deadline, created_at=self.clock())
            self.db.execute("INSERT INTO runtime_requests VALUES (?,?,?,?)",
                (saved.id, saved.invocation_id, call_ref, saved.model_dump_json()))
            return saved

    def _load(self, logical_id):
        row = self.db.execute("SELECT record_json,invocation_id,call_ref FROM runtime_requests WHERE id=?", (logical_id,)).fetchone()
        if not row:
            raise RuntimeConflict("LOGICAL_REQUEST_NOT_FOUND")
        saved = LogicalRequest.model_validate_json(row[0])
        if (saved.id, saved.invocation_id, saved.call_ref) != (logical_id, row[1], row[2]):
            raise RuntimeConflict("LOGICAL_REQUEST_IDENTITY_MISMATCH")
        return saved

    def load(self, claim, logical_id, *, allow_expired=False):
        self.current(claim, allow_expired=allow_expired)
        saved = self._load(logical_id)
        if saved.invocation_id != claim.invocation_id:
            raise RuntimeConflict("FENCED")
        return saved

    def attempt_count(self, logical_id):
        return self.db.execute("SELECT COUNT(*) FROM runtime_attempts WHERE request_id=?", (logical_id,)).fetchone()[0]

    def begin(self, claim, logical_id, nonce):
        with self.store.transaction():
            saved = self.load(claim, logical_id)
            old = self.db.execute("SELECT record_json FROM runtime_attempts WHERE request_id=? AND nonce=?",
                                  (logical_id, nonce)).fetchone()
            if old:
                attempt = RuntimeAttempt.model_validate_json(old[0])
                if attempt.owner != claim.owner or attempt.fence != claim.fence:
                    raise RuntimeConflict("FENCED")
                return attempt
            count = self.attempt_count(logical_id)
            prior = self.db.execute("SELECT a.record_json,o.observation_json FROM runtime_attempts a LEFT JOIN "
                "runtime_observations o ON o.attempt_id=a.id WHERE a.request_id=? ORDER BY a.ordinal DESC LIMIT 1", (logical_id,)).fetchone()
            if prior and prior[1] is None:
                previous = RuntimeAttempt.model_validate_json(prior[0])
                if previous.owner == claim.owner and previous.fence == claim.fence:
                    raise RuntimeConflict("ATTEMPT_UNRESOLVED")
            if saved.terminal_json is not None:
                raise RuntimeConflict("LOGICAL_REQUEST_TERMINAL")
            if saved.deadline <= self.clock():
                raise RuntimeConflict("DEADLINE_EXCEEDED")
            if count >= 3:
                raise RuntimeConflict("ATTEMPTS_EXHAUSTED")
            attempt = RuntimeAttempt(id=str(uuid4()), logical_request_id=logical_id, owner=claim.owner,
                fence=claim.fence, ordinal=count + 1, deadline=min(saved.deadline, claim.deadline), created_at=self.clock())
            self.db.execute("INSERT INTO runtime_attempts VALUES (?,?,?,?,?)",
                            (attempt.id, logical_id, nonce, attempt.ordinal, attempt.model_dump_json()))
            return attempt

    def finish(self, claim, attempt_id, observation):
        with self.store.transaction():
            self.current(claim, allow_expired=True)
            row = self.db.execute("SELECT record_json FROM runtime_attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row:
                raise RuntimeConflict("ATTEMPT_NOT_FOUND")
            attempt = RuntimeAttempt.model_validate_json(row[0])
            saved = self.load(claim, attempt.logical_request_id, allow_expired=True)
            if attempt.owner != claim.owner or attempt.fence != claim.fence:
                raise RuntimeConflict("FENCED")
            if observation.attempt_id != attempt_id or observation.logical_request_id != saved.id:
                raise RuntimeConflict("ATTEMPT_IDENTITY_MISMATCH")
            from dataclasses import asdict
            raw = json.dumps(asdict(observation), sort_keys=True, allow_nan=False)
            old = self.db.execute("SELECT observation_json FROM runtime_observations WHERE attempt_id=?", (attempt_id,)).fetchone()
            if old and old[0] != raw:
                raise RuntimeConflict("ATTEMPT_OBSERVATION_CONFLICT")
            if not old:
                self.db.execute("INSERT INTO runtime_observations VALUES (?,?)", (attempt_id, raw))
            if not observation.retryable:
                result = validated_envelope(observation.result, restored_command(saved.command).operation,
                                            observation.status_code or 200)
                saved = saved.model_copy(update={"terminal_json": json.dumps(result, sort_keys=True)})
                self.db.execute("UPDATE runtime_requests SET record_json=? WHERE id=?", (saved.model_dump_json(), saved.id))
            return saved

    def reconcile(self, claim, logical_id):
        with self.store.transaction():
            # The original owner may read an actual receipt even after final exhaustion;
            # this grants no claim, new attempt, or domain mutation permission.
            self.current(claim, allow_expired=True, allow_terminal=True)
            saved = self._load(logical_id)
            if saved.invocation_id != claim.invocation_id:
                raise RuntimeConflict("FENCED")
            command = restored_command(saved.command)
            if saved.terminal_json:
                return saved
            if not command.mutation:
                # An interrupted read never creates a domain effect. Preserve the unknown read
                # result, then allow a fresh context read; do not invent a successful response.
                from .tools.protocol import error
                saved = saved.model_copy(update={"terminal_json": json.dumps(error("READ_INTERRUPTED"))})
                self.db.execute("UPDATE runtime_requests SET record_json=? WHERE id=?", (saved.model_dump_json(), saved.id))
                return saved
            row = self.db.execute("SELECT id FROM request_receipts WHERE actor_id='steward-service' AND operation=? "
                "AND idempotency_key=?", (command.receipt_operation, saved.idempotency_key)).fetchone()
            if row:
                receipt = self.store.get_request(row[0])
                if receipt.invocation_id != claim.invocation_id:
                    raise RuntimeConflict("RECEIPT_INVOCATION_MISMATCH")
                result = validated_envelope(receipt.result.model_dump(mode="json"), command.operation)
                saved = saved.model_copy(update={"terminal_json": json.dumps(result, sort_keys=True), "receipt_id": receipt.id})
                self.db.execute("UPDATE runtime_requests SET record_json=? WHERE id=?", (saved.model_dump_json(), saved.id))
            return saved

    def requests(self, claim, *, unresolved_only=False):
        self.current(claim)
        return [LogicalRequest.model_validate_json(row[0]) for row in self.db.execute(
            "SELECT record_json FROM runtime_requests WHERE invocation_id=? "
            + ("AND json_extract(record_json,'$.terminal_json') IS NULL " if unresolved_only else "")
            + "ORDER BY rowid", (claim.invocation_id,))]

    def execution(self, claim, nonce, kind, ordinal, *, observation=None, details=None):
        with self.store.transaction():
            if observation is None:
                self.current(claim)
            else:
                known = self.db.execute("SELECT 1 FROM runtime_controls WHERE invocation_id=? AND "
                    "json_extract(result_json,'$.owner')=? AND json_extract(result_json,'$.fence')=?",
                    (claim.invocation_id, claim.owner, claim.fence)).fetchone()
                if known is None:
                    raise RuntimeConflict("UNKNOWN_OBSERVATION_SOURCE")
            raw = json.dumps({"kind": kind, "ordinal": ordinal, "observation": observation,
                              "details": details}, sort_keys=True, allow_nan=False)
            old = self.db.execute("SELECT record_json FROM runtime_trace WHERE invocation_id=? AND nonce=?",
                                  (claim.invocation_id, nonce)).fetchone()
            if old:
                if old[0] != raw:
                    raise RuntimeConflict("EXECUTION_CONFLICT")
                return True
            state = self._state(claim.invocation_id)
            if observation is None and kind in {"model", "tool"}:
                column, count, cap = ("model_cycles", state[2], 12) if kind == "model" else ("tool_requests", state[3], 40)
                if count >= cap:
                    raise RuntimeConflict("LIFETIME_LIMIT_EXHAUSTED")
                self.db.execute(f"UPDATE runtime_state SET {column}={column}+1 WHERE invocation_id=?", (claim.invocation_id,))
            elif observation is not None and kind == "tool" and observation.get("outcome") == "CANCELLED":
                authorized = self.db.execute("SELECT 1 FROM runtime_trace WHERE invocation_id=? AND nonce=?",
                    (claim.invocation_id, f"authorize-{claim.fence}-tool-{ordinal}")).fetchone()
                inv = self.store.get_invocation(claim.invocation_id)
                if authorized is None and state[3] < 40 and inv.fencing_token == claim.fence:
                    self.db.execute("UPDATE runtime_state SET tool_requests=tool_requests+1 WHERE invocation_id=?", (claim.invocation_id,))
            self.db.execute("INSERT INTO runtime_trace(invocation_id,nonce,kind,record_json) VALUES (?,?,?,?)",
                            (claim.invocation_id, nonce, kind, raw))
            return True

    def complete(self, claim, status, outcome):
        with self.store.transaction() as tx:
            old = self.store.get_invocation(claim.invocation_id)
            if (old.status == status and old.lease_owner == claim.owner and old.fencing_token == claim.fence
                    and (status != "ERROR" or old.error_code == outcome)):
                return old
            inv = self.current(claim, allow_expired=True)
            if status not in {"WAITING", "COMPLETED", "ERROR"}:
                raise RuntimeConflict("INVALID_DISPOSITION")
            result = inv.model_copy(update={"status": status, "finished_at": self.clock(),
                "error_code": outcome if status == "ERROR" else None, "lease_expires_at": self.clock(),
                "state_revision": inv.state_revision + 1})
            tx.replace_invocation(result, inv.state_revision)
            return result
