# RECYM — Suite multi-alimentador CYMDIST (Electro Dunas)

Suite universal para **múltiples alimentadores** vía CymPy / CYMDIST 9.2 R1.  
UI SPA v6 (React) + API FastAPI · flujo operativo **§§1–7**.

## Rutas Electro Dunas

| Rol | Ruta |
|-----|------|
| Raíz estudios | `D:\BaseDatosElectroDunas\260919BaseDatos` |
| Proyectos (`.zxst`) | `D:\BaseDatosElectroDunas\260919BaseDatos\proyectos` |
| Base de datos (`.mdb`) | `D:\BaseDatosElectroDunas\260919BaseDatos\202603` |
| BD activa | `...\202603\20260919.mdb` |

Configurado en `config/settings.json` (+ overlay local `config/settings.local.json`, ver [docs/PRODUCCION.md](docs/PRODUCCION.md)).

## Objetivo

Por cada alimentador:

1. **Calidad de modelo** — diagnóstico + corrección masiva (nodos / equipos DEFAULT) + tensiones base.
2. **Clientes importantes → SED** — cruzar NIS; cargar **EA→Consumo (kWh)** / **Pot→kW**; distribución por **Consumo (kWh)** (método fijo, no configurable); Excel de verificación §3.3b con potencia real (no energía/Pot contratada).
3. **SpotLoad concentrada** — P trifásica → A/B/C monofásica (Locked); verificación en vivo contra CYMDIST.
4. **Flujos** — **situacional** (desconecta SpotLoad) / **proyectado** (conecta SpotLoad) + informes; reportes nativos CYMDIST (§3.4b / §5.1b, selección guardada `RECYM_Informe`).

**Regla general:** cuando falta un dato real (kWh, capacidad conectada, carga §4), el sistema
marca REVISAR/needs_review — nunca inventa un valor.

## Documentación

| Documento | Contenido |
|-----------|-----------|
| **[docs/PRODUCCION.md](docs/PRODUCCION.md)** | Auth, CORS, checklist go-live estación |
| **[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)** | Capas, CymPy/COM, API, artefactos, v7 |
| **[docs/CAMPAIGN_V7.md](docs/CAMPAIGN_V7.md)** | Campaign Aggregate §§1–7 + API v2 |
| **[docs/FLUJO_TRABAJO.md](docs/FLUJO_TRABAJO.md)** | Campaña §§1–7 end-to-end + batch |
| **[docs/MANUAL_UI_DEMANDA.md](docs/MANUAL_UI_DEMANDA.md)** | Manual operativo UI |
| [docs/API_CONTRATO_UI.md](docs/API_CONTRATO_UI.md) | Contrato REST / jobs / SSE |
| [docs/VALIDACION_INTEGRAL.md](docs/VALIDACION_INTEGRAL.md) | Checklist validación PA217 |
| [docs/cymdist/README.md](docs/cymdist/README.md) | LoadAllocation vs LoadFlow (CYME) |
| **[docs/SEPARACION_INFORME_ARTICULO.md](docs/SEPARACION_INFORME_ARTICULO.md)** | Informe `doc/` ≠ artículo `docs/articulo_ieee/` |
| [docs/articulo_ieee/](docs/articulo_ieee/) | **Artículo científico** (desarrollo RECYM) |
| [doc/](doc/) | **Informe de entrega** (modelo + resultados de ejecución) |

## Estructura del repo

```
config/settings.json              # global Electro Dunas + run_sequence
config/feeders/<ID>.json          # un alimentador
src/api_app/                      # FastAPI + jobs + tablero
src/ui/demand_app.py              # handlers Flask (puente)
src/core/                         # CymPy, COM, feeder_context, Excel
src/pipeline/                     # pasos de negocio + run_all
src/analysis/                     # diagnóstico, tablero, validación
src/optimization/                 # §7 reclosers / regulators / capacitors
web/src/                          # SPA React §§1–7
data/input/feeders/<ID>/          # Excel control/catálogo
data/input/common/                # equipos, suministro, medición…
data/output/feeders/<ID>/         # resultados por alimentador
doc/                              # INFORME de entrega (≠ artículo)
docs/articulo_ieee/               # ARTÍCULO científico IEEE
docs/                             # arquitectura, flujo, manuales
scripts/                          # .bat de entorno, pipeline, UI
```

## Uso rápido

En Windows, ejecutar `Abrir RECYM.bat` desde la raíz del proyecto para iniciar la API local y abrir la interfaz en el navegador.

```bat
scripts\01_check_environment.bat
scripts\03_test_cymdist_connection.bat
scripts\30_contract_tests.bat

scripts\10_pipeline_dryrun.bat
scripts\11_run_feeder.bat --feeder PA217
scripts\11_run_feeder.bat --all-feeders

:: SPA demanda §§1–7
scripts\20_demand_ui.bat
:: → http://127.0.0.1:5055

:: SpotLoad CLI (P + cosfi|Q → P/3 Q/3 por fase)
scripts\22_add_spot_load.bat NODE_ID 50 --cosfi 0.95

:: nuevo alimentador (el .zxst debe estar en projects_dir)
scripts\12_new_feeder.bat PA218 --name "PA218" --network-id NET_PA218
```

Build frontend (si cambia `web/src`):

```bat
cd web
npm install
npm run build
```

## Harness de verificación

Ejecute `scripts\30_contract_tests.bat` para correr Vitest, TypeScript, build de producción, toda la suite Python y el smoke de readiness en un solo paso. Requiere el runtime `.tools\python37-win32` y las dependencias web ya instaladas (`cd web && npm ci`); el runner no instala paquetes durante la prueba. Los tests de contexto usan MDB/estudios temporales y COM simulado, por lo que cubren alimentadores y rutas arbitrarios sin escribir en la base real.

## Flujo de contexto CYMDIST (UI §§1–1.3)

1. Seleccione la base `.mdb` y pulse **Cargar alimentadores**.
2. Seleccione el **Alimentador (BD)**.
3. Seleccione manualmente un estudio existente. Si no existe uno dedicado, pulse **Crear estudio para alimentador**; RECYM crea y guarda un `.zxst` con la red elegida y actualiza el selector.
4. Con un estudio seleccionado, pulse **1.1 · Verificar y conectar en CYMDIST**. El paso solo queda listo si el backend devuelve la huella del contexto.
5. Después de 1.1, ejecute **1.3b · Probar conexión CYMDIST**. Este botón requiere una huella válida; si se cambia BD, alimentador o estudio, vuelva a aplicar 1.1.
6. Cargue las mediciones y use **1.4 · Cargar en la fuente**.

## WRITE en CYMDIST

1. Verificar `study_file` / `study_path` en `config/feeders/<ID>.json`
2. En `config/settings.json`: `"dry_run": false`
3. Ejecutar pipeline del alimentador o UI de demanda

## Reglas operativas (resumen)

- **Incluir off** (clientes): desconexión física en modelo + 0 kW.
- **EA** → Consumo (kWh); distribución actualiza kW residual.
- **SpotLoad §4**: Locked; P₃φ → A/B/C = P/3, Q/3.
- **Situacional / proyectado**: independientes (desconecta / conecta §4); cada uno alimenta §6.
- Tras SpotLoad **no** redistribuir: solo LoadFlow.
