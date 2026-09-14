"""Export only observable synthetic-fixture results; never credentials or reasoning blocks."""
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

root = Path.cwd()
names = ["nova-micro", "nova-lite", "gpt-oss-20b", "gpt-oss-120b", "ministral-8b",
         "nova-2-lite", "haiku-4-5", "sonnet-4-6"]
result = {
    "kind": "component_screen_not_workflow_acceptance",
    "date_utc": "2026-09-13",
    "source_commit_at_export": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(),
    "source_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in [
        "uv.lock", "src/agent/bedrock_check.py", "src/agent/vision.py",
        "src/agent/vision_spike.py", "src/agent/verification.py", "data/images/manifest.json"]},
    "limits": [
        "One tool round trip per model; no Steward domain tools were available.",
        "One pass through four frozen synthetic photo pairings per image model.",
        "The strict vision spike requires at least three repeats, so passed=false is expected even for 4/4.",
        "False automatic acceptance means the component predicate returned true; no payment was executed.",
        "No hidden reasoning is exported; model-generated tool input and visible observations are retained.",
        "The CLI generic tool check grades tool use and a final reply, not strict timestamp-only formatting.",
    ],
    "models": [],
}

def without_request_ids(value):
    if isinstance(value, dict):
        return {k: without_request_ids(v) for k, v in value.items() if k != "request_id"}
    if isinstance(value, list):
        return [without_request_ids(v) for v in value]
    return value

for name in names:
    tool = json.loads(Path(f".steward/model-screen-{name}-tools.json").read_text())
    item = {"label": name, "tool_round_trip": tool}
    path = Path(f".steward/model-screen-{name}-vision.json")
    if path.exists():
        vision = without_request_ids(json.loads(path.read_text()))
        runs = [run for values in vision["pairings"].values() for run in values]
        summary = {
            "matched": sum(r.get("matches_expectation") is True for r in runs),
            "total": len(runs),
            "false_acceptances": sum(r.get("false_automatic_acceptance") is True for r in runs),
            "errors": sum(bool(r.get("error")) for r in runs),
            "input_tokens": sum(r.get("inspection", {}).get("usage", {}).get("inputTokens", 0) for r in runs),
            "output_tokens": sum(r.get("inspection", {}).get("usage", {}).get("outputTokens", 0) for r in runs),
            "median_latency_s": statistics.median(r["latency_s"] for r in runs),
        }
        item.update(vision_summary=summary, vision_screen=vision)
    result["models"].append(item)
    print(name, json.dumps({"tools": tool["passed"], "tool_usage": tool.get("usage"),
                            "tool_latency": tool["latency_s"],
                            "vision": item.get("vision_summary")}))

out = Path("docs/evaluations/2026-09-13-model-screen.json")
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
