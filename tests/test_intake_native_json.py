"""Native Bedrock JSON (not Python tuple fixtures) at the real intake API boundary."""
import pytest
from test_investigation_repair import client_for, headers, photo

from agent import aws_session, investigation
from agent.store import Store


@pytest.mark.parametrize("defect", [None, "extra", "type", "truncated"])
def test_native_intake_json_and_truthful_stop_metadata(tmp_path, monkeypatch, defect):
    observed = []
    findings = {"visible_objects": ["couch"], "visible_hazards": [], "location_clues": [],
                "unknowns": ["ownership"], "observations": ["Couch occupies the sidewalk."]}
    if defect == "extra":
        findings["invented"] = True
    if defect == "type":
        findings["visible_objects"] = "couch"
    class Client:
        def converse(self, **request):
            observed.append(request)
            return {"stopReason": "max_tokens" if defect == "truncated" else "tool_use",
                "output": {"message": {"role": "assistant", "content": [{"toolUse": {
                    "name": "report_intake_findings", "input": findings}}]}},
                "usage": {"inputTokens": 12, "outputTokens": 30, "totalTokens": 42},
                "ResponseMetadata": {"RequestId": "offline-native-json"}}
    class Session:
        def client(self, *args, **kwargs):
            return Client()
    monkeypatch.setattr(aws_session, "frozen_boto3_session", lambda profile: Session())
    with Store(tmp_path / "b4.sqlite3") as store:
        signal = photo(store, tmp_path)
    with client_for(tmp_path) as client:
        response = client.post(f"/api/signals/{signal.id}/intake-inspection", headers=headers("native-json"))
        assert response.status_code == (200 if defect is None else 503), response.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        saved = store.intake_inspections_for_signal(signal.id)[0]
        assert saved.outcome == ("SUCCESS" if defect is None else "ERROR")
        assert saved.metadata.stop_reason == ("max_tokens" if defect == "truncated" else "tool_use")
        assert saved.metadata.usage.outputTokens == 30
        assert saved.request_version == investigation.INTAKE_REQUEST_VERSION
        if defect is not None:
            assert saved.findings is None
            assert not saved.cache_eligible
    assert len(observed) == 1
    assert observed[0]["inferenceConfig"]["maxTokens"] == investigation.INTAKE_MAX_TOKENS == 1024
