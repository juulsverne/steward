import io

import pytest
from PIL import Image

from agent.vision import VisionOutputError, inspect_pair_result


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (24, 24), "gray").save(out, format="JPEG")
    return out.getvalue()


def output():
    return {
        "stopReason": "tool_use", "output": {"message": {
            "role": "assistant", "content": [{"toolUse": {
                "name": "report_findings", "toolUseId": "findings-1", "input": {
                    "target_present_before": True, "same_scene": True, "target_removed": True,
                    "no_new_hazard": True, "area_clear": False, "observations": ["Bags remain."],
                },
            }}],
        }}, "usage": {"inputTokens": 25, "outputTokens": 40},
    }


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def converse(self, **request):
        self.calls.append(request)
        return self.response


def test_one_bounded_converse_request_with_images_and_strict_findings():
    client = Client(output())
    result = inspect_pair_result(jpeg(), jpeg(), target="couch", work_area="sidewalk", client=client)
    assert len(client.calls) == 1
    request = client.calls[0]
    assert request["inferenceConfig"] == {"maxTokens": 1024, "temperature": 0}
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": "report_findings"}}
    assert result["findings"]["area_clear"] is False
    assert result["usage"]["inputTokens"] == 25


@pytest.mark.parametrize("failure", ["truncated", "wrong_tool", "invalid_boolean", "no_tool"])
def test_bad_model_response_cannot_become_a_finding(failure):
    response = output()
    if failure == "truncated":
        response["stopReason"] = "max_tokens"
    elif failure == "wrong_tool":
        response["output"]["message"]["content"][0]["toolUse"]["name"] = "pay"
    elif failure == "invalid_boolean":
        response["output"]["message"]["content"][0]["toolUse"]["input"]["area_clear"] = "yes"
    else:
        response["output"]["message"]["content"] = [{"text": "Everything is fine"}]
    with pytest.raises(VisionOutputError) as error:
        inspect_pair_result(jpeg(), jpeg(), target="couch", work_area="sidewalk",
                            client=Client(response))
    assert error.value.inspection["stop_reason"] == response["stopReason"]
    assert "structured_outputs" in error.value.inspection


def test_invalid_image_does_not_call_bedrock():
    client = Client(output())
    with pytest.raises(ValueError):
        inspect_pair_result(b"", jpeg(), target="couch", work_area="sidewalk", client=client)
    assert client.calls == []
