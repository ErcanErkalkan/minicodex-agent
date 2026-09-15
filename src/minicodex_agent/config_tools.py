"""Configuration-file validation helpers."""

from __future__ import annotations

import json
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

from .fs_tools import is_probably_binary
from .safety import safe_resolve
from .utils import truncate

JSON_SUFFIXES = {".json"}
TOML_SUFFIXES = {".toml"}
ENV_NAMES = {".env", ".env.example"}
YAML_SUFFIXES = {".yaml", ".yml"}


def _validate_env_text(text: str) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            issues.append(f"L{index}: '=' içermeyen env satırı")
            continue
        key = stripped.split("=", 1)[0].strip()
        if not key:
            issues.append(f"L{index}: boş env anahtarı")
        if " " in key:
            issues.append(f"L{index}: env anahtarında boşluk var: {key!r}")
        if key in seen:
            issues.append(f"L{index}: tekrar eden env anahtarı: {key}")
        seen.add(key)
    return issues


def _validate_yaml_like_text(text: str) -> list[str]:
    """A dependency-free lightweight YAML sanity checker.

    This is intentionally conservative; it does not fully parse YAML. It catches
    common mistakes without pretending to be a full YAML implementation.
    """

    issues: list[str] = []
    previous_indent = 0
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            issues.append(f"L{index}: YAML girintisinde tab karakteri var")
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not stripped.startswith("-") and ":" not in stripped:
            issues.append(f"L{index}: YAML satırında ':' veya liste işareti yok")
        if indent % 2 != 0:
            issues.append(f"L{index}: tek sayılı girinti; iki boşluk önerilir")
        if indent - previous_indent > 2 and previous_indent != 0:
            issues.append(f"L{index}: girinti beklenenden fazla sıçradı")
        previous_indent = indent
    return issues


def validate_config_file(root: Path, user_path: str, max_chars: int = 12000) -> str:
    """Validate common config file formats using safe local parsers."""

    path = safe_resolve(root, user_path)
    if not path.exists():
        return f"Dosya bulunamadı: {user_path}"
    if not path.is_file():
        return f"Dosya değil: {user_path}"
    if is_probably_binary(path):
        return f"Binary veya desteklenmeyen config atlandı: {user_path}"

    suffix = path.suffix.lower()
    name = path.name.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    issues: list[str] = []
    detected = "unknown"

    if suffix in JSON_SUFFIXES:
        detected = "json"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            issues.append(f"JSON parse hatası L{exc.lineno} C{exc.colno}: {exc.msg}")
        else:
            root_type = type(parsed).__name__
            issues.append(f"OK: JSON parse edildi; root type={root_type}")
    elif suffix in TOML_SUFFIXES:
        detected = "toml"
        if tomllib is None:
            issues.append("TOML doğrulama için Python 3.11+ tomllib gerekli.")
        else:
            try:
                parsed = tomllib.loads(text)
            except Exception as exc:  # noqa: BLE001 - tomllib has multiple parse exceptions
                issues.append(f"TOML parse hatası: {exc}")
            else:
                issues.append(f"OK: TOML parse edildi; üst seviye anahtar sayısı={len(parsed)}")
    elif name in ENV_NAMES or name.startswith(".env"):
        detected = "env"
        env_issues = _validate_env_text(text)
        issues.extend(env_issues or ["OK: env biçiminde belirgin sorun bulunamadı."])
    elif suffix in YAML_SUFFIXES:
        detected = "yaml-like"
        yaml_issues = _validate_yaml_like_text(text)
        issues.extend(yaml_issues or ["OK: hafif YAML kontrolünde belirgin sorun bulunamadı."])
    else:
        issues.append(
            "Destek sınırlı: .json, .toml, .env, .yaml/.yml için doğrulama yapılabiliyor."
        )

    status = "PASS" if all(item.startswith("OK:") for item in issues) else "CHECK"
    output = [
        f"Config validation: {user_path}",
        f"Detected format: {detected}",
        f"Status: {status}",
        "",
    ]
    output.extend(f"- {issue}" for issue in issues)
    return truncate("\n".join(output), max_chars)
