from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "PROJECT_DOCUMENTATION.md"

GUIDE_SOURCES = [
    ROOT / "README.md",
    ROOT / "docs" / "quickstart.md",
    ROOT / "docs" / "usage.md",
    ROOT / "docs" / "local-llm.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "security.md",
    ROOT / "docs" / "evals.md",
    ROOT / "docs" / "github.md",
    ROOT / "docs" / "testing.md",
]

ARCHIVED_REPORT_SOURCES = [
    "FIX_REPORT.md",
    "MODEL_LAYER_FIX_REPORT.md",
    "CONTEXT_LAYER_FIX_REPORT.md",
    "TOOL_LAYER_FIX_REPORT.md",
    "SANDBOX_LAYER_FIX_REPORT.md",
    "PATCH_LAYER_FIX_REPORT.md",
    "TEST_CI_LAYER_FIX_REPORT.md",
    "SKILL_LAYER_FIX_REPORT.md",
    "MULTI_AGENT_LAYER_FIX_REPORT.md",
    "LONG_HORIZON_LAYER_FIX_REPORT.md",
    "DEV_EXPERIENCE_LAYER_FIX_REPORT.md",
    "LANGUAGE_LAYER_FIX_REPORT.md",
    "EVAL_LAYER_FIX_REPORT.md",
    "GITHUB_LAYER_FIX_REPORT.md",
    "OBSERVABILITY_LAYER_FIX_REPORT.md",
    "PROMPT_LAYER_FIX_REPORT.md",
    "SECURITY_LAYER_FIX_REPORT.md",
    "FINAL_COMPLETION_REPORT.md",
    "SECURITY_FALSE_POSITIVE_FIX_REPORT.md",
    "FINAL_READINESS_GATE_FIX_REPORT.md",
    "JSON_REPORT_TRUNCATION_FIX_REPORT.md",
    "BYTECODE_CLEAN_READINESS_FIX_REPORT.md",
    "AGENT_WORKSPACE_ISOLATION_FIX_REPORT.md",
    "TEST_MATRIX_SPLIT_FIX_REPORT.md",
    "EVAL_BENCHMARK_EXPANSION_FIX_REPORT.md",
    "MODEL_TOOL_CALLING_FIX_REPORT.md",
    "EVAL_CLAIM_BENCHMARK_FIX_REPORT.md",
    "SEMANTIC_LANGUAGE_LAYER_FIX_REPORT.md",
    "AST_PATCH_LAYER_FIX_REPORT.md",
    "GITHUB_FULL_AGENT_LAYER_FIX_REPORT.md",
]

EXCLUDED_FIXTURES = [
    Path("tests/fixtures/unsafe_examples/AGENTS.md"),
    Path("tests/fixtures/unsafe_examples/README.md"),
]

INTERNAL_LINKS = {
    "docs/usage.md": "#usage-guide",
    "usage.md": "#usage-guide",
    "docs/security.md": "#security-model",
    "security.md": "#security-model",
    "docs/local-llm.md": "#local-llm-providers",
    "local-llm.md": "#local-llm-providers",
    "docs/evals.md": "#evals-telemetry-and-prompt-ab",
    "evals.md": "#evals-telemetry-and-prompt-ab",
    "docs/github.md": "#github-integration",
    "github.md": "#github-integration",
    "docs/architecture.md": "#architecture",
    "architecture.md": "#architecture",
    "docs/quickstart.md": "#quickstart",
    "quickstart.md": "#quickstart",
    "docs/testing.md": "#testing-and-ci",
    "testing.md": "#testing-and-ci",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()


def _title_and_body(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body = "\n".join(lines[:index] + lines[index + 1 :]).strip()
            return title, body
    raise ValueError("Markdown source has no level-one heading")


def _demote_headings(text: str, levels: int) -> str:
    output: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            output.append(line)
            continue
        if not in_fence:
            match = re.match(r"^(#{1,6})(\s+.*)$", line)
            if match:
                hashes = "#" * min(6, len(match.group(1)) + levels)
                line = hashes + match.group(2)
        output.append(line)
    return "\n".join(output)


def _rewrite_links(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        clean_target = target.split("#", 1)[0]
        replacement = INTERNAL_LINKS.get(clean_target)
        return f"[{label}]({replacement})" if replacement else match.group(0)

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, text)


def _source_label(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _render_source_section(path: Path, *, heading_level: int, body_demote: int) -> str:
    title, body = _title_and_body(_read(path))
    body = _rewrite_links(_demote_headings(body, body_demote))
    source = _source_label(path)
    return f"{'#' * heading_level} {title}\n\n_Source: `{source}`_\n\n{body}".rstrip()


def _existing_historical_archive() -> str:
    if not OUTPUT.exists():
        raise FileNotFoundError(
            f"{OUTPUT.name} is the canonical archive and must exist before regeneration."
        )
    text = _read(OUTPUT)
    match = re.search(
        r"(?ms)^## Historical Engineering Reports\s*$\n+(.*?)"
        r"\n+^## Source Inventory\s*$",
        text,
    )
    if not match:
        raise ValueError(f"{OUTPUT.name} has no historical engineering report archive.")
    return match.group(1).strip()


def render() -> str:
    active_sources = [*GUIDE_SOURCES, ROOT / "CHANGELOG.md"]
    historical_archive = _existing_historical_archive()

    parts = [
        "# MiniCodex Agent - Unified Project Documentation",
        (
            "> Canonical documentation consolidated from the project's user guides, "
            "changelog, and archived engineering reports. Security-test fixture Markdown "
            "is intentionally excluded."
        ),
        "## Contents",
        "\n".join(
            [
                "- [Project documentation](#project-documentation)",
                "- [Changelog](#changelog)",
                "- [Historical engineering reports](#historical-engineering-reports)",
                "- [Source inventory](#source-inventory)",
            ]
        ),
        "## Project Documentation",
    ]

    parts.extend(
        _render_source_section(path, heading_level=3, body_demote=2) for path in GUIDE_SOURCES
    )

    changelog_title, changelog_body = _title_and_body(_read(ROOT / "CHANGELOG.md"))
    parts.extend(
        [
            f"## {changelog_title}",
            "_Source: `CHANGELOG.md`_",
            _demote_headings(changelog_body, 1),
            "## Historical Engineering Reports",
            historical_archive,
        ]
    )

    inventory = (
        [f"- Active source: `{_source_label(path)}`" for path in active_sources]
        + [f"- Archived after consolidation: `{path}`" for path in ARCHIVED_REPORT_SOURCES]
        + [
            (
                f"- Excluded test fixture: `{path.as_posix()}` "
                "(intentional unsafe prompt/security sample)"
            )
            for path in EXCLUDED_FIXTURES
        ]
    )
    parts.extend(["## Source Inventory", "\n".join(inventory)])

    return "\n\n".join(part.strip() for part in parts if part.strip()) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the unified MiniCodex Markdown documentation file."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if PROJECT_DOCUMENTATION.md is not current.",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not OUTPUT.exists() or _read(OUTPUT) + "\n" != rendered:
            print(f"{OUTPUT.name} is out of date.")
            return 1
        print(f"{OUTPUT.name} is current.")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT} ({len(rendered)} characters).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
