#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Callable


def request_json(
    path: str,
    *,
    port: int = 8787,
    payload: dict | None = None,
    timeout: float = 2.0,
) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"content-type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError(f"{path} returned a non-object JSON value")
    return result


def wait_for_status(
    predicate: Callable[[dict], bool],
    *,
    port: int = 8787,
    timeout: float = 10.0,
    interval: float = 0.02,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = request_json("/input-control/status", port=port)
            if predicate(last):
                return last
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(interval)
    raise TimeoutError(
        f"browser input barrier did not reach the requested state; last status: {last}"
    )


def arm(
    category: str,
    *,
    required: bool,
    port: int = 8787,
    timeout: float = 10.0,
) -> dict:
    accepted = request_json(
        "/input-control",
        port=port,
        payload={
            "command": "arm",
            "category": category,
            "required": required,
        },
    )
    command_sequence = int(accepted["sequence"])
    arm_sequence = int(accepted["arm_sequence"])
    return wait_for_status(
        lambda item: int(item.get("command_sequence") or -1) >= command_sequence
        and int(item.get("arm_sequence") or -1) == arm_sequence
        and item.get("phase") == "armed",
        port=port,
        timeout=timeout,
    )


def complete(
    arm_sequence: int,
    *,
    port: int = 8787,
    timeout: float = 10.0,
) -> dict:
    accepted = request_json(
        "/input-control",
        port=port,
        payload={"command": "complete", "arm_sequence": arm_sequence},
    )
    command_sequence = int(accepted["sequence"])
    return wait_for_status(
        lambda item: int(item.get("command_sequence") or -1) >= command_sequence
        and int(item.get("arm_sequence") or -1) == arm_sequence
        and item.get("phase") in {"completed", "missing"},
        port=port,
        timeout=timeout,
    )


def cancel(
    arm_sequence: int,
    *,
    port: int = 8787,
    timeout: float = 10.0,
) -> dict:
    accepted = request_json(
        "/input-control",
        port=port,
        payload={"command": "cancel", "arm_sequence": arm_sequence},
    )
    command_sequence = int(accepted["sequence"])
    return wait_for_status(
        lambda item: int(item.get("command_sequence") or -1) >= command_sequence
        and int(item.get("arm_sequence") or -1) == arm_sequence
        and item.get("phase") == "cancelled",
        port=port,
        timeout=timeout,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize native input delivery with the Gym-Anything-RT browser."
    )
    parser.add_argument("command", choices=("status", "arm", "complete", "cancel"))
    parser.add_argument("--category", choices=("mouse", "keyboard", "mixed"))
    parser.add_argument("--arm-sequence", type=int)
    parser.add_argument("--required", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.command == "arm" and args.category is None:
        parser.error("arm requires --category")
    if args.command in {"complete", "cancel"} and not args.arm_sequence:
        parser.error(f"{args.command} requires --arm-sequence")
    return args


def main() -> None:
    args = parse_args()
    if args.command == "status":
        result = request_json("/input-control/status", port=args.port)
    elif args.command == "arm":
        result = arm(
            args.category,
            required=args.required,
            port=args.port,
            timeout=args.timeout,
        )
    elif args.command == "complete":
        result = complete(
            args.arm_sequence,
            port=args.port,
            timeout=args.timeout,
        )
    else:
        result = cancel(
            args.arm_sequence,
            port=args.port,
            timeout=args.timeout,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
