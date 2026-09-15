"""Repo-local skill discovery, validation, and progressive disclosure.

MiniCodex skills are intentionally simple, reviewable Markdown folders under
``.minicodex/skills/<skill-name>/SKILL.md``.  The agent sees a small ranked
catalog in the context pack and can explicitly call ``read_skill`` when it
needs the full instructions for a selected skill.  This mirrors the practical
"metadata first, full skill on demand" pattern used by stronger coding-agent
harnesses without executing arbitrary local code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from .safety import safe_resolve, sensitive_path_reason
from .utils import to_pretty_json, truncate

SKILLS_ROOT = Path(".minicodex/skills")
SKILL_FILENAME = "SKILL.md"
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")

DEFAULT_SKILL_TEMPLATE = """---
description: {description}
triggers: [{trigger}]
---

# {title}

## When to use
- Use this skill when the task matches: {description}

## Workflow
1. Inspect the relevant files and project instructions first.
2. Make the smallest safe change that satisfies the task.
3. Run targeted checks before broad checks.
4. Summarize changed files, checks run, and remaining risks.

## Guardrails
- Do not expose secrets.
- Read files before editing them.
- Prefer plan_patch/apply_patch for multi-line edits.
"""


@dataclass(frozen=True)
class SkillMetadata:
    """Model-facing metadata for one repo-local skill."""

    name: str
    path: str
    title: str
    description: str
    triggers: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    when_to_use: str = ""
    summary: str = ""
    relevance: float = 0.0
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["triggers"] = list(self.triggers)
        data["tags"] = list(self.tags)
        data["warnings"] = list(self.warnings)
        return data


def split_terms(text: str) -> set[str]:
    """Return normalized terms for skill matching."""

    terms: set[str] = set()
    for match in TERM_RE.finditer(text):
        raw = match.group(0).strip()
        lowered = raw.lower()
        if len(lowered) >= 2:
            terms.add(lowered)
        for piece in (
            re.sub(r"(?<!^)(?=[A-Z])", " ", raw.replace("-", "_")).replace("_", " ").split()
        ):
            piece = piece.lower()
            if len(piece) >= 2:
                terms.add(piece)
    return terms


def _parse_scalar(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    return value


def _parse_list(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return ()
        return tuple(_parse_scalar(part) for part in inner.split(",") if _parse_scalar(part))
    return tuple(_parse_scalar(part) for part in value.split(",") if _parse_scalar(part))


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a conservative YAML-like front matter block without PyYAML."""

    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block = text[4:end].strip()
    body = text[end + len("\n---") :].lstrip("\n")
    data: dict[str, Any] = {}
    current_key = ""
    current_list: list[str] | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-") and current_key and current_list is not None:
            item = _parse_scalar(stripped[1:].strip())
            if item:
                current_list.append(item)
            continue
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        value = raw_value.strip()
        current_key = key
        current_list = None
        if value == "":
            current_list = []
            data[key] = current_list
        elif value.startswith("[") or key in {"triggers", "tags", "tools"}:
            data[key] = list(_parse_list(value))
        else:
            data[key] = _parse_scalar(value)
    for key, value in list(data.items()):
        if isinstance(value, list):
            list_value = cast(list[Any], value)
            data[key] = tuple(str(item) for item in list_value if str(item).strip())
    return data, body


def _first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _extract_section(text: str, heading: str, max_chars: int = 700) -> str:
    """Extract a short markdown section by heading name."""

    lines = text.splitlines()
    target = heading.lower().strip()
    start = -1
    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("#") and stripped.lstrip("#").strip() == target:
            start = idx + 1
            break
    if start == -1:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if line.strip().startswith("#"):
            break
        if line.strip():
            collected.append(line.strip())
        if len("\n".join(collected)) >= max_chars:
            break
    return truncate("\n".join(collected), max_chars)


def _summarize_skill_body(body: str, *, max_chars: int) -> str:
    """Create a metadata-grade summary for the context pack."""

    selected: list[str] = []
    when = _extract_section(body, "When to use", max_chars=max_chars // 2)
    workflow = _extract_section(body, "Workflow", max_chars=max_chars // 2)
    if when:
        selected.append("When to use:\n" + when)
    if workflow:
        selected.append("Workflow:\n" + workflow)
    if not selected:
        for line in body.splitlines()[:120]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("-") or len(selected) < 10:
                selected.append(stripped)
            if len("\n".join(selected)) >= max_chars:
                break
    return truncate("\n".join(selected) or body, max_chars)


def _skill_file_is_allowed(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if len(rel.parts) != 4:
        return False
    if rel.parts[0] != ".minicodex" or rel.parts[1] != "skills" or rel.parts[3] != SKILL_FILENAME:
        return False
    if not SKILL_NAME_RE.match(rel.parts[2]):
        return False
    if sensitive_path_reason(path, root):
        return False
    return True


def iter_skill_files(root: Path, *, skills_dir: str = str(SKILLS_ROOT)) -> Iterable[Path]:
    """Yield safe SKILL.md files under the project skills directory."""

    base = safe_resolve(root, skills_dir)
    if not base.exists() or not base.is_dir():
        return []
    return (
        path
        for path in sorted(base.glob(f"*/{SKILL_FILENAME}"))
        if path.is_file() and _skill_file_is_allowed(path, root)
    )


def _metadata_from_text(
    root: Path, skill_file: Path, text: str, *, goal: str = "", max_summary_chars: int = 1000
) -> SkillMetadata:
    fm, body = _parse_front_matter(text)
    rel = skill_file.relative_to(root).as_posix()
    name = skill_file.parent.name
    title = str(fm.get("title") or _first_heading(body, name.replace("-", " ").title()))
    description = str(
        fm.get("description") or _extract_section(body, "Description", max_chars=500) or title
    )
    triggers_value = fm.get("triggers", ())
    tags_value = fm.get("tags", ())
    triggers = tuple(
        str(item).strip()
        for item in (
            triggers_value
            if isinstance(triggers_value, tuple)
            else _parse_list(str(triggers_value))
        )
        if str(item).strip()
    )
    tags = tuple(
        str(item).strip()
        for item in (tags_value if isinstance(tags_value, tuple) else _parse_list(str(tags_value)))
        if str(item).strip()
    )
    when_to_use = str(fm.get("when_to_use") or _extract_section(body, "When to use", max_chars=700))
    summary = _summarize_skill_body(body, max_chars=max_summary_chars)

    goal_terms = split_terms(goal)
    skill_terms = split_terms(
        "\n".join(
            [name, title, description, " ".join(triggers), " ".join(tags), when_to_use, summary]
        )
    )
    trigger_terms = split_terms(" ".join(triggers))
    relevance = float(len(goal_terms & skill_terms))
    relevance += 1.5 * len(goal_terms & trigger_terms)
    if goal and name.lower() in goal.lower():
        relevance += 2.0
    if triggers:
        relevance += 0.1

    warnings: list[str] = []
    if not description or description == title:
        warnings.append("missing explicit description")
    if not triggers:
        warnings.append("missing triggers")
    if len(text) > 32_000:
        warnings.append("large skill file; consider splitting")

    return SkillMetadata(
        name=name,
        path=rel,
        title=title,
        description=truncate(description, 500),
        triggers=triggers,
        tags=tags,
        when_to_use=truncate(when_to_use, 700),
        summary=summary,
        relevance=round(relevance, 3),
        warnings=tuple(warnings),
    )


def discover_skills(
    root: Path,
    *,
    goal: str = "",
    max_skills: int = 8,
    max_summary_chars: int = 1000,
) -> list[SkillMetadata]:
    """Discover safe repo-local skills and rank them for the current goal."""

    results: list[SkillMetadata] = []
    for skill_file in iter_skill_files(root):
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        results.append(
            _metadata_from_text(
                root,
                skill_file,
                text,
                goal=goal,
                max_summary_chars=max_summary_chars,
            )
        )
    results.sort(key=lambda item: (-item.relevance, item.name))
    return results[: max(0, int(max_skills))]


def resolve_skill_file(root: Path, name_or_path: str) -> Path:
    """Resolve a skill name or relative SKILL.md path safely."""

    value = name_or_path.strip()
    if not value:
        raise ValueError("skill name/path is required")
    if value.endswith(f"/{SKILL_FILENAME}") or value.startswith(".minicodex/"):
        path = safe_resolve(root, value)
    else:
        if not SKILL_NAME_RE.match(value):
            raise ValueError(
                "skill name may only contain letters, numbers, dot, dash, and underscore"
            )
        path = safe_resolve(root, str(SKILLS_ROOT / value / SKILL_FILENAME))
    if not _skill_file_is_allowed(path, root):
        raise ValueError(
            "skill path is outside the allowed .minicodex/skills/<name>/SKILL.md layout"
        )
    return path


def read_skill(root: Path, name_or_path: str, *, max_chars: int = 8000) -> str:
    """Read one safe skill file with a metadata header and bounded content."""

    path = resolve_skill_file(root, name_or_path)
    if not path.exists() or not path.is_file():
        return f"SKILL NOT FOUND: {name_or_path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata = _metadata_from_text(root, path, text, goal="", max_summary_chars=1200)
    payload = {
        "skill": metadata.to_dict(),
        "content": truncate(text, max(1000, int(max_chars))),
        "truncated": len(text) > max(1000, int(max_chars)),
    }
    return "SKILL_JSON\n" + to_pretty_json(payload)


def render_skill_catalog(
    root: Path, *, goal: str = "", max_skills: int = 12, max_summary_chars: int = 800
) -> str:
    """Render the discovered skill catalog for the model/user."""

    skills = discover_skills(
        root, goal=goal, max_skills=max_skills, max_summary_chars=max_summary_chars
    )
    payload = {
        "goal": goal,
        "count": len(skills),
        "skills": [skill.to_dict() for skill in skills],
        "usage": "Call read_skill with a selected skill name/path before following detailed workflow instructions.",
    }
    return "SKILL_CATALOG_JSON\n" + to_pretty_json(payload)


def validate_skills(root: Path, *, max_skills: int = 200) -> str:
    """Validate repo-local skill layout and metadata."""

    base = safe_resolve(root, str(SKILLS_ROOT))
    errors: list[str] = []
    warnings: list[str] = []
    skills: list[dict[str, Any]] = []
    if not base.exists():
        return "SKILL_VALIDATION_JSON\n" + to_pretty_json(
            {
                "ok": True,
                "count": 0,
                "skills": [],
                "warnings": ["no .minicodex/skills directory found"],
                "errors": [],
            }
        )
    for idx, skill_file in enumerate(sorted(base.glob("*/SKILL.md"))):
        if idx >= max_skills:
            warnings.append("skill validation stopped at max_skills limit")
            break
        if not _skill_file_is_allowed(skill_file, root):
            errors.append(f"blocked invalid skill path: {skill_file}")
            continue
        try:
            text = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"cannot read {skill_file}: {exc}")
            continue
        meta = _metadata_from_text(root, skill_file, text, max_summary_chars=500)
        skills.append(meta.to_dict())
        warnings.extend(f"{meta.name}: {warning}" for warning in meta.warnings)
    payload = {
        "ok": not errors,
        "count": len(skills),
        "skills": skills,
        "warnings": warnings,
        "errors": errors,
    }
    return "SKILL_VALIDATION_JSON\n" + to_pretty_json(payload)


def init_skill(
    root: Path,
    *,
    name: str,
    description: str = "Project-local workflow guidance.",
    overwrite: bool = False,
    dry_run: bool = False,
) -> str:
    """Create a reviewable starter SKILL.md file."""

    if not SKILL_NAME_RE.match(name):
        raise ValueError("skill name may only contain letters, numbers, dot, dash, and underscore")
    path = safe_resolve(root, str(SKILLS_ROOT / name / SKILL_FILENAME))
    if not _skill_file_is_allowed(path, root):
        raise ValueError("resolved skill path is not allowed")
    trigger = name.replace("-", " ")
    title = name.replace("-", " ").replace("_", " ").title()
    content = DEFAULT_SKILL_TEMPLATE.format(description=description, trigger=trigger, title=title)
    if path.exists() and not overwrite:
        return f"Skill kept existing: {path.relative_to(root)}"
    if dry_run:
        action = "overwrite" if path.exists() else "write"
        return f"DRY-RUN: would {action} skill: {path.relative_to(root)}\n\n" + content
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Skill created: {path.relative_to(root)}\n\n" + content


def skills_to_json(skills: Iterable[SkillMetadata]) -> str:
    """Serialize skills for debugging/tests."""

    return json.dumps([skill.to_dict() for skill in skills], ensure_ascii=False, indent=2)
