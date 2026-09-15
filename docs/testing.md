# Testing and CI

MiniCodex uses a marker-aware test matrix plus release quality gates.

## Local targeted tests

```bash
PYTHONPATH=src pytest -q tests/test_context_layer_v30.py
PYTHONPATH=src pytest -q tests/test_security_product_layer_v44.py
PYTHONPATH=src pytest -q tests/test_quality_gate_layer_v45.py
```

## Marker-aware matrix

```bash
python scripts/run_test_matrix.py --group fast --json
python scripts/run_test_matrix.py --group unit --json
python scripts/run_test_matrix.py --group integration --json
python scripts/run_test_matrix.py --group subprocess --json
python scripts/run_test_matrix.py --group sandbox --json
python scripts/run_test_matrix.py --group slow --json
python scripts/run_test_matrix.py --group all --json
```

`--final-readiness` uses the bounded `fast` group by default to avoid monolithic pytest timeouts in local checks.

## Release quality commands

The release CI should install `.[dev]` and run bounded, marker-aware gates instead of one monolithic coverage process:

```bash
ruff check .
ruff format --check .
mypy src/minicodex_agent
python scripts/run_test_matrix.py --group fast --json
python scripts/run_test_matrix.py --group integration --json
python scripts/run_test_matrix.py --group subprocess --json
python scripts/run_test_matrix.py --group sandbox --json
python scripts/run_coverage_gate.py --group all --fail-under 85 --json
python -m build
twine check dist/*
```

Coverage must include every marker group because the 85% threshold represents the complete release suite. Per-file timeouts keep slow, subprocess, and sandbox tests bounded.

Do not use a single package-wide coverage process as a required gate for this repository; the bounded coverage script aggregates coverage while keeping each test file under a timeout. These tools may be unavailable in a constrained local environment. In that case, `--final-readiness` reports missing tools as warnings unless `--final-readiness-run-verification-tools` is used and installed tools fail.

## Final readiness

```bash
minicodex --final-readiness --root .
minicodex --final-readiness --final-readiness-run-verification-tools --root .
```

Full verification runs Python lint, type checking, build, package validation, and file-level
coverage in an isolated temporary project copy. The default per-command timeout is 1200 seconds;
override it with `--final-readiness-verification-timeout` for slower environments.

Readiness includes:

- version alignment
- generated artifact check
- Python syntax check
- tool registry alignment
- documentation presence, including README-linked quickstart/testing docs
- documented MiniCodex CLI example parser validation
- security audit gate
- verification tool availability/results
- bounded test matrix result
- CLI smoke test

## Security test fixtures

Intentional unsafe examples must be isolated under:

```text
tests/fixtures/unsafe_examples/
```

or marked with:

```text
# minicodex-security-test-fixture
```

This prevents fake `shell=True`, `eval`, fake tokens, and malicious instruction samples from being reported as real vulnerabilities.

## Cleaning generated artifacts

```bash
minicodex --clean-generated-artifacts --clean-generated-artifacts-dry-run --root .
minicodex --clean-generated-artifacts --root .
```

## Zip-based release manifest

Use this when local test runs have created caches in the working tree but you want to validate the actual archive:

```bash
minicodex --release-package-manifest --from-zip dist/release.zip --root .
```


The zip manifest is intentionally artifact-sourced. In this mode, version, documentation list, source module counts, test counts, and generated-artifact findings come from zip members only; `root` is only used to resolve a relative zip path.
