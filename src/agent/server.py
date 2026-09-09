"""FastAPI server -- the basis for a live demo link.

The hackathon notes that projects with a live demo score higher on Technical
Implementation, so this streams the agent over SSE and is ready to deploy.

    uv run uvicorn agent.server:app --reload
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .core import build_agent

app = FastAPI(title="Agents for Humans")


class Ask(BaseModel):
    prompt: str


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


async def _stream(prompt: str) -> AsyncIterator[str]:
    # callback_handler=None so Strands does not also print to stdout.
    agent = build_agent(callback_handler=None)
    async for event in agent.stream_async(prompt):
        if "data" in event:
            yield f"data: {json.dumps({'type': 'text', 'text': event['data']})}\n\n"
        elif "current_tool_use" in event and event["current_tool_use"].get("name"):
            name = event["current_tool_use"]["name"]
            yield f"data: {json.dumps({'type': 'tool', 'name': name})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


@app.post("/ask")
async def ask(body: Ask) -> StreamingResponse:
    return StreamingResponse(_stream(body.prompt), media_type="text/event-stream")
