# Contrato API UI RECYM (§§1–7)

Base: `http://127.0.0.1:5055` · UI version `6.0-spa`  
Arquitectura: [`ARQUITECTURA.md`](ARQUITECTURA.md) · Flujo: [`FLUJO_TRABAJO.md`](FLUJO_TRABAJO.md) · Campaign v7: [`CAMPAIGN_V7.md`](CAMPAIGN_V7.md)  
Contexto CYMDIST obligatorio para operaciones protegidas:

- headers: `X-Feeder`, `X-Network-Id`, `X-Study-Path`, `X-Database-Mdb` y `X-Context-Fingerprint`;
- body equivalente: `feeder_id`, `network_id`, `study_path`, `database_mdb`, `context_fingerprint`;
- la huella es SHA-256 truncada a 16 caracteres sobre las cuatro claves canónicas;
- una ausencia o cruce retorna `CONTEXT_INCOMPLETE` o HTTP 409 `CONTEXT_IDENTITY_MISMATCH` antes de ejecutar CYMDIST.

`POST /api/contexto/aplicar` es la única operación que persiste la selección de §1.1. Los jobs ordinarios reciben una copia explícita y no cambian el contexto global.

## Campaign API v2

- `GET /api/v2/campaigns/{feeder}` → steps + gates
- `POST /api/v2/campaigns/{feeder}/commands` `{ "command": "RunLoadFlow", "params": { "scenario": "situacional" } }`
- `POST /api/v2/campaigns/{feeder}/skip-spot`
- `GET /api/v2/jobs/{job_id}`

Los jobs legacy también actualizan el ledger de campaña.

## Numerales UI → endpoints

| § | Panel | Endpoints |
|---|-------|-----------|
| 1 | Contexto + cabecera | `GET /api/contexto/archivos`, `POST /api/contexto/aplicar`, `GET|POST /api/cabecera`, `GET /api/cabecera/medicion/archivos`, `GET|POST /api/cabecera/medicion/resolver`, `GET|POST /api/cabecera/medicion/extraer`, `GET /api/ui/ping`, `POST /api/ui/reset` |
| 2 | Calidad + Tablero | `GET/POST /api/calidad/*`, `GET /api/tablero`, `POST /api/clientes/activo` |
| 3 | Clientes + distribución | `GET /api/clientes/*`, `POST /api/clientes/tabla\|aplicar`, `POST /api/distribucion` |
| 4 | SpotLoad | `GET /api/nodos/buscar`, `POST /api/nodos/resolver`, `POST /api/cargas/nueva`, `GET /api/cargas/conectadas`, `GET /api/cargas/plantilla`, `POST /api/cargas/lote/preview`, `POST /api/cargas/lote/conectar`, `GET /api/cargas/pendientes` |
| 5 | Flujos | `POST /api/flujo` (`scenario`: situacional\|proyectado\|omit) |
| 6 | Informes | `GET/POST /api/informe/*` |
| 7 | Opt + Suite | `POST /api/optimizacion/{kind}`, `GET/POST /api/suite/*` |

## Jobs (robustez)

- `POST /api/jobs` `{ "action": "calidad_diagnosticar"\|..., "payload": {} }` → `{ job_id }`
- `GET /api/jobs/{id}` → estado `queued\|running\|ok\|error` + `result`
- `GET /api/jobs/{id}/events` → SSE (`status`, `message`, `done`)
- cada resultado protegido repite `context_identity`/campos y `context_fingerprint`; la SPA descarta una respuesta con huella ajena.

## Informe y procedencia

- LoadFlow y manifiestos `assemble/fill/confirm` incluyen la identidad completa y su huella.
- `doc/` es solo el espejo activo de compatibilidad; la copia auditable vive en `data/output/feeders/<alimentador>/informe/<context_fingerprint>/`.
- vista previa, imágenes, páginas, descargas y cierre validan `fill_manifest.json`; no sirven un informe generado con otra MDB, estudio, red o alimentador.
- las descargas SPA usan `downloadApiFile`, que conserva autenticación y headers de contexto.

Canario de solo lectura:

```powershell
python scripts\validate_universal_context.py --mdb "D:\ruta\red.mdb" --study "D:\ruta\estudio.zxst" --feeder PE104 --network NET_2030_184_PE104 --skip-apply
```

## Tablero

- `GET /api/tablero` → JSON consolidado (diagnóstico + clientes). Ya no se usa `tablero.html` como producto.
