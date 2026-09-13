"""SQLite schema ownership and atomic upgrades; never reset an unknown database."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

SCHEMA_1 = """
CREATE TABLE issues (
    id TEXT PRIMARY KEY, category TEXT NOT NULL, location TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CANDIDATE',
    evidence_score INTEGER NOT NULL DEFAULT 0 CHECK(evidence_score BETWEEN 0 AND 100),
    score_json TEXT NOT NULL, geocode_json TEXT, service_record_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE signals (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE issue_sources (
    issue_id TEXT NOT NULL REFERENCES issues(id),
    signal_id TEXT NOT NULL UNIQUE REFERENCES signals(id),
    PRIMARY KEY (issue_id, signal_id)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL REFERENCES issues(id),
    event_type TEXT NOT NULL, timestamp TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""

# Scalar FK, state, revision and money columns are authoritative. record_json stores
# the validated full typed record for nested fields; Store overlays every scalar column
# when decoding, so a stale JSON copy cannot override a relational authority column.
TABLES = {
    "vendors": "id TEXT PRIMARY KEY",
    "plans": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
        district_id TEXT NOT NULL, quote_cents INTEGER NOT NULL CHECK(
        typeof(quote_cents)='integer' AND quote_cents>0), state_revision INTEGER NOT NULL,
        UNIQUE(id, issue_id)""",
    "jobs": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
        plan_id TEXT NOT NULL UNIQUE, vendor_id TEXT NOT NULL REFERENCES vendors(id),
        price_cents INTEGER NOT NULL CHECK(typeof(price_cents)='integer' AND price_cents>0),
        status TEXT NOT NULL CHECK(status IN ('POSTED','ASSIGNED','CHECKED_IN','PROOF_SUBMITTED',
        'VERIFIED','PAID','REWORK_REQUIRED','REJECTED','CANCELLED')),
        state_revision INTEGER NOT NULL CHECK(state_revision>=0), latest_submission_id TEXT,
        UNIQUE(id, issue_id), UNIQUE(id, vendor_id),
        FOREIGN KEY(plan_id, issue_id) REFERENCES plans(id, issue_id),
        FOREIGN KEY(latest_submission_id, id, issue_id) REFERENCES submissions(id,job_id,issue_id)
        DEFERRABLE INITIALLY DEFERRED""",
    "evidence": """id TEXT PRIMARY KEY, image_ref TEXT NOT NULL UNIQUE,
        image_sha256 TEXT NOT NULL, provenance TEXT NOT NULL""",
    "evidence_associations": """id TEXT PRIMARY KEY,
        evidence_id TEXT NOT NULL REFERENCES evidence(id), role TEXT NOT NULL,
        signal_id TEXT REFERENCES signals(id), issue_id TEXT REFERENCES issues(id), job_id TEXT,
        CHECK(signal_id IS NOT NULL OR issue_id IS NOT NULL),
        CHECK(job_id IS NULL OR issue_id IS NOT NULL),
        FOREIGN KEY(job_id, issue_id) REFERENCES jobs(id, issue_id)""",
    "submissions": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL,
        job_id TEXT NOT NULL, before_evidence_id TEXT NOT NULL REFERENCES evidence(id),
        after_evidence_id TEXT NOT NULL REFERENCES evidence(id),
        CHECK(before_evidence_id<>after_evidence_id),
        UNIQUE(id, job_id, issue_id),
        FOREIGN KEY(job_id, issue_id) REFERENCES jobs(id, issue_id)""",
    "verifications": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, job_id TEXT NOT NULL,
        submission_id TEXT NOT NULL, job_revision INTEGER NOT NULL,
        UNIQUE(id, submission_id, job_id, issue_id),
        FOREIGN KEY(submission_id, job_id, issue_id) REFERENCES submissions(id, job_id, issue_id)""",
    "exceptions": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
        job_id TEXT, submission_id TEXT, verification_id TEXT, denial_event_id INTEGER
        REFERENCES events(id), kind TEXT NOT NULL, reason_code TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING','DECIDED','HANDLED')),
        state_revision INTEGER NOT NULL CHECK(state_revision>=0),
        UNIQUE(id, submission_id, job_id, issue_id),
        CHECK(submission_id IS NULL OR job_id IS NOT NULL),
        CHECK(kind<>'completion' OR (job_id IS NOT NULL AND submission_id IS NOT NULL
            AND verification_id IS NOT NULL AND denial_event_id IS NOT NULL)),
        FOREIGN KEY(job_id, issue_id) REFERENCES jobs(id, issue_id),
        FOREIGN KEY(submission_id, job_id, issue_id) REFERENCES submissions(id,job_id,issue_id),
        FOREIGN KEY(verification_id, submission_id, job_id, issue_id)
            REFERENCES verifications(id,submission_id,job_id,issue_id)""",
    "operator_decisions": """id TEXT PRIMARY KEY, exception_id TEXT NOT NULL UNIQUE,
        issue_id TEXT NOT NULL, job_id TEXT NOT NULL, submission_id TEXT NOT NULL,
        handled_at TEXT,
        FOREIGN KEY(exception_id,submission_id,job_id,issue_id)
            REFERENCES exceptions(id,submission_id,job_id,issue_id)""",
    "budgets": """id TEXT PRIMARY KEY, initial_cents INTEGER NOT NULL
        CHECK(typeof(initial_cents)='integer' AND initial_cents>=0),
        state_revision INTEGER NOT NULL CHECK(state_revision>=0)""",
    "reservations": """id TEXT PRIMARY KEY, budget_id TEXT NOT NULL REFERENCES budgets(id),
        issue_id TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE,
        amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>0),
        status TEXT NOT NULL CHECK(status IN ('RESERVED','CONSUMED','RELEASED')),
        state_revision INTEGER NOT NULL CHECK(state_revision>=0),
        UNIQUE(id,job_id,issue_id), UNIQUE(id,job_id,budget_id),
        FOREIGN KEY(job_id,issue_id) REFERENCES jobs(id,issue_id)""",
    "payments": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE,
        reservation_id TEXT NOT NULL UNIQUE, submission_id TEXT NOT NULL,
        verification_id TEXT NOT NULL, amount_cents INTEGER NOT NULL
        CHECK(typeof(amount_cents)='integer' AND amount_cents>0),
        UNIQUE(id,reservation_id,job_id),
        FOREIGN KEY(reservation_id,job_id,issue_id) REFERENCES reservations(id,job_id,issue_id),
        FOREIGN KEY(verification_id,submission_id,job_id,issue_id)
            REFERENCES verifications(id,submission_id,job_id,issue_id)""",
    "ledger": """id TEXT PRIMARY KEY, budget_id TEXT NOT NULL,
        job_id TEXT NOT NULL, reservation_id TEXT NOT NULL, payment_id TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('RESERVE','CONSUME','RELEASE')),
        amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents>0),
        event_id INTEGER NOT NULL REFERENCES events(id), UNIQUE(reservation_id,kind),
        CHECK((kind='CONSUME' AND payment_id IS NOT NULL) OR
              (kind<>'CONSUME' AND payment_id IS NULL)),
        FOREIGN KEY(reservation_id,job_id,budget_id) REFERENCES reservations(id,job_id,budget_id),
        FOREIGN KEY(payment_id,reservation_id,job_id) REFERENCES payments(id,reservation_id,job_id)""",
    "decisions": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
        job_id TEXT, trigger_event_id INTEGER NOT NULL REFERENCES events(id),
        invocation_id TEXT REFERENCES invocations(id),
        FOREIGN KEY(job_id,issue_id) REFERENCES jobs(id,issue_id)""",
    "invocations": """id TEXT PRIMARY KEY, trigger_event_id INTEGER NOT NULL UNIQUE
        REFERENCES events(id), trigger_type TEXT NOT NULL,
        signal_id TEXT REFERENCES signals(id), issue_id TEXT REFERENCES issues(id), job_id TEXT,
        status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','WAITING','COMPLETED','ERROR')),
        state_revision INTEGER NOT NULL CHECK(state_revision>=0),
        fencing_token INTEGER NOT NULL CHECK(fencing_token>=0),
        FOREIGN KEY(job_id,issue_id) REFERENCES jobs(id,issue_id)""",
    "request_receipts": """id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, operation TEXT NOT NULL,
        idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL,
        signal_id TEXT REFERENCES signals(id), issue_id TEXT REFERENCES issues(id), job_id TEXT,
        invocation_id TEXT REFERENCES invocations(id), UNIQUE(actor_id,operation,idempotency_key),
        FOREIGN KEY(job_id,issue_id) REFERENCES jobs(id,issue_id)""",
    "service_lookups": """id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES issues(id),
        signal_id TEXT NOT NULL REFERENCES signals(id), UNIQUE(issue_id,signal_id)""",
}


def execute_ddl(db: sqlite3.Connection, script: str) -> None:
    """Unlike executescript, never implicitly commit the caller's migration."""
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete migration SQL")


def _immutable(db: sqlite3.Connection, table: str) -> None:
    for operation in ("UPDATE", "DELETE"):
        db.execute(f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} are append-only'); END")


def _upgrade_two(db: sqlite3.Connection) -> None:
    # Empty dependent tables exist before the copy so SQLite can resolve every FK.
    db.execute("ALTER TABLE issues ADD COLUMN state_revision INTEGER NOT NULL DEFAULT 0")
    db.execute("ALTER TABLE issues ADD COLUMN resolved_at TEXT")
    db.execute("ALTER TABLE issues ADD COLUMN accepted_submission_id TEXT REFERENCES submissions(id)")
    db.execute("ALTER TABLE issues ADD COLUMN responsibility TEXT")
    db.execute("ALTER TABLE issues ADD COLUMN hazards_json TEXT NOT NULL DEFAULT '[]'")
    for table, columns in TABLES.items():
        db.execute(f"CREATE TABLE {table} (record_json TEXT NOT NULL, {columns})")
    sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
    db.execute("""CREATE TABLE events_v2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT REFERENCES issues(id),
        signal_id TEXT REFERENCES signals(id), job_id TEXT,
        invocation_id TEXT REFERENCES invocations(id), event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL, payload TEXT NOT NULL,
        actor_id TEXT, actor_json TEXT, state_revision INTEGER, policy_version TEXT,
        CHECK(issue_id IS NOT NULL OR signal_id IS NOT NULL),
        CHECK(job_id IS NULL OR issue_id IS NOT NULL),
        FOREIGN KEY(job_id,issue_id) REFERENCES jobs(id,issue_id))""")
    db.execute("INSERT INTO events_v2(id,issue_id,event_type,timestamp,payload) "
               "SELECT id,issue_id,event_type,timestamp,payload FROM events")
    db.execute("DROP TABLE events")
    db.execute("ALTER TABLE events_v2 RENAME TO events")
    if sequence:
        db.execute("UPDATE sqlite_sequence SET seq=max(seq, ?) WHERE name='events'", (sequence[0],))
    _immutable(db, "events")
    db.execute("""CREATE TABLE signal_receipts (
        signal_id TEXT PRIMARY KEY REFERENCES signals(id), actor_id TEXT NOT NULL,
        event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
        record_json TEXT NOT NULL)""")
    for table in ("signals", "issue_sources", "plans", "evidence", "evidence_associations", "submissions", "verifications",
                  "payments", "ledger", "decisions", "request_receipts", "signal_receipts",
                  "service_lookups"):
        _immutable(db, table)
    db.execute("CREATE UNIQUE INDEX jobs_one_active ON jobs(issue_id) "
               "WHERE status NOT IN ('CANCELLED','REJECTED')")
    db.execute("CREATE INDEX evidence_hash ON evidence(image_sha256)")
    db.execute("CREATE INDEX receipts_actor ON request_receipts(actor_id,signal_id)")
    db.execute("CREATE INDEX signal_receipts_actor ON signal_receipts(actor_id,signal_id)")
    db.execute("CREATE INDEX events_signal ON events(signal_id,id)")
    db.execute("CREATE INDEX pending_invocations ON invocations(status,trigger_event_id)")
    db.execute("CREATE UNIQUE INDEX evidence_owner ON evidence_associations "
               "(evidence_id,role,coalesce(signal_id,''),coalesce(issue_id,''),coalesce(job_id,''))")
    db.execute("CREATE UNIQUE INDEX pending_completion ON exceptions(job_id) "
               "WHERE kind='completion' AND status IN ('PENDING','DECIDED')")
    db.execute("CREATE UNIQUE INDEX completion_failure ON exceptions(job_id,submission_id,reason_code) "
               "WHERE kind='completion'")
    db.execute("CREATE UNIQUE INDEX pending_issue_exception ON exceptions(issue_id,kind,reason_code) "
               "WHERE job_id IS NULL AND status IN ('PENDING','DECIDED')")
    db.execute("CREATE UNIQUE INDEX reservation_terminal_ledger ON ledger(reservation_id) "
               "WHERE kind IN ('CONSUME','RELEASE')")


def migrate(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    # Recheck after locking: another connection may just have initialized/upgraded.
    with db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise ValueError(f"unsupported database schema {version}")
        if version == 0:
            existing = db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
            if existing.fetchone():
                raise ValueError("unsupported unversioned nonempty database schema")
            execute_ddl(db, SCHEMA_1)
        if version < 2:
            _upgrade_two(db)
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("database schema contains foreign key violations")
        required = {"issues", "signals", "issue_sources", "events", "signal_receipts", *TABLES}
        actual = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= actual:
            raise ValueError("incomplete database schema")
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
