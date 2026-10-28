"""Fixed screenshot/input tool for the separately identified no-code protocol."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

try:
    from .codex_actions import native_action, parse_command, _unique_object
except ImportError:  # The two files are copied into the private agent container.
    from codex_actions import native_action, parse_command, _unique_object


TOOL = {
    "name": "computer",
    "description": (
        "Execute an ordered list of mouse/keyboard inputs and return the current "
        "screenshot. Send actions=[] to observe. Use native input objects described "
        "in the task instructions. This tool accepts literal inputs only."
    ),
    "inputSchema": {
        "type": "object", "properties": {
            "actions": {"type": "array", "items": {"type": "object"}},
        }, "required": ["actions"], "additionalProperties": False,
    },
}


def tool_schema():
    mode = os.environ.get("NO_CODE_TEMPORAL_MODE", "live")
    if mode not in {"paused", "live", "live_timestamped", "live_timestamped_execution"}:
        raise ValueError("Invalid no-code temporal mode")
    if mode != "live_timestamped_execution":
        return TOOL
    tool = json.loads(json.dumps(TOOL))
    tool["inputSchema"]["properties"]["execute_at_s"] = {
        "type": "number", "minimum": 0,
        "description": "Optional absolute environment time in seconds to start the action batch.",
    }
    return tool


def validate(arguments):
    fields = tool_schema()["inputSchema"]["properties"]
    if (not isinstance(arguments, dict) or "actions" not in arguments
            or set(arguments) - set(fields)):
        raise ValueError("Provide actions and only fields supported by this temporal mode")
    actions = arguments["actions"]
    if not isinstance(actions, list):
        raise ValueError("actions must be a list")
    for action in actions:
        native_action(action, (1, 1))
    # Reuse the gateway's finite-time and observation-only scheduling validation.
    parse_command(json.dumps(arguments), (1, 1))
    return actions


def computer(arguments):
    actions = validate(arguments)
    command = {"actions": actions, "observe": True}
    if "execute_at_s" in arguments:
        command["execute_at_s"] = arguments["execute_at_s"]
    request = urllib.request.Request(
        os.environ["GATEWAY_URL"],
        data=json.dumps({"command": json.dumps(command)}).encode(),
        headers={"Content-Type": "application/json",
                 "X-Gateway-Token": os.environ["GATEWAY_TOKEN"]},
    )
    started = time.perf_counter()
    status, body, error = None, b"", None
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            status = response.status
            body = response.read()
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        # End the metric before JSON parsing, image presentation, or inference.
        elapsed = 1000 * (time.perf_counter() - started)
        row = dict(total_ms=elapsed, status=status, response_bytes=len(body),
                   command=command, error=error, wall_time=time.time())
        with Path(os.environ.get("NO_CODE_TIMING", "/logs/no-code-http.jsonl")).open("a") as out:
            out.write(json.dumps(row) + "\n")
    response = json.loads(body)
    frames = response.pop("screenshots_b64", []) or []
    legacy = response.pop("screenshot_b64", None)
    if not frames and legacy:
        frames = [legacy]
    content = [{"type": "text", "text": json.dumps(response)}]
    for frame in frames:
        data = base64.b64decode(frame, validate=True)
        if data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        else:
            raise ValueError("The gateway returned an unsupported image format")
        content.append({"type": "image", "data": frame, "mimeType": mime,
                        "_meta": {"codex/imageDetail": "original"}})
    return {"content": content, "isError": bool(response.get("error"))}


def dispatch(message):
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "gym-anything-rt-no-code", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [tool_schema()]}
    if method == "tools/call":
        try:
            params = message["params"]
            if params.get("name") != "computer":
                raise ValueError("Only the computer tool is available")
            return computer(params.get("arguments"))
        except Exception as error:
            # Never automatically replay an input after an uncertain HTTP result.
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
    raise ValueError(f"Unsupported MCP method: {method}")


def main():
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line, object_pairs_hook=_unique_object)
            if "id" not in message:
                continue
            response = {"jsonrpc": "2.0", "id": message["id"], "result": dispatch(message)}
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": (message or {}).get("id"),
                        "error": {"code": -32602, "message": str(error)}}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
