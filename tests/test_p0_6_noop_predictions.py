from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.p0_6_make_noop_predictions import make_noop_patch, make_predictions


def test_make_predictions_is_unique_and_nonempty():
    manifest = {
        "tasks": [
            {"instance_id": "owner__repo-1"},
            {"instance_id": "owner__repo-2"},
        ]
    }
    predictions = make_predictions(manifest)
    assert [item["instance_id"] for item in predictions] == [
        "owner__repo-1",
        "owner__repo-2",
    ]
    assert all(item["model_patch"].strip() for item in predictions)
    assert predictions[0]["model_name_or_path"] == "minicodex-p0-6-base-oracle-probe"


def test_noop_patch_applies_without_touching_source(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    patch = tmp_path / "probe.patch"
    patch.write_text(make_noop_patch("owner__repo-1"), encoding="utf-8")
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp_path, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True)
    assert (tmp_path / ".minicodex_p0_6_probe_owner__repo-1").is_file()
