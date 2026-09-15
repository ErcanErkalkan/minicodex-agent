#!/usr/bin/env python3
"""Create SWE-bench no-op predictions for P0-6 base-oracle smoke checks.

SWE-bench skips empty patches, so the base-oracle check uses a harmless patch
that only adds a uniquely named probe file. The source tree under test is not
changed, allowing FAIL_TO_PASS tests to confirm the expected pre-fix failure.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _safe_probe_name(instance_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", instance_id).strip(".-")
    return f".minicodex_p0_6_probe_{value or 'task'}"


def make_noop_patch(instance_id: str) -> str:
    path = _safe_probe_name(instance_id)
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        "+MiniCodex P0-6 base-oracle probe; no source/test behavior change.\n"
    )


def make_predictions(manifest: dict[str, Any]) -> list[dict[str, str]]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("manifest must contain a non-empty tasks list")

    predictions: list[dict[str, str]] = []
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("each task must be an object")
        instance_id = str(task.get("instance_id", "")).strip()
        if not instance_id:
            raise ValueError("each task must define instance_id")
        if instance_id in seen:
            raise ValueError(f"duplicate instance_id: {instance_id}")
        seen.add(instance_id)
        predictions.append(
            {
                "instance_id": instance_id,
                "model_name_or_path": "minicodex-p0-6-base-oracle-probe",
                "model_patch": make_noop_patch(instance_id),
            }
        )
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    predictions = make_predictions(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "prediction_count": len(predictions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
