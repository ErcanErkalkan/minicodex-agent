#!/usr/bin/env python3
"""Run a command while sampling host RAM and NVIDIA GPU telemetry.

This pilot-only helper is intentionally stdlib-only. It is designed for the
MiniCodex TÜBİTAK P0-6 calibration runs, where VRAM/RAM/utilization evidence is
needed without changing the agent's core telemetry schema.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _linux_memory_mb() -> dict[str, float] | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if parts:
                values[key] = int(parts[0])
    except (OSError, ValueError):
        return None
    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable")
    if total_kb is None or available_kb is None:
        return None
    total = total_kb / 1024.0
    available = available_kb / 1024.0
    return {"total_mb": total, "available_mb": available, "used_mb": total - available}


def _windows_memory_mb() -> dict[str, float] | None:
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    scale = 1024.0 * 1024.0
    total = status.ullTotalPhys / scale
    available = status.ullAvailPhys / scale
    return {"total_mb": total, "available_mb": available, "used_mb": total - available}


def sample_system_memory_mb() -> dict[str, float] | None:
    if os.name == "nt":
        return _windows_memory_mb()
    if sys.platform.startswith("linux"):
        return _linux_memory_mb()
    return None


def sample_nvidia_gpus() -> tuple[list[dict[str, Any]], str | None]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return [], "nvidia-smi not found"
    command = [
        executable,
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"nvidia-smi failed: {type(exc).__name__}: {exc}"
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "unknown error").strip()
        return [], f"nvidia-smi exit={process.returncode}: {detail[:300]}"

    rows: list[dict[str, Any]] = []
    try:
        for fields in csv.reader(process.stdout.splitlines(), skipinitialspace=True):
            if len(fields) < 5:
                continue
            rows.append(
                {
                    "index": int(fields[0].strip()),
                    "name": fields[1].strip(),
                    "memory_total_mb": float(fields[2].strip()),
                    "memory_used_mb": float(fields[3].strip()),
                    "utilization_gpu_pct": float(fields[4].strip()),
                }
            )
    except (ValueError, csv.Error) as exc:
        return [], f"could not parse nvidia-smi output: {exc}"
    return rows, None


@dataclass
class GpuAggregate:
    index: int
    name: str
    memory_total_mb: float
    baseline_used_mb: float
    peak_used_mb: float
    utilization_peak_pct: float
    utilization_sum_pct: float = 0.0
    samples: int = 0

    def update(self, row: dict[str, Any]) -> None:
        used = float(row.get("memory_used_mb", 0.0))
        utilization = float(row.get("utilization_gpu_pct", 0.0))
        self.peak_used_mb = max(self.peak_used_mb, used)
        self.utilization_peak_pct = max(self.utilization_peak_pct, utilization)
        self.utilization_sum_pct += utilization
        self.samples += 1

    def to_dict(self) -> dict[str, Any]:
        mean_utilization = self.utilization_sum_pct / self.samples if self.samples else 0.0
        return {
            "index": self.index,
            "name": self.name,
            "memory_total_mb": round(self.memory_total_mb, 2),
            "memory_baseline_used_mb": round(self.baseline_used_mb, 2),
            "memory_peak_used_mb": round(self.peak_used_mb, 2),
            "memory_peak_delta_mb": round(max(0.0, self.peak_used_mb - self.baseline_used_mb), 2),
            "utilization_peak_pct": round(self.utilization_peak_pct, 2),
            "utilization_mean_pct": round(mean_utilization, 2),
            "samples": self.samples,
        }


@dataclass
class HardwareRunSampler:
    interval_seconds: float = 1.0
    started_at_utc: str = field(default_factory=utc_now)
    baseline_memory: dict[str, float] | None = None
    peak_system_used_mb: float | None = None
    gpus: dict[int, GpuAggregate] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    samples: int = 0

    def _remember_error(self, value: str | None) -> None:
        if value and value not in self.errors and len(self.errors) < 20:
            self.errors.append(value)

    def sample(self) -> None:
        memory = sample_system_memory_mb()
        if self.baseline_memory is None and memory is not None:
            self.baseline_memory = dict(memory)
        if memory is not None:
            used = float(memory["used_mb"])
            self.peak_system_used_mb = (
                used
                if self.peak_system_used_mb is None
                else max(self.peak_system_used_mb, used)
            )

        gpu_rows, gpu_error = sample_nvidia_gpus()
        self._remember_error(gpu_error)
        for row in gpu_rows:
            index = int(row["index"])
            aggregate = self.gpus.get(index)
            if aggregate is None:
                aggregate = GpuAggregate(
                    index=index,
                    name=str(row["name"]),
                    memory_total_mb=float(row["memory_total_mb"]),
                    baseline_used_mb=float(row["memory_used_mb"]),
                    peak_used_mb=float(row["memory_used_mb"]),
                    utilization_peak_pct=float(row["utilization_gpu_pct"]),
                )
                self.gpus[index] = aggregate
            aggregate.update(row)
        self.samples += 1

    def to_dict(self) -> dict[str, Any]:
        baseline_used = (
            float(self.baseline_memory["used_mb"]) if self.baseline_memory is not None else None
        )
        peak_used = self.peak_system_used_mb
        return {
            "platform": platform.platform(),
            "sampler_interval_ms": int(self.interval_seconds * 1000),
            "sample_count": self.samples,
            "system_ram_total_mb": (
                round(float(self.baseline_memory["total_mb"]), 2)
                if self.baseline_memory is not None
                else None
            ),
            "system_ram_baseline_used_mb": round(baseline_used, 2)
            if baseline_used is not None
            else None,
            "system_ram_peak_used_mb": round(peak_used, 2) if peak_used is not None else None,
            "system_ram_peak_delta_mb": (
                round(max(0.0, peak_used - baseline_used), 2)
                if peak_used is not None and baseline_used is not None
                else None
            ),
            "gpu_present": bool(self.gpus),
            "gpus": [self.gpus[index].to_dict() for index in sorted(self.gpus)],
            "sampler_errors": list(self.errors),
        }


def run_monitored(command: list[str], output: Path, interval_seconds: float) -> int:
    if not command:
        raise ValueError("command is required")
    sampler = HardwareRunSampler(interval_seconds=max(0.2, interval_seconds))
    sampler.sample()
    started = time.monotonic()
    started_utc = utc_now()
    process = subprocess.Popen(command)
    interrupted = False
    try:
        while process.poll() is None:
            time.sleep(sampler.interval_seconds)
            sampler.sample()
    except KeyboardInterrupt:
        interrupted = True
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    finally:
        sampler.sample()

    ended_utc = utc_now()
    duration = time.monotonic() - started
    exit_code = int(process.returncode if process.returncode is not None else 130)
    report = {
        "schema_version": "minicodex-pilot-hardware-v0.1",
        "command": command,
        "started_at_utc": started_utc,
        "ended_at_utc": ended_utc,
        "duration_seconds": round(duration, 4),
        "exit_code": exit_code,
        "interrupted": interrupted,
        "hardware": sampler.to_dict(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="JSON report path")
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=1000,
        help="Sampling interval in milliseconds (minimum 200; default 1000)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command after --")
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_monitored(args.command, args.output, max(200, args.interval_ms) / 1000.0)


if __name__ == "__main__":
    raise SystemExit(main())
