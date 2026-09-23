# RECYM — Puesta en producción (estación Windows + CYME)

Objetivo: **estación de ingeniería licenciada por sede**, no SaaS cloud.
Cyme/CymPy debe vivir en la misma máquina Windows.

## Qué exige la industria (fuentes web) vs RECYM

Referencias:

- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) — orígenes explícitos; no `*` con credentials
- [FastAPI Pre-Deployment Checklist](https://fastro.ai/blog/fastapi-deployment-checklist) — secrets, auth E2E, timeouts
- [Fastro production validator](https://benavlabs.github.io/FastAPI-boilerplate/user-guide/production/) — rechazar boot si `SECRET` débil / CORS `*` / docs en prod
- [K8s health probes](https://markaicode.com/integrate/fastapi-with-kubernetes/) — `/health` live vs ready (adaptado a workstation)
- Empaquetado Windows MSI (Briefcase / WiX) — instalador versionado

| Requisito producción | Estado RECYM | Acción |
|---|---|---|
| Secrets fuera de git (`.env`, API key) | Hecho P0 | `.env`, `config/.api_key`, `settings.local.json` gitignored |
| CORS allow-list (no `*`) | Hecho P0 | `RECYM_CORS_ORIGINS` |
| Auth en API | Hecho P0 | `X-Api-Key` + bootstrap localhost |
| `/health` liveness | Hecho P0 | `GET /health` |
| `/api/health/ready` | Hecho P0 | Cyme + mdb + SPA + worker |
| Docs `/docs` off en prod | Hecho P0 | `RECYM_ENV=production` |
| Bind localhost por defecto | Hecho | `RECYM_UI_HOST=127.0.0.1` |
| Settings tipados / overlay local | Hecho P0 | `settings.local.json` gana sobre `settings.json` |
| Error Boundary SPA | Hecho P0 | `web/src/components/ErrorBoundary.tsx` |
| Build SPA en arranque | Hecho P0 | `20_demand_ui.bat` + `RECYM_FORCE_SPA_BUILD` |
| Aislamiento COM (crash ≠ tumba API) | Hecho P0 | Jobs peligrosos → `job_worker_cli` |
| Rate limit / HTTPS / reverse proxy | Pendiente | Solo si se abre a LAN/VPN |
| Roles / multi-usuario | Pendiente P2 | |
| Instalador MSI + semver | Pendiente P2 | |
| Tests + CI smoke | Pendiente P1–P2 | |
| Ready check Cyme instalado | Pendiente | Extender `/api/health` |
| Observabilidad (métricas/APM) | Pendiente P2 | |
| Política PII clientes | Pendiente P2 | |

## Arranque desarrollo (estación)

```bat
scripts\20_demand_ui.bat
```

1. Copia `.env.example` → `.env` (opcional).
2. Opcional: `copy config\settings.example.json config\settings.local.json` y edita rutas.
3. Abre `http://127.0.0.1:5055/` — la SPA hace bootstrap de API key sola.

## Arranque “producción local”

```bat
scripts\20_demand_ui_production.bat
```

Equivale a:

- `RECYM_ENV=production`
- `RECYM_AUTH=1`
- rebuild SPA forzado
- sin `/docs`
- API key obligatoria (incluso localhost; bootstrap la entrega)
- Jobs CymPy en **worker aislado** (`RECYM_ISOLATE_JOBS=1` por defecto)

### Health

| Endpoint | Uso |
|---|---|
| `GET /health` | Liveness (proceso vivo) |
| `GET /api/health/ready` | Ready: Cyme, cympy, mdb, projects, SPA, worker CLI |

Smoke sin UI:

```bat
.tools\python37-win32\python.exe -u scripts\smoke_ready_isolation.py
```

### Aislamiento COM

Acciones `calidad_*`, `distribucion`, `flujo` corren en subproceso (`job_worker_cli.py`).
Si el hijo muere con `0xC0000005`, la API responde error del job y **sigue viva**.

Desactivar solo en lab: `set RECYM_ISOLATE_JOBS=0`

## Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| `RECYM_ENV` | `development` | `production` endurece boot y docs |
| `RECYM_AUTH` | `1` | `0` solo lab |
| `RECYM_API_KEY` | auto `config/.api_key` | Header `X-Api-Key` |
| `RECYM_CORS_ORIGINS` | localhost:5055 + Vite 5173 | Lista CSV |
| `RECYM_UI_HOST` | `127.0.0.1` | No usar `0.0.0.0` sin `RECYM_ALLOW_LAN=1` |
| `RECYM_UI_PORT` | `5055` | |
| `RECYM_FORCE_SPA_BUILD` | off | `1` recompila React |
| `GOOGLE_MAPS_API_KEY` | — | Override settings |

## Checklist go-live sede (operador)

- [ ] CYME 9.x instalado; `cyme_root` correcto
- [ ] `settings.local.json` con `studies_root` / `database_mdb` / `projects_dir`
- [ ] `.env` con `RECYM_ENV=production` y key rotada
- [ ] `scripts\20_demand_ui_production.bat` arranca sin `[RECYM FATAL]`
- [ ] `GET http://127.0.0.1:5055/health` → `ok`
- [ ] Smoke §§1–5 en alimentador piloto (p.ej. PA217)
- [ ] Backup de `.zxst` antes de writes (`auto_backup`)
- [ ] Documentar contacto soporte + runbook COM (reabrir estudio)

## Qué aún falta para “producción comercial”

1. **Smoke E2E §§1–5** automatizado + gate de release (el smoke ready ya existe).
2. **Instalador** + versión semver + changelog.
3. **Roles** admin/operador/lectura.
4. Si algún día es **LAN/VPN**: TLS, rate limit, no exponer `0.0.0.0` sin firewall.
5. ~~Cablear rutas Flask calidad al worker~~ (hecho; quedan otras sync no-calidad).

## Siguiente implementación (orden)

1. ~~Tests contrato 401/health/ready~~ → `scripts\30_contract_tests.bat`
2. P1 split `demand_app` (routers por §)
3. Instalador + roles (P2)
