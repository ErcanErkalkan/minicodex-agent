import json
from pathlib import Path

from minicodex_agent.action_schema import ACTION_SPECS
from minicodex_agent.agent import AgentState
from minicodex_agent.config import AgentConfig
from minicodex_agent.project_inspector import detect_project
from minicodex_agent.semantic_index import (
    build_semantic_index,
    find_symbol_references,
    inspect_routes,
    semantic_capability_report,
)
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
    state = AgentState(goal="inspect semantic language layer", project_profile=detect_project(root))
    return ToolContext(
        config=config,
        state=state,
        logger=_Logger(),
        confirm_fn=lambda *_args, **_kwargs: True,
        print_header_fn=lambda _title: None,
        ensure_auto_snapshot_before_edit=lambda _action, _target: (True, ""),
        mark_auto_snapshot_handled_fn=lambda: None,
    )


def test_semantic_language_actions_are_registered():
    registry = get_tool_registry()
    for action in [
        "semantic_capability_report",
        "build_semantic_index",
        "find_symbol_references",
        "inspect_routes",
    ]:
        assert action in ACTION_SPECS
        assert action in registry


def test_python_ast_symbols_and_fastapi_routes(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "class UserService:\n"
        "    def get_user(self, user_id: int):\n"
        "        return user_id\n"
        "@app.get('/users/{user_id}')\n"
        "def read_user(user_id: int):\n"
        "    return UserService().get_user(user_id)\n",
        encoding="utf-8",
    )

    index = build_semantic_index(tmp_path)
    symbols = {(item.name, item.kind) for item in index.symbols}
    routes = {(item.framework, item.method, item.route) for item in index.routes}

    assert ("UserService", "class") in symbols
    assert ("read_user", "function") in symbols
    assert ("fastapi", "GET", "/users/{user_id}") in routes


def test_typescript_react_symbols_references_and_next_routes(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Button.tsx").write_text(
        "export interface ButtonProps { label: string }\n"
        "export function Button(props: ButtonProps) { return <button>{props.label}</button> }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "App.tsx").write_text(
        "import { Button } from './Button'\nexport default function App(){ return <Button label='OK'/> }\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "users" / "[id]").mkdir(parents=True)
    (tmp_path / "app" / "users" / "[id]" / "page.tsx").write_text(
        "export default function Page(){ return <div/> }\n",
        encoding="utf-8",
    )

    index = build_semantic_index(tmp_path)
    assert any(
        symbol.name == "Button" and symbol.kind in {"function", "component"}
        for symbol in index.symbols
    )
    assert any(
        route.framework == "nextjs-app-router" and route.route == "/users/[id]"
        for route in index.routes
    )

    refs = find_symbol_references(tmp_path, "Button")
    assert refs["definitions"]
    assert any(ref["path"] == "src/App.tsx" for ref in refs["references"])


def test_java_go_rust_route_detection(tmp_path: Path):
    (tmp_path / "UserController.java").write_text(
        "import org.springframework.web.bind.annotation.*;\n"
        "class UserController {\n"
        '  @GetMapping("/users/{id}")\n'
        '  public String getUser() { return "ok"; }\n'
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.go").write_text(
        'package main\nfunc main(){ r.GET("/health", health) }\nfunc health(){}\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text(
        'pub struct AppState;\nfn main(){ Router::new().route("/items", get(list_items)); }\nfn list_items(){}\n',
        encoding="utf-8",
    )

    routes = inspect_routes(tmp_path)["routes"]
    route_keys = {(item["framework"], item["method"], item["route"]) for item in routes}

    assert ("spring", "GET", "/users/{id}") in route_keys
    assert ("gin", "GET", "/health") in route_keys
    assert ("axum", "GET", "/items") in route_keys


def test_semantic_tools_return_json(tmp_path: Path):
    (tmp_path / "index.ts").write_text(
        "export function greet(name: string){ return `Hello ${name}` }\nconsole.log(greet('Ada'))\n",
        encoding="utf-8",
    )

    out = dispatch_tool(_ctx(tmp_path), "build_semantic_index", {"max_symbols": 20})
    data = json.loads(out)
    assert data["summary"] == "Semantic index built."
    assert any(symbol["name"] == "greet" for symbol in data["index"]["symbols"])

    refs_out = dispatch_tool(_ctx(tmp_path), "find_symbol_references", {"symbol": "greet"})
    refs = json.loads(refs_out)
    assert refs["symbol"] == "greet"
    assert refs["references"]


def test_semantic_capability_report_is_explicit_about_backends():
    report = semantic_capability_report().to_dict()
    backends = {item["backend"] for item in report["parser_capabilities"]}
    languages = set(report["supported_languages"])

    assert "python-ast" in backends
    assert "tree-sitter" in backends
    assert {"python", "typescript", "java", "go", "rust"}.issubset(languages)
