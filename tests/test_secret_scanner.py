from __future__ import annotations

from minicodex_agent.secret_scanner import redact_secret, scan_secrets


def test_scan_secrets_detects_and_redacts_openai_key(tmp_path):
    key = "sk-" + "A" * 32
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={key}\n", encoding="utf-8")

    report = scan_secrets(tmp_path)

    assert "openai_api_key" in report
    assert "REDACTED" in report
    assert key not in report


def test_scan_secrets_reports_clean_workspace(tmp_path):
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")

    report = scan_secrets(tmp_path)

    assert "No likely secrets found" in report


def test_redact_secret_masks_sensitive_assignment():
    text = "password = supersecretpassword"

    assert "REDACTED" in redact_secret(text)


def test_scan_secrets_ignores_placeholders_and_normal_code_contexts(tmp_path):
    (tmp_path / ".env.example").write_text(
        "OPENAI_API_KEY=your_api_key_here\nGITHUB_TOKEN=<your-token>\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mini-codex-agent"\n[tool.ruff]\nline-length = 100\n',
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "payload = {\n"
        '    "project_profile": state.project_profile.to_dict(),\n'
        "}\n"
        "from minicodex_agent.project_inspector import detect_project\n",
        encoding="utf-8",
    )

    report = scan_secrets(tmp_path)

    assert "No likely secrets found" in report
    assert "high_entropy_token" not in report


def test_high_entropy_detection_requires_assignment_context(tmp_path):
    token = "Aa1_" * 10
    (tmp_path / "app.py").write_text(
        f"print('{token}')\nnot_a_secret = 'normal value'\n",
        encoding="utf-8",
    )

    report = scan_secrets(tmp_path)

    assert "high_entropy_token" not in report


def test_high_entropy_assignment_has_severity(tmp_path):
    token = "Ab3dEf4G_hIj5Kl6Mn7Op8Qr9St0UvWxYz"
    (tmp_path / "app.py").write_text(f"SESSION_TOKEN = '{token}'\n", encoding="utf-8")

    report = scan_secrets(tmp_path)

    assert "high | high_entropy_token" in report or "high | sensitive_assignment" in report
    assert "Severity counts:" in report
    assert token not in report


def test_minimum_severity_suppresses_medium_assignments(tmp_path):
    (tmp_path / "settings.py").write_text("password = 'supersecretpassword'\n", encoding="utf-8")

    low_report = scan_secrets(tmp_path, minimum_severity="low")
    high_report = scan_secrets(tmp_path, minimum_severity="high")

    assert "medium | sensitive_assignment" in low_report
    assert "No likely secrets found" in high_report
