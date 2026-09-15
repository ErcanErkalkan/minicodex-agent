# Security model

MiniCodex assumes local repositories can be untrusted. The security layer is designed to stop common agent-specific risks before a model or tool follows malicious instructions.

## Repo-local instruction scanning

Files such as these are scanned before they are included in the context pack:

- `AGENTS.md`
- `.minicodex/instructions.md`
- `.minicodex/AGENTS.md`
- repo skill files under `.minicodex/skills/*/SKILL.md`
- local plugin manifests under `.minicodex/plugins/*.json`

High/critical findings such as “ignore previous instructions”, safety bypass requests, environment dumping, network exfiltration, or secret leakage requests cause the raw instruction content to be omitted from the prompt. The context pack records the instruction with `trust_level="blocked_by_security_scan"`.

Run the scan directly:

```bash
minicodex --scan-repo-instructions --root .
```

## Security audit

```bash
minicodex --security-audit --root .
```

The audit includes:

- secret scanning
- built-in SAST fallback
- repo-instruction scan
- plugin permission validation
- workspace trust report
- dependency audit command planning

External scanners are not run by default. They are planned unless the tool is installed and the user explicitly allows execution/network access.

## Fixture allowlist

Intentional unsafe examples should live under:

```text
tests/fixtures/unsafe_examples/
```

or include this marker near the top of the file:

```text
# minicodex-security-test-fixture
```

The built-in security audit skips these files so fake `eval`, `shell=True`, fake API keys, or malicious `AGENTS.md` samples do not appear as real product vulnerabilities.

## Workspace trust

For unknown repositories, prefer:

```bash
minicodex "inspect safely" --root . --untrusted-workspace --approval ask --sandbox-mode docker --sandbox-network none
```

The prompt and tool layer still treat repo content as data, not authority. Runtime tool gates, user goals, and system policy take priority over repository instructions.
