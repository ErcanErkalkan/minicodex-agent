from minicodex_agent.snapshot_tools import create_snapshot, list_snapshots, restore_snapshot


def test_snapshot_create_list_restore(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("print('v1')\n", encoding="utf-8")

    created = create_snapshot(tmp_path, label="before", max_files=20)
    snapshot_id = created.split("Snapshot created: ")[1].splitlines()[0]
    assert "Files copied: 1" in created

    source.write_text("print('v2')\n", encoding="utf-8")
    listed = list_snapshots(tmp_path)
    assert snapshot_id in listed

    restored = restore_snapshot(tmp_path, snapshot_id)
    assert "Restored 1 file" in restored
    assert source.read_text(encoding="utf-8") == "print('v1')\n"


def test_snapshot_restore_dry_run(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("one\n", encoding="utf-8")
    created = create_snapshot(tmp_path, label="before", max_files=20)
    snapshot_id = created.split("Snapshot created: ")[1].splitlines()[0]
    source.write_text("two\n", encoding="utf-8")

    restored = restore_snapshot(tmp_path, snapshot_id, dry_run=True)

    assert "DRY-RUN" in restored
    assert source.read_text(encoding="utf-8") == "two\n"
