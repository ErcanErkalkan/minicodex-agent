#!/usr/bin/env python3
"""Validate paired SWE-bench base/gold oracle-smoke evidence for P0-6.

A pilot task is environment/oracle-ready only when:
- the harmless base probe produces a report and remains unresolved, and
- the official gold patch produces a report and resolves the same instance.

Missing reports are treated as infrastructure/oracle failures, never silently
converted into model failures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_reports(root: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("report.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        for instance_id, payload in raw.items():
            if isinstance(instance_id, str) and isinstance(payload, dict):
                reports[instance_id] = {**payload, "_report_path": str(path)}
    return reports


def validate_oracle_smoke(
    manifest: dict[str, Any], base_root: Path, gold_root: Path
) -> dict[str, Any]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("manifest must contain a non-empty tasks list")

    expected = [str(task.get("instance_id", "")).strip() for task in tasks if isinstance(task, dict)]
    if not all(expected) or len(set(expected)) != len(expected):
        raise ValueError("manifest instance_id values must be non-empty and unique")

    base = _read_reports(base_root)
    gold = _read_reports(gold_root)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for instance_id in expected:
        base_report = base.get(instance_id)
        gold_report = gold.get(instance_id)
        base_resolved = base_report.get("resolved") if base_report else None
        gold_resolved = gold_report.get("resolved") if gold_report else None

        status = "PASS"
        reasons: list[str] = []
        if base_report is None:
            status = "FAIL"
            reasons.append("missing base report")
        elif base_resolved is not False:
            status = "FAIL"
            reasons.append(f"base expected unresolved, got {base_resolved!r}")

        if gold_report is None:
            status = "FAIL"
            reasons.append("missing gold report")
        elif gold_resolved is not True:
            status = "FAIL"
            reasons.append(f"gold expected resolved, got {gold_resolved!r}")

        if status == "FAIL":
            failures.append(f"{instance_id}: {'; '.join(reasons)}")

        rows.append(
            {
                "instance_id": instance_id,
                "base_report_present": base_report is not None,
                "base_resolved": base_resolved,
                "gold_report_present": gold_report is not None,
                "gold_resolved": gold_resolved,
                "status": status,
                "reasons": reasons,
            }
        )

    unexpected_base = sorted(set(base) - set(expected))
    unexpected_gold = sorted(set(gold) - set(expected))
    return {
        "schema_version": "0.1",
        "expected_task_count": len(expected),
        "base_report_count": len(base),
        "gold_report_count": len(gold),
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "failure_count": len(failures),
        "overall_status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "unexpected_base_reports": unexpected_base,
        "unexpected_gold_reports": unexpected_gold,
        "tasks": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--base-root", required=True, type=Path)
    parser.add_argument("--gold-root", required=True, type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = validate_oracle_smoke(manifest, args.base_root, args.gold_root)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
