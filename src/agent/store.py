"""Transactional records and foundation scoring; not an HTTP authorization surface."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from . import contracts as c
from .migrations import SCHEMA_VERSION, migrate
from .models import PROVENANCE, ServiceRecord, Signal, nonempty
from .scoring import dispute_supported, score_evidence

POLICY_VERSION = "south-loop-v3"
PRECISE_GEOCODE_MAX_M = 30
__all__ = ["SCHEMA_VERSION", "IdempotencyConflict", "RevisionConflict", "Store", "StoreTransaction"]

class IdempotencyConflict(ValueError):
    """A stable key or ID was reused with different content."""


class RevisionConflict(ValueError):
    """Stored state changed since the operation's snapshot."""


RECORDS = {
    c.VendorRecord: "vendors", c.PlanRecord: "plans", c.JobRecord: "jobs",
    c.EvidenceRecord: "evidence", c.EvidenceAssociation: "evidence_associations",
    c.SubmissionRecord: "submissions", c.VerificationRecord: "verifications",
    c.ExceptionRecord: "exceptions", c.OperatorDecisionRecord: "operator_decisions",
    c.BudgetRecord: "budgets", c.ReservationRecord: "reservations", c.PaymentRecord: "payments",
    c.LedgerEntry: "ledger", c.DecisionRecord: "decisions", c.InvocationRecord: "invocations",
    c.RequestReceipt: "request_receipts", c.ServiceLookupRecord: "service_lookups",
}


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """One connection per invocation; writer transactions serialize score updates.

    Arguments are facts supplied by trusted adapters, not exposed HTTP tool inputs.
    Future action tools must derive authority from stored evidence and policy.
    """

    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            migrate(self.db)
        except Exception:
            self.db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.db.close()

    @contextmanager
    def _write(self):
        if self.db.in_transaction:
            raise RuntimeError("nested Store transaction is not permitted")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def _event(self, issue_id: str, event_type: str, payload: dict) -> None:
        self.db.execute(
            "INSERT INTO events(issue_id,signal_id,event_type,timestamp,payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_id, payload.get("signal_id"), event_type, now(), encoded({
                **payload, "policy_version": POLICY_VERSION, "actor": "foundation_service",
            })),
        )

    def _require_open(self, issue_id: str) -> dict:
        issue = self.get_issue(issue_id)
        if issue["status"] not in {"CANDIDATE", "MONITORING", "ACTIONABLE", "RESOLUTION_ACTIVE"}:
            raise ValueError("issue closed or not accepting evidence; preserve new signal for review")
        return issue

    def create_issue(self, issue_id: str, category: str, location: str) -> dict:
        for name, value in (("issue_id", issue_id), ("category", category), ("location", location)):
            nonempty(value, name)
        with self._write():
            existing = self.db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if existing:
                if existing["category"] != category or existing["location"] != location:
                    raise ValueError("issue id payload conflict")
            else:
                self.db.execute(
                    "INSERT INTO issues(id, category, location, score_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (issue_id, category, location, encoded(score_evidence([]).to_dict()), now()),
                )
                self._event(issue_id, "ISSUE_CREATED", {"category": category, "location": location})
            result = self.get_issue(issue_id)
        return result

    def _signals(self, issue_id: str) -> list[Signal]:
        rows = self.db.execute(
            "SELECT s.payload FROM signals s JOIN issue_sources x ON x.signal_id = s.id "
            "WHERE x.issue_id = ? ORDER BY s.id", (issue_id,),
        ).fetchall()
        return [Signal.from_dict(json.loads(row["payload"])) for row in rows]

    def _refresh_score(self, issue_id: str) -> dict:
        issue = self.get_issue(issue_id)
        geocode = issue["geocode"]
        record = issue["service_record"]
        score = score_evidence(
            self._signals(issue_id),
            precise_geocode=geocode is not None and geocode["accuracy_m"] <= PRECISE_GEOCODE_MAX_M,
            matching_service_record=ServiceRecord.from_dict(record) if record else None,
        ).to_dict()
        self.db.execute(
            "UPDATE issues SET evidence_score = ?, score_json = ?, "
            "state_revision=state_revision+1 WHERE id = ?",
            (score["total"], encoded(score), issue_id),
        )
        return score

    def add_signal(self, issue_id: str, signal: Signal) -> dict:
        with self._write():
            self._insert_signal(signal)
            result = self._link_signal(issue_id, signal.id)
        return result

    def record_geocode(self, issue_id: str, *, accuracy_m: float, provenance: str) -> dict:
        if (
            type(accuracy_m) not in (int, float) or not math.isfinite(accuracy_m)
            or accuracy_m < 0 or provenance not in PROVENANCE
        ):
            raise ValueError("geocode needs finite nonnegative accuracy and explicit provenance")
        geocode = {"accuracy_m": float(accuracy_m), "provenance": provenance}
        with self._write():
            issue = self._require_open(issue_id)
            if issue["geocode"] != geocode:
                self.db.execute(
                    "UPDATE issues SET geocode_json = ? WHERE id = ?", (encoded(geocode), issue_id)
                )
                self._event(issue_id, "GEOCODE_RECORDED", {
                    "geocode": geocode, "score": self._refresh_score(issue_id),
                })
            result = self.get_issue(issue_id)
        return result

    def record_service_match(self, issue_id: str, record: dict) -> dict:
        """Record a supplied matching-record fact, not a lookup or a physical dispute.

        A COMPLETED record starts as a pending conflict and credits no points until
        ``confirm_official_dispute`` finds two independent newer observations.
        """
        if set(record) != {"id", "status", "provenance", "completed_at"}:
            raise ValueError("service record requires id, status, provenance, completed_at")
        parsed = ServiceRecord(
            **record, conflict="pending" if record["status"] == "COMPLETED" else "none"
        )
        with self._write():
            issue = self._require_open(issue_id)
            current = issue["service_record"]
            same_fact = current is not None and all(
                current[key] == parsed.to_dict()[key] for key in record
            )
            if not same_fact:
                self.db.execute(
                    "UPDATE issues SET service_record_json = ? WHERE id = ?",
                    (encoded(parsed.to_dict()), issue_id),
                )
                self._event(issue_id, "SERVICE_MATCH_RECORDED", {
                    "record": parsed.to_dict(), "score": self._refresh_score(issue_id),
                })
            result = self.get_issue(issue_id)
        return result

    def confirm_official_dispute(self, issue_id: str) -> dict:
        """Deterministic gate: two independent observations newer than the completed record."""
        with self._write():
            issue = self._require_open(issue_id)
            current = issue["service_record"]
            if current is None or current["status"] != "COMPLETED":
                raise ValueError("no completed service record to dispute")
            record = ServiceRecord.from_dict(current)
            if record.conflict != "disputed":
                if not dispute_supported(self._signals(issue_id), record):
                    raise ValueError(
                        "dispute not supported: need two independent observations "
                        "newer than the official completion"
                    )
                disputed = replace(record, conflict="disputed").to_dict()
                self.db.execute(
                    "UPDATE issues SET service_record_json = ? WHERE id = ?",
                    (encoded(disputed), issue_id),
                )
                self._event(issue_id, "OFFICIAL_STATUS_DISPUTED", {
                    "record": disputed, "score": self._refresh_score(issue_id),
                    "evidence_ids": issue["signal_ids"],
                })
            result = self.get_issue(issue_id)
        return result

    def get_issue(self, issue_id: str) -> dict:
        row = self.db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            raise KeyError(issue_id)
        issue = dict(row)
        for column, key in (
            ("score_json", "score"), ("geocode_json", "geocode"),
            ("service_record_json", "service_record"),
        ):
            value = issue.pop(column)
            issue[key] = json.loads(value) if value is not None else None
        issue["signal_ids"] = [r[0] for r in self.db.execute(
            "SELECT signal_id FROM issue_sources WHERE issue_id = ? ORDER BY signal_id", (issue_id,)
        )]
        return issue

    def events(self, issue_id: str) -> list[dict]:
        self.get_issue(issue_id)
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in self.db.execute(
                "SELECT * FROM events WHERE issue_id = ? ORDER BY id", (issue_id,)
            )
        ]

    @contextmanager
    def transaction(self):
        """Trusted service unit of work; recompute policy here, never perform network I/O.

        Record inserts alone do not authorize an action. The operation owner must append
        its audit/result in this same transaction. Not exposed as a generic API/tool.
        """
        with self._write():
            tx = StoreTransaction(self)
            try:
                yield tx
            finally:
                tx.active = False

    def _insert_signal(self, signal: Signal) -> None:
        # Revalidate even callers using dataclasses.replace/custom construction.
        signal = Signal.from_dict(signal.to_dict())
        payload = encoded(signal.to_dict())
        existing = self.db.execute("SELECT payload FROM signals WHERE id=?", (signal.id,)).fetchone()
        if existing:
            if existing[0] != payload:
                raise IdempotencyConflict("signal id payload conflict")
        else:
            self.db.execute("INSERT INTO signals(id,payload) VALUES (?,?)", (signal.id, payload))

    def get_signal(self, signal_id: str) -> Signal:
        row = self.db.execute("SELECT payload FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row is None:
            raise KeyError(signal_id)
        return Signal.from_dict(json.loads(row[0]))

    def _link_signal(self, issue_id: str, signal_id: str) -> dict:
        signal = self.get_signal(signal_id)
        link = self.db.execute("SELECT issue_id FROM issue_sources WHERE signal_id=?",
                               (signal_id,)).fetchone()
        if link:
            if link[0] != issue_id:
                raise IdempotencyConflict("signal already linked to another issue")
            return self.get_issue(issue_id)
        self._require_open(issue_id)
        self.db.execute("INSERT INTO issue_sources(issue_id,signal_id) VALUES (?,?)",
                        (issue_id, signal_id))
        score = self._refresh_score(issue_id)
        self._event(issue_id, "SIGNAL_LINKED", {
            "signal_id": signal_id, "provenance": signal.provenance, "score": score,
            "evidence_ids": self.get_issue(issue_id)["signal_ids"],
        })
        return self.get_issue(issue_id)

    def link_signal(self, issue_id: str, signal_id: str, *,
                    expected_revision: int | None = None) -> dict:
        with self.transaction() as tx:
            existing = self.db.execute("SELECT issue_id FROM issue_sources WHERE signal_id=?",
                                       (signal_id,)).fetchone()
            if existing is None:
                tx.require_issue(issue_id, expected_revision)
            return self._link_signal(issue_id, signal_id)

    def get_signal_receipt(self, signal_id: str) -> c.SignalReceipt:
        row = self.db.execute("SELECT record_json FROM signal_receipts WHERE signal_id=?",
                               (signal_id,)).fetchone()
        if row is None:
            raise KeyError(signal_id)
        return c.SignalReceipt.model_validate_json(row[0])

    def seed_receipt(self) -> c.SeedReceipt:
        row = self.db.execute("SELECT record_json FROM seed_receipts ORDER BY id LIMIT 1").fetchone()
        if row is None:
            raise KeyError("seed receipt")
        return c.SeedReceipt.model_validate_json(row[0])

    def save_seed_receipt(self, receipt: c.SeedReceipt) -> None:
        receipt = c.SeedReceipt.model_validate_json(receipt.model_dump_json())
        with self.transaction():
            row = self.db.execute("SELECT record_json FROM seed_receipts WHERE id=?", (receipt.id,)).fetchone()
            if row is not None:
                if row[0] != receipt.model_dump_json():
                    raise IdempotencyConflict("seed receipt payload conflict")
                return
            self.db.execute("INSERT INTO seed_receipts(id,record_json) VALUES (?,?)",
                            (receipt.id, receipt.model_dump_json()))

    def issue_for_signal(self, signal_id: str) -> c.IssueRecord | None:
        """Current canonical link, distinct from the immutable intake receipt snapshot."""
        self.get_signal(signal_id)
        row = self.db.execute("SELECT issue_id FROM issue_sources WHERE signal_id=?",
                              (signal_id,)).fetchone()
        return self.get_issue_record(row[0]) if row is not None else None

    def signal_receipt_actor(self, signal_id: str) -> str:
        """Submitting actor, distinct from the signal's source-author/witness lineage."""
        row = self.db.execute("SELECT actor_id FROM signal_receipts WHERE signal_id=?",
                               (signal_id,)).fetchone()
        if row is None:
            raise KeyError(signal_id)
        return row[0]

    def signal_receipts_for_actor(self, actor_id: str) -> list[c.SignalReceipt]:
        return [c.SignalReceipt.model_validate_json(row[0]) for row in self.db.execute(
            "SELECT record_json FROM signal_receipts WHERE actor_id=? ORDER BY event_id", (actor_id,)
        )]

    def signal_events(self, signal_id: str) -> list[dict]:
        self.get_signal(signal_id)
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in self.db.execute(
            "SELECT * FROM events WHERE signal_id=? ORDER BY id", (signal_id,)
        )]

    def store_signal(self, signal: Signal, *, actor: c.ActorContext | None = None) -> c.SignalReceipt:
        """Persist an unlinked receipt; receive_signal adds durable invocation/idempotency."""
        actor = actor or c.ActorContext(actor_id="foundation_service", actor_type="service",
                                        label="Foundation service")
        with self.transaction() as tx:
            self._insert_signal(signal)
            try:
                return self.get_signal_receipt(signal.id)
            except KeyError:
                pass
            event = tx.append_event(c.NewEvent(
                signal_id=signal.id, event_type="SIGNAL_RECEIVED", timestamp=datetime.now(UTC),
                actor=actor, policy_version=POLICY_VERSION,
                payload=c.EventFacts(provenance=signal.provenance),
            ))
            receipt = c.SignalReceipt(signal_id=signal.id, received_at=signal.received_at,
                                       event_id=event.id)
            self.db.execute("INSERT INTO signal_receipts VALUES (?,?,?,?)",
                            (signal.id, actor.actor_id, event.id, receipt.model_dump_json()))
            return receipt

    def receive_signal(self, signal: Signal, *, context: c.MutationContext,
                       invocation: c.PendingInvocationSpec,
                       evidence: c.SignalEvidenceBundle | None = None) -> c.RequestReceipt:
        """Signal, receipt event, pending invocation and retry result commit together."""
        if invocation.trigger_type != "SIGNAL_RECEIVED":
            raise ValueError("signal intake requires SIGNAL_RECEIVED trigger")
        # The server-assigned receipt time and new invocation ID are not request content.
        request = signal.to_dict()
        request.pop("received_at")
        # The historical request shape deliberately excludes generated receipt/evidence fields.
        # Signal image digests remain part of ``request`` and distinguish client image content.
        fingerprint = request_fingerprint({"signal": request, "expected_revision":
            context.expected_revision, "actor": context.actor.model_dump(mode="json")})
        with self.transaction() as tx:
            previous = tx.lookup_request(context, fingerprint)
            if previous is not None:
                return previous
            self._insert_signal(signal)
            if evidence is not None:
                if evidence.association.signal_id != signal.id:
                    raise ValueError("signal evidence bundle belongs to a different signal")
                tx.insert_evidence(evidence.evidence)
                tx.associate_evidence(evidence.association)
            try:
                receipt = self.get_signal_receipt(signal.id)
                event = self.get_event(receipt.event_id)
                if self.signal_receipt_actor(signal.id) != context.actor.actor_id:
                    raise IdempotencyConflict("signal receipt belongs to another submitting actor")
            except KeyError:
                event = tx.append_event(c.NewEvent(
                    signal_id=signal.id, event_type="SIGNAL_RECEIVED", timestamp=datetime.now(UTC),
                    actor=context.actor, policy_version=invocation.policy_version,
                    payload=c.EventFacts(provenance=signal.provenance),
                ))
                receipt = c.SignalReceipt(signal_id=signal.id, received_at=signal.received_at,
                                           event_id=event.id)
                self.db.execute("INSERT INTO signal_receipts VALUES (?,?,?,?)", (
                    signal.id, context.actor.actor_id, event.id, receipt.model_dump_json(),
                ))
            pending = tx.insert_pending_invocation(invocation, event)
            result_receipt = c.SignalReceipt(**{
                **receipt.model_dump(), "invocation_id": pending.id,
            })
            result = c.RequestReceipt(
                id=str(uuid4()), operation=context.operation, actor_id=context.actor.actor_id,
                idempotency_key=context.idempotency_key, request_sha256=fingerprint,
                signal_id=signal.id, invocation_id=pending.id, created_at=datetime.now(UTC),
                result=c.ToolResult[c.SignalReceipt | c.EntityResult](
                    outcome="OK", data=result_receipt, event_ids=(event.id,),
                ),
            )
            tx.save_request(result)
            return result

    def _record(self, model, record_id: str):
        table = RECORDS[model]
        row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        data = json.loads(row["record_json"])
        data.update({key: value for key, value in dict(row).items() if key != "record_json"})
        return model.model_validate_json(encoded(data))

    def get_issue_record(self, issue_id: str) -> c.IssueRecord:
        issue = self.get_issue(issue_id)
        return c.IssueRecord.model_validate_json(encoded({
            key: issue[key] for key in ("id", "category", "location", "status", "state_revision",
                "evidence_score", "created_at", "resolved_at", "accepted_submission_id",
                "responsibility", "signal_ids")
        } | {"hazards": json.loads(issue["hazards_json"]),
             "components": issue["score"]["components"]}))

    def get_plan(self, record_id: str) -> c.PlanRecord:
        return self._record(c.PlanRecord, record_id)

    def plans_for_issue(self, issue_id: str) -> list[c.PlanRecord]:
        """Typed read for server-side district validation; no authorization by itself."""
        self.get_issue_record(issue_id)
        return [self.get_plan(row[0]) for row in self.db.execute(
            "SELECT id FROM plans WHERE issue_id=? ORDER BY id", (issue_id,)
        )]

    def get_vendor(self, record_id: str) -> c.VendorRecord:
        return self._record(c.VendorRecord, record_id)

    def get_job(self, record_id: str) -> c.JobRecord:
        return self._record(c.JobRecord, record_id)

    def get_evidence(self, record_id: str) -> c.EvidenceRecord:
        return self._record(c.EvidenceRecord, record_id)

    def evidence_associations(self, evidence_id: str) -> list[c.EvidenceAssociation]:
        self.get_evidence(evidence_id)
        return [self._record(c.EvidenceAssociation, row[0]) for row in self.db.execute(
            "SELECT id FROM evidence_associations WHERE evidence_id=? ORDER BY id", (evidence_id,)
        )]

    def evidence_for_entity(self, *, signal_id: str | None = None,
                            issue_id: str | None = None, job_id: str | None = None
                            ) -> list[c.EvidenceRecord]:
        """Saved associations only; the actor-aware API must authorize the entity first."""
        supplied = {key: value for key, value in {
            "signal_id": signal_id, "issue_id": issue_id, "job_id": job_id,
        }.items() if value is not None}
        if len(supplied) != 1:
            raise ValueError("select exactly one saved entity")
        key, value = next(iter(supplied.items()))
        return [self.get_evidence(row[0]) for row in self.db.execute(
            f"SELECT DISTINCT evidence_id FROM evidence_associations WHERE {key}=? "
            "ORDER BY evidence_id", (value,)
        )]

    def get_submission(self, record_id: str) -> c.SubmissionRecord:
        return self._record(c.SubmissionRecord, record_id)

    def get_verification(self, record_id: str) -> c.VerificationRecord:
        return self._record(c.VerificationRecord, record_id)

    def get_exception(self, record_id: str) -> c.ExceptionRecord:
        return self._record(c.ExceptionRecord, record_id)

    def get_operator_decision(self, record_id: str) -> c.OperatorDecisionRecord:
        return self._record(c.OperatorDecisionRecord, record_id)

    def get_budget(self, record_id: str) -> c.BudgetRecord:
        return self._record(c.BudgetRecord, record_id)

    def get_reservation(self, record_id: str) -> c.ReservationRecord:
        return self._record(c.ReservationRecord, record_id)

    def get_payment(self, record_id: str) -> c.PaymentRecord:
        return self._record(c.PaymentRecord, record_id)

    def get_ledger_entry(self, record_id: str) -> c.LedgerEntry:
        return self._record(c.LedgerEntry, record_id)

    def get_decision(self, record_id: str) -> c.DecisionRecord:
        return self._record(c.DecisionRecord, record_id)

    def get_request(self, record_id: str) -> c.RequestReceipt:
        return self._record(c.RequestReceipt, record_id)

    def get_service_lookup(self, record_id: str) -> c.ServiceLookupRecord:
        return self._record(c.ServiceLookupRecord, record_id)

    def get_invocation(self, record_id: str) -> c.InvocationRecord:
        return self._record(c.InvocationRecord, record_id)

    def pending_invocations(self, limit: int = 20) -> list[c.InvocationRecord]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        return [self.get_invocation(row[0]) for row in self.db.execute(
            "SELECT id FROM invocations WHERE status='PENDING' ORDER BY trigger_event_id LIMIT ?",
            (limit,),
        )]

    def get_event(self, event_id: int) -> c.EventRecord:
        """Typed events created by B1+. Legacy event dictionaries remain in events()."""
        row = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        if row["actor_json"] is None:
            raise ValueError("legacy event has no typed actor; use events() projection")
        data = dict(row)
        data["actor"] = json.loads(data.pop("actor_json"))
        data.pop("actor_id")
        data["payload"] = json.loads(data["payload"])
        return c.EventRecord.model_validate_json(encoded(data))


def request_fingerprint(data: dict) -> str:
    """Canonical validated request facts; callers exclude generated receipt/result IDs."""
    return hashlib.sha256(encoded(data).encode("utf-8")).hexdigest()


class StoreTransaction:
    """Internal typed repositories, usable only within Store.transaction().

    All names/columns come from a fixed registry, never request strings. Consumers must
    call policy-owning operations, not expose these inserts directly through HTTP tools.
    """

    def __init__(self, store: Store):
        self.store = store
        self.active = True

    def _check(self):
        if not self.active or not self.store.db.in_transaction:
            raise RuntimeError("StoreTransaction is no longer active")

    def _insert(self, record: c.Record):
        self._check()
        model = type(record)
        record = model.model_validate_json(record.model_dump_json())
        table = RECORDS[model]
        try:
            previous = self.store._record(model, record.id)
        except KeyError:
            previous = None
        if previous is not None:
            if previous != record:
                raise IdempotencyConflict(f"{table} id payload conflict")
            return
        data = record.model_dump(mode="json")
        columns = [row[1] for row in self.store.db.execute(f"PRAGMA table_info({table})")]
        values = [record.model_dump_json() if key == "record_json" else data[key] for key in columns]
        self.store.db.execute(f"INSERT INTO {table} ({','.join(columns)}) "
                              f"VALUES ({','.join('?' for _ in columns)})", values)

    def _replace(self, record: c.Record, expected_revision: int, mutable: set[str]):
        self._check()
        record = type(record).model_validate_json(record.model_dump_json())
        current = self.store._record(type(record), record.id)
        self._revision(current.state_revision, expected_revision)
        if record.state_revision != expected_revision + 1:
            raise RevisionConflict("replacement must increment state_revision exactly once")
        for name in type(record).model_fields:
            if name not in mutable | {"state_revision"} and getattr(current, name) != getattr(record, name):
                raise ValueError(f"immutable {name}")
        table = RECORDS[type(record)]
        data = record.model_dump(mode="json")
        columns = [row[1] for row in self.store.db.execute(f"PRAGMA table_info({table})")
                   if row[1] != "id"]
        values = [record.model_dump_json() if name == "record_json" else data[name]
                  for name in columns]
        self.store.db.execute(f"UPDATE {table} SET " + ",".join(f"{name}=?" for name in columns)
                              + " WHERE id=?", [*values, record.id])

    @staticmethod
    def _revision(actual: int, expected: int | None):
        if expected is not None and (type(expected) is not int or expected < 0 or actual != expected):
            raise RevisionConflict("stale or invalid expected revision")

    def require_issue(self, issue_id: str, expected_revision: int | None = None) -> c.IssueRecord:
        self._check()
        issue = self.store.get_issue_record(issue_id)
        self._revision(issue.state_revision, expected_revision)
        return issue

    def require_job(self, job_id: str, expected_revision: int | None = None) -> c.JobRecord:
        self._check()
        job = self.store.get_job(job_id)
        self._revision(job.state_revision, expected_revision)
        return job

    def lookup_request(self, context: c.MutationContext, fingerprint: str) -> c.RequestReceipt | None:
        self._check()
        row = self.store.db.execute(
            "SELECT id,request_sha256 FROM request_receipts WHERE actor_id=? AND operation=? "
            "AND idempotency_key=?", (context.actor.actor_id, context.operation, context.idempotency_key)
        ).fetchone()
        if row is None:
            return None
        if row[1] != fingerprint:
            raise IdempotencyConflict("idempotency key payload conflict")
        return self.store.get_request(row[0])

    def append_event(self, event: c.NewEvent) -> c.EventRecord:
        self._check()
        event = c.NewEvent.model_validate_json(event.model_dump_json())
        cursor = self.store.db.execute(
            "INSERT INTO events(issue_id,signal_id,job_id,invocation_id,event_type,timestamp,"
            "payload,actor_id,actor_json,state_revision,policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (event.issue_id, event.signal_id, event.job_id, event.invocation_id, event.event_type,
             event.timestamp.isoformat(), event.payload.model_dump_json(), event.actor.actor_id,
             event.actor.model_dump_json(), event.state_revision, event.policy_version),
        )
        return c.EventRecord(**event.model_dump(), id=cursor.lastrowid)

    def insert_pending_invocation(self, spec: c.PendingInvocationSpec,
                                  trigger: c.EventRecord) -> c.InvocationRecord:
        self._check()
        persisted = self.store.get_event(trigger.id)
        if persisted != trigger or trigger.event_type != spec.trigger_type:
            raise ValueError("invocation requires matching persisted trigger event")
        row = self.store.db.execute("SELECT id FROM invocations WHERE trigger_event_id=?",
                                    (trigger.id,)).fetchone()
        if row:
            return self.store.get_invocation(row[0])
        record = c.InvocationRecord(
            id=spec.id, trigger_event_id=trigger.id, trigger_type=spec.trigger_type,
            signal_id=trigger.signal_id, issue_id=trigger.issue_id, job_id=trigger.job_id,
            policy_version=spec.policy_version, created_at=datetime.now(UTC),
        )
        self._insert(record)
        return record

    def insert_vendor(self, record: c.VendorRecord) -> None:
        self._insert(record)

    def insert_budget(self, record: c.BudgetRecord) -> None:
        self._insert(record)

    def insert_plan(self, record: c.PlanRecord) -> None:
        self._insert(record)

    def insert_job(self, record: c.JobRecord) -> None:
        self._check()
        plan = self.store.get_plan(record.plan_id)
        if plan.quote_cents != record.price_cents:
            raise ValueError("job price differs from plan quote")
        self._insert(record)

    def insert_evidence(self, record: c.EvidenceRecord) -> None:
        self._insert(record)

    def associate_evidence(self, record: c.EvidenceAssociation) -> None:
        self._check()
        if record.signal_id is not None and record.issue_id is not None:
            link = self.store.db.execute("SELECT issue_id FROM issue_sources WHERE signal_id=?",
                                         (record.signal_id,)).fetchone()
            if link is None or link[0] != record.issue_id:
                raise ValueError("evidence signal is not linked to this issue")
        self._insert(record)

    def insert_submission(self, record: c.SubmissionRecord) -> None:
        self._check()
        job = self.require_job(record.job_id)
        if job.issue_id != record.issue_id or job.vendor_id != record.submitted_by.vendor_id:
            raise ValueError("submission actor/job/issue mismatch")
        for evidence_id, role in ((record.before_evidence_id, "before"),
                                   (record.after_evidence_id, "completion")):
            rows = self.store.evidence_associations(evidence_id)
            if not any(a.issue_id == record.issue_id and a.role == role
                       and a.job_id in (None, record.job_id) for a in rows):
                raise ValueError("submission requires saved same-issue/job evidence association")
        self._insert(record)

    def insert_verification(self, record: c.VerificationRecord) -> None:
        self._insert(record)

    def insert_exception(self, record: c.ExceptionRecord) -> None:
        self._check()
        if record.kind == "completion":
            submission = self.store.get_submission(record.submission_id)
            if (record.before_evidence_id, record.after_evidence_id) != (
                submission.before_evidence_id, submission.after_evidence_id,
            ):
                raise ValueError("exception proof does not match submission")
            denial = self.store.get_event(record.denial_event_id)
            if (denial.payload.outcome != "DENIED" or denial.job_id != record.job_id
                    or denial.issue_id != record.issue_id
                    or denial.payload.submission_id != record.submission_id):
                raise ValueError("completion exception requires actual same-proof denial")
        self._insert(record)

    def insert_operator_decision(self, record: c.OperatorDecisionRecord) -> None:
        self._insert(record)

    def insert_reservation(self, record: c.ReservationRecord) -> None:
        self._check()
        if self.store.get_job(record.job_id).price_cents != record.amount_cents:
            raise ValueError("reservation amount differs from job")
        self._insert(record)

    def insert_payment(self, record: c.PaymentRecord) -> None:
        self._check()
        if self.store.get_reservation(record.reservation_id).amount_cents != record.amount_cents:
            raise ValueError("payment amount differs from reservation")
        self._insert(record)

    def append_ledger(self, record: c.LedgerEntry) -> None:
        self._check()
        if self.store.get_reservation(record.reservation_id).amount_cents != record.amount_cents:
            raise ValueError("ledger amount differs from reservation")
        self._insert(record)

    def append_decision(self, record: c.DecisionRecord) -> None:
        self._insert(record)

    def save_request(self, record: c.RequestReceipt) -> None:
        self._check()
        for event_id in record.result.event_ids:
            if self.store.db.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone() is None:
                raise ValueError("request result references missing event")
        self._insert(record)

    def insert_service_lookup(self, record: c.ServiceLookupRecord) -> None:
        self._insert(record)

    def replace_job(self, record: c.JobRecord, expected_revision: int) -> None:
        self._replace(record, expected_revision, {"status", "checkin_location", "checked_in_at",
            "accepted_at", "submitted_at", "paid_at", "latest_submission_id", "rework_instructions"})

    def replace_exception(self, record: c.ExceptionRecord, expected_revision: int) -> None:
        self._replace(record, expected_revision, {"status", "handled_at"})

    def replace_reservation(self, record: c.ReservationRecord, expected_revision: int) -> None:
        self._check()
        current = self.store.get_reservation(record.id)
        if current.status != "RESERVED" and record.status != current.status:
            raise ValueError("reservation is terminal")
        self._replace(record, expected_revision, {"status", "closed_at"})

    def replace_invocation(self, record: c.InvocationRecord, expected_revision: int) -> None:
        self._replace(record, expected_revision, {"issue_id", "job_id", "status", "started_at",
            "finished_at", "attempt_count", "lease_owner", "lease_expires_at", "fencing_token",
            "error_code", "metadata"})

    def mark_operator_decision_handled(self, decision_id: str, handled_at: datetime) -> None:
        self._check()
        current = self.store.get_operator_decision(decision_id)
        handled_at = c.utc_time(handled_at)
        if current.handled_at is not None:
            if current.handled_at != handled_at:
                raise IdempotencyConflict("operator decision already handled")
            return
        self.store.db.execute("UPDATE operator_decisions SET handled_at=? WHERE id=?",
                              (handled_at.isoformat(), decision_id))

    def replace_issue(self, record: c.IssueRecord, expected_revision: int) -> None:
        record = c.IssueRecord.model_validate_json(record.model_dump_json())
        current = self.require_issue(record.id, expected_revision)
        if record.state_revision != expected_revision + 1:
            raise RevisionConflict("replacement must increment state_revision exactly once")
        for key in ("id", "location", "evidence_score", "components", "created_at", "signal_ids"):
            if getattr(record, key) != getattr(current, key):
                raise ValueError(f"immutable/derived issue {key}")
        if record.accepted_submission_id is not None:
            submission = self.store.get_submission(record.accepted_submission_id)
            if submission.issue_id != record.id:
                raise ValueError("accepted submission belongs to another issue")
        self.store.db.execute(
            "UPDATE issues SET category=?,status=?,state_revision=?,resolved_at=?,"
            "accepted_submission_id=?,responsibility=?,hazards_json=? WHERE id=?",
            (record.category,record.status,record.state_revision,
             record.resolved_at.isoformat() if record.resolved_at else None,
             record.accepted_submission_id,record.responsibility,encoded(record.hazards),record.id),
        )
