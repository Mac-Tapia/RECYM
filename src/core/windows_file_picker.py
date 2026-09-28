# -*- coding: utf-8 -*-
"""Local Windows file picker for paths consumed directly by CYMDIST."""
from __future__ import print_function

import json
import os
import subprocess
import threading

from core.context_identity import canonical_file_path


_PICKER_LOCK = threading.Lock()
_STUDY_EXTENSIONS = (".zxst", ".sxst", ".zsxst", ".xst")
_POWERSHELL = r"""
Add-Type -AssemblyName System.Windows.Forms
$kind = $env:RECYM_PICKER_KIND
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Multiselect = $false
$dialog.CheckFileExists = $true
if ($kind -eq 'database') {
  $dialog.Title = 'Seleccione base de datos CYMDIST'
  $dialog.Filter = 'Base CYMDIST (*.mdb)|*.mdb'
} else {
  $dialog.Title = 'Seleccione estudio CYMDIST'
  $dialog.Filter = 'Estudio CYMDIST (*.zxst;*.sxst;*.zsxst;*.xst)|*.zxst;*.sxst;*.zsxst;*.xst'
}
if ($env:RECYM_PICKER_INITIAL_DIR -and (Test-Path -LiteralPath $env:RECYM_PICKER_INITIAL_DIR)) {
  $dialog.InitialDirectory = $env:RECYM_PICKER_INITIAL_DIR
}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
  @{ path = $dialog.FileName; cancelled = $false } | ConvertTo-Json -Compress
} else {
  @{ cancelled = $true } | ConvertTo-Json -Compress
}
$dialog.Dispose()
"""


def _error(code, message, kind=None):
    result = {"ok": False, "error_code": code, "error": message}
    if kind:
        result["kind"] = kind
    return result


def _parse_json_output(raw):
    for line in reversed(str(raw or "").splitlines()):
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def pick_context_file(kind, initial_dir=None, timeout=600, runner=None):
    """Open the workstation picker and return a path only, never file contents."""
    kind = str(kind or "").strip().lower()
    if kind not in ("database", "study"):
        return _error("INVALID_PICKER_KIND", "Tipo de selector inválido: %s" % kind)
    if runner is None and os.name != "nt":
        return _error("PICKER_UNAVAILABLE", "Selector disponible solo en Windows", kind)

    execute = runner or subprocess.run
    env = os.environ.copy()
    env["RECYM_PICKER_KIND"] = kind
    env["RECYM_PICKER_INITIAL_DIR"] = str(initial_dir or "")
    args = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-STA",
        "-NonInteractive",
        "-Command",
        _POWERSHELL,
    ]
    try:
        with _PICKER_LOCK:
            completed = execute(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=float(timeout),
            )
    except subprocess.TimeoutExpired:
        return _error("PICKER_TIMEOUT", "El selector excedió %s segundos" % timeout, kind)
    except Exception as ex:
        return _error("PICKER_UNAVAILABLE", "No se pudo abrir el selector: %s" % ex, kind)

    if int(getattr(completed, "returncode", 1) or 0) != 0:
        detail = str(getattr(completed, "stderr", "") or "").strip()
        return _error(
            "PICKER_UNAVAILABLE",
            "PowerShell no pudo abrir el selector%s"
            % ((": " + detail) if detail else ""),
            kind,
        )
    payload = _parse_json_output(getattr(completed, "stdout", ""))
    if not isinstance(payload, dict):
        return _error("PICKER_UNAVAILABLE", "Respuesta inválida del selector", kind)
    if payload.get("cancelled") or not payload.get("path"):
        return {"ok": True, "cancelled": True, "kind": kind}

    path = os.path.realpath(os.path.abspath(os.path.normpath(str(payload["path"]))))
    if not os.path.isfile(path):
        return _error("FILE_NOT_FOUND", "Archivo seleccionado no encontrado: %s" % path, kind)
    extension = os.path.splitext(path)[1].lower()
    allowed = (".mdb",) if kind == "database" else _STUDY_EXTENSIONS
    if extension not in allowed:
        return _error(
            "INVALID_FILE_EXTENSION",
            "Extensión no permitida para %s: %s" % (kind, extension or "(sin extensión)"),
            kind,
        )
    if kind == "study" and os.path.getsize(path) < 1024:
        return _error(
            "STUDY_FILE_INVALID",
            "Estudio vacío o demasiado pequeño: %s" % path,
            kind,
        )
    return {
        "ok": True,
        "cancelled": False,
        "kind": kind,
        "path": path,
        "canonical_path": canonical_file_path(path),
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
    }


__all__ = ["pick_context_file"]
