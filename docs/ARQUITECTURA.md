# Arquitectura RECYM — Electro Dunas

Suite **multi-alimentador** para modelado, corrección, asignación de demanda, flujos de carga e informes sobre **CYMDIST 9.2 / CymPy**, con UI SPA (React) y API (FastAPI + puente Flask).

Versión de referencia UI: **SPA v6** (`ui_version: 6.0-spa`).

---

## 1. Vista general

```
┌─────────────────────────────────────────────────────────────────┐
│  Presentación                                                    │
│  web/ (React + Vite)  →  SPA §§1–7  →  http://127.0.0.1:5055     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / JSON / SSE (jobs)
┌────────────────────────────▼────────────────────────────────────┐
│  API                                                             │
│  FastAPI (src/api_app)  ·  jobs asíncronos  ·  /api/tablero      │
│  Puente WSGI → Flask (src/ui/demand_app.py) para /api/* legacy   │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Dominio / orquestación                                          │
│  pipeline/  ·  analysis/  ·  optimization/                       │
│  Orquestador batch: pipeline/run_all.py (run_sequence)           │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Núcleo CYMDIST                                                  │
│  core/cympy_adapter.py  ·  core/cymdist_com.py  ·  feeder_context│
│  Python 3.7 win32 (.tools) + COM CYME                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│  Datos externos Electro Dunas                                    │
│  .zxst (estudio)  ·  .mdb (BD Access)  ·  Excel entrada/salida   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Capas de software

| Capa | Ubicación | Responsabilidad |
|------|-----------|-----------------|
| **UI SPA** | `web/src/` | Navegación §§1–7, formularios, tablero, polling/SSE de jobs |
| **API** | `src/api_app/` | Contrato REST, jobs (`POST /api/jobs`), tablero nativo, estáticos `web/dist` |
| **UI legacy** | `src/ui/demand_app.py` | Handlers Flask reutilizados vía puente FastAPI |
| **Pipeline** | `src/pipeline/` | Pasos de negocio: clientes, SpotLoad, LoadAllocation, LoadFlow, informes |
| **Análisis** | `src/analysis/` | Diagnóstico red/sistema/ELD, tablero, validación, precisión EA/Pot |
| **Optimización** | `src/optimization/` | Reclosers, reguladores, capacitores (§7) |
| **Core** | `src/core/` | Settings multi-feeder, Excel I/O, adaptador CymPy, COM LoadFlow |
| **Config** | `config/` | Global + un JSON por alimentador |
| **Datos** | `data/input|output/` | Entradas Excel y artefactos por alimentador / sistema |

---

## 3. Datos CYMDIST (Electro Dunas)

Configurados en `config/settings.json`:

| Rol | Clave | Ejemplo |
|-----|-------|---------|
| Raíz estudios | `studies_root` | `D:\BaseDatosElectroDunas\260919BaseDatos` |
| Proyectos `.zxst` | `projects_dir` | `...\proyectos` |
| BD Access | `database_dir` / `database_mdb` | `...\202603\20260919.mdb` |
| Estudio sistema (96) | `eld_study_path` | `...\proyectos\ELD.zxst` |
| CYME / Python | `cyme_root` / `python_exe` | CYME + `.tools\python37-win32` |

Por alimentador (`config/feeders/<ID>.json`):

- `network_id`, `study_file` / `study_path`
- `control_workbook`, `catalog_workbook`
- `output_dir` → `data/output/feeders/<ID>/`

Selección de alimentador (prioridad):

1. `--feeder <ID>` / `RECYM_FEEDER`
2. Contexto UI (§1 / header `X-Feeder`)
3. `active_feeder` en `settings.json`
4. `--all-feeders` (batch)

---

## 4. Flujo operativo SPA (§§1–7)

Orden de trabajo recomendado (detalle en [`FLUJO_TRABAJO.md`](FLUJO_TRABAJO.md)):

| § | Panel | Qué hace |
|---|-------|----------|
| **1** | Contexto + cabecera | BD + estudio; medición de cabecera (P/Q máx) → entrada LoadAllocation |
| **2** | Calidad + Tablero | NetworkDiagnostic (feeder / sistema 96 / ELD); correcciones; gate 0 errores |
| **3** | Clientes + distribución | Cruce NIS → EA/Pot en SED; Incluir on/off; LoadAllocation por Consumo (kWh) |
| **4** | SpotLoad nueva | Carga concentrada en nodo existente (P₃φ → A/B/C = P/3, Q/3); Locked |
| **5** | Flujos | Situacional (desconecta §4) / proyectado (conecta §4) / general |
| **6** | Informes | Meta OCR PDF + relleno Word/PDF de entrega |
| **7** | Opt + Suite | Optimización equipos; herramientas batch / sync / nuevo feeder |

**Reglas de acoplamiento:**

- §2 (diagnóstico) **no depende** de §§4–5; usa red/equipos ya en BD.
- Tras §3 o §4, CYMDIST suele quedar con sesión abierta; §§3–6 operan sobre el mismo estudio.
- Tras SpotLoad (§4) **no** redistribuir demanda: solo LoadFlow (§5).
- Guardar cabecera (§1) restablece artefactos de sesión §§3–5 para no mezclar campañas.

---

## 5. Pipeline batch (`run_sequence`)

Orquestador: `src/pipeline/run_all.py`.

Secuencia típica en `settings.json`:

```
validate_inputs
→ network_diagnostic
→ sync_equipment
→ build_corrections
→ bulk_fix
→ fix_base_voltages
→ network_diagnostic_after
→ inventory_loads
→ build_clientes
→ apply_clientes
→ verify_precision
→ demand_allocation
→ report
```

Flags del Excel `Control_Simulacion.xlsx` (hoja `Control_Proyecto`) pueden omitir LoadFlow / opts.

Scripts de entrada:

| Script | Uso |
|--------|-----|
| `scripts\01_check_environment.bat` | Preflight |
| `scripts\03_test_cymdist_connection.bat` | COM / estudio |
| `scripts\10_pipeline_dryrun.bat` | Pipeline sin WRITE |
| `scripts\11_run_feeder.bat` | Un feeder o `--all-feeders` |
| `scripts\20_demand_ui.bat` | SPA + API :5055 |
| `scripts\24_*.bat` / `25_*.bat` | Diagnóstico sistema / ELD |

---

## 6. Integración CymPy / COM

| Módulo | Rol |
|--------|-----|
| `core/cympy_adapter.py` | Apertura estudio/BD, lectura/escritura cargas, customers, SpotLoad |
| `core/cymdist_com.py` | LoadFlow y operaciones vía API COM (`loadflow_engine: COM`) |
| `core/feeder_context.py` | Merge settings + feeder; resolución de rutas `.zxst`/`.mdb` |
| `config/cympy_api_map.json` | Mapa de campos/API CymPy |

Campos clave (consumidor SED / SpotLoad): ver tabla en [`MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md).

WRITE en modelo:

1. `study_path` válido en `config/feeders/<ID>.json`
2. `"dry_run": false` en `settings.json`
3. `require_study_for_write: true` (por defecto)

---

## 7. API y jobs

Contrato completo: [`API_CONTRATO_UI.md`](API_CONTRATO_UI.md).

- Base: `http://127.0.0.1:5055`
- Contexto: header `X-Feeder` o query/body `feeder`
- Operaciones largas (§2 calidad, §3 distribución, §5 flujo):  
  `POST /api/jobs` → `GET /api/jobs/{id}` / SSE `.../events`
- Tablero: `GET /api/tablero` (JSON); `tablero.html` ya no es producto

Puente: rutas `/api/*` no nativas de FastAPI se reenvían a Flask (`demand_app`).

---

## 8. Artefactos por alimentador

```
data/output/feeders/<ID>/
  clientes/          # tabla + apply report
  demand/            # allocation, loadflow_*, session, informe_meta
  diagnostics/       # tablero.json, dashboard_summary*
  informe_images/    # topología, tensión/cargabilidad situacional|proyectado
  inventory/         # loads.json, nodes.json
```

Sistema (96 alimentadores):

```
data/output/system/diagnostics/
  cymdist_diagnostic_errors_system.csv
  diagnostic_by_code_system.csv
  ELD/               # salida estudio ELD
```

Plantillas de **informe de entrega** (producto operativo ≠ artículo): `doc/informe.docx`, `doc/justificacion.xlsx`.  
**Artículo científico:** `docs/articulo_ieee/`. Separación: [`SEPARACION_INFORME_ARTICULO.md`](SEPARACION_INFORME_ARTICULO.md).

---

## 9. Diagrama de dependencias de módulos

```
web/src/pages/StepN*
        │
        ▼
api_app/main.py ──► jobs.py / routers/tablero.py
        │
        ├──► ui/demand_app.py (handlers)
        │         │
        └─────────┼──► pipeline/*  ·  analysis/*  ·  optimization/*
                  │
                  └──► core/cympy_adapter · cymdist_com · feeder_context · excel_io
```

---

## 10. Documentación relacionada

| Documento | Contenido |
|-----------|-----------|
| [`FLUJO_TRABAJO.md`](FLUJO_TRABAJO.md) | Flujo de campaña end-to-end |
| [`MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md) | Manual operativo UI §§1–7 |
| [`API_CONTRATO_UI.md`](API_CONTRATO_UI.md) | Endpoints |
| [`VALIDACION_INTEGRAL.md`](VALIDACION_INTEGRAL.md) | Checklist validación PA217 |
| [`cymdist/README.md`](cymdist/README.md) | Notas LoadAllocation vs LoadFlow (CYME) |
| [`SEPARACION_INFORME_ARTICULO.md`](SEPARACION_INFORME_ARTICULO.md) | Informe `doc/` ≠ artículo IEEE |
| [`articulo_ieee/`](articulo_ieee/) | Manuscrito científico (no es el informe) |
