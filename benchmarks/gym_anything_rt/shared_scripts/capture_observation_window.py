#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

try:
    from .time_control import get_status, send_command, wait_for_status, wait_until_ready
except ImportError:
    from time_control import get_status, send_command, wait_for_status, wait_until_ready


def frame_targets(start_ms: float, duration_ms: float, count: int) -> list[float]:
    if count < 1:
        raise ValueError("frame count must be positive")
    if count == 1:
        return [start_ms + duration_ms]
    return [start_ms + duration_ms * index / (count - 1) for index in range(count)]


def select_frames(paths: list[Path], targets_ms: list[float]) -> list[Path]:
    if not paths:
        raise RuntimeError("screen recorder produced no frames")
    timestamps = [(path, path.stat().st_mtime_ns / 1_000_000) for path in paths]
    return [min(timestamps, key=lambda item: abs(item[1] - target))[0] for target in targets_ms]


def start_recorder(raw_dir: Path, *, display: str, width: int, height: int, fps: int) -> subprocess.Popen:
    raw_dir.mkdir(parents=True, exist_ok=True)
    display_input = display if "." in display.rsplit(":", 1)[-1] else f"{display}.0"
    command = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(fps),
        "-video_size", f"{width}x{height}", "-i", display_input,
        "-compression_level", "1",
        str(raw_dir / "raw-%06d.png"),
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def display_size(display: str) -> tuple[int, int]:
    output = subprocess.check_output(
        ["xdpyinfo", "-display", display],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    match = re.search(r"dimensions:\s+(\d+)x(\d+)", output)
    if match is None:
        raise RuntimeError("xdpyinfo did not report display dimensions")
    return int(match.group(1)), int(match.group(2))


def wait_for_recording(raw_dir: Path, process: subprocess.Popen, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(list(raw_dir.glob("raw-*.png"))) >= 2:
            return
        if process.poll() is not None:
            error = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
            raise RuntimeError(f"ffmpeg exited before recording frames: {error}")
        time.sleep(0.02)
    raise TimeoutError("ffmpeg did not produce frames")


def stop_recorder(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def capture(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    raw_dir = output_dir / "raw"
    output_dir.mkdir(parents=True)

    wait_until_ready(port=args.port, timeout=args.timeout)
    scale = float(get_status(port=args.port).get("time_scale", 1.0))
    wall_duration_ms = args.duration_ms if args.hold_paused else args.duration_ms / scale
    width, height = (args.width, args.height) if args.width and args.height else display_size(args.display)
    if args.mode == "live" and args.duration_ms == 0 and args.frames == 1:
        # One live observation needs one frame, not a running window recorder
        # whose shutdown can outlast the capture itself.
        destination = output_dir / "frame-000.png"
        display_input = args.display if "." in args.display.rsplit(":", 1)[-1] else f"{args.display}.0"
        start_ms = time.time_ns() / 1_000_000
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "x11grab",
            "-draw_mouse", "1", "-framerate", "30", "-video_size", f"{width}x{height}",
            "-i", display_input, "-frames:v", "1", "-compression_level", "1", str(destination),
        ], check=True, timeout=args.timeout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        captured_ms = destination.stat().st_mtime_ns / 1_000_000
        end_ms = time.time_ns() / 1_000_000
        manifest = {
            "mode": "live", "resolution": [width, height],
            "observation_window_ms": 0, "frames_per_observation": 1,
            "window_started_wall_ms": start_ms, "window_completed_wall_ms": end_ms,
            "scheduled_window_completed_wall_ms": start_ms,
            "actual_window_wall_ms": max(0, end_ms - start_ms),
            "frames": [{"path": str(destination), "offset_ms": round(captured_ms - start_ms, 3), "target_offset_ms": 0}],
            "time_status": get_status(port=args.port),
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    fps = max(30, math.ceil(args.frames * 1000 / max(1, args.duration_ms)) * 2)
    recorder = start_recorder(
        raw_dir,
        display=args.display,
        width=width,
        height=height,
        fps=fps,
    )
    try:
        wait_for_recording(raw_dir, recorder, timeout=args.timeout)
        if args.mode == "paused":
            if args.hold_paused:
                paused = send_command("pause", port=args.port)
                sequence = int(paused["sequence"])
                status = wait_for_status(
                    lambda item: int(item.get("sequence") or -1) == sequence
                    and item.get("state") == "paused",
                    port=args.port,
                    timeout=args.timeout,
                )
                start_ms = time.time_ns() / 1_000_000
                if args.duration_ms > 0:
                    time.sleep(args.duration_ms / 1000)
                end_ms = time.time_ns() / 1_000_000
                if abs(float(get_status(port=args.port).get("task_time_ms") or 0) - float(status.get("task_time_ms") or 0)) > 5:
                    raise RuntimeError("paused hold advanced the task clock")
            elif args.duration_ms > 0:
                # Identify OUR window by a completion newer than any seen
                # before the command. Equality on the controller's command
                # sequence races: input-delivery receipts share the counter,
                # so any command landing between polls moves the sequence
                # past ours and the wait times out on a window that in fact
                # completed.
                before = get_status(port=args.port)
                prior_done = float(before.get("window_completed_wall_ms") or 0)
                command = send_command(
                    "run_for",
                    port=args.port,
                    milliseconds=args.duration_ms,
                    start_delay_ms=args.start_delay_ms,
                )
                sequence = int(command["sequence"])
                completed = wait_for_status(
                    lambda item: int(item.get("sequence") or -1) >= sequence
                    and item.get("phase") == "completed"
                    and float(item.get("window_completed_wall_ms") or 0) > prior_done,
                    port=args.port,
                    timeout=args.timeout + wall_duration_ms / 1000,
                )
                start_ms = float(completed["window_started_wall_ms"])
                end_ms = float(completed["window_completed_wall_ms"])
            else:
                paused = send_command("pause", port=args.port)
                sequence = int(paused["sequence"])
                status = wait_for_status(
                    lambda item: int(item.get("sequence") or -1) == sequence
                    and item.get("state") == "paused",
                    port=args.port,
                    timeout=args.timeout,
                )
                start_ms = end_ms = float(status["native_date_ms"])
        else:
            start_ms = time.time_ns() / 1_000_000
            if args.duration_ms > 0:
                time.sleep(wall_duration_ms / 1000)
            end_ms = time.time_ns() / 1_000_000
        time.sleep(max(0.08, 2 / fps))
    finally:
        stop_recorder(recorder)

    raw_paths = sorted(raw_dir.glob("raw-*.png"))
    # The configured task-time schedule is binding. Host timer callbacks can
    # arrive late, but frame selection must not silently stretch the window.
    targets = frame_targets(start_ms, wall_duration_ms, args.frames)
    selected = select_frames(raw_paths, targets)
    frames = []
    for index, (source, target) in enumerate(zip(selected, targets, strict=True)):
        destination = output_dir / f"frame-{index:03d}.png"
        shutil.copy2(source, destination)
        actual_ms = source.stat().st_mtime_ns / 1_000_000
        frames.append({
            "path": str(destination),
            "offset_ms": round(actual_ms - start_ms, 3),
            "target_offset_ms": round(target - start_ms, 3),
        })
    shutil.rmtree(raw_dir)
    manifest = {
        "mode": args.mode,
        "resolution": [width, height],
        "observation_window_ms": args.duration_ms,
        "frames_per_observation": args.frames,
        "window_started_wall_ms": start_ms,
        "window_completed_wall_ms": end_ms,
        "scheduled_window_completed_wall_ms": start_ms + wall_duration_ms,
        "actual_window_wall_ms": max(0, end_ms - start_ms),
        "frames": frames,
        "time_status": get_status(port=args.port),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture frames from one Gym-Anything-RT observation window.")
    parser.add_argument("--mode", choices=("live", "paused"), required=True)
    parser.add_argument("--duration-ms", type=int, required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--display", default=os.environ.get("DISPLAY", ":1"))
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--start-delay-ms", type=int, default=150)
    parser.add_argument(
        "--hold-paused",
        action="store_true",
        help="capture scheduled literal frames while the shared paused clock remains frozen",
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.duration_ms < 0:
        parser.error("--duration-ms must be non-negative")
    if args.frames < 1:
        parser.error("--frames must be positive")
    if args.hold_paused and args.mode != "paused":
        parser.error("--hold-paused requires --mode paused")
    return args


def main() -> None:
    print(json.dumps(capture(parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
