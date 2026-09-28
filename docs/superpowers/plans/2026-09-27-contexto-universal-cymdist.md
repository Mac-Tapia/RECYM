# Universal Asynchronous CYMDIST Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir seleccionar una MDB y un estudio desde cualquier carpeta, descubrir de forma asíncrona las redes reales de esa MDB y garantizar que §§1–7 y el informe operen con la misma identidad explícita.

**Architecture:** Un selector nativo local entrega rutas canónicas; un job CymPy aislado descubre redes sin heredar ni persistir el contexto activo; 1.1 valida y persiste las cuatro identidades. El cliente conserva MDB, estudio y alimentador como estados independientes, y cada resultado técnico o de informe lleva una huella de contexto verificable antes de ser reutilizado o servido.

**Tech Stack:** Python 3.7.9 win32, FastAPI 0.95, Flask 2.2, CymPy/CYMDIST, React 19, TypeScript 5.7, Vite 6, Vitest 3.2, unittest.

**Spec:** `docs/superpowers/specs/2026-09-27-contexto-universal-cymdist-design.md`

## Global Constraints

- Windows es el único sistema soportado para `Examinar…`; fuera de Windows se devuelve `PICKER_UNAVAILABLE`.
- MDB y estudio se usan en su ruta original: no se copian ni suben al repositorio.
- Extensiones admitidas: `.mdb` para base y `.zxst`, `.sxst`, `.zsxst`, `.xst` para estudio.
- MDB, estudio y alimentador son independientes; no se infiere alimentador desde el nombre del estudio.
- Toda operación §§2–7 recibe `database_mdb`, `study_path`, `feeder_id` y `network_id` explícitos cuando el contexto ya está completo.
- El selector y el descubrimiento tienen timeout de 600 s; el descubrimiento corre en el worker aislado y no guarda el estudio.
- Examinar y descubrir no modifican `config/settings.json` ni crean configuraciones de alimentador; solo 1.1 persiste.
- Los archivos del usuario ya modificados o no versionados se preservan; cada commit incluye únicamente los archivos de su tarea.
- La prueba real CYMDIST es un canario de solo lectura para descubrimiento y no autoriza guardar/modificar el estudio.

## Review Focus

- Dos MDB con igual nombre en carpetas diferentes deben producir claves y catálogos distintos; Task 3 lo fija con `test_same_basename_databases_do_not_share_cache`.
- Una respuesta de descubrimiento antigua no debe reemplazar la MDB elegida después; Task 5 lo fija con `ignores_out_of_order_discovery_result`.
- Cancelar `OpenFileDialog` debe conservar las tres selecciones; Task 5 lo fija con `cancelled_picker_preserves_context`.
- Un LoadFlow o informe de otro contexto no debe satisfacer el gate ni poder cerrarse; Task 7 lo fija con `test_report_rejects_foreign_context_artifacts`.
- Un proceso CymPy que termina con Access Violation después de escribir un resultado útil debe conservar el resultado y mantener viva la API; Task 8 lo comprueba con el canario real y `/health`.

---

## File Map

- Create `src/core/context_identity.py`: normalización, comparación y huella de las cuatro identidades.
- Create `src/core/windows_file_picker.py`: diálogo Windows seguro y validación posterior.
- Create `src/api_app/routers/context.py`: selector, catálogo rápido y aplicación estricta del contexto.
- Modify `src/api_app/main.py`: registrar el router nativo antes del puente Flask.
- Modify `src/api_app/jobs.py`: acción `contexto_descubrir_redes` sin contexto heredado ni persistencia.
- Modify `src/core/cympy_isolation.py`: aislar la nueva acción.
- Modify `src/pipeline/model_quality_gate.py`: claves de caché por ruta canónica y descubrimiento sin escritura en disco.
- Modify `src/core/feeder_context.py`: aplicación estricta MDB/red y eliminación de inferencias en el flujo nuevo.
- Modify `src/ui/demand_app.py`: compatibilidad legacy y uso del contrato estricto compartido.
- Create `web/src/context/selection.ts`: reductor puro para cambios independientes y control de secuencia.
- Modify `web/src/api/client.ts`: `runDetachedJob` y propagación explícita del contexto completo.
- Modify `web/src/state/feeder.tsx`: estado completo y huella/versión de selección.
- Modify `web/src/pages/Step1Contexto.tsx`: botones Examinar, progreso y descubrimiento asíncrono.
- Modify `web/src/pages/Step2CalidadTablero.tsx` through `Step7Suite.tsx`: llamadas con contrato completo y mensajes de identidad.
- Modify `src/pipeline/run_load_flow.py`: guardar identidad y huella con cada resultado.
- Modify `src/pipeline/assemble_informe.py`, `fill_informe.py`, `deliver_informe.py`: procedencia, gate y copias auditables por contexto.
- Modify `web/src/pages/Step6Informes.tsx`: mostrar/verificar contexto del informe y descargar con autenticación/contexto.
- Create focused tests under `tests/` and `web/src/context/selection.test.ts`.
- Modify `docs/API_CONTRATO_UI.md`, `docs/VALIDACION_INTEGRAL.md`: contrato y evidencia operativa.

### Task 1: Canonical context identity

**Files:**
- Create: `src/core/context_identity.py`
- Create: `tests/test_context_identity.py`

**Interfaces:**
- Consumes: rutas Windows y los campos `database_mdb`, `study_path`/`ui_study_path`, `feeder_id`, `network_id`.
- Produces: `canonical_file_path(path) -> str`, `build_context_identity(settings_or_payload, require_complete=False) -> dict`, `context_fingerprint(identity) -> str`, `assert_same_context(expected, actual) -> None`.

- [ ] **Step 1: Write failing identity tests**

  Add `test_paths_are_casefolded_without_collapsing_parent_directory`, `test_fingerprint_changes_for_same_basename_in_other_folder`, `test_complete_identity_requires_four_fields`, and `test_identity_mismatch_names_the_different_fields`. Assert a 16-character lowercase SHA-256 prefix and structured error code `CONTEXT_IDENTITY_MISMATCH`.

- [ ] **Step 2: Run the focused test and confirm it fails**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_identity.py" -v`

  Expected: FAIL because `core.context_identity` does not exist.

- [ ] **Step 3: Implement the identity primitives**

  Canonicalize with `os.path.abspath`, `os.path.realpath`, `os.path.normpath`, and `os.path.normcase`; hash the stable JSON object with sorted keys. Preserve the display paths separately from normalized comparison values.

- [ ] **Step 4: Run the focused test**

  Expected: all tests from `test_context_identity.py` PASS under Python 3.7.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/core/context_identity.py tests/test_context_identity.py
  git commit -m "Add canonical CYMDIST context identity"
  ```

### Task 2: Native Windows file selector and API

**Files:**
- Create: `src/core/windows_file_picker.py`
- Create: `src/api_app/routers/context.py`
- Modify: `src/api_app/main.py:44-122`
- Modify: `src/api_app/security.py`
- Create: `tests/test_context_picker.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: `canonical_file_path` from Task 1 and existing loopback/API-key helpers.
- Produces: `pick_context_file(kind, initial_dir=None, timeout=600, runner=None) -> dict` and `POST /api/contexto/examinar`.

- [ ] **Step 1: Write failing selector unit tests**

  Cover `database`/`study`, cancellation, nonexistent file, wrong extension, timeout and PowerShell failure. Inject a fake `runner` so tests never open a GUI. Assert the exact codes `INVALID_PICKER_KIND`, `PICKER_TIMEOUT`, `FILE_NOT_FOUND`, `INVALID_FILE_EXTENSION`, `STUDY_FILE_INVALID`, and `PICKER_UNAVAILABLE`.

- [ ] **Step 2: Run the selector tests and confirm failure**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_picker.py" -v`

- [ ] **Step 3: Implement `pick_context_file`**

  Launch a fixed PowerShell STA script using `subprocess.run([...], timeout=600)` and `System.Windows.Forms.OpenFileDialog`. Pass `kind` and `initial_dir` through environment variables, use one process-wide lock, parse one JSON result, and validate the selected path after the process exits.

- [ ] **Step 4: Add the FastAPI route**

  Define Pydantic input `ContextPickRequest(kind: str, initial_dir: Optional[str])`; enforce loopback in the handler in addition to normal authentication; call the selector through `run_in_threadpool`; register the router before `bridge_flask_api`.

- [ ] **Step 5: Add API contract tests**

  Mock `pick_context_file` and assert JSON shape, cancellation as HTTP 200, invalid type as HTTP 400, non-loopback as HTTP 403, and no file contents in the response.

- [ ] **Step 6: Run unit/API regression tests**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_picker.py" -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_api_contract.py" -v`

- [ ] **Step 7: Commit**

  ```powershell
  git add src/core/windows_file_picker.py src/api_app/routers/context.py src/api_app/main.py src/api_app/security.py tests/test_context_picker.py tests/test_api_contract.py
  git commit -m "Add local Windows context file picker"
  ```

### Task 3: Path-keyed asynchronous MDB discovery

**Files:**
- Modify: `src/pipeline/model_quality_gate.py:28-333`
- Modify: `src/api_app/jobs.py:97-307,743-765`
- Modify: `src/core/cympy_isolation.py:26-54`
- Create: `tests/test_context_discovery.py`
- Modify: `tests/test_interface_hardening.py`

**Interfaces:**
- Consumes: canonical MDB identity from Task 1 and `list_bd_networks` CymPy access.
- Produces: `list_bd_networks(settings=None, force=False, cache_ttl_sec=300, soft=False, persist_cache=True) -> dict` and isolated action `contexto_descubrir_redes`.

- [ ] **Step 1: Write failing discovery/cache tests**

  Add `test_same_basename_databases_do_not_share_cache`, `test_detached_discovery_does_not_write_settings_or_catalog`, `test_discovery_rejects_non_mdb`, `test_no_networks_is_structured_error`, and `test_discovery_action_is_isolated`. Mock CymPy and file writes; assert `source == "cympy"`, requested canonical path echoed in `database_mdb`, and feeders derived only from returned networks.

- [ ] **Step 2: Run and observe the current basename-cache collision**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_discovery.py" -v`

- [ ] **Step 3: Key catalogs by canonical MDB path**

  Add a path hash to memory/disk cache metadata and validate both connection name and canonical path on reads. When `persist_cache=False`, do not call `_save_networks_disk` and do not update the shared memory cache.

- [ ] **Step 4: Implement `contexto_descubrir_redes`**

  Validate one explicit `.mdb`; build ephemeral settings without `apply_context_selection` or `load_settings(..., persist_synth=True)`; call `list_bd_networks(..., force=True, soft=False, persist_cache=False)`; normalize/sort `{feeder_id, network_id, label}`; return `NO_NETWORKS_FOUND` when empty.

- [ ] **Step 5: Add the action to `ISOLATED_ACTIONS` and set 600 s timeout**

  Ensure the parent reports timeout, crash code and useful worker result using the existing isolation contract.

- [ ] **Step 6: Run focused and isolation regressions**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_discovery.py" -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_interface_hardening.py" -v`

- [ ] **Step 7: Commit**

  ```powershell
  git add src/pipeline/model_quality_gate.py src/api_app/jobs.py src/core/cympy_isolation.py tests/test_context_discovery.py tests/test_interface_hardening.py
  git commit -m "Discover MDB networks in isolated path-keyed jobs"
  ```

### Task 4: Strict catalog and 1.1 identity gate

**Files:**
- Modify: `src/api_app/routers/context.py`
- Modify: `src/core/feeder_context.py:266-371,412-589,720-805`
- Modify: `src/ui/demand_app.py:3728-3798,4024-4285`
- Create: `tests/test_context_api.py`
- Modify: `tests/test_interface_hardening.py`

**Interfaces:**
- Consumes: discovery response `{database_mdb, networks, feeders}` and Task 1 identity helpers.
- Produces: fast `GET /api/contexto/archivos`, strict `POST /api/contexto/aplicar`, and `apply_context_selection(..., network_id=None, allowed_networks=None, strict=False) -> dict`.

- [ ] **Step 1: Write failing catalog/application tests**

  Assert external current paths are added to quick access, entries deduplicate by canonical path, duplicate basenames receive parent labels, the quick catalog never calls CymPy, and a selected `feeder_id`/`network_id` pair absent from the discovered MDB fails with `CONTEXT_IDENTITY_MISMATCH`.

- [ ] **Step 2: Add explicit-precedence regressions**

  Cover PE104 + CA101V2, changing only study, changing only feeder, and changing MDB. Assert 1.1 returns exactly the requested MDB, UI study, feeder and network; no family fallback may replace an explicit field.

- [ ] **Step 3: Implement the quick catalog**

  List configured directories without `list_bd_networks`; append selected external MDB/study; deduplicate by normalized path. For a selected MDB accept feeders only from the completed discovery response supplied to the UI, never orphan studies.

- [ ] **Step 4: Implement strict application**

  Require all four fields for the new route, validate file existence/extensions, verify feeder/network membership for that canonical MDB, then persist once. Retain the old optional behavior only for legacy callers using `strict=False`.

- [ ] **Step 5: Make the Flask compatibility routes delegate to shared core logic**

  Remove inline refresh/CymPy discovery from `/api/contexto/archivos`; ensure `/api/contexto/aplicar` accepts `network_id` and returns structured identity errors. Do not duplicate validation rules between FastAPI and Flask.

- [ ] **Step 6: Run context tests**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_api.py" -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_interface_hardening.py" -v`

- [ ] **Step 7: Commit**

  ```powershell
  git add src/api_app/routers/context.py src/core/feeder_context.py src/ui/demand_app.py tests/test_context_api.py tests/test_interface_hardening.py
  git commit -m "Enforce strict independent context selection"
  ```

### Task 5: React independent selection and stale-response protection

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Create: `web/src/context/selection.ts`
- Create: `web/src/context/selection.test.ts`
- Modify: `web/src/api/client.ts:1-230`
- Modify: `web/src/state/feeder.tsx:1-73`
- Modify: `web/src/pages/Step1Contexto.tsx:156-430,769-1000,1110-1210`

**Interfaces:**
- Consumes: picker API and isolated discovery action from Tasks 2–3.
- Produces: `runDetachedJob(action, payload, onUpdate?) -> Promise<Json>`, `beginDatabaseSelection(state, path)`, and `acceptDiscoveryResult(state, requestId, result)`.

- [ ] **Step 1: Add Vitest 3.2.4 and failing pure-state tests**

  Test `changing_database_keeps_study_and_clears_feeder`, `changing_study_keeps_database_and_feeder`, `changing_feeder_keeps_database_and_study`, `cancelled_picker_preserves_context`, and `ignores_out_of_order_discovery_result`.

- [ ] **Step 2: Run tests and confirm failure**

  Run: `npm --prefix web test -- --run`

- [ ] **Step 3: Implement `runDetachedJob`**

  Share polling/SSE mechanics with `runJob`, but send exactly the supplied payload and omit active context injection in both job envelope and JSON body. Add a unit-visible payload builder so the test asserts no old feeder/study is present.

- [ ] **Step 4: Implement the selection reducer**

  Store a monotonic `databaseRequestId`; accept discovery only when its id and canonical MDB match the current selection. A picker cancellation returns the unchanged state.

- [ ] **Step 5: Wire `Step1Contexto`**

  Add `Examinar…` buttons, full paths, progress and actionable errors. MDB browse calls picker then detached discovery; study browse only changes study. Send all four explicit fields, including `network_id`, to 1.1 and reject any response whose identity differs.

- [ ] **Step 6: Remove old synchronous discovery behavior**

  Delete the two-call `loadFiles(... refresh false/true)` path and any basename-based `studyStillThere` matching. Keep configured directories only as quick-access dropdowns.

- [ ] **Step 7: Run frontend tests/type/build**

  Run: `npm --prefix web test -- --run`

  Run: `web\node_modules\.bin\tsc.cmd -p web\tsconfig.json --noEmit`

  Run: `npm --prefix web run build`

- [ ] **Step 8: Commit**

  ```powershell
  git add web/package.json web/package-lock.json web/src/context/selection.ts web/src/context/selection.test.ts web/src/api/client.ts web/src/state/feeder.tsx web/src/pages/Step1Contexto.tsx
  git commit -m "Add independent asynchronous context selection"
  ```

### Task 6: Verify and harden module wiring for §§2–7

**Files:**
- Modify: `web/src/pages/Step2CalidadTablero.tsx`
- Modify: `web/src/pages/Step3Clientes.tsx`
- Modify: `web/src/pages/Step4SpotLoad.tsx`
- Modify: `web/src/pages/Step5Flujos.tsx`
- Modify: `web/src/pages/Step6Informes.tsx`
- Modify: `web/src/pages/Step7Suite.tsx`
- Modify: `src/api_app/jobs.py`
- Create: `tests/test_context_module_wiring.py`

**Interfaces:**
- Consumes: active four-field context from Task 5 and `_run_action` settings overlay.
- Produces: a fail-closed context contract shared by every state-changing or CYMDIST-backed action.

- [ ] **Step 1: Write a table-driven backend wiring test**

  Enumerate every CYMDIST action used by §§2–7. For each, assert explicit request fields win over persisted settings and the result echoes the same `context_fingerprint`. Missing or inconsistent context must fail before the pipeline function is called.

- [ ] **Step 2: Write a SPA call-site contract test**

  Assert Step 2 diagnostics, Step 3 clientes/distribución, Step 4 SpotLoad, Step 5 flows, Step 6 report operations and Step 7 suite jobs all use `api`/`runJob` and never raw `fetch` for protected operations. FormData calls must still carry context headers.

- [ ] **Step 3: Centralize job context construction**

  Add `_settings_from_explicit_context(payload, feeder) -> dict` in `src/api_app/jobs.py`. It must not call `apply_context_selection(..., persist=True)` for ordinary jobs; persistence remains exclusive to 1.1.

- [ ] **Step 4: Update each page to show the execution identity**

  Before launch show feeder/network and MDB/study basename; after completion compare `context_fingerprint`. On mismatch discard the result and display `CONTEXT_IDENTITY_MISMATCH`.

- [ ] **Step 5: Run wiring and full Python regressions**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_context_module_wiring.py" -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

- [ ] **Step 6: Run TypeScript and production build**

  Run: `web\node_modules\.bin\tsc.cmd -p web\tsconfig.json --noEmit`

  Run: `npm --prefix web run build`

- [ ] **Step 7: Commit**

  ```powershell
  git add web/src/pages/Step2CalidadTablero.tsx web/src/pages/Step3Clientes.tsx web/src/pages/Step4SpotLoad.tsx web/src/pages/Step5Flujos.tsx web/src/pages/Step6Informes.tsx web/src/pages/Step7Suite.tsx src/api_app/jobs.py tests/test_context_module_wiring.py
  git commit -m "Propagate strict context through all interface modules"
  ```

### Task 7: Context-correct reports and auditable provenance

**Files:**
- Modify: `src/pipeline/run_load_flow.py:101-339`
- Modify: `src/pipeline/assemble_informe.py:67-155`
- Modify: `src/pipeline/fill_informe.py:1910-2160,2330-2486`
- Modify: `src/pipeline/deliver_informe.py:37-171`
- Modify: `src/ui/demand_app.py:6037-6325`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/pages/Step6Informes.tsx`
- Create: `tests/test_informe_context.py`

**Interfaces:**
- Consumes: `build_context_identity`, `context_fingerprint`, LoadFlow JSON and current request context.
- Produces: context-tagged LoadFlow/results/manifests, per-context audit copies, `assert_report_context(settings, manifest)`, and authenticated contextual downloads.

- [ ] **Step 1: Write failing report provenance tests**

  Add `test_loadflow_records_four_field_identity`, `test_report_rejects_foreign_context_artifacts`, `test_report_same_feeder_different_mdb_is_not_reused`, `test_close_requires_matching_fill_manifest`, and `test_preview_returns_context_identity`. Use temporary files only.

- [ ] **Step 2: Run and confirm the current shared-`doc/` behavior fails**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_informe_context.py" -v`

- [ ] **Step 3: Tag LoadFlow outputs**

  Add `context_identity` and `context_fingerprint` before writing `loadflow_result.json` and scenario files. Fail before report generation if an existing scenario lacks or mismatches the current fingerprint; rerun only when `ensure_lf=True`.

- [ ] **Step 4: Make report manifests context-verifiable**

  Add the identity/fingerprint to assemble, fill, OCR-review and closure manifests. Store immutable audit copies under `<output_dir>/informe/<context_fingerprint>/`; preserve `doc/` as the active compatibility mirror only.

- [ ] **Step 5: Gate preview, download and close**

  Resolve context from request headers/body, compare it with `fill_manifest.json`, and return HTTP 409 `CONTEXT_IDENTITY_MISMATCH` instead of serving stale documents/images. `confirm_informe_entrega` must include the fingerprint and hashes of the delivered DOCX/XLSX/PDF.

- [ ] **Step 6: Make Step 6 visibly context-safe**

  Display MDB, study, feeder, network and fingerprint from preview. Add `downloadApiFile(path)` to fetch blobs with API key and context headers instead of plain anchor navigation; disable close on any mismatch.

- [ ] **Step 7: Run report and complete regression suites**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_informe_context.py" -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

  Run: `npm --prefix web test -- --run`

  Run: `npm --prefix web run build`

- [ ] **Step 8: Commit**

  ```powershell
  git add src/pipeline/run_load_flow.py src/pipeline/assemble_informe.py src/pipeline/fill_informe.py src/pipeline/deliver_informe.py src/ui/demand_app.py web/src/api/client.ts web/src/pages/Step6Informes.tsx tests/test_informe_context.py
  git commit -m "Bind reports to verified CYMDIST context"
  ```

### Task 8: Real integration canary, operational report and documentation

**Files:**
- Modify: `docs/API_CONTRATO_UI.md`
- Modify: `docs/VALIDACION_INTEGRAL.md`
- Create: `scripts/validate_universal_context.py`
- Create: `tests/test_universal_context_canary.py`

**Interfaces:**
- Consumes: live API, native picker contract, isolated discovery, strict 1.1 and report identity gates.
- Produces: timestamped JSON evidence with paths, hashes, job ids, identities, durations and API health; no claim of success without live CYMDIST evidence.

- [ ] **Step 1: Add a safe canary script and dry unit test**

  Implement CLI arguments `--mdb`, `--study`, `--feeder`, `--network`, `--base-url`, `--out`, and `--skip-apply`. The unit test mocks HTTP and asserts the script stops on any identity mismatch and never launches a write/report action by default.

- [ ] **Step 2: Run every automated gate**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

  Run: `npm --prefix web test -- --run`

  Run: `web\node_modules\.bin\tsc.cmd -p web\tsconfig.json --noEmit`

  Run: `npm --prefix web run build`

- [ ] **Step 3: Start the real local web route**

  Use the production launcher and verify `GET /health`, `GET /api/health/ready`, UI version and SPA load. Record the PID/port and do not claim readiness if only liveness passes.

- [ ] **Step 4: Execute real read-only discovery**

  Choose an MDB outside `database_dir`, run `contexto_descubrir_redes`, verify every listed network comes from CymPy, then call `/health` again. Record Access Violation separately as `crash_soft` only if the useful JSON existed first.

- [ ] **Step 5: Execute controlled 1.1 with the approved fixture**

  Use an existing safe MDB/study/feeder/network combination, assert the four returned and persisted identities match exactly, and verify no study-save operation occurred. If no safe fixture exists, report this check as pending rather than simulate success.

- [ ] **Step 6: Verify every child module and report gate**

  Exercise read-only/status calls for §§2–7 and confirm each response or job contains the same fingerprint. Verify Step 6 rejects one deliberately mismatched temporary manifest and accepts the current matching manifest; do not regenerate a production report unless the required real LF/OCR inputs already exist.

- [ ] **Step 7: Publish evidence boundaries**

  Update `VALIDACION_INTEGRAL.md` with separate sections for automated tests, real selector, real CymPy discovery, real 1.1, child-module propagation, report provenance, native teardown warnings and pending operations. Include SHA-256 for the evidence JSON and generated artifacts.

- [ ] **Step 8: Commit documentation and canary**

  ```powershell
  git add scripts/validate_universal_context.py tests/test_universal_context_canary.py docs/API_CONTRATO_UI.md docs/VALIDACION_INTEGRAL.md
  git commit -m "Document and validate universal CYMDIST context"
  ```

## Academic and technical basis

- Fielding's doctoral dissertation requires each request to carry all information needed for interpretation; this supports explicit four-field context rather than hidden server fallback: https://ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- Doğan, Betin-Can and Garousi's indexed systematic review motivates layered unit, contract and integration coverage for web applications: https://www.sciencedirect.com/science/article/pii/S0164121214000223
- The indexed workflow-provenance model by Butt and Fitch supports recording enough execution and data lineage to validate outputs; this motivates context identity in LoadFlow/report manifests: https://www.sciencedirect.com/science/article/pii/S0169023X21000045
- Microsoft documents `System.Windows.Forms.OpenFileDialog`, the native local-file mechanism used here: https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.openfiledialog?view=netframework-4.8.1
- MDN documents that browser file inputs expose a protected fake path, which rules out relying on an HTML file input for an original Windows path: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file
