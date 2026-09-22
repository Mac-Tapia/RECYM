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

os.environ.setdefault("RECYM_SPA", "1")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.wsgi import WSGIMiddleware

from api_app.jobs import router as jobs_router
from api_app.routers.tablero import router as tablero_router

UI_VERSION = "6.0-spa"

app = FastAPI(
    title="RECYM UI API",
    version=UI_VERSION,
    description="API §§1–7 demanda Electro Dunas (React + CymPy)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
app.include_router(tablero_router, prefix="/api", tags=["tablero"])


@app.get("/api/spa/meta")
def spa_meta():
    return {
        "ok": True,
        "ui_version": UI_VERSION,
        "spa": True,
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


# Puente: reutilizar todas las rutas /api/* de Flask (misma lógica CymPy).
from ui.demand_app import app as flask_app  # noqa: E402

app.mount("/flask", WSGIMiddleware(flask_app))


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def bridge_flask_api(path: str, request: Request):
    """Reenvía /api/* al Flask legacy excepto rutas ya definidas en FastAPI."""
    from starlette.responses import Response

    # Evitar sombrear routers FastAPI si el catch-all gana el match.
    if path == "tablero" or path == "spa/meta" or path == "jobs" or path.startswith("jobs/"):
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
    for hk, hv in headers:
        if hk.lower() == "content-type":
            media = hv
            break
    return Response(content=raw, status_code=status, media_type=media)


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
