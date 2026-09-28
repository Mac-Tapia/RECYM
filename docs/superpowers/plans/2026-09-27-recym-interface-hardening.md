# RECYM Interface Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SPA launch path, feeder/file identity gates, API-to-CYMDIST child isolation, and frontend contracts fail closed and verifiable with real CA101 canaries.

**Architecture:** Preserve the React/FastAPI/Flask bridge, but move every CYMDIST-facing §7 launch invoked by React through the existing isolated job worker. Add structured feeder input capability and strict Excel/config identity validation at the backend boundary, then surface it in the SPA. Keep read-only real CYMDIST tests separate from model-writing operations.

**Tech Stack:** Python 3.7, FastAPI, Flask, CymPy/CYMDIST 9.2 r1, React 19, TypeScript 5.7, Vite 6, unittest.

**Spec:** User-approved diagnostic and plan in the 2026-09-27 conversation; no separate repository spec exists.

## Global Constraints

- Preserve existing user changes in `src/core/feeder_context.py`, `src/core/new_feeder.py`, `src/pipeline/apply_clientes_to_cymdist.py`, and feeder input folders.
- Do not save or mutate a CYMDIST study during verification; connection probes must close with `save=False`.
- A mismatched feeder/NetworkID is an error, not a warning or inferred match.
- Do not claim browser-click E2E unless an actual browser controller runs it.
- Real worker evidence must report native crash codes rather than hiding them.

## Review Focus

- Missing feeder Excel files must block only Excel-dependent operations and explain which files are absent.
- Excel NetworkID mismatches must return `ok=false` through both CLI and HTTP.
- Unknown job actions and unapproved legacy paths must remain rejected.
- A native worker crash after producing JSON must remain visible while the API survives.
- Production launch must target the real launcher and fail fast if prerequisites are missing.

---

### Task 1: Production launcher, version contract, and TypeScript gate

**Files:**
- Modify: `scripts/20_demand_ui_production.bat`
- Modify: `src/ui/demand_app.py`
- Modify: `web/package.json`
- Modify: `web/src/pages/Step2CalidadTablero.tsx`
- Modify: `web/src/pages/Step6Informes.tsx`
- Test: `tests/test_interface_hardening.py`

**Interfaces:** Produces one UI version contract and a runnable production launcher.

- [x] Write and run failing version/launcher contract tests and `tsc --noEmit`.
- [x] Point production to `20_demand_ui.bat`, align versions, and correct unsafe TypeScript narrowing.
- [x] Run focused tests, TypeScript, and isolated Vite build.

### Task 2: Strict feeder input capability and identity validation

**Files:**
- Modify: `src/pipeline/validate_inputs.py`
- Modify: `src/core/feeder_context.py`
- Modify: `src/ui/demand_app.py`
- Modify: `web/src/pages/Step1Contexto.tsx`
- Modify: `web/src/pages/Step7Suite.tsx`
- Test: `tests/test_interface_hardening.py`

**Interfaces:** Produces `inspect_feeder_inputs(settings) -> dict` and feeder catalog fields `inputs_ready`, `input_errors`, and `operational`.

- [x] Write failing tests for CA101 mismatch, AL104 missing files, and structured catalog capability.
- [x] Implement fail-closed validation and expose capability in `/api/contexto/archivos`.
- [x] Surface readiness in §1 and disable Excel-dependent §7 actions when inputs are invalid.
- [x] Run focused and TypeScript tests; full regression is tracked in Task 4.

### Task 3: Isolate all CYMDIST-facing §7 launches

**Files:**
- Modify: `src/core/cympy_isolation.py`
- Modify: `src/api_app/jobs.py`
- Modify: `web/src/pages/Step7Suite.tsx`
- Test: `tests/test_interface_hardening.py`

**Interfaces:** Produces allow-listed job actions `suite_conexion`, `suite_inventario_cargas`, `suite_sync_equipos`, `suite_fix_default`, `suite_export_ascii`, `suite_pipeline`, and `optimizacion_*`.

- [x] Write failing tests proving each action is isolated and unknown legacy dispatch is rejected.
- [x] Dispatch exact allow-listed Flask routes inside the child worker and switch React to `runJob`.
- [x] Run contract tests and a real read-only `suite_conexion` worker canary.

### Task 4: Worker teardown containment and final canary

**Files:**
- Modify: `src/api_app/job_worker_cli.py`
- Test: `tests/test_interface_hardening.py`

**Interfaces:** Produces durable result writing followed by immediate process termination, with parent-side crash metadata preserved.

- [x] Write a subprocess test for durable JSON and exit code zero.
- [x] Move worker exit immediately after flush/fsync of the result.
- [x] Run a real CA101 diagnostic canary, SSE check, API survival check, and full regression suite.
