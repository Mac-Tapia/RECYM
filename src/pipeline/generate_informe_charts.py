# -*- coding: utf-8 -*-
"""
Genera PNG de informe desde metricas LoadFlow situacional / proyectado.

Slots LF (obligatorios para entrega):
  situacional_tension.png | situacional_cargabilidad.png
  proyectado_tension.png  | proyectado_cargabilidad.png

No sobrescribe un PNG manual si su mtime es mas reciente que el JSON LF fuente.
"""
from __future__ import print_function
import os
from datetime import datetime

REQUIRED_LF_IMAGES = (
    "situacional_tension.png",
    "situacional_cargabilidad.png",
    "proyectado_tension.png",
    "proyectado_cargabilidad.png",
)

# Informe técnico solo estado situacional (Electro Dunas): 2 PNG de coloreo
SITUACIONAL_LF_IMAGES = (
    "situacional_tension.png",
    "situacional_cargabilidad.png",
)


def required_lf_images_for_mode(mode=None):
    """Imágenes obligatorias según modo de informe (completo | situacional)."""
    m = str(mode or "completo").strip().lower()
    if m in ("situacional", "sit", "estado_situacional", "diagnostico_situacional"):
        return SITUACIONAL_LF_IMAGES
    return REQUIRED_LF_IMAGES


def _mtime(path):
    try:
        return os.path.getmtime(path) if path and os.path.isfile(path) else 0.0
    except Exception:
        return 0.0


def _is_cymdist_capture(png_path):
    side = (png_path or "") + ".cymdist.json"
    if not png_path or not os.path.isfile(png_path):
        return False
    if os.path.isfile(side):
        try:
            import json
            meta = json.load(open(side, encoding="utf-8"))
            return str(meta.get("source") or "").startswith("cymdist")
        except Exception:
            return True
    return False


def _should_skip(png_path, lf_json_path):
    """True si PNG manual/cymdist es mas reciente que el JSON LF fuente.

    Si el LoadFlow §5 es mas nuevo que la captura, NO omitir: hay que
    regenerar para que situacional/proyectado reflejen el flujo actual.
    """
    if not os.path.isfile(png_path):
        return False
    lf_m = _mtime(lf_json_path)
    png_m = _mtime(png_path)
    # LF mas nuevo que la imagen → regenerar (aunque sea captura CYMDIST)
    if lf_m > 0 and png_m > 0 and lf_m > png_m + 1.0:
        return False
    if _is_cymdist_capture(png_path):
        return True
    if lf_m <= 0:
        return True
    return png_m > lf_m + 1.0


def _save_fig(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight", facecolor="white")
    try:
        import matplotlib.pyplot as plt
        plt.close(fig)
    except Exception:
        pass


def _plot_tension(metrics, title, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["Fase A", "Fase B", "Fase C"]
    vals = [
        metrics.get("v_pct_a") or 0.0,
        metrics.get("v_pct_b") or 0.0,
        metrics.get("v_pct_c") or 0.0,
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    bars = ax.bar(labels, vals, color=["#2f6fed", "#3d8b40", "#c47a00"], width=0.55)
    ax.axhline(95.0, color="#b00020", linestyle="--", linewidth=1.2, label="Limite 95%")
    ax.axhline(105.0, color="#b00020", linestyle=":", linewidth=1.2, label="Limite 105%")
    ax.set_ylabel("Tension (%)")
    ax.set_xlabel("Fase")
    ax.set_title(title)
    ax.set_ylim(90.0, max(108.0, max(vals) + 2.0 if vals else 108.0))
    ax.legend(loc="lower right", fontsize=8)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2.0, v + 0.25, "%.2f" % v,
                ha="center", va="bottom", fontsize=9)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save_fig(fig, out_path)


def _plot_cargabilidad(metrics, title, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = ["kW", "kvar", "kVA", "Perdidas kW"]
    vals = [
        metrics.get("kw") or 0.0,
        metrics.get("kvar") or 0.0,
        metrics.get("kva") or 0.0,
        metrics.get("kw_loss") or 0.0,
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    colors = ["#2f6fed", "#6a5acd", "#3d8b40", "#b00020"]
    bars = ax.bar(labels, vals, color=colors, width=0.6)
    ax.set_ylabel("Potencia")
    ax.set_xlabel("Magnitud")
    ax.set_title(title)
    ymax = max(vals) if vals else 1.0
    ax.set_ylim(0.0, ymax * 1.18 if ymax > 0 else 1.0)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2.0, v + ymax * 0.02, "%.1f" % v,
                ha="center", va="bottom", fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save_fig(fig, out_path)


def _plot_trafo_cargabilidad(sit, proy, out_path, rated_mva=30.0):
    """Barras de cargabilidad del trafo SET (kVA cabecera / MVA nominal)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rated_kva = float(rated_mva) * 1000.0
    def _pct(m):
        if not m:
            return 0.0
        kva = m.get("kva")
        if kva is None:
            return 0.0
        return 100.0 * float(kva) / rated_kva

    labels = ["Situacional", "Proyectado"]
    vals = [_pct(sit), _pct(proy)]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    colors = ["#2f6fed", "#c47a00"]
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.axhline(80.0, color="#3d8b40", linestyle="--", linewidth=1.0, label="80%")
    ax.axhline(100.0, color="#b00020", linestyle=":", linewidth=1.0, label="100%")
    ax.set_ylabel("Cargabilidad trafo (%)")
    ax.set_title("Cargabilidad transformador SET (base %.0f MVA)" % rated_mva)
    ax.set_ylim(0.0, max(110.0, max(vals) * 1.15 if vals else 110.0))
    ax.legend(loc="upper right", fontsize=8)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2.0, v + 1.0, "%.1f%%" % v,
                ha="center", va="bottom", fontsize=10)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    _save_fig(fig, out_path)


def generate_informe_charts(img_dir, scenarios, paths=None, force=False):
    """
    Genera los 4 PNG LF en img_dir (+ trafo_cargabilidad si falta).
    scenarios: dict con situacional/proyectado (metrics_from_lf).
    paths: informe_paths (para mtime de JSON).
    Errores de escenario ausente van a `pending` (no a `errors`) para no
    ensuciar el gate cuando aun falta correr el otro LF.
    """
    paths = paths or {}
    mkdir = __import__("core.common", fromlist=["mkdir"]).mkdir
    mkdir(img_dir)

    generated = []
    skipped = []
    pending = []
    errors = []

    jobs = [
        ("situacional", "tension", "situacional_tension.png",
         "Tension cabecera — estado situacional (sin carga nueva)",
         paths.get("loadflow_situacional")),
        ("situacional", "cargabilidad", "situacional_cargabilidad.png",
         "Demanda / perdidas — estado situacional (sin carga nueva)",
         paths.get("loadflow_situacional")),
        ("proyectado", "tension", "proyectado_tension.png",
         "Tension cabecera — estado proyectado (con carga nueva)",
         paths.get("loadflow_proyectado")),
        ("proyectado", "cargabilidad", "proyectado_cargabilidad.png",
         "Demanda / perdidas — estado proyectado (con carga nueva)",
         paths.get("loadflow_proyectado")),
    ]

    for scenario_key, kind, fname, title, lf_json in jobs:
        m = scenarios.get(scenario_key)
        if not m:
            pending.append(fname)
            continue
        out = os.path.join(img_dir, fname)
        # Nunca pisar capturas CYMDIST de coloreo §5 con barras matplotlib
        if _is_cymdist_capture(out):
            skipped.append({"file": fname, "reason": "cymdist_capture_preserved"})
            continue
        if not force and _should_skip(out, lf_json):
            skipped.append({"file": fname, "reason": "manual_newer_than_lf"})
            continue
        try:
            if kind == "tension":
                _plot_tension(m, title, out)
            else:
                _plot_cargabilidad(m, title, out)
            # Si habia sidecar CYMDIST huerfano, limpiarlo (ya no aplica)
            side = out + ".cymdist.json"
            if os.path.isfile(side):
                try:
                    os.remove(side)
                except Exception:
                    pass
            generated.append({
                "file": fname,
                "path": out,
                "scenario": scenario_key,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "loadflow_json",
            })
        except Exception as ex:
            errors.append("%s: %s" % (fname, ex))

    # Grafico trafo SET (image10) — no es captura CYMDIST
    trafo_out = os.path.join(img_dir, "trafo_cargabilidad.png")
    if scenarios.get("situacional") or scenarios.get("proyectado"):
        if force or not os.path.isfile(trafo_out):
            try:
                _plot_trafo_cargabilidad(
                    scenarios.get("situacional"),
                    scenarios.get("proyectado"),
                    trafo_out,
                )
                generated.append({
                    "file": "trafo_cargabilidad.png",
                    "path": trafo_out,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "source": "loadflow_json",
                })
            except Exception as ex:
                errors.append("trafo_cargabilidad.png: %s" % ex)
        else:
            skipped.append({"file": "trafo_cargabilidad.png", "reason": "exists"})

    present = [f for f in REQUIRED_LF_IMAGES if os.path.isfile(os.path.join(img_dir, f))]
    missing = [f for f in REQUIRED_LF_IMAGES if f not in present]
    return {
        "ok": len(missing) == 0 and not errors,
        "generated": generated,
        "skipped": skipped,
        "pending": pending,
        "errors": errors,
        "present": present,
        "missing": missing,
        "images_dir": img_dir,
    }


def main():
    from core.feeder_context import load_settings
    from pipeline.fill_informe import _load_scenarios
    import json

    s = load_settings()
    sc = _load_scenarios(s)
    out_base = s.get("output_dir") or os.path.join("data", "output", "feeders", str(s.get("feeder_id") or "feeder"))
    if not os.path.isabs(out_base):
        from core.common import p
        img_dir = p(*(out_base.replace("\\", "/").split("/") + ["informe_images"]))
    else:
        img_dir = os.path.join(out_base, "informe_images")
    res = generate_informe_charts(img_dir, sc, paths=sc.get("paths"))
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    if not res.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
