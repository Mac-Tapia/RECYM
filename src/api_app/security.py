# -*- coding: utf-8 -*-
"""Auth API key + CORS/env de producción para estación RECYM."""
from __future__ import print_function

import os
import secrets

from core.common import mkdir, p

API_KEY_HEADER = "X-Api-Key"
API_KEY_QUERY = "api_key"
API_KEY_COOKIE = "recym_api_key"
API_KEY_FILE = "config/.api_key"

# Rutas públicas (sin API key).
PUBLIC_PATH_PREFIXES = (
    "/assets/",
    "/favicon",
    "/health",
    "/api/health",
    "/api/spa/meta",
    "/api/auth/bootstrap",
)
PUBLIC_EXACT = ("/", "/docs", "/redoc", "/openapi.json")


def environment():
    return (os.environ.get("RECYM_ENV") or os.environ.get("ENVIRONMENT") or "development").strip().lower()


def is_production():
    return environment() in ("production", "prod", "prod-local")


def cors_origins():
    raw = (os.environ.get("RECYM_CORS_ORIGINS") or "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip() and x.strip() != "*"]
    port = os.environ.get("RECYM_UI_PORT") or "5055"
    return [
        "http://127.0.0.1:%s" % port,
        "http://localhost:%s" % port,
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]


def _api_key_path():
    return p(*API_KEY_FILE.split("/"))


def get_or_create_api_key():
    """Lee RECYM_API_KEY / archivo local; genera uno si falta (workstation)."""
    env_key = (os.environ.get("RECYM_API_KEY") or "").strip()
    if env_key:
        return env_key
    path = _api_key_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = (f.read() or "").strip()
            if key:
                return key
        except Exception:
            pass
    key = secrets.token_urlsafe(32)
    try:
        mkdir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(key + "\n")
    except Exception:
        pass
    os.environ["RECYM_API_KEY"] = key
    return key


def auth_enabled():
    """Auth activa salvo RECYM_AUTH=0 (solo lab explícito)."""
    flag = (os.environ.get("RECYM_AUTH") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def extract_api_key(request):
    header = request.headers.get(API_KEY_HEADER) or request.headers.get("x-api-key")
    if header:
        return header.strip()
    try:
        q = request.query_params.get(API_KEY_QUERY)
        if q:
            return str(q).strip()
    except Exception:
        pass
    cookie = request.cookies.get(API_KEY_COOKIE)
    if cookie:
        return cookie.strip()
    return ""


def is_public_path(path):
    if not path:
        return True
    if path in PUBLIC_EXACT:
        return True
    for pref in PUBLIC_PATH_PREFIXES:
        if path == pref.rstrip("/") or path.startswith(pref):
            return True
    # Flask bridge y API de negocio: protegidos
    if path.startswith("/api") or path.startswith("/flask"):
        return False
    # Rutas SPA (HTML/JS) públicas; la API lleva la auth
    return True


def client_is_loopback(request):
    try:
        host = (request.client.host if request.client else "") or ""
    except Exception:
        host = ""
    host = host.strip().lower()
    return host in ("127.0.0.1", "::1", "localhost")


def validate_production_boot():
    """Fallos duros al arrancar en RECYM_ENV=production."""
    errors = []
    warnings = []
    if not is_production():
        return errors, warnings

    if not auth_enabled():
        errors.append("RECYM_AUTH=0 no permitido en production")
    key = get_or_create_api_key()
    if not key or len(key) < 16:
        errors.append("RECYM_API_KEY demasiado corta (<16)")
    origins = cors_origins()
    if not origins:
        errors.append("RECYM_CORS_ORIGINS vacío")
    if "*" in origins:
        errors.append("CORS no puede ser * en production")
    host = (os.environ.get("RECYM_UI_HOST") or "127.0.0.1").strip()
    if host in ("0.0.0.0", "::") and not (os.environ.get("RECYM_ALLOW_LAN") or "").strip():
        warnings.append(
            "RECYM_UI_HOST=%s expone la API en red; defina RECYM_ALLOW_LAN=1 conscientemente" % host
        )
    return errors, warnings
