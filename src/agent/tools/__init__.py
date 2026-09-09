"""Tool registry.

Every tool the agent can call is collected here. Add your own tools as modules in
this package, then append them to TOOLS.

Two kinds of tools are available:
  1. Community tools from `strands_tools` (calculator, current_time, http_request,
     file_read, shell, ...). See https://github.com/strands-agents/tools
  2. Your own functions decorated with @tool -- see example.py
"""

from strands_tools import current_time

from .example import summarize_workload

TOOLS = [
    current_time,
    summarize_workload,
]

__all__ = ["TOOLS"]
