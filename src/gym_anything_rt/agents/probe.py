from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


class AuthoritativeObservationProbeAgent:
    """Screenshot-only policy used to audit the evaluator transport.

    This is an evidence probe, not a benchmark-solving baseline. Every request
    runs Tesseract over the exact final frame supplied in ``obs["screen"]``.
    The first successful turn applies the visible action configured in
    ``agent_args`` (or the historical Grillmaster drag by default); the
    second successful turn ends the probe.
    """

    autonomous = False

    def __init__(
        self,
        *,
        agent_args: dict[str, Any],
        verbose: bool = False,
        debug: bool = False,
    ) -> None:
        self.agent_args = dict(agent_args)
        self.verbose = verbose
        self.debug = debug
        self.done = False
        self.request_index = 0
        self.successful_turn = 0
        self.save_path: Path | None = None
        self.display_resolution = (1920, 1080)

    def init(
        self,
        task_description: str,
        display_resolution: tuple[int, int],
        save_path: str,
    ) -> None:
        self.task_description = task_description
        self.display_resolution = tuple(display_resolution)
        self.save_path = Path(save_path)
        self.manifest_path = self.save_path / "model_input_manifest.jsonl"

    @staticmethod
    def _hash_frames(obs: dict[str, Any]) -> list[dict[str, Any]]:
        frames = list(obs.get("frames") or [])
        if not frames:
            raise ValueError("the authoritative probe requires obs['frames']")
        rows = []
        for index, frame in enumerate(frames):
            path = Path(str(frame["path"]))
            rows.append(
                {
                    "index": index,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "offset_ms": frame.get("offset_ms"),
                    "target_offset_ms": frame.get("target_offset_ms"),
                }
            )
        screen_path = Path(str((obs.get("screen") or {}).get("path") or ""))
        if screen_path.resolve() != Path(rows[-1]["path"]).resolve():
            raise ValueError("obs['screen'] is not the final delivered frame")
        return rows

    def _record(self, value: dict[str, Any]) -> None:
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    def _infer_visible_text(self, screen_path: str, request_index: int) -> str:
        transient_attempts = int(
            self.agent_args.get("transient_timeout_attempts", 0)
        )
        timeout = (
            0.000001
            if request_index <= transient_attempts
            else float(self.agent_args.get("inference_timeout_seconds", 10))
        )
        try:
            completed = subprocess.run(
                [
                    str(self.agent_args.get("tesseract_binary", "tesseract")),
                    screen_path,
                    "stdout",
                    "--psm",
                    "6",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"local vision inference exceeded its {timeout:g}s deadline"
            ) from exc
        return completed.stdout

    def step(
        self,
        obs: dict[str, Any],
        action_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        del action_outputs
        self.request_index += 1
        frames = self._hash_frames(obs)
        record: dict[str, Any] = {
            "request_index": self.request_index,
            "successful_turn_before_request": self.successful_turn,
            "backend": "tesseract-lstm",
            "frames": frames,
            "frame_count": len(frames),
            "screen_path": str(obs["screen"]["path"]),
            "screen_is_last_frame": True,
            "time": obs.get("time"),
            "capture_manifest": obs.get("capture_manifest"),
        }
        try:
            visible_text = self._infer_visible_text(
                str(obs["screen"]["path"]),
                self.request_index,
            )
        except TimeoutError as exc:
            record.update(
                {
                    "outcome": "transient_timeout",
                    "error": str(exc),
                }
            )
            self._record(record)
            raise

        normalized_text = " ".join(visible_text.upper().split())
        record.update(
            {
                "outcome": "success",
                "ocr_sha256": hashlib.sha256(
                    visible_text.encode("utf-8")
                ).hexdigest(),
                "ocr_excerpt": normalized_text[:240],
            }
        )
        expected_markers = [
            str(marker).upper()
            for marker in self.agent_args.get(
                "expected_text_markers",
                ["COOK", "GRILL", "DINNER", "RAW ORDER"],
            )
        ]
        if not any(marker in normalized_text for marker in expected_markers):
            record["decision"] = "stop_unrecognized_visible_task"
            record["expected_text_markers"] = expected_markers
            self.done = True
            self._record(record)
            return []

        if self.successful_turn == 0:
            configured_actions = self.agent_args.get("actions")
            if configured_actions is None:
                start = list(self.agent_args.get("drag_start", [546, 400]))
                end = list(self.agent_args.get("drag_end", [990, 510]))
                actions = [
                    {"mouse": {"move": start}},
                    {"mouse": {"buttons": {"left_down": True}}},
                    {"action": "wait", "time": 0.15},
                    {"mouse": {"move": [680, 433]}},
                    {"action": "wait", "time": 0.1},
                    {"mouse": {"move": [835, 472]}},
                    {"action": "wait", "time": 0.1},
                    {"mouse": {"move": end}},
                    {"action": "wait", "time": 0.2},
                    {"mouse": {"buttons": {"left_up": True}}},
                ]
                record.update(
                    {
                        "decision": "drag_top_left_visible_food_to_grill",
                        "drag_start": start,
                        "drag_end": end,
                    }
                )
            else:
                if not isinstance(configured_actions, list) or not configured_actions:
                    raise ValueError("configured probe actions must be a non-empty list")
                actions = configured_actions
                record.update(
                    {
                        "decision": str(
                            self.agent_args.get(
                                "decision_label",
                                "apply_configured_visible_action",
                            )
                        ),
                        "configured_actions": actions,
                    }
                )
            self.successful_turn += 1
            self._record(record)
            return [
                {
                    "tool_id": f"authoritative-probe-{self.successful_turn}",
                    "actions": actions,
                }
            ]

        record["decision"] = "complete_transport_probe"
        self.successful_turn += 1
        self.done = True
        self._record(record)
        return []

    def finish(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
