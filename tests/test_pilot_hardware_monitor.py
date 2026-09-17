from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_with_hardware_telemetry.py"
SPEC = importlib.util.spec_from_file_location("pilot_hw", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def test_system_memory_sampler_is_non_negative_when_available():
    data = MOD.sample_system_memory_mb()
    if data is None:
        return
    assert data["total_mb"] > 0
    assert data["used_mb"] >= 0
    assert data["available_mb"] >= 0


def test_hardware_run_wrapper_writes_json(tmp_path: Path):
    output = tmp_path / "hardware.json"
    code = MOD.run_monitored(
        [sys.executable, "-c", "import time; x=bytearray(1024*1024); time.sleep(0.25)"],
        output,
        0.2,
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "minicodex-pilot-hardware-v0.1"
    assert payload["exit_code"] == 0
    assert payload["hardware"]["sample_count"] >= 2
    assert "gpu_present" in payload["hardware"]
    assert "system_ram_peak_used_mb" in payload["hardware"]
