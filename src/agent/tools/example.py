"""A worked example of a custom Strands tool.

Delete this once your real tools exist -- it is here to show the shape:
the @tool decorator turns a typed function into something the model can call,
and the docstring is what the model reads to decide *when* to call it.
"""

from __future__ import annotations

from strands import tool


@tool
def summarize_workload(items: list[str], threshold: int = 5) -> dict:
    """Summarize a list of pending work items and flag when it needs attention.

    Args:
        items: The pending work items, one per string.
        threshold: Count at or above which the workload is flagged as heavy.

    Returns:
        A dict with the item count, whether it is heavy, and the first few items.
    """
    count = len(items)
    return {
        "count": count,
        "is_heavy": count >= threshold,
        "preview": items[:3],
    }
