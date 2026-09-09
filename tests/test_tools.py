from agent.tools.example import summarize_workload


def _call(fn, **kwargs):
    """@tool wraps the function; unwrap it so tests exercise plain Python."""
    return getattr(fn, "__wrapped__", fn)(**kwargs)


def test_flags_heavy_workload():
    result = _call(summarize_workload, items=["a", "b", "c", "d", "e"], threshold=5)
    assert result["count"] == 5
    assert result["is_heavy"] is True


def test_light_workload_not_flagged():
    result = _call(summarize_workload, items=["a"], threshold=5)
    assert result["is_heavy"] is False
    assert result["preview"] == ["a"]
