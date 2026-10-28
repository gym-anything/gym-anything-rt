"""The screenshot/keyboard/mouse subset of Gym's public step contract.

Native actions keep their env.step structure and order. Only pointer coordinates
are converted from the displayed screenshot to the environment's resolution.
No task internals, runner commands, or privileged time controls cross this API.
"""

from __future__ import annotations

import json
import math
from typing import Any


MOUSE_POINTS = (
    "move",
    "left_click",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
)
MOUSE_DRAGS = ("left_click_drag", "right_click_drag")
MOUSE_BUTTONS = tuple(
    f"{button}_{state}"
    for button in ("left", "right", "middle")
    for state in ("down", "up")
)
KEYBOARD_FIELDS = ("text", "keys", "keys_down", "keys_up")
TERMINATE_ACTIONS = ("terminate", "done", "finish")


def _fields(value: Any, allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"unsupported {where} fields: {', '.join(sorted(unknown))}")


def _number(value: Any, where: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (nonnegative and value < 0):
        raise ValueError(
            f"{where} must be finite" + (" and non-negative" if nonnegative else "")
        )
    return value


def _point(value: Any, ratio: tuple[float, float]) -> list[int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("a pointer coordinate must be [x, y]")
    scaled = [_number(v, "coordinate") * r for v, r in zip(value, ratio)]
    return [int(_number(v, "scaled coordinate")) for v in scaled]


def native_action(action: Any, ratio: tuple[float, float]) -> dict[str, Any]:
    """Validate an entire native action before any part can reach the runner."""
    if not isinstance(action, dict) or not action:
        raise ValueError("each action must be a non-empty object")
    if "action" in action or "type" in action:
        kind = action.get("action", action.get("type"))
        if kind not in ("wait", "screenshot"):
            raise ValueError("native control actions are wait and screenshot only")
        label = "action" if "action" in action else "type"
        _fields(
            action,
            (label, "time", "seconds") if kind == "wait" else (label,),
            "control",
        )
        if "time" in action and "seconds" in action:
            raise ValueError("specify time or seconds, not both")
        if kind == "wait":
            _number(
                action.get("time", action.get("seconds", 1.0)),
                "wait time",
                nonnegative=True,
            )
        return dict(action)

    _fields(action, ("mouse", "keyboard"), "action")
    result: dict[str, Any] = {}
    if "mouse" in action:
        mouse = action["mouse"]
        _fields(mouse, (*MOUSE_POINTS, *MOUSE_DRAGS, "buttons", "scroll"), "mouse")
        if not mouse:
            raise ValueError("mouse must contain an input")
        converted = dict(mouse)
        for field in MOUSE_POINTS:
            if field in mouse:
                converted[field] = _point(mouse[field], ratio)
        for field in MOUSE_DRAGS:
            if field in mouse:
                points = mouse[field]
                if not isinstance(points, list) or len(points) != 2:
                    raise ValueError(
                        f"{field} requires two endpoints; use held-button moves for a path"
                    )
                converted[field] = [_point(point, ratio) for point in points]
        if "buttons" in mouse:
            _fields(mouse["buttons"], MOUSE_BUTTONS, "mouse.buttons")
            if not mouse["buttons"] or any(
                type(v) is not bool for v in mouse["buttons"].values()
            ):
                raise ValueError("mouse.buttons must contain boolean button states")
            converted["buttons"] = dict(mouse["buttons"])
        if "scroll" in mouse:
            amount = _number(mouse["scroll"], "mouse.scroll")
            if int(amount) != amount:
                raise ValueError(
                    "mouse.scroll is an integer number of wheel notches, not pixels"
                )
        result["mouse"] = converted
    if "keyboard" in action:
        keyboard = action["keyboard"]
        _fields(keyboard, KEYBOARD_FIELDS, "keyboard")
        if not keyboard:
            raise ValueError("keyboard must contain an input")
        for field, value in keyboard.items():
            if field == "text":
                if not isinstance(value, str):
                    raise ValueError("keyboard.text must be a string")
            elif not (
                isinstance(value, str)
                and value
                or isinstance(value, list)
                and value
                and all(isinstance(key, str) and key for key in value)
            ):
                raise ValueError(
                    f"keyboard.{field} must be a key name or a non-empty list of key names"
                )
        result["keyboard"] = dict(keyboard)
    return result


def _legacy_actions(action: dict[str, Any]) -> list[dict[str, Any]]:
    """Retain old tap/click clients, but never silently discard their fields."""
    name = action.get("action")
    point_actions = {
        "mouse_move": "move",
        "click": "left_click",
        **{k: k for k in MOUSE_POINTS[1:]},
    }
    if name in point_actions:
        _fields(action, ("action", "coordinate"), str(name))
        return [{"mouse": {point_actions[name]: action["coordinate"]}}]
    if name in ("drag", *MOUSE_DRAGS):
        _fields(action, ("action", "coordinate", "coordinate2"), str(name))
        field = "left_click_drag" if name == "drag" else name
        return [{"mouse": {field: [action["coordinate"], action["coordinate2"]]}}]
    if name == "key":
        if "duration" in action or "time" in action:
            raise ValueError(
                "key is a tap; use keyboard.keys_down and keyboard.keys_up in separate steps to hold"
            )
        _fields(action, ("action", "keys"), "key")
        return [{"keyboard": {"keys": action["keys"]}}]
    if name == "type":
        _fields(action, ("action", "text", "clear", "enter"), "type")
        if any(type(action[k]) is not bool for k in ("clear", "enter") if k in action):
            raise ValueError("clear and enter must be booleans")
        actions = [{"keyboard": {"keys": ["ctrl", "a"]}}] if action.get("clear") else []
        actions.append({"keyboard": {"text": action["text"]}})
        if action.get("enter"):
            actions.append({"keyboard": {"keys": ["Return"]}})
        return actions
    if name == "scroll":
        _fields(action, ("action", "coordinate", "pixels", "scroll"), "scroll")
        if "pixels" in action and "scroll" in action:
            raise ValueError("specify one scroll amount")
        if not ("pixels" in action or "scroll" in action):
            raise ValueError("scroll requires an amount in wheel notches")
        # Historical 'pixels' was always passed to the runtime as wheel notches.
        actions = (
            [{"mouse": {"move": action["coordinate"]}}]
            if "coordinate" in action
            else []
        )
        return actions + [
            {"mouse": {"scroll": action.get("pixels", action.get("scroll"))}}
        ]
    raise ValueError(f"unsupported action: {name!r}; use native mouse/keyboard actions")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_command(
    command: str,
    ratio: tuple[float, float],
) -> tuple[list[dict[str, Any]], bool, bool, float | None]:
    """Return native actions, termination, observation-only, and start time."""
    if not isinstance(command, str):
        raise ValueError("command must be a JSON-encoded object or action list")
    request = json.loads(command, object_pairs_hook=_unique_object)
    execute_at_s = None
    if isinstance(request, dict) and "execute_at_s" in request:
        execute_at_s = _number(
            request.pop("execute_at_s"), "execute_at_s", nonnegative=True
        )
    if (
        isinstance(request, dict)
        and isinstance(request.get("action"), str)
        and request["action"] in TERMINATE_ACTIONS
    ):
        _fields(request, ("action", "status"), "termination")
        if "status" in request and not isinstance(request["status"], str):
            raise ValueError("termination status must be a string")
        if execute_at_s is not None:
            raise ValueError("termination cannot be scheduled")
        return [], True, False, None
    if isinstance(request, dict) and "actions" in request:
        _fields(request, ("actions",), "request")
        request = request["actions"]
        if not isinstance(request, list):
            raise ValueError("actions must be a list")
    if isinstance(request, list):
        actions = [native_action(action, ratio) for action in request]
    elif isinstance(request, dict):
        if "action" in request and request["action"] not in ("wait", "screenshot"):
            actions = [
                native_action(action, ratio) for action in _legacy_actions(request)
            ]
        else:
            actions = [native_action(request, ratio)]
    else:
        raise ValueError("command must contain an action object or list")
    observation_only = not actions or all(
        action.get("action", action.get("type")) == "screenshot" for action in actions
    )
    if observation_only and execute_at_s is not None:
        raise ValueError("an observation cannot be scheduled")
    return actions, False, observation_only, execute_at_s
