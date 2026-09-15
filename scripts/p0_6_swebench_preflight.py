#!/usr/bin/env python3
"""P0-6 SWE-bench environment preflight for the MiniCodex pilot.

No network calls are made. The script checks whether the host is plausibly ready
for the official Docker-based SWE-bench harness and validates a pilot manifest.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

MIN_DISK_GB = 120
MIN_RAM_GB = 16
MIN_CPU = 8


def _run(cmd: list[str], timeout: int = 8) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        text = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode == 0, text[:4000]
    except Exception as exc:  # noqa: BLE001 - preflight must report all host failures
        return False, f"{type(exc).__name__}: {exc}"


def _ram_total_bytes() -> int | None:
    if os.name == "nt":
        try:
            import ctypes

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
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError):
            return None

    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
        raise ValueError("manifest must be an object containing a tasks list")
    return raw


def _validate_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    required = {
        "instance_id",
        "repo",
        "base_commit",
        "environment_setup_commit",
        "difficulty",
        "fail_to_pass",
    }
    problems: list[str] = []
    ids: list[str] = []
    repos: set[str] = set()

    for index, task in enumerate(raw.get("tasks", []), 1):
        if not isinstance(task, dict):
            problems.append(f"task[{index}] is not an object")
            continue

        missing = sorted(key for key in required if not task.get(key))
        if missing:
            problems.append(f"{task.get('instance_id', index)} missing: {', '.join(missing)}")

        instance_id = str(task.get("instance_id", ""))
        if instance_id in ids:
            problems.append(f"duplicate instance_id: {instance_id}")
        ids.append(instance_id)
        repos.add(str(task.get("repo", "")))

        fail_to_pass = task.get("fail_to_pass")
        if not isinstance(fail_to_pass, list) or not fail_to_pass:
            problems.append(f"{instance_id}: fail_to_pass must be a non-empty list")

    return {
        "ok": not problems,
        "task_count": len(ids),
        "repo_count": len(repos),
        "problems": problems,
    }


def collect(manifest: Path, probe_docker_server: bool = True) -> dict[str, Any]:
    disk = shutil.disk_usage(manifest.resolve().anchor or ".")
    ram = _ram_total_bytes()
    cpu = os.cpu_count() or 0
    arch = platform.machine().lower()
    docker_path = shutil.which("docker")
    git_path = shutil.which("git")
    nvidia_path = shutil.which("nvidia-smi")
    swebench_installed = importlib.util.find_spec("swebench") is not None

    docker_client_ok = False
    docker_client = ""
    docker_server_ok = False
    docker_server = ""
    if docker_path:
        docker_client_ok, docker_client = _run([docker_path, "--version"])
        if probe_docker_server:
            docker_server_ok, docker_server = _run(
                [docker_path, "info", "--format", "{{json .ServerVersion}}"]
            )

    manifest_check = _validate_manifest(_load_manifest(manifest))
    checks = {
        "architecture_x86_64_recommended": arch in {"x86_64", "amd64"},
        "disk_free_ge_120_gb": disk.free >= MIN_DISK_GB * 1024**3,
        "ram_total_ge_16_gb": ram is not None and ram >= MIN_RAM_GB * 1024**3,
        "cpu_count_ge_8": cpu >= MIN_CPU,
        "git_available": bool(git_path),
        "docker_client_available": bool(docker_path) and docker_client_ok,
        "docker_server_reachable": bool(docker_path)
        and (docker_server_ok if probe_docker_server else True),
        "swebench_python_package_installed": swebench_installed,
        "manifest_valid": manifest_check["ok"],
    }
    blocking = [
        key
        for key, value in checks.items()
        if not value and key != "architecture_x86_64_recommended"
    ]

    return {
        "schema_version": "0.1",
        "host": {
            "platform": platform.platform(),
            "architecture": arch,
            "cpu_count": cpu,
        },
        "resources": {
            "disk_free_gb": round(disk.free / 1024**3, 2),
            "disk_total_gb": round(disk.total / 1024**3, 2),
            "ram_total_gb": round(ram / 1024**3, 2) if ram else None,
        },
        "tools": {
            "git": git_path,
            "docker": docker_path,
            "docker_client": docker_client,
            "docker_server": docker_server,
            "nvidia_smi": nvidia_path,
            "swebench_installed": swebench_installed,
        },
        "manifest": manifest_check,
        "checks": checks,
        "blocking_checks": blocking,
        "ready_for_local_swebench_smoke": not blocking,
        "notes": [
            "Official SWE-bench uses Docker for reproducible evaluation.",
            "Recommended local resources: x86_64, >=120 GB free storage, >=16 GB RAM, >=8 CPU cores.",
            "Use a unique run_id whenever the prediction patch changes because SWE-bench caches by run_id + instance_id.",
            "GPU is not required by SWE-bench itself, but MiniCodex local-model pilot arms may require it and should use the P0-6 hardware telemetry wrapper.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--no-docker-server-probe", action="store_true")
    args = parser.parse_args()

    result = collect(
        args.manifest,
        probe_docker_server=not args.no_docker_server_probe,
    )
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ready_for_local_swebench_smoke"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
