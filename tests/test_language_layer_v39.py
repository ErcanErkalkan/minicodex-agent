import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.language_adapters import analyze_language_stack, suggest_verification_commands
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.test_ci import plan_tests
from minicodex_agent.tool_registry import dispatch_tool, get_tool_registry
from minicodex_agent.tools.context import ToolContext


class _Logger:
    def write_tool_call(self, *_args, **_kwargs):
        pass

    def write_observation(self, *_args, **_kwargs):
        pass


def _ctx(root: Path):
    config = AgentConfig(
        root=root,
        model="stub",
        provider="stub",
        approval="auto",
        dry_run=True,
        log_enabled=False,
        project_config_enabled=False,
    )
    state = AgentState(goal="inspect languages", project_profile=detect_project(root))
    return ToolContext(
        config=config,
        state=state,
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_language_actions_are_registered():
    registry = get_tool_registry()
    for action in [
        "detect_language_stack",
        "inspect_frameworks",
        "suggest_verification_commands",
        "language_adapter_report",
    ]:
        assert action in ACTION_SPECS
        assert action in registry


def test_detects_typescript_next_stack_and_commands(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"next": "15.0.0", "react": "19.0.0"},
                "devDependencies": {"typescript": "^5.0.0", "vitest": "^2.0.0"},
                "scripts": {
                    "test": "vitest run",
                    "build": "next build",
                    "typecheck": "tsc --noEmit",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "export default function Page(){ return <div/> }", encoding="utf-8"
    )

    report = analyze_language_stack(tmp_path)
    frameworks = {item.name for item in report.frameworks}
    commands = {item.command for item in report.commands}

    assert any(lang.name == "typescript" for lang in report.languages)
    assert "nextjs" in frameworks
    assert "react" in frameworks
    assert "npm test" in commands
    assert "npm run typecheck" in commands


def test_detects_java_go_and_rust_frameworks(tmp_path: Path):
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency><artifactId>spring-boot</artifactId></dependency></dependencies></project>",
        encoding="utf-8",
    )
    (tmp_path / "go.mod").write_text(
        "module x\nrequire github.com/gin-gonic/gin v1.10.0\n", encoding="utf-8"
    )
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname="x"\nversion="0.1.0"\n[dependencies]\naxum="0.7"\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / "App.java").write_text("class App {}\n", encoding="utf-8")

    report = analyze_language_stack(tmp_path)
    frameworks = {item.name for item in report.frameworks}
    commands = {item.command for item in report.commands}

    assert {"spring-boot", "gin", "axum"}.issubset(frameworks)
    assert {"mvn test", "go test ./...", "cargo test"}.issubset(commands)


def test_project_profile_includes_language_adapter_typecheck(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"typecheck": "tsc --noEmit"}}), encoding="utf-8"
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("const x: number = 1;", encoding="utf-8")

    profile = detect_project(tmp_path)

    assert "typescript" in profile.project_types
    assert "typescript" in profile.languages
    assert "npm run typecheck" in profile.typecheck_commands


def test_plan_tests_can_include_typecheck_commands(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"typecheck": "tsc --noEmit", "test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    profile = detect_project(tmp_path)

    plan = plan_tests(tmp_path, profile, include_typecheck=True, max_commands=5)
    commands = [item.command for item in plan.commands]

    assert "npm run typecheck" in commands


def test_language_tools_return_json(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")

    out = dispatch_tool(_ctx(tmp_path), "detect_language_stack", {})
    data = json.loads(out)

    assert data["summary"].startswith("Language/framework")
    assert any(item["name"] == "python" for item in data["report"]["languages"])


def test_suggest_verification_commands_prioritizes_changed_language(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "widget.ts").write_text("export const x = 1;", encoding="utf-8")

    result = suggest_verification_commands(
        tmp_path, changed_files=["src/widget.ts"], purposes=["typecheck", "test"]
    )

    assert result["changed_languages"] == ("typescript/javascript",)
    assert result["commands"][0]["command"] in {"npm test", "npm run typecheck"}
