# RECYM — Suite multi-alimentador CYMDIST (Electro Dunas)

Suite universal para **múltiples alimentadores** vía CymPy / CYMDIST 9.2 R1.

## Rutas Electro Dunas

| Rol | Ruta |
|-----|------|
| Raíz estudios | `D:\BaseDatosElectroDunas\260919BaseDatos` |
| Proyectos (`.zxst`) | `D:\BaseDatosElectroDunas\260919BaseDatos\proyectos` |
| Base de datos (`.mdb`) | `D:\BaseDatosElectroDunas\260919BaseDatos\202603` |
| BD activa | `...\202603\20260919.mdb` |

Configurado en `config/settings.json` (`studies_root`, `projects_dir`, `database_dir`, `database_mdb`).

## Objetivo

Por cada alimentador:
1. Corrección masiva (nodos / equipos DEFAULT) + tensiones base.
2. Clientes importantes → SED: cruzar NIS y cargar **EA→Consumo (kWh)** / **Pot→kW** en CYMDIST; distribución por **Consumo (kWh)**.
3. Nueva SpotLoad concentrada (P trifásica → A/B/C monofásica).
4. Flujos independientes: **situacional** (desconecta §3) / **proyectado** (conecta §3) + informes.

## Manuales

| Documento | Contenido |
|-----------|-----------|
| **[docs/MANUAL_UI_DEMANDA.md](docs/MANUAL_UI_DEMANDA.md)** | UI §§1–5 (cabecera, clientes, SpotLoad, flujos, informes) |
| [docs/VALIDACION_INTEGRAL.md](docs/VALIDACION_INTEGRAL.md) | Última revisión integral / checklist |
| [docs/cymdist/README.md](docs/cymdist/README.md) | LoadAllocation vs LoadFlow (tutoriales CYME) |
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Capas multi-alimentador |

## Estructura RECYM

```
config/settings.json           # global Electro Dunas + rutas BD
config/feeders/<ID>.json       # un alimentador
data/input/feeders/<ID>/       # Excel control/catálogo
data/input/common/equipment/   # catálogos compartidos
data/output/feeders/<ID>/      # resultados
docs/MANUAL_UI_DEMANDA.md      # manual operativo UI
```

## Uso

```bat
scripts\01_check_environment.bat
scripts\03_test_cymdist_connection.bat

scripts\10_pipeline_dryrun.bat
scripts\11_run_feeder.bat --feeder PA217
scripts\11_run_feeder.bat --all-feeders

:: interfaz demanda / clientes SED / nueva SpotLoad / flujos / informes
scripts\20_demand_ui.bat
:: → http://127.0.0.1:5055   (ver docs/MANUAL_UI_DEMANDA.md)

:: CLI: nueva carga concentrada trifasica (P + cosfi|Q) → P/3 Q/3 por fase
scripts\22_add_spot_load.bat NODE_ID 50 --cosfi 0.95

:: nuevo alimentador (el .zxst debe estar en projects_dir)
scripts\12_new_feeder.bat PA218 --name "PA218" --network-id NET_PA218
```

## WRITE en CYMDIST

1. Verificar `study_file` / `study_path` en `config/feeders/<ID>.json`
2. En `config/settings.json`: `"dry_run": false`
3. Ejecutar pipeline del alimentador o UI de demanda

## Reglas operativas (resumen)

- **Incluir off** (clientes): desconexión física en modelo + 0 kW.
- **EA** → Consumo (kWh); distribución actualiza kW residual.
- **SpotLoad §3**: Locked; P₃φ → A/B/C = P/3, Q/3.
- **Situacional / proyectado**: botones independientes (desconecta / conecta §3); cada uno actualiza §5.
- Tras SpotLoad **no** redistribuir: solo LoadFlow.
