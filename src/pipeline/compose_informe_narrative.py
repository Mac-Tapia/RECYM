# -*- coding: utf-8 -*-
"""
Redaccion formal del informe de factibilidad (con/sin proyecto).

Genera parrafos tecnicos en espanol para:
  - Antecedentes / objeto
  - Analisis de tension (caidas)
  - Analisis de cargabilidad
  - Comparativo situacional vs proyectado
  - Conclusiones y recomendaciones

Salida: demand/informe_narrative.json (+ texto plano)
"""
from __future__ import print_function
import json
import os
from datetime import datetime


def _fmt(val, nd=2):
    if val is None:
        return "—"
    try:
        return ("%." + str(nd) + "f") % float(val)
    except Exception:
        return str(val)


def _pct(val, nd=2):
    if val is None:
        return "—"
    return _fmt(val, nd) + " %"


def _delta(a, b, nd=2):
    if a is None or b is None:
        return None
    return round(float(b) - float(a), nd)


def compose_narrative(meta, scenarios, utility="Electro Dunas"):
    """
    meta: informe_meta / _meta_cliente
    scenarios: {situacional, proyectado} metrics_from_lf
    """
    meta = meta or {}
    sit = scenarios.get("situacional") or {}
    proy = scenarios.get("proyectado") or {}
    cliente = meta.get("cliente") or "el solicitante"
    ubic = meta.get("ubicacion") or ""
    feeder = meta.get("alimentador") or sit.get("feeder_id") or proy.get("feeder_id") or ""
    proyecto = meta.get("proyecto") or ""
    pot = meta.get("potencia_kw")
    pot_txt = meta.get("potencia_txt") or (("%d kW" % int(round(pot))) if pot is not None else "")
    tension = meta.get("tension_kv") or sit.get("vll") or proy.get("vll") or 22.9
    expediente = meta.get("expediente") or ""
    solicitud = meta.get("solicitud") or "Factibilidad y Punto de Diseño"

    d_kw = _delta(sit.get("kw"), proy.get("kw"))
    d_kvar = _delta(sit.get("kvar"), proy.get("kvar"))
    d_kva = _delta(sit.get("kva"), proy.get("kva"))
    d_v = _delta(sit.get("v_pct_a") or sit.get("vpu"), proy.get("v_pct_a") or proy.get("vpu"))

    # Caida respecto a nominal (100%)
    def _caida(m):
        vp = m.get("v_pct_a")
        if vp is None and m.get("vpu") is not None:
            vp = float(m["vpu"]) * 100.0
        if vp is None:
            return None
        return round(100.0 - float(vp), 2)

    caida_sit = _caida(sit)
    caida_proy = _caida(proy)

    antecedentes = (
        "La presente evaluación técnica se elabora a solicitud de %s%s, "
        "en el marco del expediente %s, respecto del alimentador %s operado por %s, "
        "a un nivel de tensión nominal de %s kV. El objeto del estudio es determinar "
        "la factibilidad de conexión y el punto de diseño asociado a una demanda "
        "máxima de %s%s."
    ) % (
        cliente,
        (" — proyecto «%s»" % proyecto) if proyecto else "",
        expediente or "en trámite",
        feeder or "indicado",
        utility,
        _fmt(tension, 1),
        pot_txt or "la potencia solicitada",
        (", ubicado en %s" % ubic) if ubic else "",
    )

    objeto = (
        "Se contrastan dos estados de operación del alimentador %s: (i) escenario "
        "situacional o sin proyecto de cargabilidad adicional (cargas nuevas "
        "desconectadas) y (ii) escenario proyectado o con proyecto (cargas nuevas "
        "conectadas con su potencia asignada). El análisis cubre régimen de tensión, "
        "caídas de tensión en cabecera, demanda activa/reactiva y cargabilidad "
        "evidente del punto de suministro."
    ) % (feeder or "en estudio")

    tension_txt = (
        "En el escenario situacional (sin proyecto), la tensión de cabecera "
        "registrada es de %s %% en fase A (%s %% B / %s %% C), equivalente a "
        "una caída de %s puntos porcentuales respecto del valor nominal. "
        "En el escenario proyectado (con proyecto), la tensión de cabecera "
        "es de %s %% (A/B/C: %s / %s / %s), con una caída de %s puntos "
        "porcentuales. La variación de tensión entre ambos estados es de "
        "%s puntos porcentuales, lo que %s."
    ) % (
        _pct(sit.get("v_pct_a"), 2),
        _fmt(sit.get("v_pct_b"), 2),
        _fmt(sit.get("v_pct_c"), 2),
        _fmt(caida_sit, 2) if caida_sit is not None else "—",
        _pct(proy.get("v_pct_a"), 2),
        _fmt(proy.get("v_pct_a"), 2),
        _fmt(proy.get("v_pct_b"), 2),
        _fmt(proy.get("v_pct_c"), 2),
        _fmt(caida_proy, 2) if caida_proy is not None else "—",
        _fmt(d_v, 2) if d_v is not None else "—",
        (
            "se considera compatible con los límites operativos habituales de ±5 % "
            "en media tensión, sin perjuicio de verificar nodos remotos del radial"
            if (d_v is None or abs(d_v) < 3.0)
            else "debe verificarse frente a los umbrales de calidad de servicio "
            "y a la regulación vigente aplicable"
        ),
    )

    carga_txt = (
        "Respecto de la cargabilidad, la demanda de cabecera en el estado "
        "situacional asciende a %s kW / %s kvar (%s kVA, FP %s %%). Con el "
        "proyecto conectado, la demanda proyectada es de %s kW / %s kvar "
        "(%s kVA, FP %s %%). El incremento atribuible al proyecto es de "
        "%s kW / %s kvar (%s kVA). La demanda máxima declarada del interesado "
        "(%s) se incorpora al modelo como carga concentrada (SpotLoad) en el "
        "nodo/tramo de conexión definido en el estudio."
    ) % (
        _fmt(sit.get("kw"), 1),
        _fmt(sit.get("kvar"), 1),
        _fmt(sit.get("kva"), 1),
        _fmt(sit.get("fp_pct"), 2),
        _fmt(proy.get("kw"), 1),
        _fmt(proy.get("kvar"), 1),
        _fmt(proy.get("kva"), 1),
        _fmt(proy.get("fp_pct"), 2),
        _fmt(d_kw, 1) if d_kw is not None else "—",
        _fmt(d_kvar, 1) if d_kvar is not None else "—",
        _fmt(d_kva, 1) if d_kva is not None else "—",
        pot_txt or "declarada",
    )

    # Criterio simple de viabilidad
    viable = True
    notes = []
    if pot is not None and d_kw is not None and d_kw < pot * 0.5:
        notes.append(
            "El incremento de demanda en cabecera es inferior a la potencia "
            "declarada; conviene corroborar el estado de conexión de la SpotLoad "
            "y la convergencia del flujo de carga."
        )
    if caida_proy is not None and caida_proy > 5.0:
        viable = False
        notes.append(
            "La caída de tensión proyectada en cabecera supera 5 puntos "
            "porcentuales; se recomienda evaluar compensación reactiva, "
            "refuerzo de red o punto de diseño alternativo."
        )
    if caida_proy is not None and caida_proy <= 5.0:
        notes.append(
            "La caída de tensión en cabecera se mantiene dentro de ±5 % "
            "respecto del valor nominal en el escenario con proyecto."
        )

    conclusiones = (
        "Con base en la simulación de flujo de carga del alimentador %s, "
        "comparando el estado situacional (sin proyecto) y el proyectado "
        "(con proyecto de %s), se concluye que la conexión solicitada "
        "%s desde el punto de vista de tensión de cabecera y variación "
        "de cargabilidad observada. %s "
        "Se deja constancia de que el presente informe corresponde al "
        "análisis de régimen permanente (LoadFlow) y no sustituye estudios "
        "complementarios de cortocircuito, protección o calidad de energía "
        "que la concesionaria estime pertinentes."
    ) % (
        feeder or "analizado",
        pot_txt or "la potencia indicada",
        "resulta factible" if viable else "requiere condicionantes técnicas",
        " ".join(notes),
    )

    recomendaciones = [
        "Mantener la SpotLoad del proyecto con potencia y factor de potencia "
        "acordes a la demanda máxima declarada (%s)." % (pot_txt or "según solicitud"),
        "Verificar en campo el punto de diseño y la capacidad térmica del tramo "
        "receptor antes de la energización.",
        "Revisar la operación de bancos de condensadores shunt y reguladores "
        "ante el nuevo perfil de carga.",
        "Actualizar el expediente %s con planos unifilares y cuadro de cargas "
        "firmado por ingeniero electricista habilitado." % (expediente or "del proyecto"),
    ]

    return {
        "utility": utility,
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "cliente": cliente,
        "ubicacion": ubic,
        "alimentador": feeder,
        "proyecto": proyecto,
        "potencia_kw": pot,
        "potencia_txt": pot_txt,
        "solicitud": solicitud,
        "expediente": expediente,
        "viable": viable,
        "deltas": {
            "d_kw": d_kw,
            "d_kvar": d_kvar,
            "d_kva": d_kva,
            "d_v_pct": d_v,
            "caida_sit_pct": caida_sit,
            "caida_proy_pct": caida_proy,
        },
        "secciones": {
            "antecedentes": antecedentes,
            "objeto": objeto,
            "analisis_tension": tension_txt,
            "analisis_cargabilidad": carga_txt,
            "conclusiones": conclusiones,
            "recomendaciones": recomendaciones,
        },
        "texto_plano": "\n\n".join([
            "1. ANTECEDENTES",
            antecedentes,
            "2. OBJETO Y METODOLOGÍA",
            objeto,
            "3. ANÁLISIS DE TENSIÓN Y CAÍDAS",
            tension_txt,
            "4. ANÁLISIS DE CARGABILIDAD",
            carga_txt,
            "5. CONCLUSIONES",
            conclusiones,
            "6. RECOMENDACIONES",
            "\n".join("%d. %s" % (i + 1, r) for i, r in enumerate(recomendaciones)),
        ]),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_narrative(settings, narrative):
    from core.feeder_context import output_path
    from core.common import mkdir
    path = output_path(settings, "demand", "informe_narrative.json")
    mkdir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(narrative, f, indent=2, ensure_ascii=False, default=str)
    txt = output_path(settings, "demand", "informe_narrative.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(narrative.get("texto_plano") or "")
    return path
