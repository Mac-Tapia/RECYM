# Arquitectura multi-alimentador — Electro Dunas

## Datos CYMDIST

- `studies_root`: `D:\BaseDatosElectroDunas\260919BaseDatos`
- `projects_dir`: estudios `.zxst` por alimentador
- `database_dir` / `database_mdb`: BD Access compartida (`.mdb`)

## Capas (por alimentador)

1. Calidad del modelo (equipos Excel → CYMDIST, correcciones, tensiones base)  
2. Clientes importantes → SED (NIS / **EA→Consumo kWh** / **Pot→kW**; Incluir off = desconectado)  
3. Distribución LoadAllocation método **Consumo (kWh)** (fijos Locked; residual Unlocked)  
4. Nueva SpotLoad concentrada: P trifásica → **A/B/C = P/3, Q/3**; Locked  
5. Flujos independientes: situacional (desconecta §3) / proyectado (conecta §3)  
6. Informes §5 (`doc/`) actualizados tras cada flujo  
7. Diagnóstico + tablero / Optimización / Comparación  

Manual operativo UI: [`MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md).

## Selección

`settings.json` + `config/feeders/<ID>.json`  
Override: `--feeder`, `RECYM_FEEDER`, `--all-feeders`
