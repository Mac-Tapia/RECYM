# Arquitectura multi-alimentador — Electro Dunas

## Datos CYMDIST

- `studies_root`: `D:\BaseDatosElectroDunas\260919BaseDatos`
- `projects_dir`: estudios `.zxst` por alimentador
- `database_dir` / `database_mdb`: BD Access compartida (`.mdb`)

## Capas (por alimentador) — SPA §§1–7

1. Contexto + cabecera (BD/estudio + medición)  
2. Calidad del modelo + Tablero dinámico  
3. Clientes importantes → SED + distribución LoadAllocation  
4. Nueva SpotLoad concentrada  
5. Flujos situacional / proyectado  
6. Informes de entrega  
7. Optimización + Suite  

Manual operativo UI: [`MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md). Contrato: [`API_CONTRATO_UI.md`](API_CONTRATO_UI.md).


## Selección

`settings.json` + `config/feeders/<ID>.json`  
Override: `--feeder`, `RECYM_FEEDER`, `--all-feeders`
