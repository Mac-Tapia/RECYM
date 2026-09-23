# -*- coding: utf-8 -*-
"""FastAPI app RECYM — SPA React + jobs + puente a handlers Flask/pipeline."""
from __future__ import print_function

import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = os.path.join(ROOT, "src")
for p in (_SRC, os.path.join(_SRC, "core"), os.path.join(_SRC, "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_dotenv():
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv()
os.environ.setdefault("RECYM_SPA", "1")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.wsgi import WSGIMiddleware

from api_app.jobs import router as jobs_router
from api_app.routers.tablero import router as tablero_router
from api_app.security import (
    API_KEY_COOKIE,
    auth_enabled,
    client_is_loopback,
    cors_origins,
    environment,
    extract_api_key,
    get_or_create_api_key,
    is_production,
    is_public_path,
    validate_production_boot,
)

UI_VERSION = "6.1-spa-prod"

_openapi_url = None if is_production() else "/openapi.json"
_docs_url = None if is_production() else "/docs"
_redoc_url = None if is_production() else "/redoc"

app = FastAPI(
    title="RECYM UI API",
    version=UI_VERSION,
    description="API §§1–7 demanda Electro Dunas (React + CymPy)",
    openapi_url=_openapi_url,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*", "X-Api-Key", "X-Feeder", "Content-Type", "Authorization"],
)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path or "/"
        if request.method == "OPTIONS" or is_public_path(path):
            return await call_next(request)
        if not auth_enabled():
            return await call_next(request)
        expected = get_or_create_api_key()
        provided = extract_api_key(request)
        if provided and secrets_compare(provided, expected):
            return await call_next(request)
        # Workstation: loopback sin key solo en development (SPA same-origin).
        if not is_production() and client_is_loopback(request):
            return await call_next(request)
        return JSONResponse(
            {
                "ok": False,
                "error": "API key requerida. Envíe header X-Api-Key o use /api/auth/bootstrap.",
                "auth": True,
            },
            status_code=401,
        )


def secrets_compare(a, b):
    try:
        import hmac

        return hmac.compare_digest(str(a), str(b))
    except Exception:
        return a == b


app.add_middleware(ApiKeyMiddleware)

app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
app.include_router(tablero_router, prefix="/api", tags=["tablero"])


@app.on_event("startup")
def _startup_guard():
    errs, warns = validate_production_boot()
    for w in warns:
        print("[RECYM WARN]", w)
    if errs:
        for e in errs:
            print("[RECYM FATAL]", e)
        raise RuntimeError("Arranque production rechazado: " + "; ".join(errs))
    key = get_or_create_api_key()
    print(
        "RECYM env=%s auth=%s api_key=%s… cors=%s"
        % (
            environment(),
            "on" if auth_enabled() else "off",
            (key[:6] if key else "?"),
            ",".join(cors_origins()[:3]),
        )
    )


@app.get("/health")
@app.get("/api/health")
def health():
    isolation = {}
    try:
        from core.cympy_isolation import describe_isolation

        isolation = describe_isolation()
    except Exception as ex:
        isolation = {"error": str(ex)}
    return {
        "ok": True,
        "status": "live",
        "ui_version": UI_VERSION,
        "env": environment(),
        "auth": auth_enabled(),
        "isolation": isolation,
    }


@app.get("/api/health/ready")
@app.get("/health/ready")
def health_ready():
    from api_app.readiness import check_ready

    payload = check_ready()
    code = 200 if payload.get("ok") else 503
    return JSONResponse(payload, status_code=code)


@app.get("/api/auth/bootstrap")
def auth_bootstrap(request: Request):
    """Entrega API key solo a clientes loopback (SPA workstation)."""
    if not client_is_loopback(request):
        return JSONResponse(
            {"ok": False, "error": "bootstrap solo desde localhost"},
            status_code=403,
        )
    key = get_or_create_api_key()
    resp = JSONResponse(
        {
            "ok": True,
            "api_key": key if auth_enabled() else "",
            "auth_required": auth_enabled(),
            "env": environment(),
            "header": "X-Api-Key",
        }
    )
    if auth_enabled() and key:
        resp.set_cookie(
            API_KEY_COOKIE,
            key,
            httponly=False,
            samesite="lax",
            path="/",
        )
    return resp


@app.get("/api/spa/meta")
def spa_meta(request: Request):
    payload = {
        "ok": True,
        "ui_version": UI_VERSION,
        "spa": True,
        "env": environment(),
        "auth_required": auth_enabled(),
        "steps": [
            {"n": 1, "id": "contexto", "title": "Contexto + cabecera"},
            {"n": 2, "id": "calidad", "title": "Calidad + Tablero"},
            {"n": 3, "id": "clientes", "title": "Clientes SED + distribución"},
            {"n": 4, "id": "spotload", "title": "SpotLoad nueva"},
            {"n": 5, "id": "flujos", "title": "Flujos"},
            {"n": 6, "id": "informes", "title": "Informes"},
            {"n": 7, "id": "suite", "title": "Optimización + Suite"},
        ],
    }
    if auth_enabled() and client_is_loopback(request):
        payload["api_key_bootstrap"] = True
    return payload


# Puente: reutilizar todas las rutas /api/* de Flask (misma lógica CymPy).
from ui.demand_app import app as flask_app  # noqa: E402

app.mount("/flask", WSGIMiddleware(flask_app))


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def bridge_flask_api(path: str, request: Request):
    """Reenvía /api/* al Flask legacy excepto rutas ya definidas en FastAPI."""
    from starlette.responses import Response

    if path == "tablero" or path == "spa/meta" or path == "jobs" or path.startswith("jobs/") or path == "health" or path.startswith("health/") or path.startswith("auth/"):
        return JSONResponse({"ok": False, "error": "ruta FastAPI nativa"}, status_code=404)

    body = await request.body()
    environ = {
        "REQUEST_METHOD": request.method,
        "SCRIPT_NAME": "",
        "PATH_INFO": "/api/" + path,
        "QUERY_STRING": request.url.query.encode("latin-1") if isinstance(request.url.query, str) else (request.url.query or b""),
        "SERVER_NAME": request.url.hostname or "127.0.0.1",
        "SERVER_PORT": str(request.url.port or 5055),
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": request.url.scheme,
        "wsgi.input": io.BytesIO(body or b""),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "CONTENT_LENGTH": str(len(body or b"")),
    }
    if isinstance(environ["QUERY_STRING"], bytes):
        environ["QUERY_STRING"] = environ["QUERY_STRING"].decode("latin-1")
    ct = request.headers.get("content-type")
    if ct:
        environ["CONTENT_TYPE"] = ct
    for k, v in request.headers.items():
        key = "HTTP_" + k.upper().replace("-", "_")
        if key not in ("HTTP_CONTENT_LENGTH", "HTTP_CONTENT_TYPE"):
            environ[key] = v

    status_headers = []

    def start_response(status, headers, exc_info=None):
        status_headers[:] = [status, headers]

    result = flask_app(environ, start_response)
    raw = b"".join(result)
    status = int(status_headers[0].split()[0]) if status_headers else 500
    headers = status_headers[1] if len(status_headers) > 1 else []
    media = "application/json"
    out_headers = {}
    for hk, hv in headers:
        low = hk.lower()
        if low == "content-type":
            media = hv
        elif low in ("content-disposition", "cache-control", "content-length"):
            out_headers[hk] = hv
    return Response(content=raw, status_code=status, media_type=media, headers=out_headers)


_WEB_DIST = os.path.join(ROOT, "web", "dist")
_INDEX = os.path.join(_WEB_DIST, "index.html")

if os.path.isdir(os.path.join(_WEB_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_WEB_DIST, "assets")), name="assets")


@app.get("/")
def spa_root():
    if os.path.isfile(_INDEX):
        return FileResponse(_INDEX)
    return JSONResponse(
        {
            "ok": True,
            "spa": False,
            "msg": "Build React pendiente: cd web && npm install && npm run build",
            "legacy": "/flask/",
            "docs": "/docs",
        }
    )


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    blocked = (
        full_path.startswith("api/")
        or full_path.startswith("flask/")
        or full_path.startswith("docs")
        or full_path.startswith("redoc")
        or full_path == "openapi.json"
        or full_path.startswith("health")
    )
    if blocked:
        return JSONResponse({"ok": False, "error": "Not found"}, status_code=404)
    candidate = os.path.join(_WEB_DIST, full_path.replace("/", os.sep))
    if os.path.isfile(candidate):
        return FileResponse(candidate)
    if os.path.isfile(_INDEX):
        return FileResponse(_INDEX)
    return JSONResponse({"ok": False, "error": "SPA no construida", "path": full_path}, status_code=404)


def main():
    import uvicorn

    port = int(os.environ.get("RECYM_UI_PORT") or "5055")
    host = os.environ.get("RECYM_UI_HOST") or "127.0.0.1"
    print("RECYM SPA API v%s · http://%s:%s/" % (UI_VERSION, host, port))
    uvicorn.run(
        "api_app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
