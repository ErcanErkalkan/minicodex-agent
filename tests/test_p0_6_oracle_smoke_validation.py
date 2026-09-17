from __future__ import annotations

import json
from pathlib import Path

from scripts.p0_6_validate_oracle_smoke import validate_oracle_smoke


def _write_report(root: Path, instance_id: str, resolved: bool) -> None:
    path = root / "model" / instance_id / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({instance_id: {"resolved": resolved}}), encoding="utf-8")


def test_oracle_smoke_passes_only_for_unresolved_base_and_resolved_gold(tmp_path: Path):
    manifest = {"tasks": [{"instance_id": "owner__repo-1"}]}
    base = tmp_path / "base"
    gold = tmp_path / "gold"
    _write_report(base, "owner__repo-1", False)
    _write_report(gold, "owner__repo-1", True)

    result = validate_oracle_smoke(manifest, base, gold)

    assert result["overall_status"] == "PASS"
    assert result["pass_count"] == 1
    assert result["failure_count"] == 0


def test_oracle_smoke_fails_on_missing_or_wrong_resolution(tmp_path: Path):
    manifest = {
        "tasks": [
            {"instance_id": "owner__repo-1"},
            {"instance_id": "owner__repo-2"},
        ]
    }
    base = tmp_path / "base"
    gold = tmp_path / "gold"
    _write_report(base, "owner__repo-1", True)
    _write_report(gold, "owner__repo-1", False)
    _write_report(base, "owner__repo-2", False)

    result = validate_oracle_smoke(manifest, base, gold)

    assert result["overall_status"] == "FAIL"
    assert result["failure_count"] == 2
    assert any("base expected unresolved" in item for item in result["failures"])
    assert any("missing gold report" in item for item in result["failures"])
