"""Project-type detection and suggested commands."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .language_adapters import analyze_language_stack


@dataclass
class ProjectProfile:
    """Detected project metadata used by the agent."""

    project_types: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    lint_commands: list[str] = field(default_factory=list)
    typecheck_commands: list[str] = field(default_factory=list)
    format_commands: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    def summary(self) -> str:
        """Return a compact human-readable summary."""

        data = self.to_dict()
        return json.dumps(data, ensure_ascii=False, indent=2)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _exists(root: Path, name: str) -> bool:
    return (root / name).exists()


def _read_package_json(root: Path) -> dict[str, Any]:
    package_json = root / "package.json"
    if not package_json.exists():
        return {}
    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def detect_project(root: Path) -> ProjectProfile:
    """Detect common project stacks and suggest safe commands."""

    profile = ProjectProfile()
    language_report = analyze_language_stack(root)
    for language in language_report.languages:
        _append_unique(profile.languages, language.name)
    for framework in language_report.frameworks:
        _append_unique(profile.frameworks, framework.name)

    for name in [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "package.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "gradlew",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "README.md",
    ]:
        if _exists(root, name):
            _append_unique(profile.key_files, name)
    for name in language_report.key_files:
        _append_unique(profile.key_files, name)

    # Python
    if any(
        _exists(root, name)
        for name in ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"]
    ):
        _append_unique(profile.project_types, "python")
        if _exists(root, "uv.lock"):
            _append_unique(profile.package_managers, "uv")
        elif _exists(root, "poetry.lock"):
            _append_unique(profile.package_managers, "poetry")
        else:
            _append_unique(profile.package_managers, "pip")
        if (root / "tests").exists() or any(root.glob("test_*.py")):
            _append_unique(profile.test_commands, "pytest -q")
        _append_unique(profile.lint_commands, "ruff check .")

    # Node / frontend
    package_data = _read_package_json(root)
    if package_data:
        _append_unique(profile.project_types, "node")
        if _exists(root, "pnpm-lock.yaml"):
            package_runner = "pnpm"
            _append_unique(profile.package_managers, "pnpm")
        elif _exists(root, "yarn.lock"):
            package_runner = "yarn"
            _append_unique(profile.package_managers, "yarn")
        else:
            package_runner = "npm"
            _append_unique(profile.package_managers, "npm")

        scripts = package_data.get("scripts", {})
        if isinstance(scripts, dict):
            if "test" in scripts:
                _append_unique(profile.test_commands, f"{package_runner} test")
            if "build" in scripts:
                if package_runner in {"npm", "pnpm"}:
                    _append_unique(profile.build_commands, f"{package_runner} run build")
                else:
                    _append_unique(profile.build_commands, "yarn build")
            if "lint" in scripts:
                if package_runner in {"npm", "pnpm"}:
                    _append_unique(profile.lint_commands, f"{package_runner} run lint")
                else:
                    _append_unique(profile.lint_commands, "yarn lint")

    # Java Maven
    if _exists(root, "pom.xml"):
        _append_unique(profile.project_types, "java-maven")
        _append_unique(profile.package_managers, "maven")
        _append_unique(profile.test_commands, "mvn test")

    # Java/Kotlin Gradle
    if any(_exists(root, name) for name in ["build.gradle", "build.gradle.kts", "gradlew"]):
        _append_unique(profile.project_types, "gradle")
        _append_unique(profile.package_managers, "gradle")
        command = "./gradlew test" if _exists(root, "gradlew") else "gradle test"
        _append_unique(profile.test_commands, command)

    # Rust
    if _exists(root, "Cargo.toml"):
        _append_unique(profile.project_types, "rust")
        _append_unique(profile.package_managers, "cargo")
        _append_unique(profile.test_commands, "cargo test")
        _append_unique(profile.build_commands, "cargo build")

    # Go
    if _exists(root, "go.mod"):
        _append_unique(profile.project_types, "go")
        _append_unique(profile.package_managers, "go")
        _append_unique(profile.test_commands, "go test ./...")
        _append_unique(profile.build_commands, "go build ./...")

    # Makefile fallback
    if _exists(root, "Makefile"):
        makefile = root / "Makefile"
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if "test:" in text:
            _append_unique(profile.test_commands, "make test")
        if "build:" in text:
            _append_unique(profile.build_commands, "make build")
        if "lint:" in text:
            _append_unique(profile.lint_commands, "make lint")

    # Language adapters add richer framework/typecheck/format hints without
    # removing the legacy command suggestions that older integrations expect.
    for adapter in language_report.adapters:
        if adapter.language == "typescript/javascript":
            _append_unique(
                profile.project_types, "typescript" if "typescript" in profile.languages else "node"
            )
        elif adapter.language == "java/kotlin":
            _append_unique(profile.project_types, "java")
        else:
            _append_unique(profile.project_types, adapter.language)
        for manager in adapter.package_managers:
            _append_unique(profile.package_managers, manager)
        for suggestion in adapter.commands:
            if suggestion.purpose == "test":
                _append_unique(profile.test_commands, suggestion.command)
            elif suggestion.purpose == "build":
                _append_unique(profile.build_commands, suggestion.command)
            elif suggestion.purpose == "lint":
                _append_unique(profile.lint_commands, suggestion.command)
            elif suggestion.purpose == "typecheck":
                _append_unique(profile.typecheck_commands, suggestion.command)
            elif suggestion.purpose == "format":
                _append_unique(profile.format_commands, suggestion.command)
    for note in language_report.notes:
        _append_unique(profile.notes, note)

    if not profile.project_types:
        profile.notes.append(
            "Proje tipi otomatik algılanamadı; dosya listesi üzerinden ilerlenmeli."
        )

    if not profile.test_commands:
        profile.notes.append(
            "Test komutu otomatik bulunamadı; agent uygun komutu dosyalardan çıkarmalı."
        )

    return profile


def choose_test_command(profile: ProjectProfile, override: str = "auto") -> str | None:
    """Choose the test command to run."""

    if override and override != "auto":
        return override
    if profile.test_commands:
        return profile.test_commands[0]
    return None
