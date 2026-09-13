"""Invocation-bound domain sessions and the preserved starter/preflight registry.

B11 consumes build_steward_tool_session().tools. TOOLS remains the unchanged
starter compatibility list; it is not Steward's domain capability set.
"""

from strands_tools import current_time

from .example import summarize_workload
from .session import InvocationToolSession, build_steward_tool_session

TOOLS = [
    current_time,
    summarize_workload,
]

__all__ = ["TOOLS", "InvocationToolSession", "build_steward_tool_session"]
