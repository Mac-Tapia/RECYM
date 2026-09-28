# Universal Asynchronous CYMDIST Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir seleccionar una MDB y un estudio desde cualquier carpeta, descubrir de forma asíncrona sus redes reales, persistir y verificar físicamente cada mutación CYMDIST, y producir un cierre auditable módulo por módulo de §§1–7 con un informe construido solo con datos de esa ejecución.

**Architecture:** Un selector nativo local entrega rutas canónicas; un job CymPy aislado descubre redes sin heredar ni persistir el contexto activo; 1.1 valida y persiste las cuatro identidades. Un coordinador serializado por ruta de estudio respalda, muta, guarda una sola vez y verifica por reapertura cada cambio. El cliente conserva MDB, estudio y alimentador como estados independientes; cada módulo emite evidencia con una huella de contexto y un `run_id`, y el informe/cierre 1–7 solo acepta artefactos de esa misma corrida.

**Tech Stack:** Python 3.7.9 win32, FastAPI 0.95, Flask 2.2, CymPy/CYMDIST, React 19, TypeScript 5.7, Vite 6, Vitest 3.2, unittest.

**Spec:** `docs/superpowers/specs/2026-09-27-contexto-universal-cymdist-design.md` and `docs/superpowers/specs/2026-09-27-persistencia-multialimentador-cymdist-design.md`

## Global Constraints

- Windows es el único sistema soportado para `Examinar…`; fuera de Windows se devuelve `PICKER_UNAVAILABLE`.
- MDB y estudio se usan en su ruta original: no se copian ni suben al repositorio.
- Extensiones admitidas: `.mdb` para base y `.zxst`, `.sxst`, `.zsxst`, `.xst` para estudio.
- MDB, estudio y alimentador son independientes; no se infiere alimentador desde el nombre del estudio.
- Toda operación §§2–7 recibe `database_mdb`, `study_path`, `feeder_id` y `network_id` explícitos cuando el contexto ya está completo.
- El selector y el descubrimiento tienen timeout de 600 s; el descubrimiento corre en el worker aislado y no guarda el estudio.
- Examinar y descubrir no modifican `config/settings.json` ni crean configuraciones de alimentador; solo 1.1 persiste.
- Los archivos del usuario ya modificados o no versionados se preservan; cada commit incluye únicamente los archivos de su tarea.
- Toda mutación crea respaldo, usa lock por ruta canónica, guarda una sola vez y exige reapertura/relectura en un proceso nuevo antes de informar éxito.
- Los diagnósticos 2.1 y 3.4 solo aceptan LoadFlow y capturas nativas CYMDIST verificadas; no se permiten imágenes sintéticas ni fallbacks como evidencia.
- La ejecución integral requiere parámetros explícitos `--mdb`, `--study`, `--feeder` y `--network`; no contiene un alimentador fijo ni elige por nombre de archivo.
- El informe final y el anexo de cierre solo consumen artefactos con el mismo `run_id` y la misma huella MDB–estudio–alimentador–red.

## Review Focus

- Dos MDB con igual nombre en carpetas diferentes deben producir claves y catálogos distintos; Task 3 lo fija con `test_same_basename_databases_do_not_share_cache`.
- Una respuesta de descubrimiento antigua no debe reemplazar la MDB elegida después; Task 5 lo fija con `ignores_out_of_order_discovery_result`.
- Cancelar `OpenFileDialog` debe conservar las tres selecciones; Task 5 lo fija con `cancelled_picker_preserves_context`.
- Un LoadFlow o informe de otro contexto no debe satisfacer el gate ni poder cerrarse; Task 7 lo fija con `test_report_rejects_foreign_context_artifacts`.
- Un proceso CymPy que termina con Access Violation después de escribir un resultado útil debe conservar el resultado y mantener viva la API; Task 8 lo comprueba con el canario real y `/health`.
- Dos commits consecutivos sobre redes distintas del mismo estudio no deben perder el primero; Task 9 lo fija con una prueba A→B→reapertura.
- Un guardado COM no debe recibir un segundo `study.Save`; Task 10 lo fija para `external_engine_saved`.
- Una captura antigua, sintética o de otra huella no debe satisfacer 2.1, 3.4 ni el informe; Tasks 11 y 13 lo fijan.
- Una corrida 1–7 interrumpida no debe producir un informe “completo”; Task 14 exige gates fail-closed y una matriz de evidencia por módulo.
- La etapa 7 no debe ejecutar optimizaciones mutantes de manera implícita; Task 14 limita el cierre automático a validaciones/suite y exige una opción explícita para cualquier optimización.

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
- Create `src/core/cymdist_commit.py`: lock, respaldo, modos de commit, manifiesto y verificación independiente.
- Create `src/pipeline/verify_cymdist_commit.py`: reapertura y relectura estricta de valores/redes.
- Modify mutaciones de `src/pipeline/` y sus rutas API: adopción del coordinador persistente.
- Modify `src/pipeline/capture_informe_color_views.py`: evidencia nativa estricta para 2.1 y 3.4.
- Create `src/pipeline/run_evidence.py`: `run_id`, registro append-only y gates de §§1–7.
- Rewrite `scripts/run_cierre_1_7.py`: CLI universal, asincrónica y fail-closed sin `PA217` fijo.
- Create `tests/test_cymdist_commit.py`, `tests/test_native_color_evidence.py`, `tests/test_run_1_7.py`.

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

### Task 9: Persistent CYMDIST unit of work

**Files:**
- Create: `src/core/cymdist_commit.py`
- Create: `src/pipeline/verify_cymdist_commit.py`
- Create: `tests/test_cymdist_commit.py`

**Interfaces:**
- Consumes: `ContextIdentity` from Task 1 and existing `CymPyAdapter` open/save APIs.
- Produces: `CommitMode`, `CommitRequest`, `commit_cymdist_action(request, mutate) -> dict`, study-path lock, backup/manifest schema and independent `verify_commit(manifest_path) -> dict`.

- [ ] **Step 1: Write failing transaction tests**

  Add `test_lock_key_uses_canonical_study_path`, `test_read_operation_cannot_request_commit`, `test_study_commit_saves_once`, `test_database_commit_calls_update_and_save_project_once`, `test_external_engine_saved_does_not_save_twice`, `test_failed_save_preserves_backup`, `test_readback_mismatch_fails_closed`, and `test_two_network_commits_preserve_a_after_b`. Use a filesystem-backed fake study so hashes, backup and append-only manifests are real while CymPy calls remain injected boundaries.

- [ ] **Step 2: Run focused tests and confirm RED**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_cymdist_commit -v`

  Expected: FAIL because `core.cymdist_commit` and `verify_cymdist_commit` do not exist.

- [ ] **Step 3: Implement the coordinator and verifier contracts**

  Implement canonical-path `StudyLock`, pre-write SHA-256 backup, modes `study`, `study_and_database`, `external_engine_saved`, one-save enforcement, before/requested/read-back values, neighbor-network inventory and JSON manifest. Fail with the exact codes from the persistence spec; never delete or overwrite the backup on failure.

- [ ] **Step 4: Run focused and core regressions**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_cymdist_commit tests.test_api_contract -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/core/cymdist_commit.py src/pipeline/verify_cymdist_commit.py tests/test_cymdist_commit.py
  git commit -m "Add verifiable CYMDIST commit coordinator"
  ```

### Task 10: Persist every mutating action in §§1–3

**Files:**
- Modify: `src/pipeline/run_demand_allocation.py`
- Modify: `src/pipeline/apply_clientes_to_cymdist.py`
- Modify: `src/pipeline/model_quality_gate.py`
- Modify: `src/pipeline/add_spot_load.py`
- Modify: `src/api_app/jobs.py`
- Modify: `src/ui/demand_app.py`
- Create: `tests/test_mutating_actions_commit.py`

**Interfaces:**
- Consumes: `commit_cymdist_action` and commit modes from Task 9; complete context from Tasks 1–6.
- Produces: uniform `commit` result on 1.2, 2.3, Guardar inclusiones, 3.1 when it changes CYMDIST, 3.2 and 3.3; verified flags consumed by 3.4 and the report.

- [ ] **Step 1: Write failing table-driven mutation tests**

  Assert each action selects the required mode, forwards the exact `network_id`, refuses incomplete/mismatched context, exposes backup/manifest/readback fields and cannot report `ok` when `reopen_verified` is false. Pin 3.3 COM to `external_engine_saved` and assert no second `study.Save`.

- [ ] **Step 2: Run focused tests and confirm RED**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_mutating_actions_commit -v`

  Expected: FAIL because current actions use mixed direct saves and do not return the uniform commit contract.

- [ ] **Step 3: Route mutations through the coordinator**

  Keep domain calculations in their existing modules; wrap only the physical mutation/save boundary. Use `study_and_database` for 1.2 and for quality corrections that mutate equipment/BD, `study` for normal study edits, and `external_engine_saved` for COM Load Allocation. Preserve `save_after_write=False` internally so nested functions cannot save twice.

- [ ] **Step 4: Add job/API gates**

  Make routes and isolated jobs fail closed unless identity, save result and independent reopen/readback match. Persist the commit manifest path in the active session without replacing the selected feeder.

- [ ] **Step 5: Run focused and full Python suites**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_mutating_actions_commit tests.test_cymdist_commit -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

  Expected: PASS.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/pipeline/run_demand_allocation.py src/pipeline/apply_clientes_to_cymdist.py src/pipeline/model_quality_gate.py src/pipeline/add_spot_load.py src/api_app/jobs.py src/ui/demand_app.py tests/test_mutating_actions_commit.py
  git commit -m "Persist and verify CYMDIST mutations"
  ```

### Task 11: Native colored diagnostics and situational step 3.4

**Files:**
- Modify: `src/pipeline/capture_informe_color_views.py`
- Modify: `src/pipeline/run_load_flow.py`
- Modify: `src/pipeline/diagnostic_registry.py`
- Modify: `src/api_app/jobs.py`
- Modify: `web/src/pages/Step2CalidadTablero.tsx`
- Modify: `web/src/pages/Step3Clientes.tsx`
- Create: `tests/test_native_color_evidence.py`

**Interfaces:**
- Consumes: complete context/fingerprint and verified 1.2/3.2/3.3 commit manifests.
- Produces: diagnostic evidence for 2.1 and situational evidence for 3.4, each with real LoadFlow metrics plus `VoltageLevel` and `LoadingLevel` PNG sidecars where `color_verified=true`.

- [ ] **Step 1: Write failing strict-evidence tests**

  Add cases rejecting renderer fallback, missing CYMDIST window identity, stale fingerprint, missing PNG hash, `color_verified=false`, unconverged LoadFlow and un-restored temporary state. Add a 3.4 gate test that requires verified 1.2, 3.2 and 3.3 manifests.

- [ ] **Step 2: Run focused tests and confirm RED**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_native_color_evidence -v`

  Expected: FAIL because no strict 2.1/3.4 evidence contract exists.

- [ ] **Step 3: Implement strict native capture**

  Separate `capture_native_color_view(context, color_type, scenario, run_id) -> dict` from any report renderer. Permit only `VoltageLevel` and `LoadingLevel`; record window/process identity, capture method, PNG SHA-256, metrics and fingerprint. Snapshot and restore visual/scenario state, then close without saving.

- [ ] **Step 4: Add isolated `flujo_situacional_34` and UI**

  Execute real situational LoadFlow after 3.3, create both verified native captures and `loadflow_situacional.json`, and expose the action as 3.4 after the three persistence gates. 2.1 invokes the same strict capture primitive for diagnostic evidence but remains read-only.

- [ ] **Step 5: Run Python and frontend verification**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_native_color_evidence tests.test_mutating_actions_commit -v`

  Run: `npm --prefix web test -- --run`

  Run: `web\node_modules\.bin\tsc.cmd -p web\tsconfig.json --noEmit`

  Expected: PASS.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/pipeline/capture_informe_color_views.py src/pipeline/run_load_flow.py src/pipeline/diagnostic_registry.py src/api_app/jobs.py web/src/pages/Step2CalidadTablero.tsx web/src/pages/Step3Clientes.tsx tests/test_native_color_evidence.py
  git commit -m "Add native CYMDIST diagnostic and situational evidence"
  ```

### Task 12: Renumber projected LoadFlow and enforce report provenance

**Files:**
- Modify: `src/api_app/jobs.py`
- Modify: `src/pipeline/assemble_informe.py`
- Modify: `src/pipeline/fill_informe.py`
- Modify: `src/pipeline/deliver_informe.py`
- Modify: `web/src/pages/Step5Flujos.tsx`
- Modify: `web/src/pages/Step6Informes.tsx`
- Modify: `scripts/_run_cierre_informe.py`
- Modify: `scripts/_run_lf_informe.py`
- Create: `tests/test_report_run_provenance.py`

**Interfaces:**
- Consumes: 3.4 situational evidence, §4 commit evidence, 5.1 projected evidence and common context/run identity.
- Produces: renumbered UI/API labels and report manifest that lists every accepted source artifact and rejects cross-run/cross-context data.

- [ ] **Step 1: Write failing provenance and numbering tests**

  Assert Step 5 exposes only projected 5.1 in the guided flow; no active 5.2/5.3 call site remains. Assert assembly rejects mismatched `run_id`, fingerprint, MDB/study/feeder/network, missing native capture sidecars and unverified commits.

- [ ] **Step 2: Run focused tests and confirm RED**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_report_run_provenance -v`

  Expected: FAIL on current 5.1/5.2/5.3 labels and shared artifacts.

- [ ] **Step 3: Renumber the guided flow**

  Remove situational/general buttons from Step 5, expose projected LoadFlow as 5.1, and update progress/messages/scripts. Keep a non-guided compatibility endpoint only if existing callers require it; it must not satisfy report gates without current evidence.

- [ ] **Step 4: Gate report assembly by run provenance**

  Require verified manifests from 1.2, 3.2, 3.3, 3.4 and, for complete projected delivery, §4/5.1. Copy accepted artifacts into a `run_id`-scoped delivery directory and write hashes in `assemble_manifest.json` and `fill_manifest.json`.

- [ ] **Step 5: Run report, Python and frontend regressions**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_report_run_provenance tests.test_informe_context -v`

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

  Run: `npm --prefix web test -- --run`

  Run: `npm --prefix web run build`

  Expected: PASS.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/api_app/jobs.py src/pipeline/assemble_informe.py src/pipeline/fill_informe.py src/pipeline/deliver_informe.py web/src/pages/Step5Flujos.tsx web/src/pages/Step6Informes.tsx scripts/_run_cierre_informe.py scripts/_run_lf_informe.py tests/test_report_run_provenance.py
  git commit -m "Bind reports to renumbered verified CYMDIST runs"
  ```

### Task 13: Universal module-by-module 1–7 runner

**Files:**
- Create: `src/pipeline/run_evidence.py`
- Rewrite: `scripts/run_cierre_1_7.py`
- Create: `tests/test_run_1_7.py`
- Modify: `docs/API_CONTRATO_UI.md`

**Interfaces:**
- Consumes: authenticated API, explicit four-field context, commit/capture/report manifests from Tasks 1–12.
- Produces: `run_id`-scoped JSON/Markdown matrix for every module and substep, with inputs, hashes, jobs, timings, outputs, gate decisions and final closure status.

- [ ] **Step 1: Write failing orchestration tests**

  Cover arbitrary paths containing spaces, no hard-coded feeder, asynchronous job polling, context propagation on every request, stop-on-failed-gate, resume only with matching `run_id`, report refusal before all mandatory stages, and omission of mutating §7 optimization unless `--allow-optimization` is explicitly passed.

- [ ] **Step 2: Run focused tests and confirm RED**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_run_1_7 -v`

  Expected: FAIL because the current script fixes `PA217`, uses outdated numbering and lacks provenance gates.

- [ ] **Step 3: Implement `RunEvidence`**

  Provide append-only stage records with status `passed`, `failed`, `blocked` or `pending_real`; record input/output SHA-256, `context_fingerprint`, `run_id`, API/job identifiers, native engine and evidence paths. A skipped required stage makes closure fail.

- [ ] **Step 4: Rewrite the CLI without fixed paths or feeders**

  Required arguments: `--mdb`, `--study`, `--feeder`, `--network`. Optional: `--base-url`, `--api-key`, `--resume-run`, `--allow-write`, `--allow-optimization`, `--out`. Default is diagnostic/read-only; physical §§1–6 execution requires `--allow-write`. Run 3.4 after 3.3, projected 5.1 after §4, generate the §6 draft, perform §7 validation, then refresh the report with the §7 execution annex.

- [ ] **Step 5: Verify module coverage and output contract**

  Run: `.tools\python37-win32\python.exe -m unittest tests.test_run_1_7 tests.test_universal_context_canary tests.test_report_run_provenance -v`

  Expected: PASS and the dry-run fixture contains an evidence row for every required substep.

- [ ] **Step 6: Commit**

  ```powershell
  git add src/pipeline/run_evidence.py scripts/run_cierre_1_7.py tests/test_run_1_7.py docs/API_CONTRATO_UI.md
  git commit -m "Add universal audited runner for sections one through seven"
  ```

### Task 14: Full automated verification and controlled real execution

**Files:**
- Modify: `docs/VALIDACION_INTEGRAL.md`
- Create at runtime: `data/output/runs/<run_id>/module_matrix.json`
- Create at runtime: `data/output/runs/<run_id>/module_matrix.md`
- Create at runtime: `data/output/runs/<run_id>/final_manifest.json`

**Interfaces:**
- Consumes: completed Tasks 1–13 and an explicitly selected real MDB/study/feeder/network discovered through the universal selector.
- Produces: fresh automated-test evidence, real CYMDIST execution evidence for §§1–7, final report artifacts and a precise list of any blocked/pending-real stage.

- [ ] **Step 1: Run all non-native gates**

  Run: `.tools\python37-win32\python.exe -m unittest discover -s tests -p "test_*.py" -v`

  Run: `npm --prefix web test -- --run`

  Run: `web\node_modules\.bin\tsc.cmd -p web\tsconfig.json --noEmit`

  Run: `npm --prefix web run build`

  Expected: all commands exit 0; record exact counts and logs, not a summary inferred from earlier runs.

- [ ] **Step 2: Start and verify the real web route**

  Launch with `scripts\20_demand_ui_production.bat`, obtain session/API credentials through the supported bootstrap flow, and verify `/health`, `/api/health/ready`, `/api/spa/meta` and the SPA route. Record PID, port, UI version and timestamps.

- [ ] **Step 3: Resolve the real context without inference**

  Use picker/discovery results or explicit user-selected paths; record canonical paths and initial hashes. Abort if the network is not returned by CymPy from that MDB or if the study/context binding differs.

- [ ] **Step 4: Execute the real 1–7 closure**

  Run `scripts/run_cierre_1_7.py` with all four identity arguments and `--allow-write`. Before each mutating stage confirm backup creation; after each worker verify API health. Do not use `--allow-optimization` unless separately authorized because §7 optimization changes the model.

- [ ] **Step 5: Inspect every module and final report**

  Require zero `failed`/`blocked` mandatory rows, independently reopen/readback each saved stage, validate native capture sidecars and hashes, inspect Word/Excel/PDF existence and report manifest, and confirm the §7 annex shares the same `run_id` and fingerprint. If any condition fails, report the report as incomplete rather than regenerating synthetic evidence.

- [ ] **Step 6: Publish the validation boundary**

  Update `docs/VALIDACION_INTEGRAL.md` with commands, exact results, context identity, backup/manifests, artifact hashes, module matrix and pending-real limitations. Never translate unit/fake success into real CYMDIST success.

- [ ] **Step 7: Commit only code/documentation evidence**

  ```powershell
  git add docs/VALIDACION_INTEGRAL.md
  git commit -m "Record module by module CYMDIST validation"
  ```

  Runtime MDB/study backups and `data/output/runs/` remain operational evidence and are not committed unless repository policy explicitly requires it.

## Academic and technical basis

- Fielding's doctoral dissertation requires each request to carry all information needed for interpretation; this supports explicit four-field context rather than hidden server fallback: https://ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- Doğan, Betin-Can and Garousi's indexed systematic review motivates layered unit, contract and integration coverage for web applications: https://www.sciencedirect.com/science/article/pii/S0164121214000223
- The indexed workflow-provenance model by Butt and Fitch supports recording enough execution and data lineage to validate outputs; this motivates context identity in LoadFlow/report manifests: https://www.sciencedirect.com/science/article/pii/S0169023X21000045
- Microsoft documents `System.Windows.Forms.OpenFileDialog`, the native local-file mechanism used here: https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.openfiledialog?view=netframework-4.8.1
- MDN documents that browser file inputs expose a protected fake path, which rules out relying on an HTML file input for an original Windows path: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file
- Puustjärvi's doctoral thesis on transactional workflows supports explicit phases and concurrency control for durable long-running operations: https://www.cs.helsinki.fi/TR/A-1999/2/
- Chkliaev's doctoral thesis links concurrency control, recovery and commit verification: https://research.tue.nl/en/publications/mechanical-verification-of-concurrency-control-and-recovery-proto/
- Wang et al. provide an indexed atomicity/provenance model with commit and abort semantics for scientific workflows: https://doi.org/10.1016/j.future.2008.06.007
