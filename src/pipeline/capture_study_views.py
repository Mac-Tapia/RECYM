# -*- coding: utf-8 -*-
"""
Captura de vistas del estudio CYMDIST (GUI Cyme.exe) para el informe.

Prioridad:
  1) Ventana Cyme.exe visible → PrintWindow / BitBlt → PNG
  2) Si no hay GUI → None (el informe usa graficas LoadFlow)

Salidas tipicas en informe_images/:
  estudio_situacional.png | estudio_proyectado.png | estudio_topologia.png
"""
from __future__ import print_function
import os
import time
from datetime import datetime


def _mkdir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


def cyme_hwnd():
    """HWND de la ventana principal Cyme.exe (o None)."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
    )
    IsWindowVisible = user32.IsWindowVisible
    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    found = []

    def _cb(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value or ""
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        # Titulo tipico: "CYME ..." o contiene el .zxst
        if "CYME" in title.upper() or title.lower().endswith(".zxst"):
            found.append((hwnd, title, int(pid.value)))
        return True

    EnumWindows(EnumWindowsProc(_cb), 0)
    if not found:
        return None
    # Preferir la mas grande / con estudio
    return found[0][0]


def capture_hwnd_png(hwnd, out_path):
    """Captura cliente de ventana HWND a PNG (PrintWindow + BitBlt)."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    GetClientRect = user32.GetClientRect
    GetWindowDC = user32.GetWindowDC
    ReleaseDC = user32.ReleaseDC
    PrintWindow = user32.PrintWindow
    CreateCompatibleDC = gdi32.CreateCompatibleDC
    CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
    SelectObject = gdi32.SelectObject
    BitBlt = gdi32.BitBlt
    DeleteObject = gdi32.DeleteObject
    DeleteDC = gdi32.DeleteDC
    GetDIBits = gdi32.GetDIBits

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    rect = RECT()
    if not GetClientRect(hwnd, ctypes.byref(rect)):
        return False
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 80 or height < 80:
        return False

    hwnd_dc = GetWindowDC(hwnd)
    mem_dc = CreateCompatibleDC(hwnd_dc)
    bmp = CreateCompatibleBitmap(hwnd_dc, width, height)
    old = SelectObject(mem_dc, bmp)
    # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    ok = PrintWindow(hwnd, mem_dc, 2)
    if not ok:
        SRCCOPY = 0x00CC0020
        BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)

    bmi = BITMAPINFO()
    ctypes.memset(ctypes.byref(bmi), 0, ctypes.sizeof(bmi))
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf_len = width * height * 4
    buf = (ctypes.c_char * buf_len)()
    GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), 0)

    SelectObject(mem_dc, old)
    DeleteObject(bmp)
    DeleteDC(mem_dc)
    ReleaseDC(hwnd, hwnd_dc)

    img = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)
    _mkdir(os.path.dirname(out_path))
    img.save(out_path, "PNG", optimize=True)
    return os.path.isfile(out_path)


def capture_cyme_view(out_path, bring_to_front=True, settle_s=0.6):
    """
    Captura la vista actual de Cyme a out_path.
    Retorna dict {ok, path, error?, hwnd?}.
    """
    hwnd = cyme_hwnd()
    if not hwnd:
        return {"ok": False, "error": "Cyme.exe no visible (abra el estudio en CYMDIST)", "path": out_path}
    try:
        import ctypes
        if bring_to_front:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(float(settle_s))
        ok = capture_hwnd_png(hwnd, out_path)
        return {
            "ok": bool(ok),
            "path": out_path,
            "hwnd": int(hwnd),
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "error": None if ok else "PrintWindow/BitBlt fallo",
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "path": out_path}


def capture_study_for_informe(img_dir, label="topologia", open_gui=False, settings=None):
    """
    Captura estudio → informe_images/estudio_<label>.png
    Si open_gui=True intenta abrir CYMDIST via COM antes de capturar.
    """
    _mkdir(img_dir)
    out = os.path.join(img_dir, "estudio_%s.png" % label)
    if open_gui and settings:
        try:
            from core.cymdist_com import open_cymdist_gui, cyme_is_running
            if not cyme_is_running():
                open_cymdist_gui(settings, kill_existing=False, reason="informe_capture")
                time.sleep(2.0)
        except Exception as ex:
            return {"ok": False, "error": "open_gui: %s" % ex, "path": out}
    res = capture_cyme_view(out)
    res["label"] = label
    return res
