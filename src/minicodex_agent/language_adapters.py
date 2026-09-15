"""Language and framework intelligence for MiniCodex.

This module gives the agent a deterministic, cheap map of the repository's
languages, frameworks, package managers, and likely verification commands.  It
is intentionally dependency-free and conservative: it reads only visible,
workspace-safe text files and treats its output as hints for the model, not as
proof that a command will pass.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .fs_tools import is_probably_binary
from .safety import safe_resolve, sensitive_path_reason, should_skip_path
from .utils import to_pretty_json, truncate

LANGUAGE_EXTENSIONS: Mapping[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "java": (".java", ".kt", ".kts"),
    "go": (".go",),
    "rust": (".rs",),
    "c-cpp": (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"),
    "csharp": (".cs",),
    "php": (".php",),
    "ruby": (".rb",),
    "swift": (".swift",),
    "shell": (".sh", ".bash", ".zsh"),
}

KEY_CONFIG_FILES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
    "tox.ini",
    "pytest.ini",
    "mypy.ini",
    "ruff.toml",
    ".ruff.toml",
    "package.json",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.mjs",
    "eslint.config.js",
    ".eslintrc.json",
    "jest.config.js",
    "vitest.config.ts",
    "pnpm-workspace.yaml",
    "turbo.json",
    "nx.json",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradlew",
    "go.mod",
    "Cargo.toml",
    "Cargo.lock",
    "Makefile",
    "Dockerfile",
}

FRAMEWORK_PATTERNS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "fastapi": ("python", ("fastapi", "from fastapi", "FastAPI(")),
    "django": ("python", ("django", "manage.py", "DJANGO_SETTINGS_MODULE")),
    "flask": ("python", ("flask", "from flask", "Flask(")),
    "pytest": ("python", ("pytest", "pytest.ini", "tests/")),
    "nextjs": ("typescript", ("next", "next.config", "app/", "pages/")),
    "react": ("typescript", ("react", "jsx", "tsx")),
    "vite": ("typescript", ("vite", "vite.config")),
    "vue": ("typescript", ("vue", ".vue")),
    "angular": ("typescript", ("@angular", "angular.json")),
    "nestjs": ("typescript", ("@nestjs", "NestFactory")),
    "express": ("javascript", ("express", "app.listen", "Router(")),
    "spring-boot": ("java", ("spring-boot", "SpringApplication", "@SpringBootApplication")),
    "junit": ("java", ("junit", "@Test", "org.junit")),
    "gin": ("go", ("github.com/gin-gonic/gin", "gin.Default")),
    "fiber": ("go", ("github.com/gofiber/fiber", "fiber.New")),
    "go-echo": ("go", ("github.com/labstack/echo", "echo.New")),
    "axum": ("rust", ("axum", "Router::new")),
    "actix-web": ("rust", ("actix-web", "HttpServer")),
    "rocket": ("rust", ("rocket", "#[launch]")),
    "tauri": ("rust", ("tauri", "tauri::Builder")),
}


@dataclass(frozen=True)
class LanguageStat:
    """Repository-level statistics for one language family."""

    name: str
    file_count: int = 0
    bytes: int = 0
    sample_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrameworkDetection:
    """A detected framework or important toolchain signal."""

    name: str
    language: str
    confidence: float
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandSuggestion:
    """A command the agent can run for a specific verification purpose."""

    command: str
    purpose: str  # test | lint | typecheck | build | format | dev
    language: str = ""
    framework: str = ""
    reason: str = ""
    scope: str = "project"


@dataclass(frozen=True)
class LanguageAdapterReport:
    """Per-language adapter output."""

    language: str
    detected: bool
    package_managers: tuple[str, ...] = ()
    frameworks: tuple[FrameworkDetection, ...] = ()
    commands: tuple[CommandSuggestion, ...] = ()
    key_files: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass(frozen=True)
class LanguageStackReport:
    """Full repository language/framework profile."""

    languages: tuple[LanguageStat, ...]
    adapters: tuple[LanguageAdapterReport, ...]
    frameworks: tuple[FrameworkDetection, ...]
    commands: tuple[CommandSuggestion, ...]
    package_managers: tuple[str, ...]
    key_files: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    def summary(self) -> str:
        """Return a compact JSON summary for tools and project inspection."""

        return to_pretty_json(self.to_dict())


@dataclass(frozen=True)
class _RepoFacts:
    root: Path
    files: tuple[Path, ...]
    relative_files: tuple[str, ...]
    key_files: tuple[str, ...]
    package_json: dict[str, Any]
    pyproject_text: str
    requirements_text: str
    pom_text: str
    gradle_text: str
    go_mod_text: str
    cargo_text: str
    sample_text: str


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./") or "."


def _safe_read(root: Path, rel: str, max_chars: int = 120_000) -> str:
    try:
        path = safe_resolve(root, rel)
    except ValueError:
        return ""
    if not path.exists() or not path.is_file():
        return ""
    if (
        should_skip_path(path, root)
        or sensitive_path_reason(path, root)
        or is_probably_binary(path)
    ):
        return ""
    try:
        return truncate(path.read_text(encoding="utf-8", errors="replace"), max_chars)
    except OSError:
        return ""


def _read_json(root: Path, rel: str) -> dict[str, Any]:
    text = _safe_read(root, rel, max_chars=200_000)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _iter_visible_files(
    root: Path, *, max_files: int = 1200, max_file_bytes: int = 500_000
) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        if (
            should_skip_path(path, root)
            or sensitive_path_reason(path, root)
            or is_probably_binary(path)
        ):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        files.append(path)
    return tuple(files)


def _collect_facts(root: Path, *, max_files: int = 1200) -> _RepoFacts:
    files = _iter_visible_files(root, max_files=max_files)
    rels: list[str] = []
    key_files: list[str] = []
    sample_parts: list[str] = []
    for path in files:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        rels.append(rel)
        if path.name in KEY_CONFIG_FILES or rel in KEY_CONFIG_FILES:
            key_files.append(rel)
        if len("\n".join(sample_parts)) < 160_000 and path.suffix.lower() in {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".kt",
            ".go",
            ".rs",
            ".toml",
            ".json",
            ".xml",
            ".gradle",
            ".kts",
        }:
            try:
                sample_parts.append(
                    f"\n--- {rel} ---\n" + path.read_text(encoding="utf-8", errors="replace")[:3000]
                )
            except OSError:
                pass
    return _RepoFacts(
        root=root,
        files=files,
        relative_files=tuple(rels),
        key_files=tuple(dict.fromkeys(key_files)),
        package_json=_read_json(root, "package.json"),
        pyproject_text=_safe_read(root, "pyproject.toml"),
        requirements_text="\n".join(
            text
            for text in [
                _safe_read(root, "requirements.txt"),
                _safe_read(root, "requirements-dev.txt"),
            ]
            if text
        ),
        pom_text=_safe_read(root, "pom.xml"),
        gradle_text="\n".join(
            text
            for text in [
                _safe_read(root, "build.gradle"),
                _safe_read(root, "build.gradle.kts"),
                _safe_read(root, "settings.gradle"),
                _safe_read(root, "settings.gradle.kts"),
            ]
            if text
        ),
        go_mod_text=_safe_read(root, "go.mod"),
        cargo_text=_safe_read(root, "Cargo.toml"),
        sample_text=truncate("\n".join(sample_parts), 220_000),
    )


def _language_stats(facts: _RepoFacts) -> tuple[LanguageStat, ...]:
    stats: dict[str, dict[str, Any]] = {}
    ext_to_lang = {ext: lang for lang, exts in LANGUAGE_EXTENSIONS.items() for ext in exts}
    for path in facts.files:
        lang = ext_to_lang.get(path.suffix.lower())
        if not lang:
            continue
        try:
            rel = path.relative_to(facts.root).as_posix()
            size = path.stat().st_size
        except OSError:
            continue
        item = stats.setdefault(lang, {"count": 0, "bytes": 0, "samples": []})
        item["count"] += 1
        item["bytes"] += size
        if len(item["samples"]) < 8:
            item["samples"].append(rel)
    result = [
        LanguageStat(
            name=lang,
            file_count=data["count"],
            bytes=data["bytes"],
            sample_files=tuple(data["samples"]),
        )
        for lang, data in stats.items()
    ]
    result.sort(key=lambda item: (-item.file_count, item.name))
    return tuple(result)


def _package_runner(facts: _RepoFacts) -> str:
    if "pnpm-lock.yaml" in facts.relative_files or "pnpm-workspace.yaml" in facts.relative_files:
        return "pnpm"
    if "yarn.lock" in facts.relative_files:
        return "yarn"
    if "bun.lockb" in facts.relative_files or "bun.lock" in facts.relative_files:
        return "bun"
    return "npm"


def _script_command(runner: str, script: str) -> str:
    if runner == "yarn":
        return f"yarn {script}"
    if runner == "bun":
        return f"bun run {script}"
    if runner in {"npm", "pnpm"}:
        if script == "test" and runner == "npm":
            return "npm test"
        return f"{runner} run {script}"
    return f"{runner} run {script}"


def _dependency_blob_for_language(lang: str, facts: _RepoFacts) -> str:
    if lang == "python":
        return "\n".join([facts.pyproject_text, facts.requirements_text])
    if lang in {"typescript", "javascript"}:
        return json.dumps(facts.package_json)
    if lang == "java":
        return "\n".join([facts.pom_text, facts.gradle_text])
    if lang == "go":
        return facts.go_mod_text
    if lang == "rust":
        return facts.cargo_text
    return ""


def _has_dependency(blob: str, package: str) -> bool:
    """Return True when package appears as a dependency-like token.

    This intentionally avoids scanning arbitrary source text.  Framework names in
    detector tables, route-regex catalogs, docs, or tests must not become
    repository-level framework detections.
    """

    package_re = re.escape(package.lower())
    return bool(re.search(rf"(?<![a-z0-9_.-]){package_re}(?![a-z0-9_.-])", blob.lower()))


def _is_testish_path(rel: str) -> bool:
    parts = set(Path(rel).parts)
    name = Path(rel).name
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _source_python_files(facts: _RepoFacts, *, include_tests: bool = False) -> Iterable[Path]:
    for path in facts.files:
        if path.suffix.lower() not in {".py", ".pyi"}:
            continue
        try:
            rel = path.relative_to(facts.root).as_posix()
        except ValueError:
            continue
        if not include_tests and _is_testish_path(rel):
            continue
        yield path


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _python_ast_framework_evidence(name: str, facts: _RepoFacts) -> tuple[str, ...]:
    evidence: list[str] = []
    for path in _source_python_files(facts):
        try:
            rel = path.relative_to(facts.root).as_posix()
            tree = ast.parse(
                path.read_text(encoding="utf-8", errors="replace")[:250_000], filename=rel
            )
        except (OSError, SyntaxError, ValueError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".")[0] for alias in node.names}
                if name == "fastapi" and "fastapi" in imported:
                    evidence.append(f"import fastapi in {rel}")
                elif name == "flask" and "flask" in imported:
                    evidence.append(f"import flask in {rel}")
                elif name == "django" and "django" in imported:
                    evidence.append(f"import django in {rel}")
                elif name == "pytest" and "pytest" in imported:
                    evidence.append(f"import pytest in {rel}")
            elif isinstance(node, ast.ImportFrom):
                module_root = (node.module or "").split(".")[0]
                if name == "fastapi" and module_root == "fastapi":
                    evidence.append(f"from fastapi import ... in {rel}")
                elif name == "flask" and module_root == "flask":
                    evidence.append(f"from flask import ... in {rel}")
                elif name == "django" and module_root == "django":
                    evidence.append(f"from django import ... in {rel}")
                elif name == "pytest" and module_root == "pytest":
                    evidence.append(f"from pytest import ... in {rel}")
            elif isinstance(node, ast.Call):
                call = _call_name(node.func)
                if name == "fastapi" and call.endswith("FastAPI"):
                    evidence.append(f"FastAPI() call in {rel}")
                elif name == "flask" and call.endswith("Flask"):
                    evidence.append(f"Flask() call in {rel}")

        if len(evidence) >= 8:
            break
    return tuple(dict.fromkeys(evidence))


def _python_framework_evidence(name: str, facts: _RepoFacts) -> tuple[str, ...]:
    rels = set(facts.relative_files)
    dependency_blob = _dependency_blob_for_language("python", facts)
    evidence: list[str] = []

    if name in {"fastapi", "django", "flask", "pytest"} and _has_dependency(dependency_blob, name):
        evidence.append(f"{name} dependency/config entry")

    if name == "django":
        if "manage.py" in rels:
            evidence.append("manage.py")
        if any(Path(rel).name == "settings.py" for rel in rels):
            evidence.append("settings.py")
    elif name == "pytest":
        if any(rel == "pytest.ini" or rel.endswith("/pytest.ini") for rel in rels):
            evidence.append("pytest.ini")
        if any(rel.startswith("tests/") for rel in rels):
            evidence.append("tests/ layout")

    evidence.extend(_python_ast_framework_evidence(name, facts))
    return tuple(list(dict.fromkeys(evidence))[:8])


def _framework_evidence(name: str, facts: _RepoFacts) -> tuple[str, ...]:
    lang, patterns = FRAMEWORK_PATTERNS[name]
    if lang == "python":
        return _python_framework_evidence(name, facts)

    # Non-Python framework detection uses file layout and package/build
    # metadata only.  It deliberately avoids arbitrary source-code sampling so
    # string literals in analyzers, route catalogs, docs, or tests do not create
    # repository-level framework false positives.
    combined = "\n".join(
        ["\n".join(facts.relative_files), _dependency_blob_for_language(lang, facts)]
    ).lower()
    evidence: list[str] = []
    for pattern in patterns:
        if pattern.lower() in combined:
            evidence.append(pattern)
    return tuple(list(dict.fromkeys(evidence))[:8])


def _detect_frameworks(
    facts: _RepoFacts, language_filter: str | None = None
) -> tuple[FrameworkDetection, ...]:
    detections: list[FrameworkDetection] = []
    for name, (language, _patterns) in FRAMEWORK_PATTERNS.items():
        if language_filter and language != language_filter:
            continue
        evidence = _framework_evidence(name, facts)
        if not evidence:
            continue
        confidence = min(0.95, 0.45 + 0.17 * len(evidence))
        detections.append(
            FrameworkDetection(
                name=name, language=language, confidence=round(confidence, 2), evidence=evidence
            )
        )
    detections.sort(key=lambda item: (-item.confidence, item.language, item.name))
    return tuple(detections)


def _python_typecheck_suggestion(facts: _RepoFacts) -> CommandSuggestion:
    """Return the canonical mypy command for the detected Python layout.

    Prefer the same package-scoped command used by CI for src-layout projects.
    A broad ``mypy .`` fallback is intentionally reserved for flat projects
    where no safer package or src directory can be inferred.
    """

    package_dirs: set[str] = set()
    has_src_python = False
    for rel in facts.relative_files:
        if not rel.startswith("src/") or not rel.endswith((".py", ".pyi")):
            continue
        has_src_python = True
        parts = rel.split("/")
        if len(parts) >= 3 and parts[2] == "__init__.py" and parts[1].isidentifier():
            package_dirs.add(f"src/{parts[1]}")

    if len(package_dirs) == 1:
        package_dir = sorted(package_dirs)[0]
        return CommandSuggestion(
            f"mypy {package_dir}",
            "typecheck",
            "python",
            "mypy",
            "Mypy config/dependency detected; src-layout package scope matches CI/readme policy.",
        )
    if len(package_dirs) > 1:
        return CommandSuggestion(
            "mypy src",
            "typecheck",
            "python",
            "mypy",
            "Mypy config/dependency detected; multiple src-layout packages found.",
        )
    if has_src_python:
        return CommandSuggestion(
            "mypy src",
            "typecheck",
            "python",
            "mypy",
            "Mypy config/dependency detected; src-layout Python files found.",
        )
    return CommandSuggestion(
        "mypy .",
        "typecheck",
        "python",
        "mypy",
        "Mypy config/dependency detected; no src-layout package scope was inferred.",
    )


def _python_adapter(facts: _RepoFacts, stats: Mapping[str, LanguageStat]) -> LanguageAdapterReport:
    key_files = [
        rel
        for rel in facts.key_files
        if rel
        in {
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "requirements.txt",
            "requirements-dev.txt",
            "tox.ini",
            "pytest.ini",
            "mypy.ini",
            "ruff.toml",
            ".ruff.toml",
        }
    ]
    detected = bool(key_files or stats.get("python"))
    if not detected:
        return LanguageAdapterReport(language="python", detected=False)

    package_managers: list[str] = []
    if "uv.lock" in facts.relative_files:
        _append_unique(package_managers, "uv")
    if "poetry.lock" in facts.relative_files or "[tool.poetry]" in facts.pyproject_text:
        _append_unique(package_managers, "poetry")
    if "Pipfile" in facts.relative_files:
        _append_unique(package_managers, "pipenv")
    _append_unique(package_managers, "pip")

    commands: list[CommandSuggestion] = []
    has_pytest = (
        any(rel.startswith("tests/") for rel in facts.relative_files)
        or "pytest" in (facts.pyproject_text + facts.requirements_text).lower()
    )
    if has_pytest:
        commands.append(
            CommandSuggestion(
                "pytest -q", "test", "python", "pytest", "Detected pytest/tests layout."
            )
        )
    else:
        commands.append(
            CommandSuggestion(
                "python -m unittest discover",
                "test",
                "python",
                reason="Python project without explicit pytest signal.",
            )
        )
    if (
        "ruff" in (facts.pyproject_text + facts.requirements_text).lower()
        or "ruff.toml" in facts.key_files
        or ".ruff.toml" in facts.key_files
    ):
        commands.append(
            CommandSuggestion(
                "ruff check .", "lint", "python", "ruff", "Ruff config/dependency detected."
            )
        )
    else:
        commands.append(
            CommandSuggestion(
                "ruff check .",
                "lint",
                "python",
                "ruff",
                "Common fast Python lint command; verify ruff is installed.",
            )
        )
    if (
        "mypy" in (facts.pyproject_text + facts.requirements_text).lower()
        or "mypy.ini" in facts.key_files
    ):
        commands.append(_python_typecheck_suggestion(facts))
    if "pyright" in (facts.pyproject_text + facts.requirements_text).lower():
        commands.append(
            CommandSuggestion(
                "pyright", "typecheck", "python", "pyright", "Pyright dependency/config detected."
            )
        )
    if "pyproject.toml" in facts.relative_files:
        commands.append(
            CommandSuggestion(
                "python -m build", "build", "python", reason="pyproject.toml present."
            )
        )

    notes = []
    if "src/" in "\n".join(facts.relative_files):
        notes.append(
            "src-layout detected; imports may require editable install or configured PYTHONPATH."
        )
    return LanguageAdapterReport(
        language="python",
        detected=True,
        package_managers=tuple(package_managers),
        frameworks=_detect_frameworks(facts, "python"),
        commands=tuple(commands),
        key_files=tuple(key_files),
        notes=tuple(notes),
    )


def _node_adapter(facts: _RepoFacts, stats: Mapping[str, LanguageStat]) -> LanguageAdapterReport:
    detected = bool(
        facts.package_json
        or stats.get("javascript")
        or stats.get("typescript")
        or "tsconfig.json" in facts.relative_files
    )
    if not detected:
        return LanguageAdapterReport(language="typescript/javascript", detected=False)
    runner = _package_runner(facts)
    package_managers = [runner]
    scripts = (
        facts.package_json.get("scripts", {})
        if isinstance(facts.package_json.get("scripts", {}), dict)
        else {}
    )
    commands: list[CommandSuggestion] = []
    for script, purpose in [
        ("test", "test"),
        ("lint", "lint"),
        ("typecheck", "typecheck"),
        ("check", "typecheck"),
        ("build", "build"),
        ("format", "format"),
        ("dev", "dev"),
    ]:
        if script in scripts:
            commands.append(
                CommandSuggestion(
                    _script_command(runner, script),
                    purpose,
                    "typescript/javascript",
                    reason=f"package.json script '{script}' detected.",
                )
            )
    if "tsconfig.json" in facts.relative_files and not any(
        cmd.purpose == "typecheck" for cmd in commands
    ):
        commands.append(
            CommandSuggestion(
                "npx tsc --noEmit",
                "typecheck",
                "typescript",
                "typescript",
                "tsconfig.json present.",
            )
        )
    if "vitest" in json.dumps(facts.package_json).lower() and not any(
        "vitest" in cmd.command for cmd in commands
    ):
        commands.append(
            CommandSuggestion(
                f"{runner} exec vitest run" if runner != "npm" else "npx vitest run",
                "test",
                "typescript/javascript",
                "vitest",
                "Vitest dependency detected.",
            )
        )

    key_file_names = {
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "vite.config.ts",
        "vite.config.js",
        "next.config.js",
        "next.config.mjs",
        "eslint.config.js",
        ".eslintrc.json",
        "jest.config.js",
        "vitest.config.ts",
        "pnpm-workspace.yaml",
        "turbo.json",
        "nx.json",
    }
    notes: list[str] = []
    if (
        "pnpm-workspace.yaml" in facts.relative_files
        or "turbo.json" in facts.relative_files
        or "nx.json" in facts.relative_files
    ):
        notes.append(
            "monorepo/workspace signals detected; prefer package-scoped commands before full workspace commands."
        )
    return LanguageAdapterReport(
        language="typescript/javascript",
        detected=True,
        package_managers=tuple(package_managers),
        frameworks=_detect_frameworks(facts, "typescript")
        + _detect_frameworks(facts, "javascript"),
        commands=tuple(commands),
        key_files=tuple(
            rel
            for rel in facts.key_files
            if Path(rel).name in key_file_names or rel in key_file_names
        ),
        notes=tuple(notes),
    )


def _java_adapter(facts: _RepoFacts, stats: Mapping[str, LanguageStat]) -> LanguageAdapterReport:
    detected = bool(
        stats.get("java")
        or "pom.xml" in facts.relative_files
        or any(rel.endswith(("build.gradle", "build.gradle.kts")) for rel in facts.relative_files)
    )
    if not detected:
        return LanguageAdapterReport(language="java/kotlin", detected=False)
    package_managers: list[str] = []
    commands: list[CommandSuggestion] = []
    if "pom.xml" in facts.relative_files:
        package_managers.append("maven")
        commands.extend(
            [
                CommandSuggestion("mvn test", "test", "java", "maven", "pom.xml present."),
                CommandSuggestion(
                    "mvn -q -DskipTests package",
                    "build",
                    "java",
                    "maven",
                    "Maven packaging command.",
                ),
            ]
        )
    if any(
        rel.endswith(("build.gradle", "build.gradle.kts", "gradlew"))
        for rel in facts.relative_files
    ):
        package_managers.append("gradle")
        runner = "./gradlew" if "gradlew" in facts.relative_files else "gradle"
        commands.extend(
            [
                CommandSuggestion(
                    f"{runner} test", "test", "java", "gradle", "Gradle build present."
                ),
                CommandSuggestion(
                    f"{runner} build", "build", "java", "gradle", "Gradle build present."
                ),
            ]
        )
    return LanguageAdapterReport(
        language="java/kotlin",
        detected=True,
        package_managers=tuple(dict.fromkeys(package_managers)),
        frameworks=_detect_frameworks(facts, "java"),
        commands=tuple(commands),
        key_files=tuple(
            rel
            for rel in facts.key_files
            if rel
            in {
                "pom.xml",
                "build.gradle",
                "build.gradle.kts",
                "settings.gradle",
                "settings.gradle.kts",
                "gradlew",
            }
        ),
    )


def _go_adapter(facts: _RepoFacts, stats: Mapping[str, LanguageStat]) -> LanguageAdapterReport:
    detected = bool(stats.get("go") or "go.mod" in facts.relative_files)
    if not detected:
        return LanguageAdapterReport(language="go", detected=False)
    commands = (
        CommandSuggestion("go test ./...", "test", "go", reason="go.mod or .go files present."),
        CommandSuggestion("go build ./...", "build", "go", reason="go.mod or .go files present."),
        CommandSuggestion("go vet ./...", "lint", "go", "go vet", "Standard Go static check."),
        CommandSuggestion(
            "gofmt -w .", "format", "go", "gofmt", "Standard Go formatter; modifies files."
        ),
    )
    return LanguageAdapterReport(
        language="go",
        detected=True,
        package_managers=("go",),
        frameworks=_detect_frameworks(facts, "go"),
        commands=commands,
        key_files=tuple(rel for rel in facts.key_files if rel == "go.mod"),
    )


def _rust_adapter(facts: _RepoFacts, stats: Mapping[str, LanguageStat]) -> LanguageAdapterReport:
    detected = bool(stats.get("rust") or "Cargo.toml" in facts.relative_files)
    if not detected:
        return LanguageAdapterReport(language="rust", detected=False)
    commands = (
        CommandSuggestion("cargo test", "test", "rust", reason="Cargo.toml or .rs files present."),
        CommandSuggestion(
            "cargo build", "build", "rust", reason="Cargo.toml or .rs files present."
        ),
        CommandSuggestion(
            "cargo clippy -- -D warnings", "lint", "rust", "clippy", "Common Rust lint command."
        ),
        CommandSuggestion(
            "cargo fmt --check", "format", "rust", "rustfmt", "Rust formatting verification."
        ),
    )
    return LanguageAdapterReport(
        language="rust",
        detected=True,
        package_managers=("cargo",),
        frameworks=_detect_frameworks(facts, "rust"),
        commands=commands,
        key_files=tuple(rel for rel in facts.key_files if rel in {"Cargo.toml", "Cargo.lock"}),
    )


def analyze_language_stack(root: Path, *, max_files: int = 1200) -> LanguageStackReport:
    """Analyze languages, frameworks, package managers, and verification commands."""

    facts = _collect_facts(root, max_files=max_files)
    stats_tuple = _language_stats(facts)
    stats = {item.name: item for item in stats_tuple}
    adapters = tuple(
        adapter
        for adapter in (
            _python_adapter(facts, stats),
            _node_adapter(facts, stats),
            _java_adapter(facts, stats),
            _go_adapter(facts, stats),
            _rust_adapter(facts, stats),
        )
        if adapter.detected
    )
    frameworks: list[FrameworkDetection] = []
    commands: list[CommandSuggestion] = []
    package_managers: list[str] = []
    key_files: list[str] = list(facts.key_files)
    notes: list[str] = []
    for adapter in adapters:
        frameworks.extend(adapter.frameworks)
        commands.extend(adapter.commands)
        for manager in adapter.package_managers:
            _append_unique(package_managers, manager)
        for key_file in adapter.key_files:
            _append_unique(key_files, key_file)
        notes.extend(adapter.notes)
    if not adapters and not stats_tuple:
        notes.append(
            "No strong language adapter matched; inspect files manually before choosing commands."
        )
    if len(adapters) > 1:
        notes.append(
            "Multi-language repository detected; prefer language/package-scoped verification before full-suite commands."
        )
    return LanguageStackReport(
        languages=stats_tuple,
        adapters=adapters,
        frameworks=tuple(dict.fromkeys(frameworks)),
        commands=_dedupe_commands(commands),
        package_managers=tuple(package_managers),
        key_files=tuple(dict.fromkeys(key_files)),
        notes=tuple(dict.fromkeys(notes)),
    )


def _dedupe_commands(commands: Iterable[CommandSuggestion]) -> tuple[CommandSuggestion, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[CommandSuggestion] = []
    for command in commands:
        key = (command.command, command.purpose)
        if key in seen:
            continue
        seen.add(key)
        result.append(command)
    return tuple(result)


def _changed_file_language(path: str) -> str:
    suffix = Path(path).suffix.lower()
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if suffix in exts:
            if lang in {"javascript", "typescript"}:
                return "typescript/javascript"
            if lang == "java":
                return "java/kotlin"
            return lang
    return ""


def suggest_verification_commands(
    root: Path,
    *,
    changed_files: Iterable[str] = (),
    purposes: Iterable[str] = ("test", "typecheck", "lint", "build"),
    max_commands: int = 8,
) -> dict[str, Any]:
    """Return language-aware verification commands for changed files."""

    report = analyze_language_stack(root)
    wanted = {purpose for purpose in purposes if purpose}
    changed = tuple(_norm(path) for path in changed_files if str(path).strip())
    changed_langs = {_changed_file_language(path) for path in changed} - {""}
    commands: list[dict[str, Any]] = []

    for command in report.commands:
        if wanted and command.purpose not in wanted:
            continue
        priority = 0
        if command.language in changed_langs:
            priority += 4
        if command.purpose == "test":
            priority += 3
        elif command.purpose == "typecheck":
            priority += 2
        if not changed_langs:
            priority += 1
        commands.append({**asdict(command), "priority": priority})

    commands.sort(key=lambda item: (-int(item["priority"]), item["purpose"], item["command"]))
    return {
        "summary": f"Suggested {min(len(commands), max_commands)} language-aware command(s).",
        "changed_files": changed,
        "changed_languages": tuple(sorted(changed_langs)),
        "commands": commands[: max(0, max_commands)],
        "notes": report.notes,
    }


def render_language_stack_report(
    root: Path, *, max_files: int = 1200, max_chars: int = 20000
) -> str:
    """Render the language stack report as bounded JSON text."""

    report = analyze_language_stack(root, max_files=max_files)
    return truncate(report.summary(), max_chars)
