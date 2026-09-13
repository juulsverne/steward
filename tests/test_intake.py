from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartException

from agent import contracts as c
from agent.config import ApiSettings
from agent.images import ImageStorage, UploadError, decode_upload, dhash
from agent.intake import persist_official_record, persist_signal, resident_signal
from agent.models import Signal
from agent.scoring import persistence_points, score_evidence
from agent.store import IdempotencyConflict, Store

ORIGIN = "http://localhost:8000"
SIGNING = "7a9c4e63b081f205d92461a37c90586ef413ab290675d8ebca013b25e74609df"
TOKEN = "b198d27f3ce40596a180f24d83b710e59603c147ed0f96ca5248ab031d7629fe"
INTENT = {"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "intake-1"}


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), "red").save(buffer, format="JPEG")
    return buffer.getvalue()


def colored_jpeg_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 12), color).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def config(tmp_path):
    return ApiSettings(store_path=tmp_path / "steward.sqlite3", image_root=tmp_path / "images",
                       origin=ORIGIN, session_secret=SIGNING, service_token=TOKEN,
                       local_http=True)


@pytest.fixture
def client(config):
    from agent.api import create_app

    app = create_app(config)
    with TestClient(app, base_url=ORIGIN) as result:
        assert result.post("/api/demo/persona", json={"persona_id": "resident-1"},
                           headers=INTENT).status_code == 200
        yield result


def submit(client, *, key="intake-1", image=True, description="Couch blocks sidewalk",
           location="1530 S Michigan Ave", observed_at=None):
    fields = {"description": (None, description), "location": (None, location)}
    if observed_at is not None:
        fields["observed_at"] = (None, observed_at)
    if image:
        fields["image"] = ("normal.jpg", jpeg_bytes(), "image/jpeg")
    return client.post("/api/signals", files=fields, headers={**INTENT, "Idempotency-Key": key})


def test_authenticated_intake_normalizes_and_atomically_receipts_evidence(client, config):
    response = submit(client, observed_at="2026-01-01T00:00:00Z")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["outcome"] == "OK"
    assert set(body["data"]) == {"receipt_id", "signal_id", "received_at", "accepted", "processing"}
    signal_id = body["data"]["signal_id"]
    assert body["data"]["receipt_id"] == signal_id
    assert body["data"]["processing"] == "PENDING"
    with Store(config.store_path) as store:
        signal = store.get_signal(signal_id)
        evidence = store.evidence_for_entity(signal_id=signal_id)
        receipt = store.get_signal_receipt(signal_id)
        assert signal.source_author_id == "demo-resident-1"
        assert signal.source_role == "resident_observation"
        assert len(evidence) == 1 and evidence[0].content_type == "image/jpeg"
        assert evidence[0].image_sha256 == signal.image_sha256
        assert evidence[0].size_bytes > 0
        assert evidence[0].observed_at == signal.observed_at
        assert receipt.invocation_id is None
        assert store.pending_invocations()[0].signal_id == signal_id
    assert len(list(config.image_root.glob("*.jpg"))) == 1


def test_intake_retry_is_stable_but_changed_payload_conflicts(client, config):
    first = submit(client, key="repeat")
    retry = submit(client, key="repeat")
    assert first.status_code == retry.status_code == 202
    assert first.json()["data"] == retry.json()["data"]
    changed = submit(client, key="repeat", description="Different report")
    assert changed.status_code == 409
    with Store(config.store_path) as store:
        assert len(store.pending_invocations()) == 1
        assert len(store.evidence_for_entity(signal_id=first.json()["data"]["signal_id"])) == 1


def test_intake_rejects_unauthenticated_invalid_images_and_oversize_without_receipt(client, config):
    client.cookies.clear()
    assert client.post("/api/signals", files={"description": (None, "x"),
        "location": (None, "y")}, headers={"Idempotency-Key": "x"}).status_code == 401
    assert client.post("/api/demo/persona", json={"persona_id": "resident-1"},
                       headers=INTENT).status_code == 200
    malformed = client.post("/api/signals", files={"description": (None, "x"),
        "location": (None, "y"), "image": ("x.jpg", b"not-an-image", "image/jpeg")}, headers=INTENT)
    assert malformed.status_code == 415
    oversized = client.post("/api/signals", files={"description": (None, "x"),
        "location": (None, "y"), "image": ("x.jpg", b"x" * (10 * 1024 * 1024 + 1), "image/jpeg")}, headers=INTENT)
    assert oversized.status_code == 413
    with Store(config.store_path) as store:
        assert store.pending_invocations() == []


def test_storage_uses_server_ref_and_normalized_stored_hash(tmp_path):
    normalized = decode_upload(jpeg_bytes(), "image/jpeg")
    storage = ImageStorage(tmp_path / "private-images")
    stored = storage.put("opaque-evidence-ref", normalized)
    assert stored.image_ref == "opaque-evidence-ref"
    assert storage.open(stored.image_ref) == normalized.bytes
    with pytest.raises(UploadError):
        storage.open("../../escape")


def test_normalized_dhash_matches_the_final_stored_jpeg_bytes(tmp_path):
    normalized = decode_upload(Path("data/images/reused.jpg").read_bytes(), "image/jpeg")
    storage = ImageStorage(tmp_path / "private-images")
    storage.put("opaque-evidence-ref", normalized)
    assert normalized.image_dhash == dhash(storage.root / "opaque-evidence-ref.jpg")


def test_official_never_scores_and_persistence_requires_same_author_fresh_lineage():
    at = datetime(2026, 1, 1, tzinfo=UTC)
    earlier = Signal(id="one", source="resident", source_author_id="resident-1", raw_text="couch",
        reported_location="place", received_at=at, observed_at=at, provenance="live",
        image_sha256="a" * 64, image_dhash="1" * 16, source_role="resident_observation")
    cross_author = replace(earlier, id="two", source_author_id="resident-2",
        received_at=datetime(2026, 1, 2, tzinfo=UTC), observed_at=datetime(2026, 1, 2, tzinfo=UTC),
        image_sha256="b" * 64, image_dhash="2" * 16)
    reencoded = replace(earlier, id="three", received_at=datetime(2026, 1, 2, tzinfo=UTC),
        observed_at=datetime(2026, 1, 2, tzinfo=UTC), image_sha256="c" * 64)
    later = replace(earlier, id="four", received_at=datetime(2026, 1, 2, tzinfo=UTC),
        observed_at=datetime(2026, 1, 2, tzinfo=UTC), image_sha256="d" * 64, image_dhash="f" * 16)
    official = replace(earlier, id="official", source_role="official_record", image_sha256=None,
                       image_dhash=None)
    assert score_evidence([official]).components["image"] == 0
    assert persistence_points([earlier, cross_author]) == 0
    assert persistence_points([earlier, reencoded]) == 0
    assert persistence_points([earlier, later]) == 10


def test_official_adapter_persists_a_source_record_without_agent_or_pending_work(config):
    with Store(config.store_path) as store:
        receipt = persist_official_record(store, source_id="official-1", text="311 completed",
            location="1530 S Michigan Ave", received_at=datetime(2026, 1, 1, tzinfo=UTC))
        assert store.get_signal(receipt.signal_id).source_role == "official_record"
        assert store.pending_invocations() == []


def test_known_original_and_normalized_fixture_uploads_remain_synthetic(client, config):
    original = Path("data/images/before.jpg").read_bytes()
    first = client.post("/api/signals", files={"description": (None, "fixture"),
        "location": (None, "1530 S Michigan Ave"), "image": ("before.jpg", original, "image/jpeg")},
        headers={**INTENT, "Idempotency-Key": "fixture-original"})
    normalized = decode_upload(original, "image/jpeg").bytes
    second = client.post("/api/signals", files={"description": (None, "fixture normalized"),
        "location": (None, "1530 S Michigan Ave"), "image": ("before.jpg", normalized, "image/jpeg")},
        headers={**INTENT, "Idempotency-Key": "fixture-normalized"})
    ordinary = client.post("/api/signals", files={"description": (None, "ordinary"),
        "location": (None, "1530 S Michigan Ave"), "image": ("ordinary.jpg", jpeg_bytes(), "image/jpeg")},
        headers={**INTENT, "Idempotency-Key": "ordinary"})
    assert first.status_code == second.status_code == ordinary.status_code == 202
    with Store(config.store_path) as store:
        for response in (first, second):
            signal_id = response.json()["data"]["signal_id"]
            assert store.get_signal(signal_id).provenance == "synthetic"
            assert store.evidence_for_entity(signal_id=signal_id)[0].provenance == "synthetic"
        assert store.get_signal(ordinary.json()["data"]["signal_id"]).provenance == "live"


def test_future_observation_and_pathlike_filename_are_sanitized_validation_errors(client, config):
    future = client.post("/api/signals", files={"description": (None, "x"),
        "location": (None, "y"), "observed_at": (None, "2999-01-01T00:00:00Z"),
        "image": ("normal.jpg", jpeg_bytes(), "image/jpeg")}, headers={**INTENT, "Idempotency-Key": "future"})
    traversal = client.post("/api/signals", files={"description": (None, "x"),
        "location": (None, "y"), "image": ("../../evil.jpg", jpeg_bytes(), "image/jpeg")},
        headers={**INTENT, "Idempotency-Key": "traversal"})
    assert future.status_code == traversal.status_code == 422
    assert "2999" not in future.text and "evil" not in traversal.text
    with Store(config.store_path) as store:
        assert store.pending_invocations() == []


def test_uploaded_temp_files_close_on_success_and_validation_rejection(client, monkeypatch):
    closed = []
    original_close = UploadFile.close

    async def close(upload):
        closed.append(upload.filename)
        await original_close(upload)

    monkeypatch.setattr(UploadFile, "close", close)
    assert submit(client, key="close-success").status_code == 202
    rejected = client.post("/api/signals", files={"description": (None, " "),
        "location": (None, "place"), "image": ("rejected.jpg", jpeg_bytes(), "image/jpeg")},
        headers={**INTENT, "Idempotency-Key": "close-rejected"})
    assert rejected.status_code == 422
    assert "normal.jpg" in closed and "rejected.jpg" in closed


def test_concurrent_first_arrival_same_image_returns_one_stable_receipt(config):
    from agent.api import create_app

    barrier = Barrier(2)

    def request(_):
        with TestClient(create_app(config), base_url=ORIGIN) as local:
            assert local.post("/api/demo/persona", json={"persona_id": "resident-1"},
                              headers=INTENT).status_code == 200
            barrier.wait()
            return submit(local, key="concurrent", image=True)

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(request, range(2)))
    assert all(response.status_code == 202 for response in responses)
    assert responses[0].json()["data"] == responses[1].json()["data"]
    with Store(config.store_path) as store:
        signal_id = responses[0].json()["data"]["signal_id"]
        signal = store.get_signal(signal_id)
        evidence = store.evidence_for_entity(signal_id=signal_id)[0]
        stored = ImageStorage(config.image_root).open(evidence.image_ref)
        assert hashlib.sha256(stored).hexdigest() == evidence.image_sha256 == signal.image_sha256
        assert len(store.pending_invocations()) == 1


def test_publication_never_overwrites_and_interrupted_publish_retries(tmp_path, monkeypatch):
    from agent import images

    storage = ImageStorage(tmp_path / "objects")
    first, second = decode_upload(colored_jpeg_bytes("red"), "image/jpeg"), decode_upload(
        colored_jpeg_bytes("blue"), "image/jpeg")
    original_link = images.os.link

    def interrupted(*args):
        raise OSError("interrupted before publication")

    monkeypatch.setattr(images.os, "link", interrupted)
    with pytest.raises(UploadError):
        storage.put("stable", first)
    assert not (storage.root / "stable.jpg").exists()
    monkeypatch.setattr(images.os, "link", original_link)
    storage.put("stable", first)
    with pytest.raises(UploadError):
        storage.put("stable", second)
    assert storage.open("stable") == first.bytes


def test_conflicting_concurrent_persist_keeps_committed_evidence_bytes(tmp_path):
    path = tmp_path / "race.sqlite3"
    root = tmp_path / "objects"
    actor = c.ActorContext(actor_id="resident", actor_type="resident", label="Resident")
    one, two = decode_upload(colored_jpeg_bytes("red"), "image/jpeg"), decode_upload(
        colored_jpeg_bytes("blue"), "image/jpeg")
    barrier = Barrier(2)

    def persist(image, text):
        signal = resident_signal(actor=actor, idempotency_key="race", description=text, location="place",
            received_at=datetime(2026, 1, 1, tzinfo=UTC), observed_at=None, image=image)
        try:
            context = c.MutationContext(actor=actor, operation="submit_signal", idempotency_key="race")
            barrier.wait()
            with Store(path) as store:
                return persist_signal(store, signal=signal, context=context, image=image,
                                      image_root=root, provenance="live")
        except IdempotencyConflict as error:  # test captures the competing writer result
            return error

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda item: persist(*item), ((one, "one"), (two, "two"))))
    successes = [item for item in results if not isinstance(item, Exception)]
    assert len(successes) == 1
    assert any(isinstance(item, IdempotencyConflict) for item in results if isinstance(item, Exception))
    with Store(path) as store:
        signal_id = successes[0].signal_id
        signal = store.get_signal(signal_id)
        evidence = store.evidence_for_entity(signal_id=signal_id)[0]
        stored = ImageStorage(root).open(evidence.image_ref)
        assert hashlib.sha256(stored).hexdigest() == evidence.image_sha256 == signal.image_sha256
        assert len(store.pending_invocations()) == 1


def test_truncated_http_multipart_is_rejected_without_state_or_open_upload(client, config, monkeypatch):
    from agent import api

    parsers = []
    original_init = api.IntakeMultiPartParser.__init__

    def track_parser(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        parsers.append(self)

    monkeypatch.setattr(api.IntakeMultiPartParser, "__init__", track_parser)
    boundary = "truncated"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"description\"\r\n\r\n"
        "Couch blocks sidewalk\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"location\"\r\n\r\n"
        "1530 S Michigan Ave\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"normal.jpg\"\r\n"
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + jpeg_bytes()
    response = client.post("/api/signals", content=body, headers={
        **INTENT,
        "Idempotency-Key": "truncated",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    assert response.status_code == 422
    assert "normal.jpg" not in response.text
    assert parsers and not parsers[0]._multipart_complete
    assert parsers[0]._files_to_close_on_error
    assert all(file.closed for file in parsers[0]._files_to_close_on_error)
    with Store(config.store_path) as store:
        for table in ("signals", "evidence", "signal_receipts", "request_receipts", "invocations"):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.pending_invocations() == []


def test_no_evidence_request_fingerprint_remains_pre_b3_compatible(tmp_path):
    from agent.store import request_fingerprint

    signal = Signal(id="legacy-replay", source="feed", source_author_id="resident", raw_text="text",
        reported_location="place", received_at=datetime(2026, 1, 1, tzinfo=UTC), provenance="seeded")
    actor = c.ActorContext(actor_id="service", actor_type="service", label="Service")
    context = c.MutationContext(actor=actor, operation="ingest_source", idempotency_key="legacy")
    old_request = signal.to_dict()
    old_request.pop("received_at")
    expected = request_fingerprint({"signal": old_request, "expected_revision": None,
                                    "actor": actor.model_dump(mode="json")})
    invocation = c.PendingInvocationSpec(id="legacy-invocation", trigger_type="SIGNAL_RECEIVED",
                                         policy_version="south-loop-v3")
    with Store(tmp_path / "legacy.sqlite3") as store:
        first = store.receive_signal(signal, context=context, invocation=invocation)
        assert first.request_sha256 == expected
        assert store.receive_signal(signal, context=context, invocation=invocation) == first


@pytest.mark.asyncio
async def test_streamed_multipart_limit_without_content_length_closes_temp_file():
    from agent.api import IntakeMultiPartParser

    body = (b"--bounded\r\nContent-Disposition: form-data; name=\"image\"; filename=\"large.jpg\"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + b"x" * (10 * 1024 * 1024 + 1)
            + b"\r\n--bounded--\r\n")

    async def stream():
        for offset in range(0, len(body), 8192):
            yield body[offset:offset + 8192]

    parser = IntakeMultiPartParser(Headers({"content-type": "multipart/form-data; boundary=bounded"}),
                                    stream())
    with pytest.raises(MultiPartException):
        await parser.parse()
    assert parser._files_to_close_on_error
    assert all(file.closed for file in parser._files_to_close_on_error)
