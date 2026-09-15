"""Local role-based multi-agent execution helpers.

MiniCodex multi-agent support now has two layers:

1. Legacy task-batch bookkeeping (``run_task_batch``/``list_agent_batches``).
2. A bounded in-process subagent coordinator with per-role threads, a shared
   mailbox, strict tool allowlists, per-worker budgets, and a deterministic
   result merger.

The coordinator is still local and supervised. It does not start a background
service and it does not promise cloud-scale autonomy, but it gives each role a
separate thread identity and auditable transcript so multi-agent runs are much
closer to real Codex-style subagent orchestration.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .action_schema import ActionValidationError, validate_action
from .config import AgentConfig
from .model_client import ModelBudgetExceeded, ModelCallError, ModelClient, ModelOutputParseError
from .project_inspector import ProjectProfile, detect_project
from .secret_scanner import redact_secret
from .tool_registry import dispatch_tool
from .tool_result import render_structured_observation
from .tools.context import ToolContext
from .utils import extract_json, to_pretty_json, truncate

BATCH_LOG = Path(".minicodex/agent_batches.jsonl")
MULTI_AGENT_RUNS_DIR = Path(".minicodex/multi_agent_runs")
CONTROL_TOOLS = {"finish", "update_plan", "ask_user"}


@dataclass(frozen=True)
class RoleWorkItem:
    """One role in a role-based coding workflow."""

    role: str
    objective: str
    tools: tuple[str, ...]
    output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "tools": list(self.tools),
            "output": self.output,
        }


@dataclass(frozen=True)
class RoleAgentSpec:
    """Executable local worker role specification."""

    role: str
    objective: str
    allowed_tools: tuple[str, ...]
    max_steps: int = 3
    model_call_budget: int = 4
    write_capable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "objective": self.objective,
            "allowed_tools": list(self.allowed_tools),
            "max_steps": self.max_steps,
            "model_call_budget": self.model_call_budget,
            "write_capable": self.write_capable,
        }


@dataclass(frozen=True)
class AgentMessage:
    """A compact mailbox/thread message exchanged by local subagents."""

    message_id: str
    sender: str
    recipient: str
    kind: str
    content: str
    created_at: str
    step: int = 0
    thread_id: str = ""

    def to_dict(self, *, max_chars: int = 4000) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "kind": self.kind,
            "content": truncate(redact_secret(self.content), max_chars),
            "created_at": self.created_at,
            "step": self.step,
            "thread_id": self.thread_id,
        }


@dataclass
class AgentThread:
    """Independent child-agent transcript."""

    thread_id: str
    parent_run_id: str
    role: str
    objective: str
    allowed_tools: tuple[str, ...]
    status: str = "planned"
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    messages: list[AgentMessage] = field(default_factory=list)
    result_summary: str = ""
    actions: list[str] = field(default_factory=list)
    workspace_hint: str = "shared-root"

    def add_message(
        self, sender: str, recipient: str, kind: str, content: str, *, step: int = 0
    ) -> None:
        self.messages.append(
            AgentMessage(
                message_id=uuid.uuid4().hex[:10],
                sender=sender,
                recipient=recipient,
                kind=kind,
                content=content,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                step=step,
                thread_id=self.thread_id,
            )
        )

    def to_dict(
        self, *, include_messages: bool = True, max_messages: int = 20, max_chars: int = 4000
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "thread_id": self.thread_id,
            "parent_run_id": self.parent_run_id,
            "role": self.role,
            "objective": self.objective,
            "allowed_tools": list(self.allowed_tools),
            "status": self.status,
            "created_at": self.created_at,
            "result_summary": truncate(redact_secret(self.result_summary), max_chars),
            "actions": list(self.actions),
            "workspace_hint": self.workspace_hint,
        }
        if include_messages:
            payload["messages"] = [
                msg.to_dict(max_chars=max_chars) for msg in self.messages[-max_messages:]
            ]
            payload["message_count"] = len(self.messages)
        return payload


@dataclass
class AgentMailbox:
    """Shared mailbox for parent/subagent coordination."""

    messages: list[AgentMessage] = field(default_factory=list)

    def post(
        self,
        sender: str,
        recipient: str,
        content: str,
        *,
        kind: str = "note",
        step: int = 0,
        thread_id: str = "",
    ) -> AgentMessage:
        message = AgentMessage(
            message_id=uuid.uuid4().hex[:10],
            sender=sender,
            recipient=recipient,
            kind=kind,
            content=content,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            step=step,
            thread_id=thread_id,
        )
        self.messages.append(message)
        return message

    def for_recipient(
        self, role: str, *, limit: int = 12, max_chars: int = 4000
    ) -> list[dict[str, Any]]:
        selected = [
            msg
            for msg in self.messages
            if msg.recipient in {role, "all", "*"} or msg.sender in {role, "parent"}
        ]
        return [msg.to_dict(max_chars=max_chars) for msg in selected[-max(1, limit) :]]

    def to_dict(self, *, limit: int = 50, max_chars: int = 4000) -> list[dict[str, Any]]:
        return [msg.to_dict(max_chars=max_chars) for msg in self.messages[-max(1, limit) :]]


@dataclass
class WorkerObservation:
    """A role worker observation."""

    step: int
    action: str
    args: str
    observation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "step": str(self.step),
            "action": self.action,
            "args": self.args,
            "observation": self.observation,
        }


@dataclass
class RoleWorkerState:
    """Independent state for one role worker."""

    goal: str
    role: str
    objective: str
    project_profile: ProjectProfile
    thread_id: str = ""
    plan: list[str] = field(default_factory=list)
    observations: list[WorkerObservation] = field(default_factory=list)
    last_command_output: str = ""

    def recent_observations(self, limit: int = 8) -> list[dict[str, str]]:
        return [obs.to_dict() for obs in self.observations[-limit:]]


@dataclass(frozen=True)
class RoleAgentResult:
    """Finished worker result."""

    role: str
    status: str
    steps_used: int
    actions: tuple[str, ...]
    summary: str
    observations: tuple[dict[str, str], ...]
    thread_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "thread_id": self.thread_id,
            "status": self.status,
            "steps_used": self.steps_used,
            "actions": list(self.actions),
            "summary": self.summary,
            "observations": list(self.observations),
        }


class AgentResultMerger:
    """Deterministically merge subagent outcomes into one parent-facing summary."""

    @staticmethod
    def merge(
        goal: str, results: list[RoleAgentResult], mailbox: AgentMailbox, *, max_chars: int = 12000
    ) -> dict[str, Any]:
        role_summaries = [
            {
                "role": result.role,
                "thread_id": result.thread_id,
                "status": result.status,
                "steps_used": result.steps_used,
                "actions": list(result.actions),
                "summary": truncate(
                    redact_secret(result.summary), max(800, max_chars // max(1, len(results) or 1))
                ),
            }
            for result in results
        ]
        failed = [result.role for result in results if result.status != "finished"]
        write_roles = [
            result.role
            for result in results
            if any(
                action in {"write_file", "replace_in_file", "apply_patch", "rename_python_symbol"}
                for action in result.actions
            )
        ]
        next_steps: list[str] = []
        if failed:
            next_steps.append("Review unfinished subagent threads before applying broad changes.")
        if write_roles:
            next_steps.append(
                "Run targeted tests and review the git diff produced by write-capable roles."
            )
        if not next_steps:
            next_steps.append(
                "Use the merged role summaries to decide the next focused agent action."
            )
        merged_text = "\n".join(f"[{item['role']}] {item['summary']}" for item in role_summaries)
        return {
            "goal": goal,
            "status": "needs_review" if failed else "merged",
            "role_summaries": role_summaries,
            "failed_roles": failed,
            "write_roles": write_roles,
            "mailbox_message_count": len(mailbox.messages),
            "consolidated_summary": truncate(redact_secret(merged_text), max_chars),
            "recommended_next_steps": next_steps,
        }


def _profile_hint(profile: ProjectProfile) -> str:
    managers = (
        ", ".join(profile.package_managers) if profile.package_managers else "unknown manager"
    )
    return (
        f"Detected project type(s): {', '.join(profile.project_types) or 'unknown'}; "
        f"package managers: {managers}."
    )


def _candidate_role_specs(
    max_steps_each: int = 3, model_call_budget_each: int = 4
) -> list[RoleAgentSpec]:
    steps = max(1, min(int(max_steps_each), 12))
    calls = max(1, min(int(model_call_budget_each), 20))
    return [
        RoleAgentSpec(
            role="planner",
            objective="Clarify scope, constraints, risk, and a minimal acceptance plan.",
            allowed_tools=(
                "read_project_config",
                "read_project_policy",
                "decompose_task",
                "build_code_map",
                "inspect_project",
                "list_skills",
                "read_skill",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=False,
        ),
        RoleAgentSpec(
            role="code-researcher",
            objective="Find the smallest relevant code surface before edits.",
            allowed_tools=(
                "index_project",
                "search_code",
                "search_text",
                "rg_search",
                "glob_file_search",
                "list_dir",
                "read_file",
                "read_file_range",
                "read_many_files",
                "inspect_python_ast",
                "find_python_symbol",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=False,
        ),
        RoleAgentSpec(
            role="implementer",
            objective="Make minimal policy-compliant edits with snapshot/patch safeguards.",
            allowed_tools=(
                "check_project_policy",
                "create_snapshot",
                "preview_replace_in_file",
                "plan_patch",
                "verify_patch",
                "replace_in_file",
                "apply_patch",
                "write_file",
                "rename_python_symbol",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=True,
        ),
        RoleAgentSpec(
            role="tester",
            objective="Plan and run targeted checks, then classify failures without broad changes.",
            allowed_tools=(
                "plan_tests",
                "run_targeted_tests",
                "run_tests",
                "run_command",
                "classify_test_failure",
                "summarize_ci_log",
                "detect_flaky_tests",
                "analyze_failure",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=False,
        ),
        RoleAgentSpec(
            role="reviewer",
            objective="Review change set, rollback risk, and secret exposure before finalization.",
            allowed_tools=(
                "review_change_set",
                "scan_secrets",
                "check_rollback_policy",
                "prepare_pr_summary",
                "generate_commit_message",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=False,
        ),
        RoleAgentSpec(
            role="documenter",
            objective="Update docs or migration notes only when explicitly needed.",
            allowed_tools=(
                "read_file",
                "read_file_range",
                "preview_replace_in_file",
                "replace_in_file",
                "write_file",
                "finish",
                "update_plan",
            ),
            max_steps=steps,
            model_call_budget=calls,
            write_capable=True,
        ),
    ]


def _select_roles(
    max_agents: int,
    roles: Iterable[str] | None = None,
    *,
    max_steps_each: int = 3,
    model_call_budget_each: int = 4,
) -> list[RoleAgentSpec]:
    candidates = _candidate_role_specs(max_steps_each, model_call_budget_each)
    requested = [str(role).strip().lower() for role in roles or [] if str(role).strip()]
    if requested:
        selected = [spec for spec in candidates if spec.role in requested]
    else:
        selected = candidates
    return selected[: max(1, min(int(max_agents), 6))]


def _make_thread(
    run_id: str, spec: RoleAgentSpec, goal: str, *, workspace_hint: str = "shared-root"
) -> AgentThread:
    thread = AgentThread(
        thread_id=f"thr_{spec.role.replace('-', '_')}_{uuid.uuid4().hex[:8]}",
        parent_run_id=run_id,
        role=spec.role,
        objective=spec.objective,
        allowed_tools=spec.allowed_tools,
        workspace_hint=workspace_hint,
    )
    thread.add_message(
        "parent", spec.role, "assignment", f"Goal: {goal}\nObjective: {spec.objective}"
    )
    return thread


def _thread_plan_payload(
    *,
    root: Path,
    goal: str,
    max_agents: int = 4,
    roles: Iterable[str] | None = None,
    max_steps_each: int = 3,
    model_call_budget_each: int = 4,
) -> dict[str, Any]:
    profile = detect_project(root)
    specs = _select_roles(
        max_agents,
        roles,
        max_steps_each=max_steps_each,
        model_call_budget_each=model_call_budget_each,
    )
    run_id = uuid.uuid4().hex[:12]
    return {
        "run_id": run_id,
        "goal": goal,
        "profile_hint": _profile_hint(profile),
        "thread_model": "parent coordinator + role-scoped subagent threads + shared mailbox + deterministic result merger",
        "max_agents": len(specs),
        "threads": [
            _make_thread(run_id, spec, goal).to_dict(include_messages=False) for spec in specs
        ],
        "roles": [spec.to_dict() for spec in specs],
        "communication_contract": {
            "assignment": "parent -> role with scoped objective and allowed tools",
            "handoff": "completed role summaries are posted to mailbox recipient='all'",
            "isolation": "each role receives its own thread_id, observation list, step budget, and model-call budget",
            "merge": "AgentResultMerger consolidates role summaries, failed roles, write roles, and next steps",
        },
        "execution_note": "Use run_subagent_threads/run_multi_agent_work for bounded execution. Use read_multi_agent_run for saved transcript inspection.",
    }


def plan_subagent_threads(
    root: Path,
    goal: str,
    max_agents: int = 4,
    roles: Iterable[str] | None = None,
    *,
    max_steps_each: int = 3,
    model_call_budget_each: int = 4,
) -> str:
    """Create a Codex-style parent/child subagent thread plan."""

    payload = _thread_plan_payload(
        root=root,
        goal=goal,
        max_agents=max_agents,
        roles=roles,
        max_steps_each=max_steps_each,
        model_call_budget_each=model_call_budget_each,
    )
    return "Subagent thread plan:\n" + to_pretty_json(payload)


def make_multi_agent_plan(root: Path, goal: str, max_agents: int = 4) -> str:
    """Create a role-based plan for complex work."""

    payload = _thread_plan_payload(root=root, goal=goal, max_agents=max_agents)
    return "Multi-agent work plan (role-based executable plan):\n" + to_pretty_json(payload)


def _worker_prompt(
    *,
    root: Path,
    goal: str,
    spec: RoleAgentSpec,
    state: RoleWorkerState,
    step: int,
    execution_mode: str,
    mailbox: AgentMailbox | None = None,
    thread: AgentThread | None = None,
    thread_message_limit: int = 12,
) -> str:
    inbox = (
        mailbox.for_recipient(spec.role, limit=thread_message_limit) if mailbox is not None else []
    )
    payload = {
        "multi_agent_worker": True,
        "thread_id": thread.thread_id if thread else state.thread_id,
        "role": spec.role,
        "role_objective": spec.objective,
        "user_goal": goal,
        "project_root": str(root),
        "current_worker_step": step,
        "execution_mode": execution_mode,
        "allowed_tools_for_this_worker": list(spec.allowed_tools),
        "tool_budget_remaining": max(0, spec.max_steps - step + 1),
        "model_call_budget_for_this_worker": spec.model_call_budget,
        "project_profile": state.project_profile.to_dict(),
        "current_plan": state.plan,
        "inbox_messages": inbox,
        "recent_worker_observations": state.recent_observations(),
        "thread_policy": {
            "stay_in_role": True,
            "do_not_use_tools_outside_allowlist": True,
            "finish_with_role_summary": True,
            "write_roles_should_make_minimal_edits_only": spec.write_capable,
        },
        "instruction": (
            "You are one bounded MiniCodex subagent thread. Choose one action only. "
            "Use only allowed_tools_for_this_worker. Read mailbox messages as context, but do not "
            "assume another worker has changed files unless you verify. Finish with a concise role summary."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _summarize_finish_args(args: Mapping[str, object]) -> str:
    summary = str(args.get("summary", "")) if isinstance(args, Mapping) else ""
    if summary:
        return summary
    return to_pretty_json(dict(args)) if isinstance(args, Mapping) else "Role finished."


def _tool_allowed_for_worker(spec: RoleAgentSpec, action: str) -> bool:
    return action in spec.allowed_tools or action in CONTROL_TOOLS


def _make_worker_config(
    parent_config: AgentConfig, spec: RoleAgentSpec, dry_run: bool
) -> AgentConfig:
    return replace(
        parent_config,
        max_steps=spec.max_steps,
        dry_run=dry_run,
        model_call_budget=spec.model_call_budget,
    )


def _run_one_role_worker(
    *,
    parent_ctx: ToolContext,
    goal: str,
    spec: RoleAgentSpec,
    execution_mode: str,
    dry_run: bool,
    thread: AgentThread | None = None,
    mailbox: AgentMailbox | None = None,
) -> RoleAgentResult:
    config = _make_worker_config(parent_ctx.config, spec, dry_run)
    profile = detect_project(config.root)
    local_thread = thread or _make_thread("adhoc", spec, goal)
    local_thread.status = "running"
    state = RoleWorkerState(
        goal=goal,
        role=spec.role,
        objective=spec.objective,
        project_profile=profile,
        thread_id=local_thread.thread_id,
    )
    client = ModelClient(
        config.model,
        provider=config.provider,
        timeout_seconds=config.model_timeout_seconds,
        max_output_tokens=config.model_max_output_tokens,
        max_retries=config.model_max_retries,
        retry_backoff_seconds=config.model_retry_backoff_seconds,
        structured_output=config.model_structured_output,
        call_budget=spec.model_call_budget,
        cost_budget_usd=config.model_cost_budget_usd,
        input_price_per_million=config.model_input_price_per_million,
        output_price_per_million=config.model_output_price_per_million,
        base_url=config.model_base_url or None,
        api_key_env=config.model_api_key_env,
        reasoning_effort=config.model_reasoning_effort or None,
        stream=config.model_stream,
        action_protocol=config.model_action_protocol,
    )
    actions: list[str] = []
    summary = "Worker stopped without finish."
    status = "max_steps_reached"

    worker_ctx = ToolContext(
        config=config,
        state=state,
        logger=parent_ctx.logger,
        confirm_fn=parent_ctx.confirm_fn,
        print_header_fn=parent_ctx.print_header_fn,
        ensure_auto_snapshot_before_edit=parent_ctx.ensure_auto_snapshot_before_edit,
        mark_auto_snapshot_handled_fn=parent_ctx.mark_auto_snapshot_handled_fn,
    )

    for step in range(1, spec.max_steps + 1):
        try:
            raw = client.next_action_text(
                _worker_prompt(
                    root=config.root,
                    goal=goal,
                    spec=spec,
                    state=state,
                    step=step,
                    execution_mode=execution_mode,
                    mailbox=mailbox,
                    thread=local_thread,
                    thread_message_limit=getattr(config, "multi_agent_thread_max_messages", 12),
                )
            )
            decision = validate_action(extract_json(raw))
            client.record_action_validation(True)
        except (ActionValidationError, ValueError, TypeError) as exc:
            client.record_action_validation(False)
            action = "finish"
            args: dict[str, object] = {
                "summary": f"{spec.role} worker stopped because model/action validation failed: {exc}",
                "changed_files": [],
                "checks_run": [],
                "next_steps": [],
            }
            thought = "Worker validation failure."
        except (ModelBudgetExceeded, ModelCallError, ModelOutputParseError) as exc:
            action = "finish"
            args = {
                "summary": f"{spec.role} worker stopped because provider call failed: {exc}",
                "changed_files": [],
                "checks_run": [],
                "next_steps": [],
            }
            thought = "Worker provider failure."
        else:
            thought = str(decision.get("thought", ""))
            action = str(decision.get("action", ""))
            raw_args = decision.get("args", {})
            args = raw_args if isinstance(raw_args, dict) else {}

        actions.append(action)
        local_thread.actions.append(action)
        local_thread.add_message(
            spec.role, "parent", "thought", thought or f"Action: {action}", step=step
        )
        if not _tool_allowed_for_worker(spec, action):
            observation = (
                f"ROLE TOOL BLOCK: worker '{spec.role}' is not allowed to call '{action}'. "
                f"Allowed tools: {', '.join(spec.allowed_tools)}"
            )
        else:
            try:
                observation = dispatch_tool(worker_ctx, action, args)
                if config.structured_tool_results:
                    observation = render_structured_observation(
                        action=action,
                        text=observation,
                        args=args,
                        max_content_chars=config.tool_result_content_chars,
                    )
            except Exception as exc:  # noqa: BLE001 - worker should report failure, not crash coordinator
                observation = f"Role action failed: {type(exc).__name__}: {exc}"
        if action in {"run_command", "run_tests", "run_targeted_tests"}:
            state.last_command_output = observation
        state.observations.append(
            WorkerObservation(
                step=step,
                action=action,
                args=truncate(json.dumps(args, ensure_ascii=False), 2000),
                observation=truncate(observation, config.max_observation_chars),
            )
        )
        local_thread.add_message(spec.role, "parent", "observation", observation, step=step)
        parent_ctx.logger.log_event(
            {
                "type": "multi_agent_worker_step",
                "thread_id": local_thread.thread_id,
                "role": spec.role,
                "step": step,
                "thought": thought,
                "action": action,
                "args": args,
                "observation": truncate(observation, config.max_observation_chars),
            }
        )
        if action == "finish":
            status = "finished"
            summary = _summarize_finish_args(args)
            break

    local_thread.status = status
    local_thread.result_summary = summary
    if mailbox is not None:
        mailbox.post(
            spec.role,
            "all",
            summary,
            kind="result",
            step=len(actions),
            thread_id=local_thread.thread_id,
        )

    return RoleAgentResult(
        role=spec.role,
        thread_id=local_thread.thread_id,
        status=status,
        steps_used=len(actions),
        actions=tuple(actions),
        summary=summary,
        observations=tuple(obs.to_dict() for obs in state.observations),
    )


def _multi_agent_run_path(root: Path, run_id: str) -> Path:
    return (root / MULTI_AGENT_RUNS_DIR / f"{run_id}.json").resolve()


def _write_multi_agent_run(root: Path, payload: dict[str, Any]) -> None:
    path = _multi_agent_run_path(root, str(payload["run_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = redact_secret(to_pretty_json(payload))
    path.write_text(text, encoding="utf-8")


def run_multi_agent_work(
    parent_ctx: ToolContext,
    *,
    goal: str,
    max_agents: int = 4,
    execution_mode: str = "sequential",
    max_steps_each: int = 3,
    model_call_budget_each: int = 4,
    roles: list[str] | None = None,
    dry_run: bool = True,
) -> str:
    """Run bounded local role workers with separate threads, contexts, and budgets."""

    execution_mode = (
        execution_mode if execution_mode in {"sequential", "parallel"} else "sequential"
    )
    specs = _select_roles(
        max_agents,
        roles,
        max_steps_each=max_steps_each,
        model_call_budget_each=model_call_budget_each,
    )
    run_id = uuid.uuid4().hex[:12]
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    note = ""
    actual_mode = execution_mode
    allow_parallel_writes = bool(
        getattr(parent_ctx.config, "multi_agent_allow_parallel_writes", False)
    )
    if (
        execution_mode == "parallel"
        and any(spec.write_capable for spec in specs)
        and not allow_parallel_writes
    ):
        actual_mode = "sequential"
        note = "Parallel requested but write-capable roles were selected; downgraded to sequential to avoid edit conflicts."

    if not dry_run and not parent_ctx.confirm(
        "Gerçek multi-agent yürütme başlatılacak. Her worker kendi thread/step/tool budget sınırında çalışacak."
    ):
        return "Kullanıcı run_multi_agent_work işlemini reddetti."

    mailbox = AgentMailbox()
    mailbox.post("parent", "all", f"Run goal: {goal}", kind="assignment")
    workspace_hint = (
        "sandbox-copy"
        if parent_ctx.config.sandbox_mode in {"docker", "podman"}
        and parent_ctx.config.sandbox_workspace_mode == "copy"
        else "shared-root"
    )
    threads = [_make_thread(run_id, spec, goal, workspace_hint=workspace_hint) for spec in specs]
    thread_by_role = {thread.role: thread for thread in threads}
    results: list[RoleAgentResult] = []
    if actual_mode == "parallel":
        with ThreadPoolExecutor(max_workers=len(specs)) as pool:
            futures = [
                pool.submit(
                    _run_one_role_worker,
                    parent_ctx=parent_ctx,
                    goal=goal,
                    spec=spec,
                    execution_mode=actual_mode,
                    dry_run=dry_run,
                    thread=thread_by_role[spec.role],
                    mailbox=mailbox,
                )
                for spec in specs
            ]
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: [spec.role for spec in specs].index(item.role))
    else:
        for spec in specs:
            results.append(
                _run_one_role_worker(
                    parent_ctx=parent_ctx,
                    goal=goal,
                    spec=spec,
                    execution_mode=actual_mode,
                    dry_run=dry_run,
                    thread=thread_by_role[spec.role],
                    mailbox=mailbox,
                )
            )

    merged = AgentResultMerger.merge(
        goal,
        results,
        mailbox,
        max_chars=getattr(parent_ctx.config, "multi_agent_result_max_chars", 12000),
    )
    payload = {
        "run_id": run_id,
        "created_at": started_at,
        "goal": goal,
        "requested_execution_mode": execution_mode,
        "actual_execution_mode": actual_mode,
        "dry_run": dry_run,
        "note": note,
        "thread_model": {
            "threads_are_role_scoped": True,
            "mailbox_enabled": True,
            "deterministic_result_merger": True,
            "allow_parallel_writes": allow_parallel_writes,
        },
        "roles": [spec.to_dict() for spec in specs],
        "threads": [
            thread.to_dict(
                include_messages=True,
                max_messages=getattr(parent_ctx.config, "multi_agent_thread_max_messages", 12),
                max_chars=getattr(parent_ctx.config, "multi_agent_result_max_chars", 12000),
            )
            for thread in threads
        ],
        "mailbox": mailbox.to_dict(
            limit=getattr(parent_ctx.config, "multi_agent_thread_max_messages", 12)
            * max(1, len(threads)),
            max_chars=getattr(parent_ctx.config, "multi_agent_result_max_chars", 12000),
        ),
        "results": [result.to_dict() for result in results],
        "merged_result": merged,
        "summary": {
            "workers": len(results),
            "finished": sum(1 for result in results if result.status == "finished"),
            "actions": sum(len(result.actions) for result in results),
            "threads": len(threads),
            "mailbox_messages": len(mailbox.messages),
        },
    }
    if dry_run:
        return "DRY-RUN: multi-agent run not saved.\n" + to_pretty_json(payload)
    _write_multi_agent_run(parent_ctx.config.root, payload)
    location = _multi_agent_run_path(parent_ctx.config.root, run_id).relative_to(
        parent_ctx.config.root
    )
    return "Real multi-agent run completed:\n" + to_pretty_json(
        {**payload, "saved_to": str(location)}
    )


def run_subagent_threads(
    parent_ctx: ToolContext,
    *,
    goal: str,
    max_agents: int = 4,
    execution_mode: str = "sequential",
    max_steps_each: int = 3,
    model_call_budget_each: int = 4,
    roles: list[str] | None = None,
    dry_run: bool = True,
) -> str:
    """Alias with clearer Codex-style terminology for thread-based subagent execution."""

    return run_multi_agent_work(
        parent_ctx,
        goal=goal,
        max_agents=max_agents,
        execution_mode=execution_mode,
        max_steps_each=max_steps_each,
        model_call_budget_each=model_call_budget_each,
        roles=roles,
        dry_run=dry_run,
    ).replace("multi-agent run", "subagent thread run", 1)


def read_multi_agent_run(
    root: Path, run_id: str, *, include_observations: bool = False, max_chars: int = 40000
) -> str:
    """Read a saved multi-agent run transcript by run id."""

    clean_run_id = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in {"_", "-"})
    if not clean_run_id:
        return "Invalid run_id."
    path = _multi_agent_run_path(root, clean_run_id)
    if not path.exists():
        return f"Multi-agent run not found: {clean_run_id}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"Could not read multi-agent run {clean_run_id}: {exc}"
    if not include_observations:
        for result in data.get("results", []) if isinstance(data.get("results"), list) else []:
            if isinstance(result, dict):
                result.pop("observations", None)
        for thread in data.get("threads", []) if isinstance(data.get("threads"), list) else []:
            if isinstance(thread, dict):
                thread["messages"] = [
                    msg
                    for msg in thread.get("messages", [])
                    if isinstance(msg, dict) and msg.get("kind") in {"assignment", "result"}
                ]
    return "Saved multi-agent run:\n" + truncate(redact_secret(to_pretty_json(data)), max_chars)


def _batch_log_path(root: Path) -> Path:
    return (root / BATCH_LOG).resolve()


def run_task_batch(root: Path, tasks: list[str], max_tasks: int = 5, dry_run: bool = True) -> str:
    """Record a legacy bounded sequential task batch for review/execution tracking."""

    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list")
    max_tasks = max(1, min(max_tasks, 20))
    selected = [str(task).strip() for task in tasks if str(task).strip()][:max_tasks]
    batch = {
        "batch_id": uuid.uuid4().hex[:12],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": dry_run,
        "status": "planned" if dry_run else "queued",
        "tasks": [
            {
                "task_id": f"task-{idx + 1}",
                "title": task,
                "status": "planned" if dry_run else "todo",
            }
            for idx, task in enumerate(selected)
        ],
        "note": (
            "Legacy task-batch bookkeeping only. Use run_subagent_threads/run_multi_agent_work for "
            "bounded role workers with separate threads, contexts, and budgets."
        ),
    }
    path = _batch_log_path(root)
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(batch, ensure_ascii=False) + "\n")
    rendered = to_pretty_json(batch)
    prefix = (
        "DRY-RUN: task batch not saved"
        if dry_run
        else f"Task batch saved: {path.relative_to(root)}"
    )
    return prefix + "\n\n" + rendered


def list_agent_batches(root: Path, limit: int = 10) -> str:
    """List recent recorded task batches."""

    path = _batch_log_path(root)
    if not path.exists():
        return "No agent batch log found."
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return "Recent agent batches:\n" + to_pretty_json(rows[-limit:])


def list_multi_agent_runs(root: Path, limit: int = 10) -> str:
    """List recent real multi-agent run summaries."""

    base = (root / MULTI_AGENT_RUNS_DIR).resolve()
    if not base.exists():
        return "No real multi-agent runs found."
    rows: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json"), key=lambda item: item.stat().st_mtime):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append(
            {
                "run_id": data.get("run_id"),
                "created_at": data.get("created_at"),
                "goal": data.get("goal"),
                "actual_execution_mode": data.get("actual_execution_mode"),
                "summary": data.get("summary"),
                "merged_status": (data.get("merged_result") or {}).get("status")
                if isinstance(data.get("merged_result"), dict)
                else None,
                "file": str(path.relative_to(root)),
            }
        )
    return "Recent real multi-agent runs:\n" + to_pretty_json(rows[-limit:])
