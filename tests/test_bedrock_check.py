from agent.bedrock_check import round_trip_passed, tools_used


def transcript(*, status="success"):
    return [
        {"role": "assistant", "content": [{"toolUse": {
            "name": "current_time", "toolUseId": "clock-1", "input": {},
        }}]},
        {"role": "user", "content": [{"toolResult": {
            "toolUseId": "clock-1", "status": status,
            "content": [{"text": "2026-09-13T15:00:00Z"}],
        }}]},
        {"role": "assistant", "content": [{"text": "2026-09-13T15:00:00Z"}]},
    ]


def test_requested_tool_is_not_enough_to_prove_round_trip():
    messages = transcript()
    assert tools_used(messages) == ["current_time"]
    assert round_trip_passed(messages, stop_reason="end_turn")
    assert not round_trip_passed(messages[:1], stop_reason="end_turn")
    assert not round_trip_passed(messages[:2], stop_reason="end_turn")
    assert not round_trip_passed(transcript(status="error"), stop_reason="end_turn")
    assert not round_trip_passed(messages, stop_reason="max_tokens")
    messages[1]["content"][0]["toolResult"]["toolUseId"] = "another-call"
    assert not round_trip_passed(messages, stop_reason="end_turn")


def test_empty_or_fabricated_results_do_not_pass():
    assert tools_used([]) == []
    assert not round_trip_passed([], stop_reason="end_turn")
    assert not round_trip_passed(transcript()[1:], stop_reason="end_turn")
