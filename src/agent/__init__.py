"""Steward: one Strands agent on Amazon Bedrock for neighborhood operations.

The package is deliberately flat (see docs/ARCHITECTURE.md). Module map:

    runtime   config.py, core.py, cli.py, server.py, tools/
    domain    models.py, scoring.py, policy.py, verification.py, store.py
    vision    images.py, vision.py
    checks    foundation.py (offline), bedrock_check.py and vision_spike.py (live)
"""

from .core import build_agent

__all__ = ["build_agent"]
