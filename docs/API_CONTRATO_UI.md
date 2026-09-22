# Contrato API UI RECYM (§§1–7)

Base: `http://127.0.0.1:5055`  
Header de contexto: `X-Feeder: <ID>` (opcional; también `feeder` en query/body).

## Numerales UI → endpoints

| § | Panel | Endpoints |
|---|-------|-----------|
| 1 | Contexto + cabecera | `GET /api/contexto/archivos`, `POST /api/contexto/aplicar`, `POST /api/cabecera`, `GET /api/ui/ping`, `POST /api/ui/reset` |
| 2 | Calidad + Tablero | `GET/POST /api/calidad/*`, `GET /api/tablero`, `POST /api/clientes/activo` |
| 3 | Clientes + distribución | `GET /api/clientes/*`, `POST /api/clientes/tabla\|aplicar`, `POST /api/distribucion` |
| 4 | SpotLoad | `POST /api/nodos/*`, `GET /api/nodos/buscar`, `POST /api/cargas/nueva` |
| 5 | Flujos | `POST /api/flujo` (`scenario`: situacional\|proyectado\|omit) |
| 6 | Informes | `GET/POST /api/informe/*` |
| 7 | Opt + Suite | `POST /api/optimizacion/{kind}`, `GET/POST /api/suite/*` |

## Jobs (robustez)

- `POST /api/jobs` `{ "action": "calidad_diagnosticar"\|..., "payload": {} }` → `{ job_id }`
- `GET /api/jobs/{id}` → estado `queued\|running\|ok\|error` + `result`
- `GET /api/jobs/{id}/events` → SSE (`status`, `message`, `done`)

## Tablero

- `GET /api/tablero` → JSON consolidado (diagnóstico + clientes). Ya no se usa `tablero.html` como producto.
