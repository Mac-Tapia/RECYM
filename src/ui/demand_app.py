# -*- coding: utf-8 -*-
"""
Interfaz RECYM — Cabecera + clientes SED + nueva SpotLoad por nodo → CYMDIST.
"""
from __future__ import print_function
import json
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))
sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))

from flask import Flask, jsonify, render_template_string, request, make_response, send_file

from core.feeder_context import load_settings, list_feeders, output_path
from pipeline.run_demand_allocation import (
    load_session, save_session, compute_head_pq, seed_session_from_excel,
    run_allocation, apply_cabecera_medicion, sync_control_excel_cabecera,
)
from pipeline.run_load_flow import run_load_flow
from pipeline.inventory_loads import collect_loads
from pipeline.apply_clientes_to_cymdist import apply_rows
from pipeline.add_spot_load import (
    search_nodes, resolve_connection, connect_spot_load,
    parse_batch_file, build_batch_template_csv, build_batch_template_xlsx,
    connect_spot_loads_bulk, list_pending_spot_loads, normalize_batch_row,
    get_topology, append_report, attach_location_map, list_connected_spot_loads,
)
from pipeline.assemble_informe import assemble_informe, informe_paths
from pipeline.fill_informe import (
    fill_informe,
    delivery_status,
    build_informe_preview,
    confirm_informe_entrega,
)
from pipeline.extract_informe_meta_pdf import (
    extract_informe_meta_from_pdf,
    load_informe_meta,
    save_informe_meta,
    meta_is_complete,
)
from core.common import require_cympy, load_json, mkdir
from core.cympy_adapter import CymPyAdapter
from core.clientes_suministro import (
    list_suministro_files, list_clientes_importantes_files,
    build_feeder_clientes_table, attach_cymdist_loads,
    save_table_csv, save_table_json,
    merge_activo, merge_restar_cabecera, load_saved_clientes_rows,
    ensure_activo, ensure_restar_cabecera,
    list_radiales_from_suministro,
)
from core.spot_load_new import compute_pq

UI_VERSION = "5.10"
# RECYM_SPA=1: la SPA React (FastAPI) sirve `/`; Flask solo expone /api/* (+ /tablero legado).
SPA_MODE = os.environ.get("RECYM_SPA", "0") in ("1", "true", "True", "yes")
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

@app.after_request
def _no_cache_html(resp):
    try:
        ct = (resp.headers.get("Content-Type") or "")
        if "text/html" in ct:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
    except Exception:
        pass
    return resp

TEMPLATE = r"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>RECYM · Demanda y cargas v{{ ui_version }}</title>
<style>
:root{--bg:#f4f1ea;--ink:#1c1917;--accent:#0f766e;--line:#d6d3d1;--card:#fffef9}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:linear-gradient(160deg,#ece7dc,#f8f5ef 40%,#e7eef0);color:var(--ink)}
header{padding:28px 32px 12px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.55);backdrop-filter:blur(6px)}
header h1{margin:0;font-size:28px;letter-spacing:-.02em}
header p{margin:6px 0 0;color:#57534e}
header a{color:var(--accent)}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);background:#fff;color:#57534e;margin-left:8px;vertical-align:middle}
.badge.ready{border-color:#047857;color:#047857;background:#ecfdf5}
.badge.wait{border-color:#b45309;color:#b45309;background:#fffbeb}
main{display:grid;grid-template-columns:1fr;gap:18px;padding:20px 24px 40px;max-width:1100px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.panel h2{margin:0 0 12px;font-size:18px}
.check-list{list-style:none;margin:8px 0 0;padding:0}
.check-list li{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #f0ebe3;font-size:13px}
.check-list li:last-child{border-bottom:0}
.dot{width:10px;height:10px;border-radius:50%;flex:0 0 auto;background:#a8a29e}
.dot.ok{background:#047857}
.dot.bad{background:#b91c1c}
label{display:block;font-size:12px;color:#57534e;margin:10px 0 4px}
input,select,button{font:inherit}
input,select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#fff}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(min-width:900px){.grid{grid-template-columns:1fr 1fr 1fr}}
button{cursor:pointer;border:0;border-radius:10px;padding:10px 14px;background:var(--accent);color:#fff}
button:disabled{opacity:.45;cursor:not-allowed}
button.mq-running{outline:2px solid #0f766e;outline-offset:1px;box-shadow:0 0 0 3px rgba(15,118,110,.18)}
button.secondary{background:#44403c}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--accent)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;align-items:center}
.muted{color:#78716c;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left}
tr:hover{background:#f5f5f4}
.err{color:#b91c1c}.ok{color:#047857}
.pathbox{background:#f5f5f4;border:1px dashed var(--line);border-radius:10px;padding:10px 12px;font-size:12px;line-height:1.55;margin-top:10px}
.pathbox code{font-family:Consolas,"Courier New",monospace;font-size:11px;word-break:break-all}
.steps{margin:0 0 10px;padding-left:18px;font-size:13px;color:#57534e}
.steps li{margin:4px 0}
.feeder-box{border:1px solid var(--line);border-radius:10px;background:#fff;padding:8px}
.feeder-box input[type=search]{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px}
.feeder-list{max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:4px 0}
.feeder-list label{display:flex;align-items:center;gap:8px;padding:5px 10px;margin:0;font-size:13px;color:var(--ink);cursor:pointer}
.feeder-list label:hover{background:#f5f5f4}
.feeder-list label.hidden{display:none}
.feeder-list .cnt{margin-left:auto;color:#78716c;font-size:12px}
.feeder-sel{font-size:12px;color:#57534e;margin-top:6px;min-height:1.2em}
.feeder-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.feeder-actions button{padding:6px 10px;font-size:12px}
.hdr-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
.hdr-bar button{padding:8px 12px;font-size:13px}
.hdr-bar .hdr-msg{font-size:12px;color:#57534e;min-height:1.2em}
table th.col-incluir{background:#ccfbf1;color:#115e59;min-width:72px;text-align:center}
table td.col-incluir{text-align:center;background:#f0fdfa}
table td.col-incluir input{width:18px;height:18px;cursor:pointer;accent-color:#0f766e}
tr.off-row{opacity:.55;background:#fafaf9}
</style>
</head>
<body>
<header>
  <h1>RECYM · Demanda y cargas CYMDIST <span class="badge" id="hdrBadge">v{{ ui_version }}</span></h1>
  <p><span id="hdrUtility">{{ utility }}</span> · <span id="hdrScope">Sistema BD</span>
     · <span id="hdrFeederLabel">Alimentador</span> <b id="hdrFeeder">—</b>
     · <span id="hdrNetworkLabel">Red</span> <span id="hdrNetwork">—</span>
     · UI v{{ ui_version }}
     · <a href="#panelEntrega">Entrega</a>
     · <a href="#panelCalidad">Calidad modelo</a>
     · <a href="#panelOpt">Optimización</a>
     · <a href="#panelSuite">Suite</a>
     · <a href="/tablero" target="_blank">Tablero</a>
     {% if dry_run %}<span class="err"> · DRY_RUN activo</span>{% endif %}</p>
  <div class="hdr-bar">
    <button type="button" id="btnUiActualizar" class="secondary" onclick="uiActualizar()">↻ Actualizar</button>
    <button type="button" id="btnUiRestablecer" class="ghost" onclick="uiRestablecer()">⟲ Restablecer</button>
    <span class="hdr-msg muted" id="hdrMsg">Si no carga nada: Restablecer. Si sigue muerto: scripts\27_restablecer_ui.bat</span>
  </div>
</header>
<main>
  <section class="panel">
    <h2>1. Máxima demanda de cabecera (medición)</h2>
    <p class="muted">Elija primero la <b>base de datos</b> (.mdb) y el <b>estudio/proyecto</b> (.zxst)
      desde las carpetas configuradas (puede haber varios archivos). Luego cargue la medición
      de cabecera. Al <b>Guardar medición</b> se escriben <b>solo estos P/Q</b> en CYMDIST
      (Propiedades de la red → Demanda → Conectado + Total, casilleros kW / kvar)
      y en la sesión RECYM. Eso <b>restablece §§2–4</b> (tabla clientes, distribución, carga nueva e informes de análisis):
      debe volver a cargar EA/Pot, distribuir, conectar carga y analizar.
      Obligatorios para la <b>distribución de carga</b> (§2, tras cargar EA/Pot).</p>
    <div class="row">
      <div>
        <label>Base de datos (.mdb) — carpeta BD / proyectos</label>
        <select id="ctxDbFile">
          <option value="">— Seleccione base de datos —</option>
        </select>
      </div>
      <div>
        <label>Estudio / proyecto (.zxst) — carpeta proyectos</label>
        <select id="ctxStudyFile">
          <option value="">— Seleccione estudio —</option>
        </select>
      </div>
    </div>
    <div class="actions" style="margin-top:8px">
      <button type="button" id="btnCtxApply" class="secondary" onclick="applyContextFiles()">Aplicar BD + estudio</button>
      <button type="button" class="ghost" onclick="refreshContextFiles()">Actualizar listas</button>
      <span class="muted" id="ctxMsg">Seleccione base de datos y estudio/proyecto.</span>
    </div>
    <div class="pathbox" id="ctxPaths" style="margin-top:8px">
      BD: <code id="ctxDbPath">—</code><br/>
      Estudio: <code id="ctxStudyPath">—</code>
    </div>
    <label>Modo de ingreso</label>
    <select id="mode">
      <option value="KW_COSFI" {% if mode=='KW_COSFI' %}selected{% endif %}>P (kW) + cosφ</option>
      <option value="KW_KVAR" {% if mode=='KW_KVAR' %}selected{% endif %}>P (kW) + Q (kvar)</option>
      <option value="A_COSFI" {% if mode=='A_COSFI' %}selected{% endif %}>I (A) + cosφ + Vll (kV)</option>
    </select>
    <div class="row" id="row_kw">
      <div>
        <label>P máxima demanda cabecera (kW)</label>
        <input id="p_kw" type="number" step="any" value="{{ p_kw }}" placeholder="ej. 6038"/>
      </div>
      <div id="box_cosfi">
        <label>cosφ (factor de potencia)</label>
        <input id="cosfi" type="number" step="0.01" min="0.01" max="1" value="{{ cosfi }}"/>
      </div>
      <div id="box_q" style="display:none">
        <label>Q cabecera (kvar)</label>
        <input id="q_kvar" type="number" step="any" value="{{ q_kvar }}" placeholder="ej. 2588"/>
      </div>
    </div>
    <div class="row" id="row_amp" style="display:none">
      <div>
        <label>I máxima demanda cabecera (A)</label>
        <input id="i_a" type="number" step="any" value="{{ i_a }}" placeholder="ej. 160"/>
      </div>
      <div>
        <label>Vll cabecera (kV)</label>
        <input id="v_ll" type="number" step="any" value="{{ v_ll }}" placeholder="22.9"/>
      </div>
      <div>
        <label>cosφ</label>
        <input id="cosfi_a" type="number" step="0.01" min="0.01" max="1" value="{{ cosfi }}"/>
      </div>
    </div>
    <div class="row">
      <div>
        <label>Fecha / hora medición (opcional)</label>
        <input id="fecha_med" type="text" value="{{ fecha_medicion }}" placeholder="ej. 2026-03-15 19:30"/>
      </div>
      <div>
        <label>P / Q calculados (para distribución)</label>
        <div id="headPreview" class="feeder-sel" style="margin-top:8px;font-size:14px;color:#0f766e">—</div>
      </div>
    </div>
    <div class="actions">
      <button type="button" onclick="saveHead()">Guardar medición cabecera</button>
      <button type="button" class="ghost" onclick="previewHead()">Recalcular P/Q</button>
      <span class="muted" id="headMsg"></span>
    </div>
  </section>

  <section class="panel" id="panelCalidad">
    <h2>Calidad del modelo CYMDIST (antes de cargar §2)</h2>
    <p class="muted">Diagnóstico y corrección vía API <b>NetworkDiagnostic</b>
      (códigos 220000–220053 + avisos LoadFlow). <b>No depende de §3 ni §4</b>
      (cargas nuevas / flujos de escenario) ni de cabecera de demanda: usa redes y
      equipos ya en la BD. §§3–4 solo aplican después, si hay SpotLoad nueva.
      Marque <b>uno o varios alimentadores del estudio</b> y use
      <b>Ejecutar seleccionados</b> / <b>Diagnosticar seleccionados</b>.
      Use <b>Diagnosticar sistema</b> solo si necesita los ~96 alimentadores.</p>
    <ol class="steps">
      <li>Seleccione alimentador(es) del estudio (BD) abajo — el buscador muestra el código marcado.</li>
      <li><b>Cada botón ejecuta SOLO su acción</b> (no arranca los demás).</li>
      <li>Diagnosticar / Proponer / Aplicar / Verificar / Actualizar = un paso cada uno.</li>
      <li>«Ciclo completo» es el único que encadena varios pasos a propósito.</li>
      <li>Sistema (96) y ELD son paquetes globales independientes de la selección.</li>
    </ol>
    <div style="margin:10px 0 12px">
      <label>Alimentadores del estudio (BD) — buscar y marcar</label>
      <div class="feeder-box">
        <input type="search" id="mqFeederSearch" placeholder="Buscar código (ej. PA217, SI112)…" oninput="mqFilterFeederList()" onkeydown="mqFeederSearchKey(event)" onfocus="this.select()"/>
        <div id="mqFeederList" class="feeder-list"></div>
        <div class="feeder-actions">
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:12px;margin:0;cursor:pointer">
            <input type="checkbox" id="mqAllowMulti" onchange="mqOnMultiModeChange()"/>
            Permitir varios
          </label>
          <button type="button" class="ghost" onclick="mqSelectFeeders(false)">Ninguno</button>
          <button type="button" class="ghost" onclick="mqSelectFeeders(true)">Todos</button>
          <button type="button" id="btnMqSoloFeeder" class="ghost" onclick="mqSelectOnlyCurrent()">Solo {{ feeder }}</button>
          <button type="button" class="ghost" onclick="mqLoadNetworks(true)">Actualizar lista</button>
        </div>
        <div id="mqFeederSel" class="feeder-sel">Cargando redes del estudio…</div>
      </div>
    </div>
    <div class="actions" id="mqActions">
      <button type="button" id="btnMqDiag" class="secondary" onclick="mqDiagnose()">1 · Diagnosticar</button>
      <button type="button" id="btnMqProp" class="ghost" onclick="mqPropose()">2 · Proponer</button>
      <button type="button" id="btnMqApply" class="secondary" onclick="mqApply()">3 · Aplicar</button>
      <button type="button" id="btnMqConv" class="ghost" onclick="mqConverge()">4 · Verificar convergencia</button>
      <button type="button" id="btnMqRefresh" class="ghost" onclick="mqRefreshStatus()">5 · Actualizar estado</button>
      <button type="button" id="btnMqDiagSel" class="ghost" onclick="mqDiagnoseSelected()">6 · Diagnosticar selección</button>
      <button type="button" id="btnMqUntil" class="ghost" onclick="mqUntilClean()">7 · Corregir hasta limpio</button>
      <button type="button" id="btnMqUntilSel" onclick="mqRunSelected()">8 · Ciclo completo (selección)</button>
      <button type="button" id="btnMqDiagSys" class="secondary" onclick="mqDiagnoseSystem()">9 · Diagnosticar sistema (96)</button>
      <button type="button" id="btnMqDiagEld" class="secondary" onclick="mqDiagnoseEld()">10 · Diagnosticar ELD</button>
      <span class="muted" id="mqMsg">Pulse UN botón: solo esa acción se ejecuta.</span>
    </div>
    <div class="pathbox" id="mqStatus">
      Estado gate: <b id="mqReady">—</b>
      · Converge: <b id="mqConv">—</b>
      · Problemas: <b id="mqProblems">—</b>
      · Feeder: <b id="mqSelFeeder">—</b> · Red: <b id="mqSelNetwork">—</b>
      · Sistema: <b id="mqSysProblems">—</b>
    </div>
    <div id="mqTable" style="max-height:280px;overflow:auto;margin-top:10px"></div>
    <pre id="mqOut" class="muted" style="white-space:pre-wrap;margin-top:8px;font-size:12px;max-height:220px;overflow:auto"></pre>
  </section>

  <section class="panel">
    <h2>2. Clientes importantes → SED CYMDIST + distribución</h2>
    <p class="muted">Elija el archivo de <b>clientesimportantes</b> (el cruce NIS/EA/Pot es <b>solo</b> en ese archivo).
    Luego arme la tabla y <b>cargue EA (kWh) → casillero Consumo</b> y <b>Pot (kW) → potencia</b> en las SED de CYMDIST.
    Al pulsar <b>Cargar EA/Pot</b> se escriben y verifican esos valores y se <b>abre CYMDIST</b> (API COM) con el mismo estudio;
    a partir de ahí distribución, carga nueva, flujos e informes son <b>ejecuciones físicas</b> sobre esa sesión.
    Orden: <b>calidad modelo (gate) → EA/Pot (+ abrir CYMDIST) → distribución → carga nueva (§3) → flujos (§4) → informes (§5)</b>.
    Complete primero el panel <b>Calidad del modelo</b> (0 Error/Warning/Hint + converge).
    La <b>distribución (Consumo kWh)</b> deja Locked la Pot de clientes importantes y <b>actualiza kW/kvar</b>
    del resto de SED según su energía en Consumo.
    La columna <b>Incluir</b> viene marcada: desmarque cargas que no desea actualizar
    (se desconectan en CYMDIST). La columna <b>Restar cab.</b> controla si, al desmarcar
    Incluir, también se resta el Pot de esa carga a P(kW) máx §1 (p.ej. carga que ya no
    pertenece al alimentador). Si solo olvidaron actualizar EA/Pot, desmarque Incluir y
    deje Restar cab. apagado. Las excluidas quedan <b>desconectadas en el modelo físico</b>
    de CYMDIST (no entran en distribución ni en flujos).</p>
    <div class="row">
      <div>
        <label>Archivo suministrocliente</label>
        <select id="sumFile"></select>
      </div>
      <div>
        <label>Archivo clientesimportantes (obligatorio)</label>
        <select id="ciFile">
          <option value="">— Seleccione archivo —</option>
        </select>
      </div>
    </div>
    <div>
      <label>Alimentador (RADIAL) — buscar y marcar</label>
      <div class="feeder-box">
        <input type="search" id="feederSearch" placeholder="Buscar o escribir código (ej. SI112) y Enter…" oninput="filterFeederList()" onkeydown="feederSearchKey(event)" onfocus="this.select()"/>
        <div id="feederList" class="feeder-list"></div>
        <div class="feeder-actions">
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:12px;margin:0;cursor:pointer">
            <input type="checkbox" id="allowMultiFeeders" onchange="onMultiModeChange()"/>
            Permitir varios
          </label>
          <button type="button" class="ghost" onclick="selectAllFeeders(false)">Ninguno</button>
          <button type="button" id="btnCliSoloFeeder" class="ghost" onclick="selectOnlyCurrentFeeder()">Solo {{ feeder }}</button>
        </div>
        <div id="feederSel" class="feeder-sel">Cargando alimentadores del archivo…</div>
      </div>
    </div>
    <div class="pathbox" id="headForAlloc">
      <b>Máxima demanda cabecera (§1) usada en distribución</b><br/>
      <span id="headAllocSummary" class="muted">Cargue y guarde la medición en la sección 1.</span>
    </div>
    <div class="actions">
      <button type="button" class="ghost" onclick="refreshCiFiles()">Actualizar lista de archivos</button>
      <button type="button" id="btnBuildCli" onclick="buildClientes()" disabled>Armar tabla (cruzar NIS)</button>
      <button type="button" id="btnApplyCli" class="secondary" onclick="applyClientes()" disabled>Cargar EA/Pot en CYMDIST</button>
      <button type="button" id="btnAlloc" onclick="runDistribucion()" title="Tras Cargar EA/Pot: reparte cabecera − clientes → residual SED">Ejecutar distribución de carga</button>
      <span class="muted" id="cliMsg">Seleccione un archivo de clientesimportantes.</span>
    </div>
    <div class="muted" id="distMsg" style="margin-top:6px"></div>
    <pre id="distOut" class="muted" style="white-space:pre-wrap;margin-top:8px;font-size:12px;max-height:180px;overflow:auto"></pre>
    <div id="cliMeta" class="muted"></div>
    <div id="cliTable" style="max-height:420px;overflow:auto;margin-top:10px"></div>
  </section>

  <section class="panel">
    <h2>3. Nueva carga concentrada (SpotLoad trifásica)</h2>
    <p class="muted">Se conecta en el <b>mismo estudio/alimentador</b> elegido en <b>§1</b>
      (<span id="spotFeederLabel">—</span>).
      Busque un <b>nodo</b>; el sistema deriva el <b>SectionID</b>.
      Indique el <b>nombre</b> de la carga (aparecerá dibujado en el plano CYMDIST).
      Solo se ingresa <b>P (kW) trifásica</b> y <b>cos φ</b> o <b>Q (kvar)</b>. Sin EA/kWh. Una carga por vez.
      En CYMDIST se reparte a <b>monofásica por fase</b>: A/B/C = P/3 y Q/3
      (casilleros Potencia real / Potencia reactiva de la carga concentrada).
      Queda <b>Locked</b> (no entra en distribución). Se dibuja el <b>símbolo SpotLoad
      (carga concentrada)</b> en el tramo del nodo — <b>no</b> como lateral tipo SED.
      Conéctela <b>después</b> de distribuir en §2; luego flujos (§4). No redistribuir.</p>
    <div class="pathbox" id="spotCtxBox" style="margin-bottom:10px">
      Estudio §1 → SpotLoad §3:
      <b id="spotCtxFeeder">—</b>
      · Red: <b id="spotCtxNetwork">—</b>
      · Archivo: <code id="spotCtxStudy">—</code>
    </div>
    <div class="row">
      <div>
        <label>Buscar nodo</label>
        <input id="nodeQuery" type="text" placeholder="ID parcial del nodo…" oninput="debounceNodeSearch()"/>
      </div>
      <div>
        <label>Nodo seleccionado</label>
        <select id="nodeSelect" onchange="onNodeSelect()">
          <option value="">— Busque y seleccione —</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div>
        <label>Nombre carga concentrada (obligatorio)</label>
        <input id="loadName" type="text" placeholder="ej. CARGA_NUEVA_16767" oninput="onLoadNameInput()"/>
        <div class="muted" style="margin-top:4px;font-size:11px">Este nombre es el que se dibuja en CYMDIST (DeviceNumber).</div>
      </div>
      <div>
        <label>SectionID (auto)</label>
        <input id="autoSection" type="text" readonly placeholder="Se deriva del nodo"/>
      </div>
    </div>
    <div class="row">
      <div>
        <label>LoadID / nombre en plano</label>
        <input id="autoLoadId" type="text" readonly placeholder="Igual al nombre (sanitizado)"/>
      </div>
      <div></div>
    </div>
    <label>Modo potencia</label>
    <select id="loadMode" onchange="loadModeUI()">
      <option value="KW_COSFI" selected>kW + cosφ</option>
      <option value="KW_KVAR">kW + kvar</option>
    </select>
    <div class="row">
      <div>
        <label>P (kW)</label>
        <input id="loadP" type="number" step="any" placeholder="ej. 50"/>
      </div>
      <div id="box_load_cosfi">
        <label>cosφ</label>
        <input id="loadCosfi" type="number" step="0.01" min="0.01" max="1" value="0.95"/>
      </div>
      <div id="box_load_q" style="display:none">
        <label>Q (kvar)</label>
        <input id="loadQ" type="number" step="any" placeholder="ej. 16.4"/>
      </div>
    </div>
    <div class="actions">
      <button type="button" id="btnConnectLoad" onclick="connectLoad()" disabled>4.2 · Conectar y guardar en CYMDIST</button>
      <span class="muted" id="loadMsg">Busque un nodo (sin inventario manual: se resuelve solo).</span>
    </div>
    <div id="loadResolve" class="muted" style="margin-top:8px"></div>
    <div id="loadHistory" style="max-height:220px;overflow:auto;margin-top:10px"></div>

    <h3 style="margin-top:18px">4.3 · Cargas en bloque (CSV / Excel)</h3>
    <p class="muted">Independiente de 4.2. Descargue plantilla, complete filas y conéctelas.
      Accion = <code>NUEVA</code> o <code>ACTUALIZAR</code>. Quedan guardadas para §5.</p>
    <div class="actions">
      <button type="button" class="ghost" onclick="downloadSpotTemplate('xlsx')">Plantilla .xlsx</button>
      <button type="button" class="ghost" onclick="downloadSpotTemplate('csv')">Plantilla .csv</button>
      <label class="ghost" style="display:inline-block;padding:8px 12px;border:1px solid #ccc;border-radius:8px;cursor:pointer">
        Cargar CSV/Excel
        <input type="file" id="spotBatchFile" accept=".csv,.xlsx,.xlsm" style="display:none" onchange="previewSpotBatch(this)"/>
      </label>
      <button type="button" id="btnSpotBatch" onclick="connectSpotBatch()" disabled>4.3 · Conectar en bloque</button>
      <span class="muted" id="spotBatchMsg"></span>
    </div>
    <div id="spotBatchTable" style="max-height:260px;overflow:auto;margin-top:8px"></div>
    <h3 style="margin-top:14px">4.3b · Pendientes</h3>
    <div class="actions">
      <button type="button" class="ghost" onclick="loadSpotPending()">Actualizar listado</button>
      <button type="button" id="btnSpotPending" onclick="retrySpotPending()" disabled>Reintentar pendientes</button>
      <span class="muted" id="spotPendingMsg"></span>
    </div>
    <div id="spotPendingTable" style="max-height:180px;overflow:auto;margin-top:8px"></div>
  </section>

  <section class="panel">
    <h2>4. Análisis CYMDIST (flujos)</h2>
    <p class="muted">Solo <b>flujos de potencia</b> (LoadFlow). Cada botón es <b>independiente</b>:
      <b>situacional</b> desconecta físicamente las cargas nuevas (§3) y corre el flujo;
      <b>proyectado</b> las conecta con su P/Q y corre el flujo.
      Tras cada uno se intenta actualizar el §5 (solo queda <b>entrega lista</b> con ambos LF + PDF OCR + gráficas).
      <b>CYMDIST queda abierto</b>. No vuelva a distribuir tras SpotLoad.</p>
    <ol class="steps">
      <li>Previo: §1 cabecera → §2 EA/Pot + distribución → §3 carga nueva → §5.1 PDF OCR.</li>
      <li><b>Flujo estado situacional</b> — desconecta SpotLoad §3 → LoadFlow → gráficas situacional.</li>
      <li><b>Flujo con cargas nuevas</b> — conecta SpotLoad §3 (P/Q) → LoadFlow → gráficas proyectado.</li>
      <li>En §5 pulse <b>Rellenar informes</b> cuando el checklist esté en verde.</li>
    </ol>
    <div class="actions">
      <button type="button" id="btnFlowSit" class="secondary" onclick="runFlujo('situacional')">Flujo estado situacional</button>
      <button type="button" id="btnFlowProy" class="secondary" onclick="runFlujo('proyectado')">Flujo con cargas nuevas</button>
      <button type="button" id="btnFlow" class="ghost" onclick="runFlujo()">Flujo general</button>
      <span class="muted" id="analisisMsg"></span>
    </div>
    <div class="pathbox" id="analisisPaths">
      Resultados flujo:<br/>
      <code id="pathLfSit">…</code><br/>
      <code id="pathLfProy">…</code>
    </div>
    <pre id="analisisOut" class="muted" style="white-space:pre-wrap;margin-top:12px;font-size:12px;max-height:220px;overflow:auto"></pre>
  </section>

  <section class="panel" id="panelEntrega">
    <h2>5. Informes de entrega</h2>
    <p class="muted">Entrega de producción: <b>PDF OCR</b> (datos generales) + <b>ambos</b> flujos §4
      (situacional sin carga nueva / proyectado con carga) + gráficas LF auto → Word/Excel en <code>doc</code>.
      Capturas CYMDIST opcionales sobrescriben las gráficas si son más recientes.</p>

    <div class="pathbox" id="deliveryBox" style="margin-top:8px">
      <b>Checklist entrega</b>
      <span class="badge wait" id="deliveryBadge">revisando…</span>
      <ul class="check-list" id="deliveryChecks">
        <li><span class="dot" id="chkSit"></span> LoadFlow situacional (sin carga §3)</li>
        <li><span class="dot" id="chkProy"></span> LoadFlow proyectado (con carga §3)</li>
        <li><span class="dot" id="chkMeta"></span> Datos generales PDF OCR (cliente + potencia)</li>
        <li><span class="dot" id="chkImg"></span> Gráficas LF (4 PNG tensión/cargabilidad)</li>
      </ul>
      <div class="muted" id="deliveryMissing" style="margin-top:6px"></div>
      <div class="actions" style="margin-top:8px">
        <button type="button" class="ghost" onclick="refreshDeliveryStatus()">Actualizar checklist</button>
      </div>
    </div>

    <h3 style="margin:16px 0 6px;font-size:14px">5.1 Datos generales (PDF → OCR)</h3>
    <div class="actions" style="align-items:center;flex-wrap:wrap;gap:8px">
      <input type="file" id="metaPdf" accept=".pdf,application/pdf"/>
      <button type="button" id="btnMetaPdf" class="secondary" onclick="extractMetaPdf()">Extraer datos generales (OCR)</button>
      <button type="button" class="ghost" onclick="loadMetaUI()">Cargar meta guardada</button>
      <button type="button" id="btnMetaSave" onclick="saveMetaUI()">Guardar meta</button>
      <span class="muted" id="metaMsg"></span>
    </div>
    <div class="grid" style="margin-top:10px" id="metaFields">
      <div><label>Cliente</label><input id="meta_cliente" type="text"/></div>
      <div><label>Ubicación</label><input id="meta_ubicacion" type="text"/></div>
      <div><label>Solicitud</label><input id="meta_solicitud" type="text"/></div>
      <div><label>Potencia (kW)</label><input id="meta_potencia_kw" type="number" step="any"/></div>
      <div><label>Potencia texto</label><input id="meta_potencia_txt" type="text" placeholder="1500KW"/></div>
      <div><label>Alimentador</label><input id="meta_alimentador" type="text"/></div>
      <div><label>SET</label><input id="meta_set" type="text"/></div>
      <div><label>Tensión (kV)</label><input id="meta_tension_kv" type="number" step="any"/></div>
      <div><label>Transformador</label><input id="meta_transformador" type="text"/></div>
      <div><label>Expediente</label><input id="meta_expediente" type="text"/></div>
    </div>
    <pre id="metaOut" class="muted" style="white-space:pre-wrap;margin-top:8px;font-size:12px;max-height:120px;overflow:auto"></pre>

    <h3 style="margin:16px 0 6px;font-size:14px">5.2 Rellenar Word/Excel</h3>
    <div class="actions">
      <button type="button" class="ghost" onclick="refreshInformePaths()">Ver rutas de guardado</button>
      <button type="button" class="secondary" onclick="capturarCymdistInforme()">Capturar CYMDIST (API)</button>
      <button type="button" id="btnInforme" onclick="armarInformes()">Rellenar informes → doc</button>
      <span class="muted" id="informeMsg"></span>
    </div>
    <div class="pathbox" id="informePaths">
      <b>Plantillas (origen)</b><br/>
      <code id="pathTplInf">…</code><br/>
      <code id="pathTplJus">…</code><br/><br/>
      <b>Entrega (destino — aquí se guardan)</b><br/>
      <code id="pathDocDir">…</code><br/>
      <code id="pathDocInf">…</code><br/>
      <code id="pathDocJus">…</code><br/><br/>
      <b>Gráficas LF / capturas (PNG)</b><br/>
      <code id="pathImgDir">…</code>
      <div class="muted" style="margin-top:6px;font-size:12px">
        Al rellenar: LoadFlow situacional + proyectado → activa coloreo VoltageLevel/LoadingLevel en CYMDIST → ExportActiveView → Word.
      </div>
    </div>
    <pre id="informeOut" class="muted" style="white-space:pre-wrap;margin-top:12px;font-size:12px;max-height:180px;overflow:auto"></pre>
  </section>

  <section class="panel" id="panelOpt">
    <h2>6. Optimización CYMDIST</h2>
    <p class="muted">Comandos de optimización del alimentador activo (§1). Requieren flag en
      <code>Control_Simulacion.xlsx</code> (o marque <b>Forzar</b>). Tras cada corrida se intenta LoadFlow.</p>
    <div class="actions">
      <label style="display:inline-flex;align-items:center;gap:6px;margin:0;font-size:13px;cursor:pointer">
        <input type="checkbox" id="optForce"/> Forzar (ignorar flag Excel)
      </label>
      <button type="button" id="btnOptRec" class="secondary" onclick="runOpt('reclosers')">Reconectadores</button>
      <button type="button" id="btnOptReg" class="secondary" onclick="runOpt('regulators')">Reguladores</button>
      <button type="button" id="btnOptCap" class="secondary" onclick="runOpt('capacitors')">Capacitores</button>
      <span class="muted" id="optMsg"></span>
    </div>
    <pre id="optOut" class="muted" style="white-space:pre-wrap;margin-top:10px;font-size:12px;max-height:180px;overflow:auto"></pre>
  </section>

  <section class="panel" id="panelSuite">
    <h2>7. Suite RECYM — herramientas del proyecto</h2>
    <p class="muted">Acciones del resto del pipeline / scripts que antes solo estaban en <code>scripts\*.bat</code>.
      Usan el contexto BD/estudio de §1 cuando aplica.</p>

    <h3 style="margin:12px 0 6px;font-size:14px">7.1 Entorno y conexión</h3>
    <div class="actions">
      <button type="button" class="ghost" onclick="suiteEnv()">Validar entorno</button>
      <button type="button" class="secondary" onclick="suiteTestConn()">Probar conexión CYMDIST</button>
      <button type="button" class="ghost" onclick="suiteValidateInputs()">Validar entradas Excel</button>
      <button type="button" class="ghost" onclick="suiteInventoryLoads()">Inventario SpotLoad (96)</button>
      <span class="muted" id="suiteEnvMsg"></span>
    </div>

    <h3 style="margin:16px 0 6px;font-size:14px">7.2 Equipos / modelo (sistema)</h3>
    <div class="actions">
      <button type="button" class="secondary" onclick="suiteSyncEquip()">Sync equipos Excel → CYMDIST</button>
      <button type="button" class="ghost" onclick="suiteFixDefault()">Cerrar DEFAULT AAAC/XLPE</button>
      <button type="button" class="ghost" onclick="suiteExportAscii()">Exportar ASCII (Red/Equipos/Cargas)</button>
      <span class="muted" id="suiteEqMsg"></span>
    </div>

    <h3 style="margin:16px 0 6px;font-size:14px">7.3 Nuevo alimentador RECYM</h3>
    <div class="row">
      <div>
        <label>ID alimentador</label>
        <input id="nfId" type="text" placeholder="ej. PA218"/>
      </div>
      <div>
        <label>Nombre</label>
        <input id="nfName" type="text" placeholder="opcional"/>
      </div>
    </div>
    <div class="row">
      <div>
        <label>NetworkID CYMDIST</label>
        <input id="nfNet" type="text" placeholder="NET_PA218"/>
      </div>
      <div>
        <label>Tensión LL (kV)</label>
        <input id="nfKv" type="number" step="any" value="22.9"/>
      </div>
    </div>
    <div class="actions">
      <button type="button" id="btnNewFeeder" onclick="suiteNewFeeder()">Crear alimentador</button>
      <span class="muted" id="suiteNfMsg">Crea config/feeders/&lt;ID&gt;.json + carpetas input/output.</span>
    </div>

    <h3 style="margin:16px 0 6px;font-size:14px">7.4 Pipeline batch (CLI vía UI)</h3>
    <p class="muted">Ejecuta la secuencia de <code>settings.run_sequence</code> para el alimentador activo
      (equivalente a <code>scripts\11_run_feeder.bat</code>). Puede tardar varios minutos.</p>
    <div class="actions">
      <button type="button" id="btnPipeline" class="secondary" onclick="suitePipeline()">Ejecutar pipeline alimentador</button>
      <span class="muted" id="suitePipeMsg"></span>
    </div>
    <pre id="suiteOut" class="muted" style="white-space:pre-wrap;margin-top:10px;font-size:12px;max-height:260px;overflow:auto"></pre>
  </section>
</main>
<script>
let cliTableReady = false;
let _pathsCache = null;
const DEFAULT_FEEDER = {{ feeder|tojson }};
const DEFAULT_NETWORK = {{ network|tojson }};
const DEFAULT_UTILITY = {{ utility|tojson }};
window.ACTIVE_FEEDER = window.ACTIVE_FEEDER || DEFAULT_FEEDER || '';
window.ACTIVE_NETWORK = window.ACTIVE_NETWORK || DEFAULT_NETWORK || '';

/** Alimentador activo = estudio de §1 (no PA217 fijo / no RECYM_FEEDER del bat). */
function getActiveFeederPack(){
  const sel = (typeof getContextSelection === 'function') ? getContextSelection() : {};
  const mqF = (typeof getMqSelectedFeeders === 'function') ? getMqSelectedFeeders() : [];
  const mqN = (typeof getMqSelectedNetworks === 'function') ? getMqSelectedNetworks() : [];
  const cliF = (typeof getSelectedFeeders === 'function') ? getSelectedFeeders() : [];
  const feeder = String(
    window.ACTIVE_FEEDER
    || sel.feeder
    || (mqF.length === 1 ? mqF[0] : '')
    || (cliF.length === 1 ? cliF[0] : '')
    || DEFAULT_FEEDER
    || ''
  ).trim().toUpperCase();
  const network = String(
    window.ACTIVE_NETWORK
    || (mqN.length === 1 ? mqN[0] : '')
    || DEFAULT_NETWORK
    || ''
  ).trim();
  const study = sel.study_path
    || ((document.getElementById('ctxStudyPath')||{}).textContent || '').trim()
    || ((document.getElementById('ctxStudyFile')||{}).value || '');
  return { feeder: feeder, network: network, study_path: study, feeders: feeder ? [feeder] : [] };
}

function syncSpotLoadContext(){
  const p = getActiveFeederPack();
  const lab = document.getElementById('spotFeederLabel');
  const fEl = document.getElementById('spotCtxFeeder');
  const nEl = document.getElementById('spotCtxNetwork');
  const sEl = document.getElementById('spotCtxStudy');
  if (lab) lab.textContent = p.feeder || '— (aplique BD+estudio en §1)';
  if (fEl) fEl.textContent = p.feeder || '—';
  if (nEl) nEl.textContent = p.network || '—';
  if (sEl) {
    const name = p.study_path ? String(p.study_path).split(/[/\\\\]/).pop() : '—';
    sEl.textContent = name || '—';
  }
}

/** fetch con timeout: evita UI colgada «sin cargar nada» cuando Waitress/COM se satura. */
function fetchWithTimeout(url, opts, ms){
  const timeoutMs = (ms == null) ? 15000 : ms;
  const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  const parent = (opts && opts.signal) ? opts.signal : null;
  if (parent && ctrl) {
    if (parent.aborted) ctrl.abort();
    else parent.addEventListener('abort', function(){ try { ctrl.abort(); } catch(e) {} });
  }
  const timer = setTimeout(function(){ try { if (ctrl) ctrl.abort(); } catch(e) {} }, timeoutMs);
  const next = Object.assign({}, opts || {});
  if (ctrl) next.signal = ctrl.signal;
  return fetch(url, next).finally(function(){ clearTimeout(timer); }).catch(function(err){
    if (err && (err.name === 'AbortError' || /aborted/i.test(String(err)))) {
      throw new Error('Tiempo agotado ('+Math.round(timeoutMs/1000)+'s). Servidor ocupado o CYMDIST bloqueado — pulse Restablecer o scripts\\27_restablecer_ui.bat');
    }
    throw err;
  });
}

/** fetch de §3 (nodos/SpotLoad) siempre con el alimentador de §1. */
async function spotFetch(path, body){
  const pack = getActiveFeederPack();
  if (!pack.feeder) {
    throw new Error('Seleccione estudio en §1 y pulse «Aplicar BD + estudio» antes de usar §3.');
  }
  const headers = {'Content-Type': 'application/json', 'X-Feeder': pack.feeder};
  const payload = Object.assign({}, body || {}, {
    feeder: pack.feeder,
    feeders: pack.feeders,
  });
  if (pack.network) {
    payload.network = pack.network;
    payload.network_id = pack.network;
  }
  const isGet = body === undefined;
  let url = path;
  if (isGet) {
    url = path.indexOf('?') >= 0
      ? path + '&feeder=' + encodeURIComponent(pack.feeder)
      : path + '?feeder=' + encodeURIComponent(pack.feeder);
  }
  const opts = { method: isGet ? 'GET' : 'POST', headers: headers };
  if (!isGet) opts.body = JSON.stringify(payload);
  const r = await fetchWithTimeout(url, opts, 120000);
  let j = null;
  try { j = await r.json(); } catch(e) {
    throw new Error('Respuesta no JSON ('+r.status+') en '+path);
  }
  if (!r.ok && j && j.error) throw new Error(j.error);
  if (!r.ok) throw new Error('HTTP '+r.status+' en '+path);
  return j;
}

/** Contexto de cabecera: refleja selección UI (calidad / clientes), no un alimentador fijo. */
function updateHeaderContext(opts){
  const o = opts || {};
  const mqF = (typeof getMqSelectedFeeders === 'function') ? getMqSelectedFeeders() : [];
  const mqN = (typeof getMqSelectedNetworks === 'function') ? getMqSelectedNetworks() : [];
  const cliF = (typeof getSelectedFeeders === 'function') ? getSelectedFeeders() : [];
  let feeders = o.feeders || (mqF.length ? mqF : cliF);
  let networks = o.networks || mqN;
  if (o.feeder && (!feeders || !feeders.length)) feeders = [o.feeder];
  if (o.network && (!networks || !networks.length)) networks = [o.network];

  const nBd = (_mqNetworks && _mqNetworks.length) ? _mqNetworks.length : 0;
  const scopeEl = document.getElementById('hdrScope');
  const fEl = document.getElementById('hdrFeeder');
  const nEl = document.getElementById('hdrNetwork');
  const fLab = document.getElementById('hdrFeederLabel');
  const nLab = document.getElementById('hdrNetworkLabel');
  if (!fEl || !nEl) return;

  if (feeders && feeders.length === 1) {
    if (scopeEl) scopeEl.textContent = 'Alimentador seleccionado';
    if (fLab) fLab.textContent = 'Código';
    if (nLab) nLab.textContent = 'Red';
    fEl.textContent = feeders[0];
    nEl.textContent = (networks && networks[0]) ? networks[0]
      : (feeders[0] === DEFAULT_FEEDER && DEFAULT_NETWORK ? DEFAULT_NETWORK : '—');
  } else if (feeders && feeders.length > 1) {
    if (scopeEl) scopeEl.textContent = 'Selección múltiple';
    if (fLab) fLab.textContent = 'Alimentadores';
    if (nLab) nLab.textContent = 'Redes';
    fEl.textContent = feeders.length + ' (' + feeders.slice(0, 4).join(', ')
      + (feeders.length > 4 ? ', …' : '') + ')';
    nEl.textContent = (networks && networks.length) ? (networks.length + ' en análisis') : '—';
  } else {
    if (scopeEl) scopeEl.textContent = nBd ? ('Sistema BD · ' + nBd + ' redes') : 'Sistema BD';
    if (fLab) fLab.textContent = 'Alcance';
    if (nLab) nLab.textContent = 'Estudio';
    fEl.textContent = 'todos los alimentadores';
    const st = (document.getElementById('ctxStudyFile')||{}).value || '';
    const stName = st ? String(st).split(/[/\\\\]/).pop() : '';
    nEl.textContent = stName || (nBd ? (nBd + ' redes cargables') : '—');
  }
  if (typeof syncSpotLoadContext === 'function') syncSpotLoadContext();
}
let _uiAbort = null;
function uiNewAbort(){
  try { if (_uiAbort) _uiAbort.abort(); } catch(e) {}
  _uiAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  return _uiAbort;
}
function uiSignal(){
  return (_uiAbort && _uiAbort.signal) ? _uiAbort.signal : undefined;
}
async function uiActualizar(){
  const msg = document.getElementById('hdrMsg');
  const b = document.getElementById('btnUiActualizar');
  if (b) b.disabled = true;
  if (msg) msg.textContent = 'Actualizando… vaciando tablero…';
  try{
    uiLiberarBusy();
    // Vaciar Tablero dinámico (errores/códigos → 0) de forma durable
    try {
      const r = await fetch('/api/ui/actualizar', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
        cache: 'no-store',
      });
      const j = await r.json().catch(function(){ return {}; });
      if (j && j.ok === false) throw new Error(j.error || 'ui/actualizar falló');
    } catch (eTab) {
      console.warn('ui/actualizar', eTab);
      try {
        await fetch('/api/tablero?clear=1', {cache: 'no-store'});
      } catch (e2) {}
    }
    if (typeof refreshContextFiles === 'function') await refreshContextFiles();
    if (typeof mqLoadNetworks === 'function') await mqLoadNetworks(true);
    if (typeof refreshCiFiles === 'function') await refreshCiFiles();
    if (typeof mqRefreshStatus === 'function') await mqRefreshStatus();
    if (msg) msg.innerHTML = '<span class="ok">Actualizado · Tablero en cero · UI v'+ (document.getElementById('hdrBadge')||{}).textContent +'</span>';
    // Recarga suave para que §2 lea tablero.json vacío
    setTimeout(function(){
      const u = window.location.pathname + '?_r=' + Date.now();
      window.location.replace(u);
    }, 150);
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e.message+'</span>';
  }finally{
    if (b) b.disabled = false;
  }
}
function uiLiberarBusy(){
  try {
    document.querySelectorAll('button.mq-running').forEach(btn=>{
      btn.disabled = false;
      btn.classList.remove('mq-running');
    });
    if (typeof _mqBusyBtn !== 'undefined') _mqBusyBtn = null;
    document.querySelectorAll('#mqActions button:disabled').forEach(btn=>{ btn.disabled = false; });
  } catch(e) {}
}
async function uiRestablecer(){
  const msg = document.getElementById('hdrMsg');
  if (!confirm('Restablecer UI: cancela acciones en curso, limpia cachés y recarga la página.\n\n¿Continuar?')) return;
  if (msg) msg.textContent = 'Restableciendo…';
  uiLiberarBusy();
  try { if (_uiAbort) _uiAbort.abort(); } catch(e) {}
  // No esperar al servidor: si CYMDIST/diagnóstico tiene el hilo ocupado, await cuelga para siempre.
  // Disparo el reset en background con tope corto y recargo siempre.
  try {
    const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    const t = setTimeout(function(){ try { if (ctrl) ctrl.abort(); } catch(e) {} }, 1500);
    fetch('/api/ui/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: '{}',
      signal: ctrl ? ctrl.signal : undefined,
      cache: 'no-store',
    }).catch(function(){}).finally(function(){ clearTimeout(t); });
  } catch(e) {}
  if (msg) msg.textContent = 'Recargando…';
  setTimeout(function(){
    const u = window.location.pathname + '?_r=' + Date.now();
    window.location.replace(u);
  }, 200);
}

let radialCatalog = [];
function modeUI(){
  const m=document.getElementById('mode').value;
  const isA = m==='A_COSFI';
  document.getElementById('row_amp').style.display = isA?'grid':'none';
  document.getElementById('row_kw').style.display = isA?'none':'grid';
  document.getElementById('box_cosfi').style.display = (!isA && m==='KW_COSFI')?'block':'none';
  document.getElementById('box_q').style.display = (!isA && m==='KW_KVAR')?'block':'none';
  previewHead();
}
document.getElementById('mode').addEventListener('change', modeUI);
['p_kw','q_kvar','cosfi','i_a','v_ll','cosfi_a'].forEach(id=>{
  const el=document.getElementById(id);
  if(el) el.addEventListener('input', previewHead);
});
modeUI();

let _ctxDatabases = [];
let _ctxStudies = [];

function fillCtxSelect(sel, items, currentPath, placeholder){
  if (!sel) return;
  const cur = currentPath || sel.value || '';
  sel.innerHTML = '<option value="">'+ (placeholder || '— Seleccione —') +'</option>';
  (items||[]).forEach(it=>{
    const opt = document.createElement('option');
    opt.value = it.path || '';
    opt.textContent = it.name || it.path || '';
    if ((it.path||'') === cur) opt.selected = true;
    sel.appendChild(opt);
  });
  if (cur && !Array.from(sel.options).some(o=>o.value===cur)) {
    const opt = document.createElement('option');
    opt.value = cur;
    opt.textContent = (cur.split(/[/\\]/).pop() || cur) + ' (actual)';
    opt.selected = true;
    sel.appendChild(opt);
  }
}

function syncCtxPaths(){
  const db = document.getElementById('ctxDbFile');
  const st = document.getElementById('ctxStudyFile');
  const dbPath = document.getElementById('ctxDbPath');
  const stPath = document.getElementById('ctxStudyPath');
  if (dbPath) dbPath.textContent = (db && db.value) ? db.value : '—';
  if (stPath) stPath.textContent = (st && st.value) ? st.value : '—';
}

async function refreshContextFiles(){
  const msg = document.getElementById('ctxMsg');
  try{
    const r = await fetchWithTimeout('/api/contexto/archivos', {cache:'no-store'}, 12000);
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || 'No se pudieron listar archivos');
    _ctxDatabases = j.databases || [];
    _ctxStudies = j.studies || [];
    fillCtxSelect(document.getElementById('ctxDbFile'), _ctxDatabases, j.current_database, '— Seleccione base de datos —');
    fillCtxSelect(document.getElementById('ctxStudyFile'), _ctxStudies, j.current_study, '— Seleccione estudio —');
    syncCtxPaths();
    updateHeaderContext();
    if (msg) msg.textContent = (_ctxDatabases.length)+' BD · '+(_ctxStudies.length)+' estudios · elija y pulse «Aplicar BD + estudio»';
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e.message+'</span>';
  }
}

function ctxFeederFromStudy(studyPath){
  const name = ((studyPath||'').split(/[/\\]/).pop()||'');
  const stem = name.replace(/\.(zxst|sxst|zsxst)$/i, '');
  if (!stem || /^ELD$/i.test(stem)) return '';
  return stem.toUpperCase();
}

function getContextSelection(){
  const db = (document.getElementById('ctxDbFile')||{}).value || '';
  const st = (document.getElementById('ctxStudyFile')||{}).value || '';
  const feeder = ctxFeederFromStudy(st)
    || ((typeof getMqSelectedFeeders==='function' && getMqSelectedFeeders()[0]) || '')
    || ((typeof getSelectedFeeders==='function' && getSelectedFeeders()[0]) || '')
    || '';
  return { database_mdb: db, study_path: st, feeder: feeder };
}

async function applyContextFiles(){
  const msg = document.getElementById('ctxMsg');
  const sel = getContextSelection();
  if (!sel.database_mdb && !sel.study_path) {
    if (msg) msg.innerHTML = '<span class="err">Seleccione base de datos y/o estudio.</span>';
    return null;
  }
  const btn = document.getElementById('btnCtxApply');
  if (btn) btn.disabled = true;
  if (msg) msg.textContent = 'Aplicando BD/estudio → alimentador '+(sel.feeder||'?')+'…';
  try{
    const r = await fetch('/api/contexto/aplicar', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        database_mdb: sel.database_mdb || null,
        study_path: sel.study_path || null,
        feeder: sel.feeder || null,
      }),
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || 'No se pudo aplicar');
    // El alimentador activo pasa a ser el del estudio (IN112.zxst → IN112)
    if (j.feeder_id || j.active_feeder) {
      window.ACTIVE_FEEDER = j.feeder_id || j.active_feeder;
    }
    if (j.network_id) window.ACTIVE_NETWORK = j.network_id;
    // §3 debe trabajar sobre este estudio: limpia nodos/resolución previos
    try {
      _resolved = null;
      _loadHistory = [];
      const ns = document.getElementById('nodeSelect');
      if (ns) ns.innerHTML = '<option value="">— Busque y seleccione —</option>';
      ['autoSection','autoLoadId','nodeQuery'].forEach(function(id){
        const el = document.getElementById(id); if (el) el.value = '';
      });
      const lh = document.getElementById('loadHistory'); if (lh) lh.innerHTML = '';
      const lm = document.getElementById('loadMsg');
      if (lm) lm.innerHTML = '<span class="muted">Estudio §1 → <b>'+(window.ACTIVE_FEEDER||'?')
        +'</b>. Pulse «Actualizar inventario nodos» en §3.</span>';
      const btn = document.getElementById('btnConnectLoad');
      if (btn) btn.disabled = true;
    } catch(e) {}
    syncCtxPaths();
    syncSpotLoadContext();
    updateHeaderContext({
      feeders: j.feeder_id ? [j.feeder_id] : (sel.feeder ? [sel.feeder] : []),
      networks: j.network_id ? [j.network_id] : [],
    });
    // Marcar ese alimentador en calidad / clientes si está en lista
    try {
      const want = String(j.feeder_id || sel.feeder || '').toUpperCase();
      if (want && typeof mqSelectOnlyCurrent === 'function') {
        // forzar foco al feeder del estudio
        const inp = document.getElementById('mqFeederSearch');
        if (inp) inp.value = want;
        document.querySelectorAll('#mqFeederList input.mq-feeder-cb').forEach(cb=>{
          cb.checked = ((cb.getAttribute('data-feeder')||'').toUpperCase() === want);
        });
        if (typeof mqUpdateSelLabel === 'function') mqUpdateSelLabel();
      }
    } catch(e) {}
    if (msg) msg.innerHTML = '<span class="ok">Listo · alimentador <b>'+(j.feeder_id||sel.feeder||'?')
      +'</b> · BD='+(j.database_connection_name||'?')
      +' · estudio='+(j.study_file||'?')
      +(j.network_id?(' · red='+j.network_id):'')+'</span>';
    if (typeof mqLoadNetworks === 'function') await mqLoadNetworks(true);
    updateHeaderContext({
      feeders: j.feeder_id ? [j.feeder_id] : (sel.feeder ? [sel.feeder] : []),
      networks: j.network_id ? [j.network_id] : [],
    });
    return j;
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e.message+'</span>';
    return null;
  }finally{
    if (btn) btn.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', function(){
  const db = document.getElementById('ctxDbFile');
  const st = document.getElementById('ctxStudyFile');
  if (db) db.addEventListener('change', function(){ syncCtxPaths(); updateHeaderContext(); syncSpotLoadContext(); });
  if (st) st.addEventListener('change', function(){ syncCtxPaths(); updateHeaderContext(); syncSpotLoadContext(); });
  updateHeaderContext();
  syncSpotLoadContext();
  refreshContextFiles();
});

function headBody(){
  const m=document.getElementById('mode').value;
  const body={
    mode: m,
    fecha_medicion: document.getElementById('fecha_med').value,
  };
  if(m==='A_COSFI'){
    body.I_A = document.getElementById('i_a').value;
    body.Vll_kV = document.getElementById('v_ll').value;
    body.cosfi = document.getElementById('cosfi_a').value;
  }else{
    body.P_kW = document.getElementById('p_kw').value;
    body.Q_kvar = document.getElementById('q_kvar').value;
    body.cosfi = document.getElementById('cosfi').value;
  }
  return body;
}

function previewHead(){
  const prev=document.getElementById('headPreview');
  const sum=document.getElementById('headAllocSummary');
  const m=document.getElementById('mode').value;
  try{
    let p=null, q=null, fp=0.95;
    if(m==='A_COSFI'){
      const i=parseFloat(document.getElementById('i_a').value);
      const v=parseFloat(document.getElementById('v_ll').value);
      fp=parseFloat(document.getElementById('cosfi_a').value);
      if(!(i>0) || !(v>0) || !(fp>0&&fp<=1)){ prev.textContent='Ingrese I (A), Vll (kV) y cosφ'; if(sum) sum.textContent='Falta completar medición de cabecera (§1).'; return; }
      p = Math.sqrt(3)*v*i*fp;
      q = p*Math.tan(Math.acos(fp));
      prev.textContent = 'P = '+p.toFixed(2)+' kW · Q = '+q.toFixed(2)+' kvar  (√3·V·I·cosφ)';
    }else if(m==='KW_COSFI'){
      p=parseFloat(document.getElementById('p_kw').value);
      fp=parseFloat(document.getElementById('cosfi').value);
      if(!(p>=0) || !(fp>0&&fp<=1)){ prev.textContent='Ingrese P (kW) y cosφ'; if(sum) sum.textContent='Falta completar medición de cabecera (§1).'; return; }
      q = p*Math.tan(Math.acos(fp));
      prev.textContent = 'P = '+p.toFixed(2)+' kW · Q = '+q.toFixed(2)+' kvar';
    }else{
      p=parseFloat(document.getElementById('p_kw').value);
      q=parseFloat(document.getElementById('q_kvar').value);
      if(!(p>=0) || isNaN(q)){ prev.textContent='Ingrese P (kW) y Q (kvar)'; if(sum) sum.textContent='Falta completar medición de cabecera (§1).'; return; }
      prev.textContent = 'P = '+p.toFixed(2)+' kW · Q = '+q.toFixed(2)+' kvar';
    }
    if(sum) sum.innerHTML = '<b>P = '+p.toFixed(2)+' kW</b> · <b>Q = '+q.toFixed(2)+' kvar</b> · modo '+m+
      ' · <a href="#mode">editar en §1</a>';
  }catch(e){
    prev.textContent = String(e);
  }
}

async function saveHead(opts){
  opts = opts || {};
  const resetDownstream = opts.resetDownstream !== false; // por defecto sí (botón §1)
  const msgEl = document.getElementById('headMsg');
  const btns = document.querySelectorAll('button[onclick="saveHead()"]');
  btns.forEach(function(b){ b.disabled = true; });
  const sel = getContextSelection();
  if (!sel.study_path || !sel.database_mdb) {
    if (msgEl) {
      msgEl.innerHTML = '<span class="err">Seleccione BD y estudio arriba, pulse «Aplicar BD + estudio», luego guarde.</span>';
      msgEl.className = 'err';
    }
    btns.forEach(function(b){ b.disabled = false; });
    return {ok:false, error:'Falta BD/estudio'};
  }
  const feeder = sel.feeder || ctxFeederFromStudy(sel.study_path) || '';
  if (msgEl) {
    msgEl.textContent = 'Guardando cabecera '+feeder+' (sesión + SetDemand en proceso aislado)…';
    msgEl.className = 'muted';
  }
  // Un solo POST: sesión inmediata + SetDemand en subproceso (no mata la UI si COM crashea).
  const body = headBody();
  body.reset_downstream = !!resetDownstream;
  body.database_mdb = sel.database_mdb;
  body.study_path = sel.study_path;
  body.feeder = feeder;
  const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  const timer = setTimeout(function(){ try { if (ctrl) ctrl.abort(); } catch(e) {} }, 120000);
  try{
    const headers = {'Content-Type': 'application/json'};
    if (feeder) headers['X-Feeder'] = feeder;
    const r = await fetch('/api/cabecera', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body),
      signal: ctrl ? ctrl.signal : undefined,
    });
    let j = null;
    try { j = await r.json(); } catch(e) {
      throw new Error('Respuesta no JSON ('+r.status+'). Recargue la página (UI v5.6+ aísla CYMDIST).');
    }
    if(j.ok){
      let msg='OK · '+(j.feeder_id||feeder)+' · P='+Number(j.P_kW).toFixed(2)+' kW · Q='+Number(j.Q_kvar).toFixed(2)+' kvar';
      if(j.study_file || j.study_path){
        msg += ' · '+(j.study_file || j.study_path);
      }
      if(j.network_id) msg += ' · red '+j.network_id;
      if(j.cymdist_ok || j.cymdist){
        msg += ' · SetDemand API';
        if(j.cymdist && j.cymdist.saved) msg += ' · estudio .zxst guardado';
      }
      if(j.elapsed_sec!=null) msg += ' · '+j.elapsed_sec+'s';
      if(j.reset_downstream){
        msg += ' · §§2–4 restablecidos';
        resetDownstreamUI();
      }
      if (msgEl) { msgEl.textContent=msg; msgEl.className='ok'; }
      if(j.P_kW!=null && document.getElementById('mode').value==='A_COSFI'){
        document.getElementById('p_kw').value = Number(j.P_kW).toFixed(2);
        document.getElementById('q_kvar').value = Number(j.Q_kvar).toFixed(2);
      }
      updateHeaderContext({
        feeders: (j.feeder_id||feeder) ? [j.feeder_id||feeder] : [],
        networks: j.network_id ? [j.network_id] : [],
      });
    }else{
      const err = j.error || j.msg || 'Error';
      if (msgEl) { msgEl.textContent=err; msgEl.className='err'; }
    }
    previewHead();
    return j;
  }catch(e){
    const aborted = (e && (e.name==='AbortError' || /abort/i.test(String(e))));
    const text = aborted
      ? 'Tiempo agotado (>120s) escribiendo cabecera. La UI sigue viva: reintente Guardar. Si Cyme está abierto, ciérrelo.'
      : String(e.message||e);
    if (msgEl) { msgEl.textContent = text; msgEl.className = 'err'; }
    return {ok: false, error: text};
  }finally{
    clearTimeout(timer);
    btns.forEach(function(b){ b.disabled = false; });
  }
}

function resetDownstreamUI(){
  // §2 clientes + distribución
  clearCliTable();
  const cliMsg = document.getElementById('cliMsg');
  if (cliMsg) cliMsg.innerHTML = '<span class="muted">Cabecera nueva: arme de nuevo la tabla y cargue EA/Pot.</span>';
  const distMsg = document.getElementById('distMsg');
  if (distMsg) distMsg.textContent = '';
  const distOut = document.getElementById('distOut');
  if (distOut) distOut.textContent = '';
  // §3 SpotLoad (historial UI; no borra dispositivos ya en CYMDIST)
  _loadHistory = [];
  _resolved = null;
  try { renderLoadHistory(); } catch(e) {}
  const ids = ['loadName','autoSection','autoLoadId','loadP','loadResolve'];
  ids.forEach(id=>{ const el=document.getElementById(id); if(el){ if(el.tagName==='INPUT') el.value=''; else el.textContent=''; }});
  const loadMsg = document.getElementById('loadMsg');
  if (loadMsg) loadMsg.textContent = 'Tras redistribuir (§2), busque un nodo para conectar la carga.';
  const btnConnect = document.getElementById('btnConnectLoad');
  if (btnConnect) btnConnect.disabled = true;
  // §4 análisis
  const analisisMsg = document.getElementById('analisisMsg');
  if (analisisMsg) analisisMsg.textContent = '';
  const analisisOut = document.getElementById('analisisOut');
  if (analisisOut) analisisOut.textContent = '';
}
function fillSelect(sel, files, placeholder){
  const cur = sel.value;
  sel.innerHTML = '';
  if (placeholder) {
    const o = document.createElement('option');
    o.value = '';
    o.textContent = placeholder;
    sel.appendChild(o);
  }
  (files||[]).forEach(f=>{
    const o=document.createElement('option');
    o.value=f; o.textContent=f;
    sel.appendChild(o);
  });
  if (cur && files.indexOf(cur)>=0) sel.value = cur;
}

function getSelectedFeeders(){
  return Array.from(document.querySelectorAll('#feederList input.feeder-cb:checked'))
    .map(cb=>cb.value);
}

function getSelectedFeeder(){
  const sel = getSelectedFeeders();
  return sel.length ? sel[sel.length-1] : '';
}

function isMultiAllowed(){
  const el = document.getElementById('allowMultiFeeders');
  return !!(el && el.checked);
}

function clearCliTable(){
  cliTableReady = false;
  const applyBtn = document.getElementById('btnApplyCli');
  if (applyBtn) applyBtn.disabled = true;
  const box = document.getElementById('cliTable');
  if (box) box.innerHTML = '';
  cliRowsCache = [];
  const meta = document.getElementById('cliMeta');
  if (meta) meta.textContent = '';
}

function setExclusiveFeeder(id){
  const want = String(id||'').toUpperCase();
  document.querySelectorAll('#feederList input.feeder-cb').forEach(cb=>{
    cb.checked = (cb.value.toUpperCase() === want);
  });
}

function syncFeederSearchBox(){
  const sel = getSelectedFeeders();
  const inp = document.getElementById('feederSearch');
  if (!inp) return;
  // En modo un solo: mostrar ese código. En varios: lista separada por coma.
  inp.value = sel.join(', ');
  document.querySelectorAll('#feederList label.feeder-item').forEach(lab=>{
    lab.classList.remove('hidden');
  });
}

function hasCiFileSelected(){
  const v = ((document.getElementById('ciFile')||{}).value||'').trim();
  return !!v;
}

function cliFocusFeederId(){
  const sel = getSelectedFeeders();
  if (sel.length) return String(sel[0]||'').toUpperCase();
  const raw = ((document.getElementById('feederSearch')||{}).value||'').split(',')[0].trim().toUpperCase();
  if (raw) return raw;
  return '';
}

function feederCountText(id){
  // Cantidad de clientes solo si hay archivo clientesimportantes + alimentador.
  if (!hasCiFileSelected()) return '';
  const item = (radialCatalog||[]).find(x=>String(x.id||'').toUpperCase()===String(id||'').toUpperCase());
  if (!item || item.n == null) return '';
  return item.n + ' clientes';
}

function updateFeederSelLabel(){
  const sel = getSelectedFeeders();
  const el = document.getElementById('feederSel');
  const total = (radialCatalog||[]).length;
  const btn = document.getElementById('btnCliSoloFeeder');
  const focus = cliFocusFeederId();
  if (btn) btn.textContent = focus ? ('Solo ' + focus) : 'Solo (elegir alim.)';
  // Si calidad no tiene selección, el encabezado sigue al radial de clientes.
  if (typeof getMqSelectedFeeders === 'function' && !getMqSelectedFeeders().length) {
    updateHeaderContext({feeders: sel, networks: []});
  }
  if (!el) return;
  if (!hasCiFileSelected()) {
    el.textContent = total
      ? (total+' RADIAL en suministro · seleccione clientesimportantes y un alimentador')
      : 'Seleccione archivo clientesimportantes y un alimentador.';
    return;
  }
  if (!total) {
    el.textContent = 'Sin alimentadores en el archivo suministro.';
    return;
  }
  if (!sel.length) {
    el.innerHTML = '<span class="err">Seleccione un alimentador.</span>';
    return;
  }
  if (sel.length === 1) {
    const cnt = feederCountText(sel[0]);
    el.innerHTML = 'Seleccionado: <b>'+sel[0]+'</b>'
      +(cnt ? (' · '+cnt) : '')
      +' · cruce NIS <b>solo</b> este RADIAL (archivo CI elegido)';
    return;
  }
  el.innerHTML = '<b>'+sel.length+'</b> seleccionados: <b>'+sel.join(', ')+'</b>'
    +(hasCiFileSelected() ? ' · cruce NIS en archivo CI elegido' : '');
}

function filterFeederList(){
  const raw = (document.getElementById('feederSearch').value||'').trim();
  const q = raw.toUpperCase();
  const selJoined = getSelectedFeeders().join(', ').toUpperCase();
  if (!q || q === selJoined) {
    document.querySelectorAll('#feederList label.feeder-item').forEach(lab=>{
      lab.classList.remove('hidden');
    });
    return;
  }
  // Si escribe un solo código (sin comas), filtrar; no cambiar la selección hasta click/Enter
  const qOne = q.indexOf(',') >= 0 ? '' : q;
  document.querySelectorAll('#feederList label.feeder-item').forEach(lab=>{
    const id = (lab.dataset.id||'').toUpperCase();
    if (!qOne) {
      lab.classList.remove('hidden');
    } else {
      lab.classList.toggle('hidden', id.indexOf(qOne)<0);
    }
  });
}

function feederSearchKey(ev){
  if (ev.key !== 'Enter') return;
  ev.preventDefault();
  const raw = (document.getElementById('feederSearch').value||'').trim().toUpperCase();
  if (!raw || raw.indexOf(',') >= 0) return;
  // Match exacto primero, luego prefijo
  const ids = (radialCatalog||[]).map(it=>String(it.id||'').toUpperCase());
  let hit = ids.find(id=>id === raw);
  if (!hit) hit = ids.find(id=>id.indexOf(raw) === 0);
  if (!hit) hit = ids.find(id=>id.indexOf(raw) >= 0);
  if (!hit) {
    const msg = document.getElementById('cliMsg');
    if (msg) msg.innerHTML = '<span class="err">No hay alimentador «'+raw+'» en el archivo suministro.</span>';
    return;
  }
  selectFeeder(hit, false);
}

function selectFeeder(id, keepOthers){
  const want = String(id||'').toUpperCase();
  if (!want) return;
  if (keepOthers && isMultiAllowed()) {
    document.querySelectorAll('#feederList input.feeder-cb').forEach(cb=>{
      if (cb.value.toUpperCase() === want) cb.checked = true;
    });
  } else {
    setExclusiveFeeder(want);
  }
  syncFeederSearchBox();
  updateFeederSelLabel();
  clearCliTable();
  const msg = document.getElementById('cliMsg');
  const sel = getSelectedFeeders();
  if (msg) {
    msg.textContent = sel.length === 1
      ? ('Alimentador '+sel[0]+' · Pulse «Armar tabla» (solo este radial; tabla anterior descartada).')
      : ('Alimentadores '+sel.join(', ')+' · Pulse «Armar tabla».');
  }
}

function onMultiModeChange(){
  if (!isMultiAllowed()) {
    // Al desactivar varios: dejar solo el último marcado
    const last = getSelectedFeeder();
    if (last) setExclusiveFeeder(last);
    rebuildFeederInputs();
  } else {
    rebuildFeederInputs();
  }
  syncFeederSearchBox();
  updateFeederSelLabel();
}

function selectAllFeeders(on){
  if (on) {
    if (!isMultiAllowed()) {
      const msg = document.getElementById('cliMsg');
      if (msg) msg.innerHTML = '<span class="err">Active «Permitir varios» para seleccionar más de uno.</span>';
      return;
    }
    document.querySelectorAll('#feederList input.feeder-cb').forEach(cb=>{ cb.checked = true; });
  } else {
    document.querySelectorAll('#feederList input.feeder-cb').forEach(cb=>{ cb.checked = false; });
  }
  syncFeederSearchBox();
  updateFeederSelLabel();
  clearCliTable();
  const msg = document.getElementById('cliMsg');
  if (msg) msg.textContent = on ? 'Todos marcados · Pulse «Armar tabla».' : 'Seleccione un alimentador y pulse «Armar tabla».';
}

function selectOnlyCurrentFeeder(){
  const want = cliFocusFeederId();
  if (!want) {
    const msg = document.getElementById('cliMsg');
    if (msg) msg.innerHTML = '<span class="err">Seleccione o escriba un alimentador primero.</span>';
    return;
  }
  selectFeeder(want, false);
  const btn = document.getElementById('btnCliSoloFeeder');
  if (btn) btn.textContent = 'Solo ' + want;
}

function rebuildFeederInputs(){
  const multi = isMultiAllowed();
  const selected = new Set(getSelectedFeeders().map(x=>String(x).toUpperCase()));
  const showCnt = hasCiFileSelected();
  document.querySelectorAll('#feederList label.feeder-item').forEach(lab=>{
    const id = (lab.dataset.id||'').toUpperCase();
    const checked = selected.has(id) ? 'checked' : '';
    const cnt = showCnt ? feederCountText(id) : '';
    const cntHtml = cnt ? ('<span class="cnt">'+cnt+'</span>') : '<span class="cnt"></span>';
    if (multi) {
      lab.innerHTML = `<input type="checkbox" class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>`
        +`<span>${id}</span>${cntHtml}`;
    } else {
      lab.innerHTML = `<input type="radio" name="feederRadial" class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>`
        +`<span>${id}</span>${cntHtml}`;
    }
  });
}

function renderFeederList(items, preferSelected){
  radialCatalog = items || [];
  const box = document.getElementById('feederList');
  let prefer = '';
  // Solo preferir lo que el usuario ya tenía marcado o escribió; no forzar PA217 fijo.
  if (preferSelected && preferSelected.length === 1) {
    prefer = String(preferSelected[0]).toUpperCase();
  } else if (preferSelected && preferSelected.length > 1 && isMultiAllowed()) {
    prefer = '';
  } else if (preferSelected && preferSelected.length > 1 && !isMultiAllowed()) {
    prefer = String(preferSelected[preferSelected.length-1]).toUpperCase();
  } else {
    prefer = cliFocusFeederId() || '';
  }
  if (!radialCatalog.length) {
    box.innerHTML = '<div class="muted" style="padding:8px 10px">Sin RADIAL en el archivo.</div>';
    syncFeederSearchBox();
    updateFeederSelLabel();
    return;
  }
  const multi = isMultiAllowed();
  const prev = new Set();
  if (prefer) prev.add(prefer);
  else if (multi && preferSelected) {
    preferSelected.forEach(x=>prev.add(String(x).toUpperCase()));
  }
  const showCnt = hasCiFileSelected();
  box.innerHTML = radialCatalog.map(it=>{
    const id = String(it.id||'').toUpperCase();
    const checked = prev.has(id) ? 'checked' : '';
    const typ = multi ? 'checkbox' : 'radio';
    const name = multi ? '' : 'name="feederRadial"';
    const cnt = showCnt ? feederCountText(id) : '';
    const cntHtml = cnt ? ('<span class="cnt">'+cnt+'</span>') : '<span class="cnt"></span>';
    return `<label class="feeder-item" data-id="${id}">
      <input type="${typ}" ${name} class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>
      <span>${id}</span>${cntHtml}
    </label>`;
  }).join('');
  if (!getSelectedFeeders().length && radialCatalog.length && prefer) {
    setExclusiveFeeder(prefer);
  }
  syncFeederSearchBox();
  updateFeederSelLabel();
}

function onFeederCheckChange(el, ev){
  const multi = isMultiAllowed();
  const id = el ? String(el.value||'').toUpperCase() : '';
  // Sin «Permitir varios»: un click = solo ese alimentador (nunca acumula IN111+PA217)
  if (!multi) {
    if (el && el.checked) setExclusiveFeeder(id);
  } else if (ev && !ev.ctrlKey && !ev.metaKey && el && el.checked) {
    // Con varios activos: click normal sigue siendo exclusivo; Ctrl+click suma
    // (si el usuario quiere acumular sin Ctrl, ya tiene checkboxes y puede marcar varios)
  }
  syncFeederSearchBox();
  updateFeederSelLabel();
  clearCliTable();
  const sel = getSelectedFeeders();
  const msg = document.getElementById('cliMsg');
  if (msg) {
    if (!sel.length) msg.textContent = 'Seleccione un alimentador.';
    else if (sel.length === 1) {
      msg.textContent = 'Alimentador '+sel[0]+' · Pulse «Armar tabla» (tabla anterior descartada).';
    } else {
      msg.textContent = sel.length+' alimentadores: '+sel.join(', ')+' · Pulse «Armar tabla».';
    }
  }
}

async function refreshRadiales(){
  const sum = document.getElementById('sumFile').value;
  const el = document.getElementById('feederSel');
  el.textContent = 'Leyendo alimentadores del archivo…';
  try{
    const q = sum ? ('?suministro_file='+encodeURIComponent(sum)) : '';
    const r = await fetch('/api/clientes/radiales'+q);
    const j = await r.json();
    if(!j.ok){
      el.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>';
      renderFeederList([]);
      return;
    }
    renderFeederList(j.radiales||[], getSelectedFeeders());
  }catch(e){
    el.innerHTML = '<span class="err">'+e+'</span>';
  }
}

function feederRequestFields(){
  const feeders = getSelectedFeeders();
  const multi = isMultiAllowed() && feeders.length > 1;
  return {
    feeders: feeders,
    feeder: feeders.length ? (multi ? feeders.join(',') : feeders[0]) : '',
    all_feeders: false,
  };
}

function clientesFp(){
  // kvar desde Pot: usa cosφ de cabecera (§1)
  const m = (document.getElementById('mode')||{}).value || 'KW_COSFI';
  const el = document.getElementById(m==='A_COSFI' ? 'cosfi_a' : 'cosfi');
  const v = el ? parseFloat(el.value) : NaN;
  return (v>0 && v<=1) ? v : 0.95;
}

function onCiFileChange(){
  const v = document.getElementById('ciFile').value;
  cliTableReady = false;
  document.getElementById('btnBuildCli').disabled = !v;
  document.getElementById('btnApplyCli').disabled = true;
  document.getElementById('cliTable').innerHTML = '';
  cliRowsCache = [];
  document.getElementById('cliMeta').textContent = '';
  if (!v) {
    document.getElementById('cliMsg').textContent = 'Seleccione un archivo de clientesimportantes.';
  } else {
    document.getElementById('cliMsg').textContent = 'Archivo listo: '+v+' · Pulse «Armar tabla» para cruzar NIS solo en este archivo.';
  }
  // Recalcular etiquetas / conteos: solo con CI + alimentador se muestra «N clientes».
  rebuildFeederInputs();
  updateFeederSelLabel();
}

async function refreshCiFiles(){
  const r = await fetch('/api/clientes/archivos');
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('cliMsg').innerHTML = '<span class="err">'+(j.error||'Error listando archivos')+'</span>';
    return;
  }
  fillSelect(document.getElementById('sumFile'), j.suministro, null);
  fillSelect(document.getElementById('ciFile'), j.clientesimportantes, '— Seleccione archivo —');
  onCiFileChange();
  await refreshRadiales();
  document.getElementById('cliMsg').textContent =
    'Archivos CI cargados: '+(j.clientesimportantes||[]).length+' · Seleccione uno para cruzar.';
}

document.getElementById('ciFile').addEventListener('change', onCiFileChange);
document.getElementById('sumFile').addEventListener('change', ()=>{
  cliTableReady = false;
  document.getElementById('btnApplyCli').disabled = true;
  refreshRadiales();
});
refreshCiFiles();

let cliRowsCache = [];

function cliRowKey(r){
  return String(r.Suministro||'').trim()+'|'+String(r.SED||'').trim();
}

function collectActivoMap(){
  const map = {};
  document.querySelectorAll('#cliTable input.cli-activo').forEach(cb=>{
    map[cb.dataset.key] = cb.checked;
  });
  return map;
}

function collectRestarCabeceraMap(){
  const map = {};
  document.querySelectorAll('#cliTable input.cli-restar').forEach(cb=>{
    map[cb.dataset.key] = cb.checked;
  });
  return map;
}

function syncActivoFromDom(){
  const map = collectActivoMap();
  const rmap = collectRestarCabeceraMap();
  cliRowsCache.forEach(r=>{
    const k = cliRowKey(r);
    if (k in map) r.Activo = map[k];
    if (k in rmap) r.RestarCabecera = rmap[k];
  });
  const nOff = cliRowsCache.filter(r=>r.Activo===false).length;
  const nRest = cliRowsCache.filter(r=>r.Activo===false && r.RestarCabecera===true).length;
  const tip = document.getElementById('cliActivoTip');
  if (tip) {
    tip.textContent = nOff
      ? (nOff+' desmarcada(s): se desconectan · '+nRest+' restan Pot de cabecera §1')
      : 'Todas incluidas. Desmarque Incluir para desconectar; use Restar cab. si además sale del alimentador.';
  }
}

async function persistActivo(){
  syncActivoFromDom();
  try{
    await fetch('/api/clientes/activo',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        activo: collectActivoMap(),
        restar_cabecera: collectRestarCabeceraMap(),
      }),
    });
  }catch(_e){ /* la selección sigue en memoria / se reenvía al aplicar */ }
}

function toggleAllActivo(on){
  document.querySelectorAll('#cliTable input.cli-activo').forEach(cb=>{ cb.checked = !!on; });
  syncActivoFromDom();
  persistActivo();
}

function toggleAllRestarCabecera(on){
  document.querySelectorAll('#cliTable input.cli-restar').forEach(cb=>{ cb.checked = !!on; });
  syncActivoFromDom();
  persistActivo();
}

async function downloadCliExcel(){
  syncActivoFromDom();
  if (!cliRowsCache.length) {
    document.getElementById('cliMsg').innerHTML = '<span class="err">No hay tabla para descargar. Arme la tabla primero.</span>';
    return;
  }
  const btn = document.getElementById('btnCliExcel');
  if (btn) btn.disabled = true;
  const tip = document.getElementById('cliActivoTip');
  const prevTip = tip ? tip.textContent : '';
  if (tip) tip.textContent = 'Generando Excel…';
  try{
    const ff = feederRequestFields();
    const r = await fetch('/api/clientes/export_xlsx', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        rows: cliRowsCache,
        clientes_file: (document.getElementById('ciFile')||{}).value || '',
        feeders: ff.feeders || [],
      }),
    });
    if (!r.ok) {
      let err = 'Error exportando Excel';
      try { const j = await r.json(); err = j.error || err; } catch(_e) {}
      document.getElementById('cliMsg').innerHTML = '<span class="err">'+err+'</span>';
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    let fname = 'clientes_alimentador.xlsx';
    const m = /filename="?([^";]+)"?/i.exec(cd);
    if (m) fname = m[1];
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (tip) tip.textContent = prevTip || ('Excel descargado: '+fname);
  }catch(e){
    document.getElementById('cliMsg').innerHTML = '<span class="err">'+e+'</span>';
  }finally{
    if (btn) btn.disabled = false;
  }
}

function renderCliTable(rows){
  const box=document.getElementById('cliTable');
  if(!rows || !rows.length){box.innerHTML='<p class="muted">Sin filas</p>';cliRowsCache=[];return;}
  cliRowsCache = rows.map(r=>({
    ...r,
    Activo: r.Activo!==false && r.Activo!=='false' && r.Activo!==0 && r.Activo!=='0',
    RestarCabecera: r.RestarCabecera===true || r.RestarCabecera==='true' || r.RestarCabecera===1 || r.RestarCabecera==='1',
  }));
  const nOff = cliRowsCache.filter(r=>!r.Activo).length;
  const nRestOn = cliRowsCache.filter(r=>r.RestarCabecera).length;
  let html='<div class="actions" style="margin:0 0 8px 0">'
    +'<button type="button" class="ghost" onclick="toggleAllActivo(true)">Marcar todas</button>'
    +'<button type="button" class="ghost" onclick="toggleAllActivo(false)">Desmarcar todas</button>'
    +'<button type="button" class="ghost" onclick="toggleAllRestarCabecera(true)">Restar cab. todas</button>'
    +'<button type="button" class="ghost" onclick="toggleAllRestarCabecera(false)">Restar cab. ninguna</button>'
    +'<button type="button" class="secondary" onclick="downloadCliExcel()" id="btnCliExcel">Descargar Excel</button>'
    +'<span class="muted" id="cliActivoTip">'
    +(nOff
      ? (nOff+' desmarcada(s): se desconectan · use Restar cab. para restar Pot de §1')
      : 'Incluir = EA/Pot. Restar cab. = si desmarca Incluir, restar Pot de P máx §1 (carga que salió del alimentador).')
    +'</span></div>';
  html+='<table><thead><tr>'
    +'<th class="col-incluir" title="Incluir: conectada. Desmarcar = desconectar en modelo físico CYMDIST">'
    +'<input type="checkbox" id="cliActivoAll" '
    +(nOff===0?'checked':'')
    +' onchange="toggleAllActivo(this.checked)" title="Marcar/desmarcar todas"/> Incluir</th>'
    +'<th class="col-restar" title="Si Incluir off: restar Pot de P(kW) máx §1. Off = solo desconectar, sin tocar cabecera">'
    +'<input type="checkbox" id="cliRestarAll" '
    +(nRestOn===cliRowsCache.length && cliRowsCache.length>0?'checked':'')
    +' onchange="toggleAllRestarCabecera(this.checked)" title="Marcar/desmarcar Restar cabecera"/> Restar cab.</th>'
    +'<th>RADIAL</th><th>Suministro</th><th>Cliente</th><th>SED</th><th>EA</th><th>Pot</th><th>LoadID</th><th>CI</th><th>SED↔</th>'
    +'</tr></thead><tbody>';
  cliRowsCache.forEach(r=>{
    const ea = r.EA==null?'':Number(r.EA).toFixed(1);
    const pot = r.Pot==null?'':Number(r.Pot).toFixed(2);
    const key = cliRowKey(r);
    const checked = r.Activo ? 'checked' : '';
    const restarChecked = r.RestarCabecera ? 'checked' : '';
    const dim = r.Activo ? '' : ' class="off-row"';
    html+=`<tr${dim}>
      <td class="col-incluir"><input type="checkbox" class="cli-activo" data-key="${key}" ${checked} onchange="syncActivoFromDom();persistActivo()"/></td>
      <td class="col-restar"><input type="checkbox" class="cli-restar" data-key="${key}" ${restarChecked} title="Restar Pot de cabecera si Incluir off" onchange="syncActivoFromDom();persistActivo()"/></td>
      <td>${r.RADIAL||''}</td><td>${r.Suministro||''}</td><td>${r.Cliente||''}</td><td>${r.SED||''}</td>
      <td>${ea}</td><td>${pot}</td><td>${r.LoadID_CYMDIST||''}</td>
      <td>${r.Match_CI?'✓':'✗'}</td><td>${r.Match_SED?'✓':'✗'}</td></tr>`;
  });
  html+='</tbody></table>';
  box.innerHTML=html;
}

function requireCiFile(){
  const ci = document.getElementById('ciFile').value;
  if (!ci) {
    document.getElementById('cliMsg').innerHTML='<span class="err">Seleccione un archivo de clientesimportantes.</span>';
    return null;
  }
  return ci;
}

async function mqFetch(path, body, optsExtra){
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const pack = optsExtra || {};
  if (pack.feeder) headers['X-Feeder'] = String(pack.feeder);
  const opts = {
    method: body === undefined ? 'GET' : 'POST',
    headers: headers,
  };
  const sig = uiSignal();
  if (sig) opts.signal = sig;
  if (body !== undefined) {
    const payload = Object.assign({}, body || {});
    if (pack.networks) payload.networks = pack.networks;
    if (pack.feeders) payload.feeders = pack.feeders;
    if (pack.feeder && !payload.feeder) payload.feeder = pack.feeder;
    opts.body = JSON.stringify(payload);
  }
  const url = pack.feeder && body === undefined
    ? (path.indexOf('?')>=0 ? path+'&feeder='+encodeURIComponent(pack.feeder) : path+'?feeder='+encodeURIComponent(pack.feeder))
    : path;
  // force=1 (Actualizar lista) puede abrir CYMDIST; soft arranque = 12s
  const heavy = (body !== undefined) || (String(path).indexOf('force=1') >= 0);
  const r = await fetchWithTimeout(url, opts, heavy ? 180000 : 12000);
  let j = null;
  try { j = await r.json(); } catch(e) {
    throw new Error('Respuesta no JSON ('+r.status+') en '+path);
  }
  if (!r.ok && j && j.error) throw new Error(j.error);
  if (!r.ok) throw new Error('HTTP '+r.status+' en '+path);
  if (j && j.busy) throw new Error(j.error || 'CYMDIST ocupado');
  return j;
}

let _mqNetworks = [];
let _mqBusyBtn = null;

function mqBusy(btnId, on, label){
  // Nunca deshabilita ni marca el resto: cada botón es 100% individual.
  const b = btnId ? document.getElementById(btnId) : null;
  if (on) {
    _mqBusyBtn = btnId || null;
    if (b) { b.disabled = true; b.classList.add('mq-running'); }
  } else {
    if (b) { b.disabled = false; b.classList.remove('mq-running'); }
    if (!btnId || _mqBusyBtn === btnId) _mqBusyBtn = null;
  }
  const msg = document.getElementById('mqMsg');
  if (on && label) msg.textContent = label;
}

function mqBeginAction(btnId, label){
  uiNewAbort();
  mqSyncSearchToSelection();
  mqUpdateStatusSelection();
  mqBusy(btnId, true, label);
}

function mqIsMulti(){ return !!(document.getElementById('mqAllowMulti')||{}).checked; }

function getMqSelectedNetworks(){
  return Array.from(document.querySelectorAll('#mqFeederList input.mq-feeder-cb:checked'))
    .map(cb => cb.value).filter(Boolean);
}

function getMqSelectedFeeders(){
  return Array.from(document.querySelectorAll('#mqFeederList input.mq-feeder-cb:checked'))
    .map(cb => cb.getAttribute('data-feeder') || '')
    .filter(Boolean);
}

function mqSelectionPayload(){
  const networks = getMqSelectedNetworks();
  const feeders = getMqSelectedFeeders();
  return {
    networks: networks,
    feeders: feeders,
    feeder: feeders.length === 1 ? feeders[0] : (feeders[0] || ''),
    network: networks.length === 1 ? networks[0] : (networks[0] || ''),
  };
}

function mqRequireSelection(msgEl){
  const payload = mqSelectionPayload();
  if (!payload.networks.length) {
    if (msgEl) msgEl.innerHTML = '<span class="err">Seleccione al menos un alimentador del estudio.</span>';
    return null;
  }
  return payload;
}

function mqFocusFeederId(){
  // Alimentador en análisis: selección actual > texto del buscador > default sesión.
  const fids = getMqSelectedFeeders();
  if (fids.length) return String(fids[0]||'').toUpperCase();
  const raw = ((document.getElementById('mqFeederSearch')||{}).value||'').trim().toUpperCase();
  if (raw) {
    let hit = '';
    (_mqNetworks||[]).forEach(it=>{
      const fid = String(it.feeder_id||'').toUpperCase();
      const nid = String(it.network_id||'').toUpperCase();
      if (!hit && (fid === raw || nid === raw || nid.endsWith('_'+raw) || fid.indexOf(raw) >= 0)) hit = fid;
    });
    if (hit) return hit;
    if (/^[A-Z]{1,4}\d{2,4}$/.test(raw)) return raw;
  }
  return String(DEFAULT_FEEDER||'').toUpperCase();
}

function mqUpdateActionLabels(){
  const fid = mqFocusFeederId() || String(DEFAULT_FEEDER||'') || '—';
  const solo = document.getElementById('btnMqSoloFeeder');
  if (solo) solo.textContent = 'Solo ' + fid;
  const payload = mqSelectionPayload();
  const selLabel = (payload.feeders && payload.feeders.length)
    ? (payload.feeders.length === 1 ? payload.feeders[0] : (payload.feeders.length + ' alim.'))
    : fid;
  const map = {
    btnMqDiag: '1 · Diagnosticar (' + selLabel + ')',
    btnMqProp: '2 · Proponer (' + selLabel + ')',
    btnMqApply: '3 · Aplicar (' + selLabel + ')',
    btnMqConv: '4 · Verificar convergencia (' + selLabel + ')',
    btnMqRefresh: '5 · Actualizar estado (' + selLabel + ')',
    btnMqDiagSel: '6 · Diagnosticar selección (' + selLabel + ')',
    btnMqUntil: '7 · Corregir hasta limpio (' + selLabel + ')',
    btnMqUntilSel: '8 · Ciclo completo (' + selLabel + ')',
  };
  Object.keys(map).forEach(id=>{
    const b = document.getElementById(id);
    if (b && !b.classList.contains('mq-running')) b.textContent = map[id];
  });
}

function mqSyncSearchToSelection(){
  const inp = document.getElementById('mqFeederSearch');
  if (!inp) return;
  const fids = getMqSelectedFeeders();
  if (!fids.length) return;
  // En modo único: el cuadro muestra el alimentador marcado (no el filtro parcial "112").
  if (!mqIsMulti() || fids.length === 1) {
    if (document.activeElement !== inp) inp.value = fids[0];
  }
}

function mqUpdateStatusSelection(payload){
  const p = payload || mqSelectionPayload();
  const fEl = document.getElementById('mqSelFeeder');
  const nEl = document.getElementById('mqSelNetwork');
  if (fEl) fEl.textContent = p.feeders && p.feeders.length
    ? (p.feeders.length === 1 ? p.feeders[0] : p.feeders.join(', '))
    : (mqFocusFeederId() || '—');
  if (nEl) nEl.textContent = p.networks && p.networks.length
    ? (p.networks.length === 1 ? p.networks[0] : (p.networks.length+' redes'))
    : '—';
  mqUpdateActionLabels();
  updateHeaderContext({feeders: p.feeders, networks: p.networks});
}

function mqClearDiagStatus(){
  const readyEl = document.getElementById('mqReady');
  const convEl = document.getElementById('mqConv');
  const probEl = document.getElementById('mqProblems');
  if (readyEl) { readyEl.textContent = '—'; readyEl.style.color = ''; }
  if (convEl) convEl.textContent = '—';
  if (probEl) probEl.textContent = '—';
  window._mqReady = false;
}

let _mqStatusRefreshTimer = null;
let _mqLastStatusKey = '';
function mqSelectionKey(feeders, networks){
  return (feeders||[]).join(',') + '|' + (networks||[]).join(',');
}
function mqScheduleStatusRefresh(){
  if (_mqStatusRefreshTimer) clearTimeout(_mqStatusRefreshTimer);
  _mqStatusRefreshTimer = setTimeout(function(){
    _mqStatusRefreshTimer = null;
    if (_mqBusyBtn) return;
    mqRefreshStatus({quiet: true});
  }, 180);
}

function mqUpdateSelLabel(){
  const el = document.getElementById('mqFeederSel');
  if (!el) return;
  const nets = getMqSelectedNetworks();
  const fids = getMqSelectedFeeders();
  mqSyncSearchToSelection();
  mqUpdateStatusSelection({networks: nets, feeders: fids});
  if (!nets.length) {
    el.textContent = (_mqNetworks.length ? (_mqNetworks.length+' redes en BD · ') : '')
      + 'Ninguno seleccionado — marque uno o active «Permitir varios».';
    _mqLastStatusKey = '';
    mqClearDiagStatus();
    return;
  }
  el.innerHTML = '<b>'+nets.length+'</b> seleccionados: <b>'+fids.join(', ')+'</b>';
  const key = mqSelectionKey(fids, nets);
  if (key !== _mqLastStatusKey) {
    _mqLastStatusKey = key;
    // Evita mostrar Problemas/Estado del alimentador anterior mientras llega el del seleccionado.
    mqClearDiagStatus();
    mqScheduleStatusRefresh();
  }
}

function mqFilterFeederList(){
  const q = ((document.getElementById('mqFeederSearch')||{}).value||'').trim().toUpperCase();
  document.querySelectorAll('#mqFeederList label.mq-feeder-item').forEach(lab=>{
    const id = (lab.getAttribute('data-id')||'') + ' ' + (lab.getAttribute('data-feeder')||'');
    lab.classList.toggle('hidden', !!(q && id.toUpperCase().indexOf(q) < 0));
  });
  // Mientras escribe, actualiza «Solo XXX» si coincide con un alimentador.
  mqUpdateActionLabels();
}

function mqFeederSearchKey(ev){
  if (ev.key !== 'Enter') return;
  ev.preventDefault();
  const raw = ((document.getElementById('mqFeederSearch')||{}).value||'').trim().toUpperCase();
  if (!raw) return;
  const multi = mqIsMulti();
  let hit = null;
  document.querySelectorAll('#mqFeederList label.mq-feeder-item').forEach(lab=>{
    const fid = (lab.getAttribute('data-feeder')||'').toUpperCase();
    const nid = (lab.getAttribute('data-id')||'').toUpperCase();
    if (!hit && (fid === raw || nid === raw || nid.endsWith('_'+raw))) hit = lab;
  });
  if (!hit) return;
  const cb = hit.querySelector('input.mq-feeder-cb');
  if (!cb) return;
  if (!multi) {
    document.querySelectorAll('#mqFeederList input.mq-feeder-cb').forEach(x=>{ x.checked = false; });
  }
  cb.checked = true;
  mqUpdateSelLabel();
}

function mqOnMultiModeChange(){
  mqRenderNetworkList(_mqNetworks);
}

function mqSelectFeeders(all){
  if (all && !mqIsMulti()) {
    const msg = document.getElementById('mqMsg');
    if (msg) msg.innerHTML = '<span class="err">Active «Permitir varios» para seleccionar más de uno.</span>';
    return;
  }
  document.querySelectorAll('#mqFeederList input.mq-feeder-cb').forEach(cb=>{
    cb.checked = !!all;
  });
  mqUpdateSelLabel();
}

function mqSelectOnlyCurrent(){
  const want = mqFocusFeederId();
  if (!want) return;
  let found = false;
  document.querySelectorAll('#mqFeederList input.mq-feeder-cb').forEach(cb=>{
    const fid = (cb.getAttribute('data-feeder')||'').toUpperCase();
    const on = fid === want;
    cb.checked = on;
    if (on) found = true;
  });
  if (!found) {
    const msg = document.getElementById('mqMsg');
    if (msg) msg.innerHTML = '<span class="err">No está en la lista: '+want+'</span>';
  }
  mqUpdateSelLabel();
}

function mqOnNetworkCheck(cb){
  if (!mqIsMulti() && cb.checked) {
    document.querySelectorAll('#mqFeederList input.mq-feeder-cb').forEach(x=>{
      if (x !== cb) x.checked = false;
    });
  }
  mqUpdateSelLabel();
}

function mqRenderNetworkList(items){
  _mqNetworks = items || [];
  const box = document.getElementById('mqFeederList');
  if (!box) return;
  const multi = mqIsMulti();
  const prev = new Set(getMqSelectedNetworks());
  const typ = multi ? 'checkbox' : 'radio';
  const name = multi ? '' : 'name="mqFeederRadial"';
  if (!_mqNetworks.length) {
    box.innerHTML = '<div class="muted" style="padding:8px 10px">Sin redes. Pulse «Actualizar lista».</div>';
    mqUpdateSelLabel();
    return;
  }
  box.innerHTML = _mqNetworks.map(it=>{
    const nid = it.network_id || '';
    const fid = it.feeder_id || '';
    const checked = prev.has(nid) ? 'checked' : '';
    const badge = it.has_config ? ' · config' : '';
    return `<label class="mq-feeder-item feeder-item" data-id="${nid}" data-feeder="${fid}">
      <input type="${typ}" ${name} class="mq-feeder-cb" value="${nid}" data-feeder="${fid}" ${checked} onchange="mqOnNetworkCheck(this)"/>
      <span><b>${fid}</b></span><span class="cnt">${nid}${badge}</span>
    </label>`;
  }).join('');
  mqFilterFeederList();
  mqUpdateSelLabel();
  updateHeaderContext();
}

async function mqLoadNetworks(force){
  const msg = document.getElementById('mqMsg');
  const el = document.getElementById('mqFeederSel');
  if (el) el.textContent = force ? 'Actualizando redes desde CYMDIST…' : 'Cargando catálogo local…';
  try{
    const q = force ? '?force=1' : '';
    const j = await mqFetch('/api/calidad/redes'+q);
    if (j.ok === false) throw new Error(j.error || 'No se pudo listar redes');
    mqRenderNetworkList(j.networks || []);
    if (msg && !_mqBusyBtn) {
      if (!(j.n||0) && (j.soft || j.source === 'none')) {
        msg.textContent = 'Sin catálogo local · pulse «Actualizar lista» (abre CYMDIST una vez).';
      } else {
        msg.textContent = (j.n||0)+' alimentadores'
          +(j.source ? (' · '+j.source) : (j.cached ? ' (caché)' : ''))
          +' · cada botón ejecuta su acción por separado.';
      }
    }
  }catch(e){
    if (el) el.innerHTML = '<span class="err">'+e.message+'</span>';
    if (msg) msg.innerHTML = '<span class="err">'+e.message+'</span>';
  }
}

function mqRenderStatus(j){
  j = j || {};
  const gate = (j.gate && typeof j.gate === 'object') ? j.gate : {};
  const sum = j.summary || j.diagnostic_summary || {};
  let lastSum = sum;
  if ((!sum || sum.n_problems == null) && j.iterations && j.iterations.length) {
    const last = j.iterations[j.iterations.length-1] || {};
    lastSum = last.diagnostic_after || last.diagnostic || sum;
  }
  // Solo el diagnóstico de sistema completo (botón 9/10) alimenta «Sistema».
  // Un diagnóstico de selección usa el mismo API pero no debe pisar ese campo.
  const fullSystem = !!(j.system_full
    || (j.system_diagnostic && j.system_diagnostic.scope === 'system' && !j.selected_feeders && !j.selected_networks)
    || (sum && sum.scope === 'system' && !j.selected_feeders && !j.selected_networks && j.from_system_button));
  const sys = fullSystem
    ? (j.system_diagnostic || (sum.scope === 'system' ? sum : null))
    : (j.system_diagnostic && j.system_diagnostic.scope === 'system' && !j.selected_feeders ? j.system_diagnostic : null);

  const sel = mqSelectionPayload();
  const feeders = j.selected_feeders
    || (j.feeder_id ? [j.feeder_id] : null)
    || ((lastSum && lastSum.feeder_id) ? [lastSum.feeder_id] : null)
    || sel.feeders;
  const networks = j.selected_networks
    || (j.network_id ? [j.network_id] : null)
    || ((lastSum && lastSum.network_id) ? [lastSum.network_id] : null)
    || sel.networks;
  mqUpdateStatusSelection({feeders: feeders || [], networks: networks || []});

  const hasDiag = lastSum && lastSum.n_problems != null;
  const ready = !!(j.ready || gate.ready);
  const readyEl = document.getElementById('mqReady');
  if (readyEl) {
    if (ready) {
      readyEl.textContent = 'LISTO';
      readyEl.style.color = '#047857';
    } else if ((!fullSystem && (hasDiag || gate.converge || j.converge || j.from_diag)) || gate.status) {
      readyEl.textContent = 'PENDIENTE';
      readyEl.style.color = '#b91c1c';
    } else if (!fullSystem) {
      readyEl.textContent = '—';
      readyEl.style.color = '';
    }
  }
  if (!fullSystem) {
    document.getElementById('mqConv').textContent = j.converge || gate.converge || '—';
    const np = hasDiag ? lastSum.n_problems
      : (gate.n_problems != null ? gate.n_problems : '—');
    document.getElementById('mqProblems').textContent = np;
  }
  const sysEl = document.getElementById('mqSysProblems');
  if (sysEl) {
    if (sys && sys.n_problems != null) {
      sysEl.textContent = (sys.n_networks_ok||'?')+' redes · '+sys.n_problems+' problemas';
    } else if (j.clear_system) {
      sysEl.textContent = '—';
    }
  }
  window._mqReady = ready;
}

function mqRenderRows(rows){
  const box = document.getElementById('mqTable');
  if(!rows || !rows.length){ box.innerHTML = '<span class="muted">Sin filas de corrección / problemas.</span>'; return; }
  const hasFeeder = rows.some(r => r.Feeder || r.NetworkID);
  let h = '<table><thead><tr>'
    +(hasFeeder?'<th>Feeder</th>':'')
    +'<th>Activo</th><th>Código</th><th>Sev</th><th>Tipo</th><th>ID</th><th>Acción</th><th>Observación</th></tr></thead><tbody>';
  rows.slice(0,120).forEach(r=>{
    h += '<tr>'
      +(hasFeeder?'<td>'+(r.Feeder||'')+'</td>':'')
      +'<td>'+(r.Activo===true||r.Activo==='True'||r.Activo==='true'||r.Activo===1||r.Activo==='1'?'Sí':(r.Requiere_Correccion==='SI'?'Sí':(r.Activo!=null?'No':'')))+'</td>'
      +'<td>'+(r.Codigo||'')+'</td>'
      +'<td>'+(r.Severidad||'')+'</td>'
      +'<td>'+(r.Tipo||'')+'</td>'
      +'<td>'+(r.ID_CYMDIST||'')+'</td>'
      +'<td>'+(r.Accion_Sugerida||r.Accion||'')+'</td>'
      +'<td>'+String(r.Observacion||r.Mensaje||r.Mensaje_ejemplo||'').slice(0,140)+'</td>'
      +'</tr>';
  });
  h += '</tbody></table>';
  box.innerHTML = h;
}

async function mqDiagnose(){
  const msg = document.getElementById('mqMsg');
  const payload = mqRequireSelection(msg);
  if (!payload) return;
  mqBeginAction('btnMqDiag', 'Diagnosticar · paquete individual: '+payload.feeders.join(', ')+'…');
  try{
    let j;
    // Un solo alimentador: diagnóstico canónico de ese feeder (dashboard_summary del seleccionado).
    if (payload.feeders.length === 1) {
      j = await mqFetch('/api/calidad/diagnosticar', {
        action: 'diagnosticar',
        feeder: payload.feeder,
        networks: payload.networks,
      }, {feeder: payload.feeder});
    } else {
      j = await mqFetch('/api/calidad/diagnosticar_sistema', {
        networks: payload.networks,
        feeders: payload.feeders,
        action: 'diagnosticar',
      }, payload);
    }
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'diagnosticar',
      selected: payload.feeders,
      networks: payload.networks,
      feeder_id: sum.feeder_id || payload.feeder,
      network_id: sum.network_id || payload.network,
      n_networks_ok: sum.n_networks_ok,
      n_problems: sum.n_problems,
      n_errors: sum.n_errors,
      n_warnings: sum.n_warnings,
      n_hints: sum.n_hints,
      by_code: sum.by_code,
      csv: sum.csv || j.csv,
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderStatus({
      summary: sum,
      diagnostic_summary: sum,
      from_diag: true,
      keep_system: true,
      selected_feeders: payload.feeders,
      selected_networks: payload.networks,
      feeder_id: sum.feeder_id || payload.feeder,
      network_id: sum.network_id || payload.network,
    });
    mqRenderRows(sum.by_code_detail || sum.top_errors || j.rows || []);
    msg.innerHTML = '<span class="ok">Diagnosticar OK · '+payload.feeders.join(', ')
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqDiag', false); }
}

async function mqDiagnoseSelected(){
  const msg = document.getElementById('mqMsg');
  const payload = mqRequireSelection(msg);
  if (!payload) return;
  mqBeginAction('btnMqDiagSel', 'Diagnosticar seleccionados · '+payload.feeders.join(', ')+'…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar_sistema', {
      networks: payload.networks,
      feeders: payload.feeders,
      action: 'diagnosticar_seleccionados',
    }, payload);
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'diagnosticar_seleccionados',
      selected: payload.feeders,
      networks: payload.networks,
      n_networks_ok: sum.n_networks_ok,
      n_problems: sum.n_problems,
      n_errors: sum.n_errors,
      n_warnings: sum.n_warnings,
      n_hints: sum.n_hints,
      by_code: sum.by_code,
      csv: sum.csv || j.csv,
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderStatus({
      summary: sum,
      diagnostic_summary: sum,
      from_diag: true,
      keep_system: true,
      selected_feeders: payload.feeders,
      selected_networks: payload.networks,
    });
    mqRenderRows(sum.by_code_detail || sum.top_errors || j.rows || []);
    msg.innerHTML = '<span class="ok">Seleccionados OK · '+payload.feeders.join(', ')
      +' · redes='+(sum.n_networks_ok||0)
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqDiagSel', false); }
}

async function mqRunSelected(){
  const msg = document.getElementById('mqMsg');
  const payload = mqRequireSelection(msg);
  if (!payload) return;
  if(!confirm('Ejecutar (paquete individual) en '+payload.networks.length+' alimentador(es):\n'
    +payload.feeders.join(', ')+'\n\n'
    +'Con config RECYM: corrige hasta limpio + converge.\n'
    +'Sin config: solo NetworkDiagnostic del subconjunto.\n¿Continuar?')) return;
  mqBeginAction('btnMqUntilSel', 'Ejecutar seleccionados · '+payload.feeders.join(', ')+'…');
  try{
    const j = await mqFetch('/api/calidad/ejecutar_seleccionados', {
      networks: payload.networks,
      feeders: payload.feeders,
      max_iters: 8,
      action: 'ejecutar_seleccionados',
    }, payload);
    document.getElementById('mqOut').textContent = (j.log||[]).join('\n')
      + '\n\n' + JSON.stringify({
        action: 'ejecutar_seleccionados',
        mode: j.mode,
        selected_feeders: j.selected_feeders,
        selected_networks: j.selected_networks,
        msg: j.msg,
        summary: j.summary,
        results: (j.results||[]).map(r=>({
          feeder_id: r.feeder_id, ok: r.ok, converge: r.converge, msg: r.msg||r.error
        })),
      }, null, 2);
    if (j.summary || j.system_diagnostic) mqRenderStatus(j);
    else if (j.results && j.results.length) mqRenderStatus(Object.assign({}, j.results[j.results.length-1] || {}, {
      selected_feeders: payload.feeders, selected_networks: payload.networks
    }));
    else mqUpdateStatusSelection(payload);
    const rows = j.rows
      || ((j.summary||{}).by_code_detail)
      || ((j.summary||{}).top_errors)
      || [];
    if (rows.length) mqRenderRows(rows);
    else {
      const last = ((j.results||[]).slice(-1)[0] || {});
      // Mostrar problemas del último diagnóstico del ciclo (no dejar tabla vacía)
      let top = [];
      const iters = last.iterations || [];
      for (let i = iters.length - 1; i >= 0; i--) {
        const d = iters[i].diagnostic_after || iters[i].diagnostic || {};
        if (d.top_errors && d.top_errors.length) { top = d.top_errors; break; }
      }
      if (top.length) mqRenderRows(top);
      else document.getElementById('mqTable').innerHTML =
        '<p class="muted">'+(j.msg||last.msg||'Sin filas')+'</p>';
    }
    if(j.ok) msg.innerHTML = '<span class="ok">'+(j.msg||'Seleccionados listos')+'</span>';
    else msg.innerHTML = '<span class="err">'+(j.msg||j.error||'Seleccionados con pendientes')+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqUntilSel', false); }
}

async function mqDiagnoseSystem(){
  const msg = document.getElementById('mqMsg');
  if(!confirm('Diagnosticar TODO el sistema (~96 alimentadores).\n\nPaquete independiente (no usa la selección).\nPuede tardar varios minutos. ¿Continuar?')) return;
  mqBeginAction('btnMqDiagSys', 'Diagnosticar sistema (96) · paquete independiente…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar_sistema', {action: 'diagnosticar_sistema'});
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'diagnosticar_sistema',
      n_networks_ok: sum.n_networks_ok,
      n_problems: sum.n_problems,
      n_errors: sum.n_errors,
      n_warnings: sum.n_warnings,
      n_hints: sum.n_hints,
      by_code: sum.by_code,
      by_type: sum.by_type,
      csv: sum.csv || j.csv,
      csv_by_code: sum.csv_by_code,
      independent_of: sum.independent_of,
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderStatus({
      system_diagnostic: sum,
      summary: sum,
      from_system_button: true,
      system_full: true,
      clear_system: false,
    });
    mqRenderRows(sum.by_code_detail || sum.top_errors || []);
    msg.innerHTML = '<span class="ok">Sistema OK · redes='+(sum.n_networks_ok||0)
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqDiagSys', false); }
}

async function mqDiagnoseEld(){
  const msg = document.getElementById('mqMsg');
  if(!confirm('Herramienta diagnóstica API → estudio ELD.zxst (96 redes).\n\nPaquete independiente.\n¿Continuar?')) return;
  mqBeginAction('btnMqDiagEld', 'Diagnosticar ELD · paquete independiente…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar_eld', {action: 'diagnosticar_eld'});
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'diagnosticar_eld',
      study_path: sum.study_path,
      topology_settings: sum.topology_settings,
      n_networks_ok: sum.n_networks_ok,
      n_problems: sum.n_problems,
      n_errors: sum.n_errors,
      by_code: sum.by_code,
      csv: sum.csv || j.csv,
      csv_by_code: sum.csv_by_code,
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderStatus({
      system_diagnostic: Object.assign({}, sum, {scope: 'system'}),
      summary: sum,
      from_system_button: true,
      system_full: true,
    });
    mqRenderRows(sum.by_code_detail || sum.top_errors || []);
    msg.innerHTML = '<span class="ok">ELD OK · redes='+(sum.n_networks_ok||0)
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqDiagEld', false); }
}

async function mqPropose(){
  const msg = document.getElementById('mqMsg');
  const payload = mqSelectionPayload();
  mqBeginAction('btnMqProp', 'Proponer · paquete: '+(payload.feeder||DEFAULT_FEEDER)+'…');
  try{
    const j = await mqFetch('/api/calidad/proponer', {action: 'proponer'}, payload.feeder ? {feeder: payload.feeder} : {});
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'proponer', feeder: payload.feeder||DEFAULT_FEEDER,
      n_total:j.n_total, n_activas:j.n_activas, n_revisar:j.n_revisar, csv:j.csv
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderRows(j.rows||[]);
    mqUpdateStatusSelection(payload);
    msg.innerHTML = '<span class="ok">Proponer OK · '+ (payload.feeder||DEFAULT_FEEDER)
      +' · '+j.n_activas+' activas / '+j.n_total+' total</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqProp', false); }
}

async function mqApply(){
  const msg = document.getElementById('mqMsg');
  const payload = mqSelectionPayload();
  mqBeginAction('btnMqApply', 'Aplicar · paquete: '+(payload.feeder||DEFAULT_FEEDER)+'…');
  try{
    const j = await mqFetch('/api/calidad/aplicar', {action: 'aplicar'}, payload.feeder ? {feeder: payload.feeder} : {});
    document.getElementById('mqOut').textContent = JSON.stringify({
      action: 'aplicar', feeder: payload.feeder||DEFAULT_FEEDER,
      n_ok:j.n_ok, n_error:j.n_error, base_voltages:j.base_voltages, preview_csv:j.preview_csv
    }, null, 2);
    mqRenderRows(j.preview||[]);
    mqUpdateStatusSelection(payload);
    if(j.ok === false || (j.n_error||0) > 0){
      msg.innerHTML = '<span class="err">Aplicar · OK='+j.n_ok+' ERR='+j.n_error+(j.error?(' · '+j.error):'')+'</span>';
    } else {
      msg.innerHTML = '<span class="ok">Aplicar OK · '+(payload.feeder||DEFAULT_FEEDER)+' · OK='+j.n_ok+'</span>';
    }
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqApply', false); }
}

async function mqConverge(){
  const msg = document.getElementById('mqMsg');
  const payload = mqSelectionPayload();
  mqBeginAction('btnMqConv', 'Verificar convergencia · paquete: '+(payload.feeder||DEFAULT_FEEDER)+'…');
  try{
    const j = await mqFetch('/api/calidad/convergencia', {action: 'convergencia'}, payload.feeder ? {feeder: payload.feeder} : {});
    document.getElementById('mqOut').textContent = JSON.stringify(Object.assign({action:'convergencia', feeder: payload.feeder||DEFAULT_FEEDER}, j), null, 2);
    mqRenderStatus(Object.assign({}, j, {selected_feeders: payload.feeders, selected_networks: payload.networks}));
    if(j.converge==='SI') msg.innerHTML = '<span class="ok">Converge = SI · '+(payload.feeder||DEFAULT_FEEDER)+'</span>';
    else msg.innerHTML = '<span class="err">Converge = '+(j.converge||'NO')+(j.error?(' · '+j.error):'')+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqConv', false); }
}

async function mqUntilClean(){
  const msg = document.getElementById('mqMsg');
  const payload = mqRequireSelection(msg);
  if (!payload) return;
  mqBeginAction('btnMqUntil', 'Corregir hasta limpio · paquete: '+payload.feeders.join(', ')+'…');
  try{
    const j = await mqFetch('/api/calidad/ejecutar_seleccionados', {
      networks: payload.networks,
      feeders: payload.feeders,
      max_iters: 4,
      action: 'corregir_hasta_limpio',
    }, payload);
    document.getElementById('mqOut').textContent = (j.log||[]).join('\n') + '\n\n'
      + JSON.stringify({action:'corregir_hasta_limpio', mode:j.mode, msg:j.msg||j.error, selected:payload.feeders}, null, 2);
    mqRenderStatus(Object.assign({}, j, {selected_feeders: payload.feeders, selected_networks: payload.networks}));
    const last = (j.iterations||[]).slice(-1)[0] || ((j.results||[]).slice(-1)[0] || {});
    const tops = ((last.diagnostic_after||last.diagnostic||{}).top_errors) || j.rows || [];
    mqRenderRows(tops);
    if(j.ok) msg.innerHTML = '<span class="ok">'+(j.msg||'Listo')+' · '+payload.feeders.join(', ')+'</span>';
    else msg.innerHTML = '<span class="err">'+(j.msg||j.error||'No limpio')+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy('btnMqUntil', false); }
}

async function mqRefreshStatus(opts){
  const quiet = !!(opts && opts.quiet);
  const payload = mqSelectionPayload();
  if (!quiet) mqBeginAction('btnMqRefresh', 'Actualizar estado…');
  try{
    const feeder = payload.feeder || DEFAULT_FEEDER || '';
    const j = await mqFetch('/api/calidad/estado', undefined, feeder ? {feeder: feeder} : {});
    const sum = j.diagnostic_summary || j.summary || {};
    mqRenderStatus(Object.assign({}, j, {
      keep_system: true,
      selected_feeders: payload.feeders.length ? payload.feeders : (sum.feeder_id ? [sum.feeder_id] : (feeder ? [feeder] : [])),
      selected_networks: payload.networks.length ? payload.networks : (sum.network_id ? [sum.network_id] : []),
      feeder_id: sum.feeder_id || payload.feeder || feeder,
      network_id: sum.network_id || payload.network,
    }));
    const msg = document.getElementById('mqMsg');
    if (msg && !quiet) {
      const label = (payload.feeders.length ? payload.feeders.join(', ') : feeder) || DEFAULT_FEEDER;
      if (j.ready) msg.innerHTML = '<span class="ok">Gate LISTO · '+label+' · puede continuar a §2</span>';
      else msg.textContent = 'Gate pendiente · '+label+' · ejecute una acción individual.';
    }
  }catch(e){
    const msg = document.getElementById('mqMsg');
    if (msg && !quiet) msg.innerHTML = '<span class="err">'+e.message+'</span>';
  }finally{
    if (!quiet) mqBusy('btnMqRefresh', false);
  }
}

document.addEventListener('DOMContentLoaded', function(){
  updateHeaderContext();
  mqLoadNetworks(false).then(function(){
    updateHeaderContext();
    mqRefreshStatus({quiet: true});
  });
});

async function buildClientes(){
  const ci = requireCiFile();
  if (!ci) return;
  const ff = feederRequestFields();
  if (!ff.feeders.length) {
    document.getElementById('cliMsg').innerHTML='<span class="err">Seleccione un alimentador (RADIAL).</span>';
    return;
  }
  const btn = document.getElementById('btnBuildCli');
  if (btn) btn.disabled = true;
  document.getElementById('cliMsg').textContent='Cruzando NIS en '+ci+' · '+ff.feeders.join(', ')+' (solo Excel, sin abrir CYMDIST)…';
  document.getElementById('cliTable').innerHTML = '<p class="muted">Procesando cruce NIS… el archivo .xlsb puede tardar unos segundos.</p>';
  const body={
    suministro_file: document.getElementById('sumFile').value,
    clientes_file: ci,
    feeder: ff.feeders.length===1 ? ff.feeders[0] : ff.feeders.join(','),
    feeders: ff.feeders,
    all_feeders: false,
  };
  const headers = {'Content-Type':'application/json'};
  if (ff.feeders.length === 1) headers['X-Feeder'] = ff.feeders[0];
  try{
    const r=await fetch('/api/clientes/tabla',{method:'POST',headers:headers,body:JSON.stringify(body)});
    let j=null;
    try { j=await r.json(); } catch(e) {
      throw new Error('Respuesta no JSON ('+r.status+'). Servidor ocupado: Restablecer o scripts\\27_restablecer_ui.bat');
    }
    if(!j.ok){
      document.getElementById('cliMsg').innerHTML='<span class="err">'+(j.error||'Error')+'</span>';
      document.getElementById('cliTable').innerHTML='<p class="err">'+(j.error||'Sin tabla')+'</p>';
      return;
    }
    const rows = j.rows || [];
    cliTableReady = rows.length > 0;
    document.getElementById('btnApplyCli').disabled = !cliTableReady;
    const label = ff.feeders.length===1 ? ('solo <b>'+ff.feeders[0]+'</b>') : ('<b>'+ff.feeders.join(', ')+'</b>');
    document.getElementById('cliMsg').innerHTML='<span class="ok">Tabla cruzada · '+(j.n_rows!=null?j.n_rows:rows.length)+' filas · archivo '+ci+' · '+label+'</span>';
    const m=j.meta||{};
    document.getElementById('cliMeta').innerHTML=
      `Archivo CI: <b>${m.clientes_file||ci}</b> (NIS: ${m.n_nis_en_archivo_ci||'?'}) · RADIAL <b>${m.feeder_id||ff.feeder}</b> · Filtrados ${m.n_filtrados||rows.length} · EA/Pot ${m.n_con_ea_pot||'?'} · SED ${m.n_match_sed||0} · sin SED ${m.n_sin_sed||0}`
      + (m.n_loads_inventory!=null?` · inventario ${m.n_loads_inventory}`:'')
      + (m.attach_note?(` · <span class="muted">${m.attach_note}</span>`):'')
      + (m.n_excluidos?` · <b>excluidas ${m.n_excluidos}</b>`:'');
    renderCliTable(rows);
    if (!rows.length) {
      document.getElementById('cliMsg').innerHTML='<span class="err">Cruce OK pero 0 filas para '+ff.feeders.join(', ')+'. Verifique RADIAL en suministro.</span>';
    }
  }catch(e){
    document.getElementById('cliMsg').innerHTML='<span class="err">'+e.message+'</span>';
    document.getElementById('cliTable').innerHTML='<p class="err">'+e.message+'</p>';
  }finally{
    if (btn) btn.disabled = false;
  }
}

async function applyClientes(){
  if (!window._mqReady) {
    const go = confirm(
      'El gate de calidad del modelo aún no está LISTO (diagnóstico limpio + convergencia).\n'+
      '¿Continuar de todos modos con Cargar EA/Pot?'
    );
    if (!go) {
      document.getElementById('cliMsg').innerHTML =
        '<span class="err">Complete primero «Corregir hasta limpio + converge» en Calidad del modelo.</span>';
      return;
    }
  }
  const ci = requireCiFile();
  if (!ci) return;
  if (!cliTableReady) {
    document.getElementById('cliMsg').innerHTML='<span class="err">Primero arme la tabla con el archivo seleccionado.</span>';
    return;
  }
  const ff = feederRequestFields();
  if (!ff.feeders.length) {
    document.getElementById('cliMsg').innerHTML='<span class="err">Seleccione un alimentador (RADIAL).</span>';
    return;
  }
  syncActivoFromDom();
  const activo = collectActivoMap();
  const nOff = Object.keys(activo).filter(k=>!activo[k]).length;
  document.getElementById('cliMsg').textContent='Escribiendo CYMDIST con datos de '+ci+' · '+ff.feeders.join(', ')
    +(nOff?(' · '+nOff+' excluida(s) → desconectar…'):'…');
  const body={
    suministro_file: document.getElementById('sumFile').value,
    clientes_file: ci,
    feeder: ff.feeders.length===1 ? ff.feeders[0] : ff.feeders.join(','),
    feeders: ff.feeders,
    all_feeders: false,
    fp: clientesFp(),
    activo: activo,
    restar_cabecera: collectRestarCabeceraMap(),
  };
  const headers = {'Content-Type':'application/json'};
  if (ff.feeders.length === 1) headers['X-Feeder'] = ff.feeders[0];
  let j;
  try{
    const r = await fetchWithTimeout('/api/clientes/aplicar', {
      method:'POST', headers:headers, body:JSON.stringify(body), cache:'no-store'
    }, 300000);
    j = await r.json();
  }catch(e){
    document.getElementById('cliMsg').innerHTML='<span class="err">'+e+'</span>';
    return;
  }
  if(!j.ok){document.getElementById('cliMsg').innerHTML='<span class="err">'+(j.error||'Error')+'</span>';return;}
  const excl = (j.excluido_count!=null)?j.excluido_count:nOff;
  const cabAdj = j.cabecera_ajustada || {};
  const cabTxt = (j.P_kW!=null && Number(j.P_kW_excluidas_restadas||0)>0)
    ? ` · <b>Cabecera §1</b>: P_med=${j.P_kW_medicion??'?'} - sum(Pot_excl)=${j.P_kW_excluidas_restadas} → <b>P=${j.P_kW} kW</b>`
      +(j.Q_kvar!=null?` Q=${j.Q_kvar}`:'')
    : (cabAdj.msg ? ` · ${cabAdj.msg}` : '');
  document.getElementById('cliMsg').innerHTML=`<span class="ok">CYMDIST OK · ${j.ok_count}/${j.total} · archivo ${ci} · <b>${ff.feeders.join(', ')}</b>`
    +(j.kwh_verified!=null?` · Consumo(KWH) verificado ${j.kwh_verified}`:'')
    +(j.warn_kwh_count?` · <span class="err">WARN KWH ${j.warn_kwh_count}</span>`:'')
    +(excl?` · ${excl} excluida(s) desconectadas`:'')
    +cabTxt
    +`</span>`
    +(j.cymdist_open
      ? ` · <b>CYMDIST abierto</b> — sesión API activa`
      : (j.msg?(` · ${j.msg}`):''))
    +` · <b>Siguiente: Ejecutar distribución de carga</b>`
    + (j.tablero?` · <a href="/tablero" target="_blank">Ver en tablero</a>`:'');
  const btnAlloc=document.getElementById('btnAlloc');
  if(btnAlloc){ btnAlloc.disabled=false; btnAlloc.title='EA/Pot cargado — ejecute la distribución'; }
  if(j.rows) renderCliTable(j.rows);
}

async function runDistribucion(){
  const msg=document.getElementById('distMsg') || document.getElementById('cliMsg');
  const out=document.getElementById('distOut') || document.getElementById('analisisOut');
  const btn=document.getElementById('btnAlloc');
  if(btn) btn.disabled=true;
  const pack = getActiveFeederPack();
  msg.textContent='Distribuyendo en '+(pack.feeder||'?')+' (LoadAllocation)... cabecera − clientes importantes → residual';
  if(out) out.textContent='';
  try{
    // Guardar cabecera actual antes de distribuir (sin restablecer §§2–4)
    await saveHead({resetDownstream: false});
    syncActivoFromDom();
    const j = await spotFetch('/api/distribucion', {
      activo: collectActivoMap(),
      restar_cabecera: collectRestarCabeceraMap(),
    });
    if(!j.ok){msg.innerHTML='<span class="err">'+(j.error||'Error')+'</span>';if(out) out.textContent=JSON.stringify(j,null,2);return;}
    const d=j.result||{};
    const fallback = String(d.method||'').indexOf('fallback')>=0;
    const cabTxt = (Number(d.P_kW_excluidas_restadas||0)>0)
      ? ` · cabecera P=${Number(d.P_cabecera_kW||0).toFixed(1)} (med ${d.P_kW_medicion??'?'} - Restar cab. ${d.P_kW_excluidas_restadas})`
      : '';
    msg.innerHTML = fallback
      ? `<span class="ok">Distribución OK (fallback kWh) · residual ${Number(d.P_residual_kW||0).toFixed(1)} kW${cabTxt}</span>`
      : `<span class="ok">Distribución OK · ${d.method||'?'} · residual ${Number(d.P_residual_kW||0).toFixed(1)} kW${cabTxt}</span>`;
    if (d.n_residual_kw_updated!=null) {
      msg.innerHTML += ` · kW actualizados en residual: <b>${d.n_residual_kw_updated}</b>`;
    }
    if (d.consumo_ok===true) {
      msg.innerHTML += ` · Consumo(KWH) clientes: <b>OK</b>`;
    } else if (d.consumo_ok===false) {
      msg.innerHTML += ` · <span class="err">Consumo(KWH) clientes: revisar</span>`;
    }
    if (d.aviso_nuevas) {
      msg.innerHTML += ` · <span class="muted">${d.aviso_nuevas}</span>`;
    }
    msg.innerHTML += ` · <b>Siguiente: conectar carga nueva (§3) y luego flujos (§4)</b>`;
    if (d.cymdist_open) msg.innerHTML += ` · CYMDIST sigue abierto`;
    if(out) out.textContent=JSON.stringify({
      feeder: pack.feeder,
      manual: 'LoadAllocation IL917115ES · Metodo Consumo (kWh)',
      modo: d.mode,
      P_cabecera_kW: d.P_cabecera_kW,
      P_fijos_kW: d.P_fijos_kW,
      P_nuevas_kW: d.P_nuevas_kW,
      n_nuevas: d.n_nuevas,
      P_residual_kW: d.P_residual_kW,
      Q_residual_kvar: d.Q_residual_kvar,
      n_fijos: d.n_fijos,
      fijos_fuente: d.fijos_fuente,
      method: d.method,
      status: d.status,
      cymdist_settings: d.cymdist_settings,
      aviso: d.aviso||null,
      aviso_nuevas: d.aviso_nuevas||null,
      allocation_error: d.allocation_error||null,
      n_scaled: (d.scaled||[]).length || d.n_scaled || 0,
    },null,2);
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    if(btn) btn.disabled=false;
  }
}

async function runFlujo(scenario){
  const msg=document.getElementById('analisisMsg');
  const out=document.getElementById('analisisOut');
  const msgInf=document.getElementById('informeMsg');
  const btns=['btnFlow','btnFlowSit','btnFlowProy'];
  btns.forEach(id=>{const el=document.getElementById(id); if(el) el.disabled=true;});
  const label = scenario==='situacional'
    ? 'Flujo situacional ['+(getActiveFeederPack().feeder||'?')+']: desconectando cargas §3 y ejecutando LoadFlow…'
    : (scenario==='proyectado'
      ? 'Flujo proyectado ['+(getActiveFeederPack().feeder||'?')+']: conectando cargas §3 y ejecutando LoadFlow…'
      : 'Ejecutando flujo de carga normal (LoadFlow)...');
  msg.textContent=label;
  out.textContent='';
  try{
    const body = scenario ? {scenario: scenario, update_informe: true} : {update_informe: true};
    const j = await spotFetch('/api/flujo', body);
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'Error LoadFlow')+'</span>';
      out.textContent=JSON.stringify({error:j.error, ayuda:j.ayuda|| (j.result&&j.result.ayuda)||null, result:j.result||null, guardado:j.result&& (j.result.saved_scenario_to||j.result.saved_to)},null,2);
      await refreshInformePaths();
      return;
    }
    const d=j.result||{};
    const where = d.saved_scenario_to || d.saved_to || '';
    const connTxt = d.new_loads_connected===false
      ? 'cargas §3 DESCONECTADAS'
      : (d.new_loads_connected===true ? 'cargas §3 CONECTADAS' : '');
    msg.innerHTML=`<span class="ok">Flujo OK · ${(d.scenario||'general')} · status ${d.status}</span>`
      + (connTxt?` · <b>${connTxt}</b>`:'')
      + (d.n_new_loads!=null?` · n=${d.n_new_loads}`:'')
      + (d.cymdist_open?` · CYMDIST sigue abierto`:'')
      + (where?` · <code style="font-size:11px">${where}</code>`:'');
    if (j.informe && j.informe.ok) {
      msg.innerHTML += ` · <b>§5 informe actualizado (entrega lista)</b>`;
      if (msgInf) {
        msgInf.dataset.locked='1';
        msgInf.innerHTML=`<span class="ok">Informe actualizado tras flujo ${(d.scenario||'')} → ${(j.informe.doc_informe||j.informe.paths&&j.informe.paths.informe_doc)||'doc'}</span>`;
      }
      const outInf=document.getElementById('informeOut');
      if (outInf) outInf.textContent=JSON.stringify(j.informe,null,2);
    } else if (j.informe) {
      const miss=(j.informe.missing||[]).join(', ') || j.informe.error || 'incompleto';
      msg.innerHTML += ` · <span class="muted">§5 pendiente: ${miss}</span>`;
      if (msgInf) {
        msgInf.innerHTML=`<span class="err">Informe incompleto tras flujo: ${j.informe.error||miss}</span>`;
      }
      const outInf=document.getElementById('informeOut');
      if (outInf) outInf.textContent=JSON.stringify({
        delivery_ready:j.informe.delivery_ready,
        missing:j.informe.missing,
        charts:j.informe.charts_generated,
        error:j.informe.error,
      },null,2);
    }
    await refreshDeliveryStatus();
    out.textContent=JSON.stringify({
      manual: 'BalLoadFlowInd IL917123ES',
      scenario: d.scenario,
      module: d.module,
      status: d.status,
      network_id: d.network_id,
      engine: d.engine || j.engine,
      topo: d.topo,
      n_new_loads: d.n_new_loads,
      new_loads_connected: d.new_loads_connected,
      new_loads_scenario: d.new_loads_scenario,
      saved: d.saved,
      saved_to: d.saved_to,
      saved_scenario_to: d.saved_scenario_to,
      note: d.note||null,
      error: d.error||null,
      informe: j.informe||null,
    },null,2);
    await refreshInformePaths();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    btns.forEach(id=>{const el=document.getElementById(id); if(el) el.disabled=false;});
  }
}

function applyPathsUI(p){
  if(!p) return;
  const set=(id,v)=>{const el=document.getElementById(id); if(el) el.textContent=v||'—';};
  set('pathLfSit', p.loadflow_situacional);
  set('pathLfProy', p.loadflow_proyectado);
  set('pathTplInf', p.informe_plantilla);
  set('pathTplJus', p.justificacion_plantilla);
  set('pathDocDir', p.doc_dir);
  set('pathDocInf', p.informe_doc);
  set('pathDocJus', p.justificacion_doc);
  set('pathImgDir', p.images_dir || (p.doc_dir ? String(p.doc_dir).replace(/\\doc$/,'\\data\\output\\feeders\\'+ (p.feeder_id||'ID') +'\\informe_images') : '…'));
}

async function refreshInformePaths(){
  try{
    const j = await spotFetch('/api/informe/rutas');
    if(j.ok){
      _pathsCache=j.paths;
      applyPathsUI(j.paths);
      const msg=document.getElementById('informeMsg');
      if(msg && !msg.dataset.locked){
        msg.textContent='Rutas actualizadas · destino entrega: '+(j.paths.doc_dir||'doc');
      }
    }
  }catch(e){
    document.getElementById('informeMsg').innerHTML='<span class="err">'+e+'</span>';
  }
}

async function armarInformes(){
  const msg=document.getElementById('informeMsg');
  const out=document.getElementById('informeOut');
  const btn=document.getElementById('btnInforme');
  btn.disabled=true;
  msg.dataset.locked='1';
  msg.textContent='Capturando CYMDIST (situacional+proyectado) y rellenando informes…';
  out.textContent='';
  try{
    const j = await spotFetch('/api/informe/armar', {fill:true, force_captures:true});
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'Informe incompleto')+'</span>';
      out.textContent=JSON.stringify({
        delivery_ready: j.delivery_ready,
        missing: j.missing,
        charts: j.charts_generated,
        capturas: j.cymdist_captures,
        escenarios: j.scenarios_used,
        meta: j.meta,
        error: j.error,
      },null,2);
      await refreshDeliveryStatus();
      return;
    }
    applyPathsUI(Object.assign({}, j.paths||{}, {images_dir:j.images_dir}));
    msg.innerHTML='<span class="ok">Entrega lista · capturas CYMDIST + informes en doc</span>';
    out.textContent=JSON.stringify({
      delivery_ready: j.delivery_ready,
      destino: j.paths && j.paths.doc_dir,
      meta: j.meta,
      meta_source: j.meta_source,
      escenarios: j.scenarios_used,
      capturas: j.cymdist_captures,
      excel: j.excel_notes,
      word_reemplazos: (j.word&&j.word.replacements)||[],
      imagenes: (j.word&&j.word.images_replaced)||[],
      charts_generated: j.charts_generated,
      manifesto: j.fill_manifest,
      notes: j.notes,
    },null,2);
    await refreshDeliveryStatus();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    btn.disabled=false;
    delete msg.dataset.locked;
  }
}

async function capturarCymdistInforme(){
  const msg=document.getElementById('informeMsg');
  const out=document.getElementById('informeOut');
  msg.dataset.locked='1';
  msg.textContent='CYMDIST API: LF situacional/proyectado + coloreo + ExportActiveView…';
  out.textContent='';
  try{
    const j = await spotFetch('/api/informe/capturas', {force:true, open_gui:true});
    if(!j.ok){
      msg.innerHTML='<span class="err">Captura incompleta: '+(j.error|| ((j.errors||[]).join('; ')) || '?')+'</span>';
    }else{
      msg.innerHTML='<span class="ok">Capturas OK · '+(j.generated||[]).length+' PNG</span>';
    }
    out.textContent=JSON.stringify(j,null,2);
    await refreshDeliveryStatus();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    delete msg.dataset.locked;
  }
}

const META_KEYS=['cliente','ubicacion','solicitud','potencia_kw','potencia_txt','alimentador','set','tension_kv','transformador','expediente'];

function fillMetaForm(meta){
  if(!meta) return;
  META_KEYS.forEach(k=>{
    const el=document.getElementById('meta_'+k);
    if(!el) return;
    const v=meta[k];
    el.value=(v===null||v===undefined)?'':v;
  });
}

function metaFormBody(){
  const body={};
  META_KEYS.forEach(k=>{
    const el=document.getElementById('meta_'+k);
    if(!el) return;
    let v=el.value;
    if(k==='potencia_kw'||k==='tension_kv'){
      body[k]=(v===''||v===null)?null:Number(v);
    }else{
      body[k]=v;
    }
  });
  return body;
}

async function extractMetaPdf(){
  const msg=document.getElementById('metaMsg');
  const out=document.getElementById('metaOut');
  const btn=document.getElementById('btnMetaPdf');
  const inp=document.getElementById('metaPdf');
  if(!inp.files||!inp.files[0]){
    msg.innerHTML='<span class="err">Seleccione un PDF</span>';
    return;
  }
  btn.disabled=true;
  msg.textContent='Extrayendo texto / OCR del PDF…';
  out.textContent='';
  try{
    const fd=new FormData();
    fd.append('pdf', inp.files[0]);
    const r=await fetch('/api/informe/meta_pdf',{method:'POST',body:fd});
    const j=await r.json();
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'OCR falló')+'</span>';
      out.textContent=JSON.stringify(j,null,2);
      return;
    }
    fillMetaForm(j.meta||{});
    const okTag=j.complete
      ? '<span class="ok">Meta completa (cliente+potencia)</span>'
      : '<span class="err">Revise/complete cliente y potencia, luego Guardar meta</span>';
    msg.innerHTML=okTag+' · método '+(j.method||'?');
    out.textContent=JSON.stringify({
      method:j.method, complete:j.complete, warnings:j.warnings, path:j.path, meta:j.meta
    },null,2);
    await refreshDeliveryStatus();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    btn.disabled=false;
  }
}

async function loadMetaUI(){
  const msg=document.getElementById('metaMsg');
  const out=document.getElementById('metaOut');
  try{
    const r=await fetch('/api/informe/meta');
    const j=await r.json();
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'Sin meta')+'</span>';
      return;
    }
    fillMetaForm(j.meta||{});
    msg.textContent=j.complete?'Meta cargada (completa)':'Meta cargada (incompleta)';
    out.textContent=JSON.stringify(j,null,2);
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }
}

async function saveMetaUI(){
  const msg=document.getElementById('metaMsg');
  const out=document.getElementById('metaOut');
  const btn=document.getElementById('btnMetaSave');
  btn.disabled=true;
  try{
    const r=await fetch('/api/informe/meta',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(metaFormBody()),
    });
    const j=await r.json();
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'No se guardó')+'</span>';
      out.textContent=JSON.stringify(j,null,2);
      return;
    }
    fillMetaForm(j.meta||{});
    msg.innerHTML=j.complete
      ? '<span class="ok">Meta guardada (lista para informe)</span>'
      : '<span class="err">Guardada pero incompleta (falta cliente o potencia)</span>';
    out.textContent=JSON.stringify(j,null,2);
    await refreshDeliveryStatus();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    btn.disabled=false;
  }
}

async function refreshDeliveryStatus(){
  const badge=document.getElementById('deliveryBadge');
  const miss=document.getElementById('deliveryMissing');
  const hdr=document.getElementById('hdrBadge');
  try{
    const r=await fetch('/api/informe/status');
    const j=await r.json();
    if(!j.ok){
      if(badge){ badge.className='badge wait'; badge.textContent='error'; }
      if(miss) miss.textContent=j.error||'No se pudo leer estado';
      return j;
    }
    const c=j.checks||{};
    const setDot=(id,ok)=>{
      const el=document.getElementById(id);
      if(!el) return;
      el.className='dot '+(ok?'ok':'bad');
    };
    setDot('chkSit', !!c.loadflow_situacional);
    setDot('chkProy', !!c.loadflow_proyectado);
    setDot('chkMeta', !!c.informe_meta_ocr);
    setDot('chkImg', !!c.lf_images);
    if(badge){
      if(j.delivery_ready){
        badge.className='badge ready';
        badge.textContent='entrega lista';
      }else{
        badge.className='badge wait';
        badge.textContent='pendiente';
      }
    }
    if(hdr){
      hdr.className='badge '+(j.delivery_ready?'ready':'wait');
      hdr.textContent=j.delivery_ready?'entrega OK':'v4 · pendiente';
    }
    if(miss){
      const m=j.missing||[];
      miss.textContent=m.length?('Falta: '+m.join(' · ')):'Todos los requisitos de entrega cumplidos.';
    }
    const btn=document.getElementById('btnInforme');
    if(btn){
      btn.title=j.delivery_ready
        ? 'Generar Word/Excel de entrega'
        : 'Completar checklist antes de rellenar (se validará al pulsar)';
    }
    return j;
  }catch(e){
    if(badge){ badge.className='badge wait'; badge.textContent='error'; }
    if(miss) miss.textContent=String(e);
    return null;
  }
}

refreshInformePaths();
loadMetaUI();
refreshDeliveryStatus();

/* —— Nueva SpotLoad por nodo —— */
let _nodeTimer = null;
let _loadHistory = [];
let _resolved = null;

function loadModeUI(){
  const m=document.getElementById('loadMode').value;
  document.getElementById('box_load_cosfi').style.display = m==='KW_COSFI'?'block':'none';
  document.getElementById('box_load_q').style.display = m==='KW_KVAR'?'block':'none';
}
loadModeUI();

function debounceNodeSearch(){
  if (_nodeTimer) clearTimeout(_nodeTimer);
  _nodeTimer = setTimeout(()=>searchNodes(), 280);
}

async function searchNodes(){
  const q = document.getElementById('nodeQuery').value || '';
  try{
    const pack = getActiveFeederPack();
    syncSpotLoadContext();
    const j = await spotFetch('/api/nodos/buscar?q='+encodeURIComponent(q)+'&limit=80');
    const sel = document.getElementById('nodeSelect');
    sel.innerHTML = '<option value="">— Seleccione nodo —</option>';
    if (!j.ok) {
      document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'Error buscando nodos')+'</span>';
      document.getElementById('btnConnectLoad').disabled = true;
      return;
    }
    (j.nodes||[]).forEach(n=>{
      const o=document.createElement('option');
      o.value = n.NodeID;
      o.textContent = n.NodeID + (n.n_sections!=null?(' · '+n.n_sections+' tramo(s)'):'');
      sel.appendChild(o);
    });
    document.getElementById('loadMsg').textContent =
      (pack.feeder?('['+pack.feeder+'] '):'')
      + ((j.nodes||[]).length ? ('Coincidencias: '+(j.nodes||[]).length) : 'Sin nodos para esa búsqueda.');
    _resolved = null;
    document.getElementById('autoSection').value = '';
    document.getElementById('autoLoadId').value = '';
    document.getElementById('loadResolve').textContent = '';
    document.getElementById('btnConnectLoad').disabled = true;
  }catch(e){
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('btnConnectLoad').disabled = true;
  }
}

function sanitizeLoadNameClient(v){
  return String(v||'').trim().replace(/\s+/g,'_').replace(/[^A-Za-z0-9_\-]/g,'').toUpperCase();
}
function onLoadNameInput(){
  const n = sanitizeLoadNameClient(document.getElementById('loadName').value);
  document.getElementById('autoLoadId').value = n || '';
  // Re-resolver si ya hay nodo (el nombre manda sobre el LoadID)
  const nid = document.getElementById('nodeSelect').value;
  if (nid) onNodeSelect();
}

async function onNodeSelect(){
  const nid = document.getElementById('nodeSelect').value;
  if (!nid) {
    document.getElementById('btnConnectLoad').disabled = true;
    return;
  }
  const loadName = document.getElementById('loadName').value || '';
  document.getElementById('loadMsg').textContent = 'Resolviendo tramo y nombre…';
  try{
    const j = await spotFetch('/api/nodos/resolver', {node_id: nid, load_name: loadName});
    if (!j.ok) {
      document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'No se pudo resolver')+'</span>';
      document.getElementById('btnConnectLoad').disabled = true;
      return;
    }
    _resolved = j;
    document.getElementById('autoSection').value = j.SectionID || '';
    document.getElementById('autoLoadId').value = j.LoadID || sanitizeLoadNameClient(loadName) || '';
    const pack = getActiveFeederPack();
    document.getElementById('loadResolve').textContent =
      '['+(pack.feeder||'?')+'] Nodo '+j.NodeID+' · From '+ (j.FromNode||'?') +' → To '+(j.ToNode||'?')
      +' · candidatos '+(j.n_sections||0)
      +(j.LoadID?(' · dibujará como '+j.LoadID):'');
    const needName = !sanitizeLoadNameClient(loadName);
    if (needName) {
      document.getElementById('loadMsg').innerHTML = '<span class="err">Indique el nombre de la carga concentrada.</span>';
      document.getElementById('btnConnectLoad').disabled = true;
    } else {
      document.getElementById('loadMsg').innerHTML = '<span class="ok">Listo en <b>'+(pack.feeder||'?')
        +'</b>: complete P y cosφ/Q · nombre en plano: <b>'+(j.LoadID||'')+'</b></span>';
      document.getElementById('btnConnectLoad').disabled = false;
    }
  }catch(e){
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('btnConnectLoad').disabled = true;
  }
}

async function refreshNodes(force){
  try{
    const pack = getActiveFeederPack();
    document.getElementById('loadMsg').textContent =
      'Inventariando nodos de '+(pack.feeder||'?')+' desde CYMDIST…';
    syncSpotLoadContext();
    const j = await spotFetch('/api/nodos/inventario', {refresh: !!force});
    if (!j.ok) {
      document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'Error inventario')+'</span>';
      return;
    }
    document.getElementById('loadMsg').innerHTML =
      '<span class="ok">Inventario OK · '+(pack.feeder||'?')+' · '+j.n_nodes+' nodos · '+j.n_sections+' tramos</span>';
    await searchNodes();
  }catch(e){
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+e.message+'</span>';
  }
}

function renderLoadHistory(){
  const box = document.getElementById('loadHistory');
  if (!_loadHistory.length) { box.innerHTML=''; return; }
  let html = '<table><thead><tr><th>Nodo</th><th>Section</th><th>Nombre</th><th>Loc</th><th>P</th><th>Q</th><th>Estado</th></tr></thead><tbody>';
  _loadHistory.forEach(r=>{
    html += `<tr><td>${r.NodeID||''}</td><td>${r.SectionID||''}</td><td>${r.Nombre||r.LoadID||''}</td>`
      +`<td>${r.Location||''}</td><td>${Number(r.P_kW||0).toFixed(2)}</td><td>${Number(r.Q_kvar||0).toFixed(2)}</td>`
      +`<td>${r.Estado||''}</td></tr>`;
  });
  html += '</tbody></table>';
  box.innerHTML = html;
}

async function connectLoad(){
  const nid = document.getElementById('nodeSelect').value;
  if (!nid) return;
  const loadName = (document.getElementById('loadName').value || '').trim();
  if (!sanitizeLoadNameClient(loadName)) {
    document.getElementById('loadMsg').innerHTML = '<span class="err">Indique el nombre de la carga concentrada.</span>';
    return;
  }
  const pack = getActiveFeederPack();
  if (!pack.feeder) {
    document.getElementById('loadMsg').innerHTML =
      '<span class="err">Seleccione estudio en §1 y pulse «Aplicar BD + estudio».</span>';
    return;
  }
  document.getElementById('btnConnectLoad').disabled = true;
  document.getElementById('loadMsg').textContent =
    'Conectando SpotLoad «'+sanitizeLoadNameClient(loadName)+'» en '+pack.feeder+'…';
  const body = {
    node_id: nid,
    load_name: loadName,
    mode: document.getElementById('loadMode').value,
    P_kW: document.getElementById('loadP').value,
    Q_kvar: document.getElementById('loadQ').value,
    cosfi: document.getElementById('loadCosfi').value,
  };
  try{
    const j = await spotFetch('/api/cargas/nueva', body);
    if (!j.ok) {
      document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'Error')+'</span>';
      return;
    }
    const d = j.result || {};
    _loadHistory.unshift(d);
    renderLoadHistory();
    document.getElementById('autoSection').value = d.SectionID || '';
    document.getElementById('autoLoadId').value = d.LoadID || '';
    document.getElementById('loadMsg').innerHTML =
      `<span class="ok">${d.Estado||'OK'} · SpotLoad <b>${d.LoadID}</b> en <b>${pack.feeder}</b>`
      +` · nodo ${d.NodeID||''} @ ${d.SectionID||''}`
      +(d.Location?(' · Loc='+d.Location):'')
      +` · P₃φ=${Number(d.P_kW).toFixed(2)} kW Q₃φ=${Number(d.Q_kvar).toFixed(2)} kvar`
      +` · por fase A/B/C: ${(Number(d.pq_per_phase_kW)!=null && !isNaN(Number(d.pq_per_phase_kW)) ? Number(d.pq_per_phase_kW) : Number(d.P_kW)/3).toFixed(2)} kW / `
      +`${(Number(d.pq_per_phase_kvar)!=null && !isNaN(Number(d.pq_per_phase_kvar)) ? Number(d.pq_per_phase_kvar) : Number(d.Q_kvar)/3).toFixed(2)} kvar</span>`
      +(d.cymdist_open
        ? ` · <b>CYMDIST queda abierto</b> — revise Potencia real/reactiva por fase en la carga concentrada.`
        : ` · <span class="muted">${d.aviso_com||'Si Cyme no abrió, ábralo y recargue el estudio.'}</span>`)
      +` · No redistribuir.`;
    // Preparar siguiente nodo (limpiar nombre para la siguiente carga)
    document.getElementById('loadP').value = '';
    document.getElementById('loadName').value = '';
    document.getElementById('autoLoadId').value = '';
    document.getElementById('nodeQuery').focus();
  }catch(e){
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+e+'</span>';
  }finally{
    document.getElementById('btnConnectLoad').disabled = !document.getElementById('nodeSelect').value;
  }
}

/* —— SpotLoad lote CSV/Excel —— */
let _spotBatchRows = [];
let _spotPendingRows = [];

async function downloadSpotTemplate(fmt){
  const pack = (typeof getActiveFeederPack === 'function') ? getActiveFeederPack() : {};
  const h = {};
  if (pack.feeder) h['X-Feeder'] = pack.feeder;
  const r = await fetch('/api/cargas/plantilla?fmt='+(fmt||'xlsx'), {headers:h});
  if(!r.ok) throw new Error(await r.text());
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'spotload_lote.'+(fmt||'xlsx');
  a.click();
  URL.revokeObjectURL(a.href);
  const msg = document.getElementById('spotBatchMsg');
  if (msg) msg.textContent = 'Plantilla descargada.';
}

function renderSpotBatchTable(rows){
  const box = document.getElementById('spotBatchTable');
  if (!box) return;
  if (!rows || !rows.length){
    box.innerHTML = '<div class="muted">Sin filas.</div>';
    return;
  }
  let html = '<table><thead><tr><th>#</th><th>Accion</th><th>NodeID</th><th>Nombre</th><th>P_kW</th><th>Estado</th></tr></thead><tbody>';
  rows.forEach(function(r,i){
    const st = r.error || ((r.errors||[]).join('; ')) || r.Estado || (r.ok===false?'ERROR':'OK');
    html += '<tr><td>'+(r.row||i+1)+'</td><td>'+(r.Accion||'')+'</td><td>'+(r.NodeID||'')
      +'</td><td>'+(r.Nombre||r.LoadID||'')+'</td><td>'+(r.P_kW??'')+'</td><td>'+st+'</td></tr>';
  });
  html += '</tbody></table>';
  box.innerHTML = html;
}

async function previewSpotBatch(input){
  const f = input && input.files && input.files[0];
  if (!f) return;
  const msg = document.getElementById('spotBatchMsg');
  const btn = document.getElementById('btnSpotBatch');
  try{
    if (msg) msg.textContent = 'Leyendo '+f.name+'…';
    const fd = new FormData();
    fd.append('file', f);
    const pack = (typeof getActiveFeederPack === 'function') ? getActiveFeederPack() : {};
    const h = {};
    if (pack.feeder) h['X-Feeder'] = pack.feeder;
    const r = await fetch('/api/cargas/lote/preview', {method:'POST', headers:h, body:fd});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error||'Error preview');
    _spotBatchRows = j.rows || [];
    renderSpotBatchTable(_spotBatchRows);
    if (btn) btn.disabled = !_spotBatchRows.some(function(x){ return x.ok !== false; });
    if (msg) msg.textContent = 'Válidas '+(j.n_ok||0)+' · errores '+(j.n_error||0);
  }catch(e){
    _spotBatchRows = [];
    if (btn) btn.disabled = true;
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }finally{
    if (input) input.value = '';
  }
}

async function connectSpotBatch(rows){
  const data = rows || _spotBatchRows;
  const msg = document.getElementById('spotBatchMsg');
  const btn = document.getElementById('btnSpotBatch');
  if (!data.length){ if (msg) msg.textContent = 'Cargue un archivo primero.'; return; }
  if (!confirm('¿Conectar en bloque '+data.filter(function(x){return x.ok!==false;}).length+' SpotLoad?')) return;
  try{
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = 'Conectando lote…';
    const j = await spotFetch('/api/cargas/lote/conectar', {rows: data});
    if (j.ok === false && !j.n_ok) throw new Error(j.error||'Error lote');
    _spotBatchRows = j.results || data;
    renderSpotBatchTable(_spotBatchRows);
    if (msg) msg.textContent = j.msg || ('OK '+(j.n_ok||0)+' · err '+(j.n_error||0));
    loadSpotPending();
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }finally{
    if (btn) btn.disabled = !_spotBatchRows.some(function(x){ return x.ok !== false; });
  }
}

async function loadSpotPending(){
  const msg = document.getElementById('spotPendingMsg');
  const btn = document.getElementById('btnSpotPending');
  const box = document.getElementById('spotPendingTable');
  try{
    const j = await spotFetch('/api/cargas/pendientes');
    if (j && j.ok === false) throw new Error(j.error||'Error');
    // spotFetch may POST; pendientes is GET
  }catch(_e){ /* fallback GET */ }
  try{
    const pack = (typeof getActiveFeederPack === 'function') ? getActiveFeederPack() : {};
    const h = {};
    if (pack.feeder) h['X-Feeder'] = pack.feeder;
    const r = await fetch('/api/cargas/pendientes', {headers:h});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error||'Error');
    _spotPendingRows = j.rows || [];
    if (btn) btn.disabled = !_spotPendingRows.length;
    if (msg) msg.textContent = _spotPendingRows.length
      ? (_spotPendingRows.length+' pendiente(s)')
      : 'Sin pendientes.';
    if (box){
      if (!_spotPendingRows.length) box.innerHTML = '<div class="muted">Ninguna.</div>';
      else {
        let html = '<table><thead><tr><th>Nombre</th><th>NodeID</th><th>P_kW</th><th>Estado</th></tr></thead><tbody>';
        _spotPendingRows.forEach(function(p){
          html += '<tr><td>'+(p.Nombre||p.LoadID||'')+'</td><td>'+(p.NodeID||'')
            +'</td><td>'+(p.P_kW??'')+'</td><td>'+(p.Estado||'')+'</td></tr>';
        });
        html += '</tbody></table>';
        box.innerHTML = html;
      }
    }
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function retrySpotPending(){
  const rows = (_spotPendingRows||[]).map(function(p,i){
    return {
      row: i+1, Accion:'ACTUALIZAR', NodeID:p.NodeID||'', Nombre:p.Nombre||p.LoadID||'',
      Modo:'KW_COSFI', P_kW:p.P_kW, Q_kvar:p.Q_kvar, cosfi:p.cosfi||'0.95',
      ok: !!(p.NodeID && (p.Nombre||p.LoadID) && p.P_kW!=null && p.P_kW!==''),
    };
  });
  _spotBatchRows = rows;
  renderSpotBatchTable(rows);
  await connectSpotBatch(rows);
}

/* —— §6 Optimización + §7 Suite —— */
function suiteActiveHeaders(){
  const pack = (typeof getActiveFeederPack === 'function') ? getActiveFeederPack() : {};
  const h = {'Content-Type':'application/json'};
  if (pack.feeder) h['X-Feeder'] = pack.feeder;
  return {pack: pack, headers: h};
}

async function suiteFetch(path, body){
  const ctx = suiteActiveHeaders();
  const payload = Object.assign({}, body || {}, {
    feeder: (body && body.feeder) || ctx.pack.feeder || undefined,
  });
  const r = await fetchWithTimeout(path, {
    method: 'POST',
    headers: ctx.headers,
    body: JSON.stringify(payload),
    cache: 'no-store',
  }, 180000);
  const text = await r.text();
  try { return JSON.parse(text); }
  catch(e){ return {ok:false, error:'Respuesta no JSON: '+(text||'').slice(0,200)}; }
}

function suiteShow(outId, msgId, j, okText){
  const out = document.getElementById(outId || 'suiteOut');
  const msg = msgId ? document.getElementById(msgId) : null;
  if (out) out.textContent = JSON.stringify(j, null, 2);
  if (msg) {
    if (j && j.ok) msg.innerHTML = '<span class="ok">'+(okText || j.msg || 'OK')+'</span>';
    else msg.innerHTML = '<span class="err">'+((j && (j.error||j.msg)) || 'Error')+'</span>';
  }
}

async function runOpt(kind){
  const msg = document.getElementById('optMsg');
  const out = document.getElementById('optOut');
  const force = !!(document.getElementById('optForce')||{}).checked;
  if (msg) msg.textContent = 'Ejecutando optimización '+kind+'…';
  try{
    const j = await suiteFetch('/api/optimizacion/'+kind, {force: force});
    if (out) out.textContent = JSON.stringify(j, null, 2);
    if (msg) {
      if (j.ok) msg.innerHTML = '<span class="ok">'+(j.msg || j.status || 'OK')+'</span>';
      else msg.innerHTML = '<span class="err">'+(j.error || j.msg || 'Fallo')+'</span>';
    }
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteEnv(){
  const msg = document.getElementById('suiteEnvMsg');
  if (msg) msg.textContent = 'Validando entorno…';
  try{
    const r = await fetch('/api/suite/entorno', {cache:'no-store', headers: suiteActiveHeaders().headers});
    const j = await r.json();
    suiteShow('suiteOut', 'suiteEnvMsg', j, 'Entorno OK');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteTestConn(){
  const msg = document.getElementById('suiteEnvMsg');
  if (msg) msg.textContent = 'Probando conexión CYMDIST…';
  try{
    const j = await suiteFetch('/api/suite/conexion', {});
    suiteShow('suiteOut', 'suiteEnvMsg', j, j.msg || 'Conexión OK');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteValidateInputs(){
  const msg = document.getElementById('suiteEnvMsg');
  if (msg) msg.textContent = 'Validando entradas…';
  try{
    const j = await suiteFetch('/api/suite/validar_entradas', {});
    suiteShow('suiteOut', 'suiteEnvMsg', j, j.msg || 'Entradas OK');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteInventoryLoads(){
  const msg = document.getElementById('suiteEnvMsg');
  if(!confirm('Inventariar SpotLoad de TODOS los alimentadores (~96) desde ELD/BD.\n\nGenera loads.json por radial para SED↔ en Armar tabla.\nPuede tardar varios minutos. ¿Continuar?')) return;
  if (msg) msg.textContent = 'Inventariando SpotLoad sistema (96)…';
  try{
    const ctx = suiteActiveHeaders();
    const r = await fetchWithTimeout('/api/suite/inventario_cargas', {
      method: 'POST',
      headers: ctx.headers,
      body: JSON.stringify({system: true, feeder: ctx.pack.feeder || undefined}),
      cache: 'no-store',
    }, 900000);
    const text = await r.text();
    let j;
    try { j = JSON.parse(text); }
    catch(e){ j = {ok:false, error:'Respuesta no JSON: '+(text||'').slice(0,200)}; }
    const m = j.msg || ('Cargas: '+(j.n_loads_total!=null?j.n_loads_total:j.n_loads));
    suiteShow('suiteOut', 'suiteEnvMsg', j, m);
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteSyncEquip(){
  const msg = document.getElementById('suiteEqMsg');
  if (msg) msg.textContent = 'Sync equipos (puede tardar)…';
  try{
    const j = await suiteFetch('/api/suite/sync_equipos', {});
    suiteShow('suiteOut', 'suiteEqMsg', j, j.msg || 'Sync OK');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteFixDefault(){
  const msg = document.getElementById('suiteEqMsg');
  if (!confirm('Cerrar equipos DEFAULT AAAC/XLPE en toda la BD. ¿Continuar?')) return;
  if (msg) msg.textContent = 'Cerrando DEFAULT (sistema)…';
  try{
    const j = await suiteFetch('/api/suite/fix_default', {});
    suiteShow('suiteOut', 'suiteEqMsg', j, j.msg || 'DEFAULT cerrados');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteExportAscii(){
  const msg = document.getElementById('suiteEqMsg');
  if (msg) msg.textContent = 'Exportando ASCII (todas las redes)…';
  try{
    const j = await suiteFetch('/api/suite/export_ascii', {});
    suiteShow('suiteOut', 'suiteEqMsg', j, j.msg || 'Export ASCII OK');
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suiteNewFeeder(){
  const msg = document.getElementById('suiteNfMsg');
  const fid = ((document.getElementById('nfId')||{}).value || '').trim();
  if (!fid) {
    if (msg) msg.innerHTML = '<span class="err">Indique ID de alimentador.</span>';
    return;
  }
  if (msg) msg.textContent = 'Creando '+fid+'…';
  try{
    const j = await suiteFetch('/api/suite/nuevo_alimentador', {
      feeder_id: fid,
      name: ((document.getElementById('nfName')||{}).value || '').trim(),
      network_id: ((document.getElementById('nfNet')||{}).value || '').trim(),
      voltage_kv: ((document.getElementById('nfKv')||{}).value || 22.9),
    });
    suiteShow('suiteOut', 'suiteNfMsg', j, j.msg || ('Creado '+fid));
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

async function suitePipeline(){
  const msg = document.getElementById('suitePipeMsg');
  if (!confirm('Ejecutar pipeline completo del alimentador activo. Puede tardar varios minutos. ¿Continuar?')) return;
  if (msg) msg.textContent = 'Pipeline en curso…';
  try{
    const j = await suiteFetch('/api/suite/pipeline', {});
    suiteShow('suiteOut', 'suitePipeMsg', j, j.msg || ('rc='+j.rc));
  }catch(e){
    if (msg) msg.innerHTML = '<span class="err">'+e+'</span>';
  }
}

// No auto-buscar nodos al cargar: evita abrir CYMDIST y colgar el arranque.
// searchNodes() se dispara al escribir en el buscador o al actualizar inventario.
</script>
</body>
</html>
"""

_LOAD_CACHE = {"feeder": None, "loads": []}
_NODE_CACHE = {"feeder": None, "topo": None}

def _request_feeder_network():
    """feeder + network_id desde query, header X-Feeder o body JSON (selector UI)."""
    body = request.get_json(silent=True) or {}
    feeder = (
        request.args.get("feeder")
        or request.headers.get("X-Feeder")
        or body.get("feeder")
        or None
    )
    feeders = body.get("feeders") or []
    if not feeder and feeders:
        feeder = feeders[0]
    network_id = body.get("network") or body.get("network_id") or None
    networks = body.get("networks") or []
    if not network_id and networks:
        network_id = networks[0]
    return feeder, network_id


def _settings():
    """Settings del request. Sintetiza config si el alimentador está en BD sin JSON local."""
    feeder, network_id = _request_feeder_network()
    if feeder:
        return load_settings(feeder_id=feeder, network_id=network_id, synthesize=True)
    return load_settings()


def _jsonify_safe(payload, status=200):
    """JSON siempre (evita 'Respuesta no JSON (500)' por TypeError/HTML)."""
    try:
        return jsonify(payload), status
    except Exception as ex:
        try:
            return jsonify({"ok": False, "error": "Respuesta no serializable: %s" % ex}), 500
        except Exception:
            return ({"ok": False, "error": str(ex)}, 500, {"Content-Type": "application/json"})


def _calidad_run(fn):
    """Ejecuta handler de calidad; cualquier fallo → JSON {ok:false}."""
    try:
        result = fn()
        if isinstance(result, tuple):
            return result
        return _jsonify_safe(result)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return _jsonify_safe({"ok": False, "error": str(ex)}, 200)


def _cympy_run(who, fn, timeout_sec=0.35):
    """Ejecuta trabajo CYMDIST bajo lock. Si ocupado → JSON inmediato (no cuelga UI)."""
    from pipeline.model_quality_gate import with_cympy_lock

    def _wrap():
        try:
            return fn()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(ex)}

    return _jsonify_safe(with_cympy_lock(who, _wrap, timeout_sec=timeout_sec))


def _cympy_isolated_or_run(action, fn, payload=None, timeout_sec=600.0):
    """Preferir worker aislado para acciones CymPy; fallback in-process.

    Las rutas Flask legacy (HTML) y el puente FastAPI usan el mismo camino
    que /api/jobs, así un Access Violation no tumba el servidor.
    """
    try:
        from core.cympy_isolation import should_isolate_action, run_job_action_isolated

        if should_isolate_action(action):
            feeder = (request.headers.get("X-Feeder") or "").strip() or None
            body = payload
            if body is None:
                body = request.get_json(silent=True) or {}
            result = run_job_action_isolated(
                action,
                payload=body if isinstance(body, dict) else {},
                feeder=feeder,
                timeout=float(timeout_sec),
            )
            return _jsonify_safe(result)
    except Exception as ex:
        print("AVISO isolation Flask (%s):" % action, ex)

    # Fallback: lock in-process (timeout largo para writes)
    return _cympy_run(action, fn, timeout_sec=min(float(timeout_sec), 300.0))

def _invalidate_caches():
    _LOAD_CACHE["feeder"] = None
    _LOAD_CACHE["loads"] = []
    _NODE_CACHE["feeder"] = None
    _NODE_CACHE["topo"] = None


def _safe_remove(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            return True
    except Exception:
        pass
    return False


def reset_downstream_after_cabecera(settings):
    """Al guardar/aplicar §1: limpia artefactos de §§2–4 y el Tablero dinámico.

    El tablero debe quedar vacío hasta que se ejecute 2.1 · Diagnosticar.
    No borra dispositivos en CYMDIST; solo resultados/tablas de sesión RECYM.
    """
    removed = []
    # §2 calidad / tablero → ceros (helper compartido con SPA)
    try:
        from analysis.build_dashboard import clear_tablero_diagnostics
        tab = clear_tablero_diagnostics(settings, rebuild=False)
        removed.extend(tab.get("cleared") or [])
    except Exception as ex:
        print("AVISO clear_tablero_diagnostics:", ex)

    targets = [
        output_path(settings, "diagnostics", "correcciones_propuestas.csv"),
        output_path(settings, "diagnostics", "diagnostico_tecnico.csv"),
        output_path(settings, "preview_changes.csv"),
        # §3–4
        output_path(settings, "clientes", "clientes_alimentador.json"),
        output_path(settings, "clientes", "clientes_alimentador.csv"),
        output_path(settings, "clientes", "apply_cymdist_report.csv"),
        output_path(settings, "demand", "allocation_result.json"),
        output_path(settings, "demand", "loadflow_result.json"),
        output_path(settings, "demand", "loadflow_situacional.json"),
        output_path(settings, "demand", "loadflow_proyectado.json"),
        output_path(settings, "loads", "new_spot_loads_report.csv"),
    ]
    for p in targets:
        if _safe_remove(p):
            removed.append(os.path.basename(p))

    # Gate de calidad: pendiente hasta 2.1
    try:
        from pipeline.run_demand_allocation import load_session, save_session
        sess = load_session(settings)
        if sess.get("model_quality_gate"):
            sess.pop("model_quality_gate", None)
            sess["status"] = sess.get("status") or "cabecera_ok"
            save_session(settings, sess)
            removed.append("model_quality_gate")
    except Exception as ex:
        print("AVISO clear gate sesión:", ex)

    # Tablero vacío (códigos/errores en cero) para la SPA
    try:
        from analysis.build_dashboard import main as build_tablero
        build_tablero(settings)
        removed.append("tablero_reset")
    except Exception as ex:
        print("AVISO rebuild tablero vacío:", ex)

    _invalidate_caches()
    return {"cleared": removed, "n": len(removed), "tablero_reset": True}

def _loads(s, open_cymdist=True):
    """Inventario SpotLoad. Por defecto no abre CYMDIST si no hay JSON (evita colgar Armar tabla)."""
    if _LOAD_CACHE["feeder"] == s.get("feeder_id") and _LOAD_CACHE["loads"]:
        return _LOAD_CACHE["loads"]
    inv = output_path(s, "inventory", "loads.json")
    if os.path.isfile(inv):
        with open(inv, "r", encoding="utf-8") as f:
            data = json.load(f)
        _LOAD_CACHE["feeder"] = s.get("feeder_id")
        _LOAD_CACHE["loads"] = data.get("loads") or []
        return _LOAD_CACHE["loads"]
    if not open_cymdist:
        return []
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study(force_backup=False)
    rows = collect_loads(c, s.get("network_id"))
    _LOAD_CACHE["feeder"] = s.get("feeder_id")
    _LOAD_CACHE["loads"] = rows
    os.makedirs(os.path.dirname(inv), exist_ok=True)
    with open(inv, "w", encoding="utf-8") as f:
        json.dump({"feeder_id": s["feeder_id"], "loads": rows}, f, indent=2, ensure_ascii=False)
    return rows

def _loads_for_feeders(feeders, open_cymdist=False):
    """Une inventarios SpotLoad. open_cymdist=False → solo caché JSON (Armar tabla rápido)."""
    ids = [str(f).strip().upper() for f in (feeders or []) if str(f).strip()]
    if not ids:
        return _loads(_settings(), open_cymdist=open_cymdist)
    merged = []
    seen = set()
    for fid in ids:
        try:
            fs = load_settings(feeder_id=fid, synthesize=True)
            for L in (_loads(fs, open_cymdist=open_cymdist) or []):
                lid = str((L.get("LoadID") if isinstance(L, dict) else L) or "")
                if not lid or lid in seen:
                    continue
                seen.add(lid)
                merged.append(L if isinstance(L, dict) else {"LoadID": lid})
        except Exception as ex:
            print("AVISO inventario cargas %s: %s" % (fid, ex))
    return merged

def _existing_load_ids(s):
    return [str(r.get("LoadID")) for r in (_loads(s, open_cymdist=False) or []) if r.get("LoadID")]

@app.route("/")
def index():
    if SPA_MODE:
        return jsonify({
            "ok": True,
            "spa": True,
            "ui_version": UI_VERSION,
            "msg": "UI React en / (FastAPI). Flask legacy solo /api/*.",
        })
    s = _settings()
    sess = seed_session_from_excel(s)
    mode = (sess.get("mode") or "KW_COSFI").upper()
    v_default = sess.get("Vll_kV")
    if v_default in (None, ""):
        v_default = s.get("voltage_ll_kv") or 22.9
    html = render_template_string(
        TEMPLATE,
        utility=s.get("utility_name"),
        feeder=s.get("feeder_id"),
        network=s.get("network_id"),
        mode=mode,
        p_kw=sess.get("P_kW") or "",
        q_kvar=sess.get("Q_kvar") or "",
        cosfi=sess.get("cosfi") or 0.95,
        i_a=sess.get("I_A") or "",
        v_ll=v_default,
        fecha_medicion=sess.get("fecha_medicion") or "",
        dry_run=bool(s.get("dry_run")),
        ui_version=UI_VERSION,
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/api/contexto/archivos")
def api_contexto_archivos():
    """Lista .mdb, .zxst y alimentadores de la BD (cualquiera, sin fijo)."""
    from core.feeder_context import list_database_files, list_study_files, list_bd_feeder_catalog
    from core.common import load_json
    try:
        from core.common import load_json
        global_s = load_json("config/settings.json")
        try:
            s = _settings()
        except Exception:
            s = global_s
        dbs = list_database_files(global_s)
        studies = list_study_files(global_s)
        feeders = list_bd_feeder_catalog(global_s)
        cur_db = s.get("database_mdb") or global_s.get("database_mdb") or ""
        cur_st = (
            s.get("study_path")
            or global_s.get("ui_study_path")
            or global_s.get("eld_study_path")
            or ""
        )
        return jsonify({
            "ok": True,
            "databases": dbs,
            "studies": studies,
            "feeders": feeders,
            "n_feeders": len(feeders),
            "current_database": cur_db,
            "current_study": cur_st,
            "current_feeder": s.get("feeder_id") or global_s.get("active_feeder") or "",
            "current_network": s.get("network_id") or "",
            "database_dir": global_s.get("database_dir"),
            "projects_dir": global_s.get("projects_dir"),
            "msg": "Cualquier alimentador de la BD se puede cargar (sin fijo).",
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex), "databases": [], "studies": [], "feeders": []})


@app.route("/api/contexto/aplicar", methods=["POST"])
def api_contexto_aplicar():
    """Persiste BD y/o estudio elegidos en settings (+ feeder si aplica).

    Reinicia Tablero dinámico / gate §2: sin valores hasta 2.1 · Diagnosticar.
    """
    from core.feeder_context import apply_context_selection, load_settings
    body = request.get_json(silent=True) or {}
    try:
        result = apply_context_selection(
            database_mdb=body.get("database_mdb") or None,
            study_path=body.get("study_path") or None,
            feeder_id=body.get("feeder") or request.headers.get("X-Feeder"),
            persist=True,
        )
        try:
            _invalidate_caches()
        except Exception:
            pass
        try:
            from pipeline.model_quality_gate import clear_networks_cache
            clear_networks_cache()
        except Exception:
            pass
        # §1 re-aplicado → limpiar diagnósticos previos del tablero
        reset_info = None
        try:
            fid = (result.get("feeder_id") or body.get("feeder") or "").strip()
            s = load_settings(feeder_id=fid, synthesize=True) if fid else _settings()
            if body.get("study_path"):
                s["study_path"] = body.get("study_path")
            reset_info = reset_downstream_after_cabecera(s)
            result["reset_downstream"] = reset_info
            result["msg"] = (
                (result.get("msg") or "Contexto aplicado")
                + " · Tablero §2 reiniciado (ejecute 2.1 Diagnosticar)"
            )
        except Exception as ex_reset:
            print("AVISO reset tablero tras contexto:", ex_reset)
            result["reset_error"] = str(ex_reset)
        return jsonify(result)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/ui/ping")
def api_ui_ping():
    busy = False
    holder = {}
    try:
        from pipeline.model_quality_gate import cympy_busy, cympy_holder
        busy = bool(cympy_busy())
        holder = cympy_holder() or {}
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "ui_version": UI_VERSION,
        "cympy_busy": busy,
        "cympy_holder": holder.get("who"),
        "ts": __import__("time").time(),
    })


@app.route("/api/ui/actualizar", methods=["POST", "GET"])
def api_ui_actualizar():
    """Actualizar (sidebar): vacía Tablero dinámico → ceros y refresca cachés.

    Los campos (errores, códigos, muestra) quedan en 0 hasta 2.1 · Diagnosticar.
    No abre CYMDIST.
    """
    tablero_info = None
    try:
        from analysis.build_dashboard import clear_tablero_diagnostics
        s = _settings()
        feeder = (request.headers.get("X-Feeder") or "").strip()
        if feeder:
            from core.feeder_context import load_settings
            s = load_settings(feeder_id=feeder, synthesize=True)
        tablero_info = clear_tablero_diagnostics(s, rebuild=True)
    except Exception as ex:
        print("AVISO ui/actualizar tablero:", ex)
        tablero_info = {"ok": False, "error": str(ex)}
    try:
        from pipeline.model_quality_gate import clear_networks_cache
        clear_networks_cache()
    except Exception:
        pass
    try:
        _invalidate_caches()
    except Exception:
        pass
    board = (tablero_info or {}).get("tablero") or {}
    before = board.get("before") or (tablero_info or {}).get("before") or {}
    after = board.get("after") or (tablero_info or {}).get("after") or {}
    return jsonify({
        "ok": True,
        "ui_version": UI_VERSION,
        "tablero_reset": True,
        "has_diagnostic": False,
        "before": before,
        "after": after,
        "errores_antes": before.get("total_messages", 0),
        "errores_despues": after.get("total_messages", 0),
        "cleared": (tablero_info or {}).get("cleared"),
        "msg": "Tablero en cero · pulse 2.1 Diagnosticar para cargar resultados",
    })


@app.route("/api/ui/reset", methods=["POST"])
def api_ui_reset():
    """Limpia cachés, vacía Tablero y limpia medición de cabecera del alimentador.

    Restablecer sí deja P/Q/Vll/fecha vacíos; Actualizar no toca la sesión.
    """
    try:
        from pipeline.model_quality_gate import clear_networks_cache
        clear_networks_cache()
    except Exception as ex:
        print("AVISO clear_networks_cache:", ex)
    try:
        _invalidate_caches()
    except Exception as ex:
        print("AVISO _invalidate_caches:", ex)
    tablero_info = None
    try:
        from analysis.build_dashboard import clear_tablero_diagnostics
        s = _settings()
        feeder = (request.headers.get("X-Feeder") or "").strip()
        if feeder:
            from core.feeder_context import load_settings
            s = load_settings(feeder_id=feeder, synthesize=True)
        tablero_info = clear_tablero_diagnostics(s, rebuild=True)
    except Exception as ex:
        print("AVISO clear tablero en ui/reset:", ex)
        tablero_info = {"ok": False, "error": str(ex)}
    cabecera_cleared = False
    try:
        s = _settings()
        feeder = (request.headers.get("X-Feeder") or "").strip()
        if feeder:
            s = load_settings(feeder_id=feeder, synthesize=True)
        sess = load_session(s)
        for k in ("P_kW", "Q_kvar", "I_A", "Va_kV", "Vb_kV", "Vc_kV", "S_kVA", "P_avg_kW", "factor_carga_pct"):
            sess[k] = None
        sess["Vll_kV"] = None
        sess["fecha_medicion"] = ""
        sess["medidor"] = ""
        sess["medicion_file"] = ""
        sess["status"] = "empty"
        sess.pop("allocation", None)
        sess.pop("last_allocation", None)
        save_session(s, sess)
        cabecera_cleared = True
    except Exception as ex:
        print("AVISO clear cabecera en ui/reset:", ex)
    return jsonify({
        "ok": True,
        "ui_version": UI_VERSION,
        "tablero_reset": tablero_info,
        "cabecera_cleared": cabecera_cleared,
        "msg": "Caches limpiadas · Tablero en cero · cabecera vacía. Recargue la pagina.",
    })


@app.route("/api/calidad/estado")
def api_calidad_estado():
    from pipeline.model_quality_gate import get_gate_status
    return _calidad_run(lambda: get_gate_status(_settings()))


@app.route("/api/calidad/redes")
def api_calidad_redes():
    """Lista alimentadores/redes. Sin force=1 NO abre CYMDIST (disco/memoria)."""
    from pipeline.model_quality_gate import list_bd_networks
    force = request.args.get("force") in ("1", "true", "True", "yes")
    soft = not force
    return _calidad_run(lambda: list_bd_networks(_settings(), force=force, soft=soft))


@app.route("/api/calidad/ejecutar_seleccionados", methods=["POST"])
def api_calidad_ejecutar_seleccionados():
    """Diagnostica/corrige uno o varios alimentadores seleccionados del estudio."""
    from pipeline.model_quality_gate import run_selected_until_converges
    body = request.get_json(silent=True) or {}

    def _run():
        result = run_selected_until_converges(
            _settings(),
            networks=body.get("networks") or body.get("network_ids"),
            feeders=body.get("feeders"),
            max_iters=int(body.get("max_iters") or 4),
        )
        result["ok_http"] = True
        return result

    return _cympy_isolated_or_run("calidad_seleccionados", _run, payload=body, timeout_sec=900.0)


@app.route("/api/calidad/diagnosticar", methods=["POST"])
def api_calidad_diagnosticar():
    from pipeline.model_quality_gate import run_network_diagnostic
    from analysis.build_dashboard import main as build_tablero
    import shutil

    def _run():
        s = _settings()
        result = run_network_diagnostic(s, suffix="")
        summary = (result.get("summary") or {}) if isinstance(result, dict) else {}
        try:
            before_path = output_path(s, "diagnostics", "dashboard_summary.json")
            after_path = output_path(s, "diagnostics", "dashboard_summary_after.json")
            before_csv = output_path(s, "diagnostics", "cymdist_diagnostic_errors.csv")
            after_csv = output_path(s, "diagnostics", "cymdist_diagnostic_errors_after.csv")
            summary = dict(summary)
            summary["empty"] = False
            summary.setdefault("phase", "before")
            after_summary = dict(summary)
            after_summary["phase"] = "after"
            after_summary["empty"] = False
            with open(before_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            with open(after_path, "w", encoding="utf-8") as f:
                json.dump(after_summary, f, indent=2, ensure_ascii=False)
            if os.path.isfile(before_csv):
                shutil.copy2(before_csv, after_csv)
            build_tablero(s)
            if isinstance(result, dict):
                result["tablero_updated"] = True
                result["summary"] = summary
                result["tablero"] = {
                    "before": summary,
                    "after": after_summary,
                    "total_messages": summary.get("total_messages"),
                    "by_code": summary.get("by_code"),
                    "top_errors": summary.get("top_errors"),
                    "n_problems": summary.get("n_problems"),
                    "has_diagnostic": True,
                }
                result["msg"] = (
                    "Diagnóstico OK · %s msgs · tablero actualizado"
                    % summary.get("total_messages")
                )
        except Exception as ex:
            if isinstance(result, dict):
                result["tablero_error"] = str(ex)
        return result

    return _cympy_isolated_or_run("calidad_diagnosticar", _run, timeout_sec=600.0)


@app.route("/api/calidad/diagnosticar_sistema", methods=["POST"])
def api_calidad_diagnosticar_sistema():
    """Diagnóstico de todas las redes de la BD. Independiente de §§1–4 / SpotLoad."""
    from pipeline.model_quality_gate import run_system_network_diagnostic
    body = request.get_json(silent=True) or {}
    return _cympy_isolated_or_run(
        "calidad_sistema",
        lambda: run_system_network_diagnostic(
            _settings(),
            limit=int(body.get("limit") or 0),
            network_ids=body.get("networks") or None,
        ),
        payload=body,
        timeout_sec=900.0,
    )

@app.route("/api/calidad/diagnosticar_eld", methods=["POST"])
def api_calidad_diagnosticar_eld():
    """Herramienta diagnóstica API sobre ELD.zxst (Topología + Equipos)."""
    from pipeline.model_quality_gate import run_eld_network_diagnostic
    body = request.get_json(silent=True) or {}
    return _cympy_isolated_or_run(
        "calidad_eld",
        lambda: run_eld_network_diagnostic(
            _settings(),
            limit=int(body.get("limit") or 0),
            network_ids=body.get("networks") or None,
        ),
        payload=body,
        timeout_sec=900.0,
    )


@app.route("/api/calidad/proponer", methods=["POST"])
def api_calidad_proponer():
    from pipeline.model_quality_gate import propose_corrections
    return _cympy_isolated_or_run(
        "calidad_proponer",
        lambda: propose_corrections(_settings()),
        timeout_sec=600.0,
    )


@app.route("/api/calidad/aplicar", methods=["POST"])
def api_calidad_aplicar():
    from pipeline.model_quality_gate import apply_corrections
    return _cympy_isolated_or_run(
        "calidad_aplicar",
        lambda: apply_corrections(_settings(), fix_voltages=True),
        timeout_sec=600.0,
    )


@app.route("/api/calidad/convergencia", methods=["POST"])
def api_calidad_convergencia():
    from pipeline.model_quality_gate import check_convergence
    return _cympy_isolated_or_run(
        "calidad_convergencia",
        lambda: check_convergence(_settings(), run_lf=True),
        timeout_sec=600.0,
    )


@app.route("/api/calidad/hasta_limpio", methods=["POST"])
def api_calidad_hasta_limpio():
    from pipeline.model_quality_gate import run_until_converges
    body = request.get_json(silent=True) or {}

    def _run():
        result = run_until_converges(
            _settings(),
            max_iters=int(body.get("max_iters") or 4),
            skip_initial_lf=bool(body.get("skip_initial_lf")),
        )
        result["ok_http"] = True
        return result

    return _cympy_isolated_or_run(
        "calidad_hasta_limpio", _run, payload=body, timeout_sec=900.0
    )

def _cabecera_payload_from_session(s, sess):
    """Serializa la última medición guardada (session.json) para la SPA §1."""
    vll = sess.get("Vll_kV")
    try:
        vll_f = float(vll) if vll not in (None, "") else None
    except Exception:
        vll_f = None
    va = sess.get("Va_kV")
    vb = sess.get("Vb_kV")
    vc = sess.get("Vc_kV")
    if vll_f and vll_f > 0:
        vln = vll_f / (3.0 ** 0.5)
        if va in (None, ""):
            va = round(vln, 4)
        if vb in (None, ""):
            vb = round(vln, 4)
        if vc in (None, ""):
            vc = round(vln, 4)
    return {
        "ok": True,
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "mode": sess.get("mode") or "KW_KVAR",
        "P_kW": sess.get("P_kW"),
        "Q_kvar": sess.get("Q_kvar"),
        "P_kW_medicion": sess.get("P_kW_medicion"),
        "Q_kvar_medicion": sess.get("Q_kvar_medicion"),
        "P_kW_excluidas_restadas": sess.get("P_kW_excluidas_restadas"),
        "n_excluidas_cabecera": sess.get("n_excluidas_cabecera"),
        "cabecera_ajustada_por_excluidas": bool(
            sess.get("cabecera_ajustada_por_excluidas")
        ),
        "S_kVA": sess.get("S_kVA"),
        "P_avg_kW": sess.get("P_avg_kW"),
        "factor_carga_pct": sess.get("factor_carga_pct"),
        "medidor": sess.get("medidor") or "",
        "medicion_file": sess.get("medicion_file") or "",
        "cosfi": sess.get("cosfi"),
        "I_A": sess.get("I_A"),
        "Vll_kV": vll_f,
        "Va_kV": va,
        "Vb_kV": vb,
        "Vc_kV": vc,
        "fecha_medicion": sess.get("fecha_medicion") or "",
        "status": sess.get("status") or "empty",
    }


@app.route("/api/cabecera/medicion/archivos")
def api_cabecera_medicion_archivos():
    """Lista Excel de medicioncabecera + path del mapeo medidor."""
    try:
        from core.cabecera_medicion_excel import (
            list_medicioncabecera_files,
            medidoralimentador_path,
            medicioncabecera_dir,
        )
        from core.common import load_json
        global_s = load_json("config/settings.json")
        files = list_medicioncabecera_files(global_s)
        return jsonify({
            "ok": True,
            "files": files,
            "medicioncabecera_dir": medicioncabecera_dir(global_s),
            "medidoralimentador": medidoralimentador_path(global_s),
            "n_files": len(files),
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex), "files": []})


@app.route("/api/cabecera/medicion/resolver", methods=["GET", "POST"])
def api_cabecera_medicion_resolver():
    """Lookup medidor + Vll + Excel candidatos (sin leer series temporales)."""
    try:
        from core.cabecera_medicion_excel import resolve_cabecera_medicion
        from core.common import load_json
        global_s = load_json("config/settings.json")
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
        else:
            body = {}
        feeder = (
            (body.get("feeder") or "").strip()
            or (request.args.get("feeder") or "").strip()
            or (request.headers.get("X-Feeder") or "").strip()
        )
        if not feeder:
            return jsonify({"ok": False, "error": "Indique alimentador (feeder)"})
        return jsonify(resolve_cabecera_medicion(feeder, settings=global_s))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cabecera/medicion/extraer", methods=["GET", "POST"])
def api_cabecera_medicion_extraer():
    """Lookup medidor + extrae Pmax/Q/kVA/Pprom/FdC desde medicioncabecera.

    Si el Excel elegido no tiene la hoja del medidor, auto-localiza el correcto
    (auto_find_file=true por defecto) para evitar errores de selección.
    """
    try:
        from core.cabecera_medicion_excel import extract_cabecera_medicion
        from core.common import load_json
        global_s = load_json("config/settings.json")
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
        else:
            body = {}
        feeder = (
            (body.get("feeder") or "").strip()
            or (request.args.get("feeder") or "").strip()
            or (request.headers.get("X-Feeder") or "").strip()
        )
        medicion_file = (
            (body.get("medicion_file") or body.get("file") or "").strip()
            or (request.args.get("medicion_file") or request.args.get("file") or "").strip()
            or None
        )
        auto_find = body.get("auto_find_file")
        if auto_find is None:
            # Default: sí auto-corregir archivo incorrecto (robustez UI)
            auto_find = request.args.get("auto_find_file", "1") not in ("0", "false", "False")
        else:
            auto_find = bool(auto_find)
        if not feeder:
            return jsonify({"ok": False, "error": "Indique alimentador (feeder)"})
        result = extract_cabecera_medicion(
            feeder,
            medicion_file=medicion_file,
            settings=global_s,
            auto_find_file=auto_find,
        )
        return jsonify(result)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cabecera", methods=["GET", "POST"])
def api_cabecera():
    """GET: últimos P/Q/Vll/fases/fecha del alimentador.
    POST: guarda sesión + escribe SetDemand/OperatingVoltage en CYMDIST.
    """
    if request.method == "GET":
        feeder = (
            (request.headers.get("X-Feeder") or "").strip()
            or (request.args.get("feeder") or "").strip()
            or None
        )
        if feeder:
            s = load_settings(feeder_id=feeder, synthesize=True)
        else:
            s = _settings()
        try:
            sess = seed_session_from_excel(s, force=False)
        except Exception:
            sess = load_session(s)
        return jsonify(_cabecera_payload_from_session(s, sess))

    body = request.get_json(force=True) or {}
    # Aplicar BD/estudio del numeral 1 antes de escribir.
    # El alimentador lo define el estudio (PA217.zxst → PA217), no un X-Feeder viejo (IN112).
    ctx = None
    try:
        db = (body.get("database_mdb") or "").strip() or None
        st = (body.get("study_path") or "").strip() or None
        fid_body = (body.get("feeder") or "").strip() or None
        # Si hay estudio, el stem manda sobre feeder/header obsoleto
        if st:
            stem = os.path.splitext(os.path.basename(st))[0]
            if stem and stem.upper() != "ELD":
                fid_body = stem
        if db or st or fid_body:
            from core.feeder_context import apply_context_selection
            ctx = apply_context_selection(
                database_mdb=db,
                study_path=st,
                feeder_id=fid_body,
                persist=True,
            )
    except Exception as ex:
        return jsonify({"ok": False, "error": "Contexto BD/estudio: %s" % ex})

    feeder = None
    if ctx and ctx.get("feeder_id"):
        feeder = str(ctx.get("feeder_id")).strip() or None
    if not feeder:
        feeder = (body.get("feeder") or "").strip() or None
    if not feeder and body.get("study_path"):
        stem = os.path.splitext(os.path.basename(str(body.get("study_path"))))[0]
        if stem and stem.upper() != "ELD":
            feeder = stem

    if feeder:
        s = load_settings(feeder_id=feeder, synthesize=True)
    else:
        s = _settings()
    if body.get("study_path"):
        s["study_path"] = body.get("study_path")
    if body.get("database_mdb"):
        s["database_mdb"] = body.get("database_mdb")
    # Alinear network_id con el feeder del estudio (nunca mezclar IN112 + PA217)
    if ctx and ctx.get("network_id"):
        s["network_id"] = ctx.get("network_id")
    if feeder and s.get("feeder_id") and str(s.get("feeder_id")).upper() != str(feeder).upper():
        s = load_settings(feeder_id=feeder, synthesize=True)
        if body.get("study_path"):
            s["study_path"] = body.get("study_path")

    preview_only = bool(body.get("preview_only") or body.get("preview") or body.get("recalc_only"))
    try:
        p, q = compute_head_pq(
            body.get("mode"),
            body.get("P_kW"),
            body.get("Q_kvar"),
            body.get("cosfi"),
            i_a=body.get("I_A"),
            v_ll_kv=body.get("Vll_kV"),
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

    if preview_only:
        return jsonify({
            "ok": True,
            "preview_only": True,
            "P_kW": p,
            "Q_kvar": q,
            "mode": body.get("mode"),
            "feeder_id": s.get("feeder_id"),
            "network_id": s.get("network_id"),
            "msg": "Recalculo P/Q (sin escribir CYMDIST)",
        })

    # Fase 1: sesion RECYM + Excel (rapido; no depende de COM)
    reset_flag = body.get("reset_downstream")
    if reset_flag is None:
        reset_flag = True
    else:
        reset_flag = bool(reset_flag)
    sess = load_session(s)
    sess["mode"] = body.get("mode")
    sess["P_kW"] = p
    sess["Q_kvar"] = q
    # Base de medición §1: 3.2 resta Pot de desmarcadas desde aquí (no en cascada)
    sess["P_kW_medicion"] = float(p)
    sess["Q_kvar_medicion"] = float(q)
    sess["P_kW_excluidas_restadas"] = 0.0
    sess["n_excluidas_cabecera"] = 0
    sess["cabecera_ajustada_por_excluidas"] = False
    sess["cosfi"] = body.get("cosfi")
    if body.get("I_A") not in (None, ""):
        sess["I_A"] = float(body.get("I_A"))
    if body.get("Vll_kV") not in (None, ""):
        sess["Vll_kV"] = float(body.get("Vll_kV"))
    # Tensiones de fase LN (kV) → fuente/equivalente CYMDIST (siempre persistir)
    import math as _math
    for _ph_key in ("Va_kV", "Vb_kV", "Vc_kV"):
        if body.get(_ph_key) not in (None, ""):
            try:
                sess[_ph_key] = float(body.get(_ph_key))
            except Exception:
                pass
    # Si hay Vll pero faltan fases, derivar Vll/√3 para que la UI no las pierda
    if sess.get("Vll_kV") not in (None, "") and all(
        sess.get(k) in (None, "") for k in ("Va_kV", "Vb_kV", "Vc_kV")
    ):
        try:
            _vln = float(sess["Vll_kV"]) / _math.sqrt(3.0)
            sess["Va_kV"] = sess["Vb_kV"] = sess["Vc_kV"] = round(_vln, 4)
        except Exception:
            pass
    sess["fecha_medicion"] = (body.get("fecha_medicion") or "").strip()
    # Campos opcionales de extracción Excel (máx / promedio / FdC)
    for _k in ("S_kVA", "P_avg_kW", "factor_carga_pct"):
        if body.get(_k) not in (None, ""):
            try:
                sess[_k] = float(body.get(_k))
            except Exception:
                pass
    if body.get("medidor") not in (None, ""):
        sess["medidor"] = str(body.get("medidor")).strip()
    if body.get("medicion_file") not in (None, ""):
        sess["medicion_file"] = str(body.get("medicion_file")).strip()
    sess["status"] = "cabecera_session_ok"
    if reset_flag:
        sess["fixed_loads"] = []
        sess.pop("allocation", None)
        sess.pop("last_allocation", None)
        sess.pop("downstream", None)
    save_session(s, sess)
    reset_info = reset_downstream_after_cabecera(s) if reset_flag else None
    excel_path = None
    try:
        excel_path = sync_control_excel_cabecera(
            s, p, q, cosfi=sess.get("cosfi"), fecha=sess.get("fecha_medicion")
        )
    except Exception as ex:
        print("AVISO sync Excel cabecera:", ex)

    # Fase 2: SetDemand + tensiones fuente en SUBPROCESO (crash COM no mata waitress)
    from core.cympy_job import run_cympy_job
    job = run_cympy_job(
        "cabecera",
        {
            "feeder_id": s.get("feeder_id"),
            "network_id": s.get("network_id"),
            "study_path": s.get("study_path"),
            "database_mdb": s.get("database_mdb"),
            "P_kW": p,
            "Q_kvar": q,
            "Vll_kV": sess.get("Vll_kV"),
            "Va_kV": sess.get("Va_kV"),
            "Vb_kV": sess.get("Vb_kV"),
            "Vc_kV": sess.get("Vc_kV"),
        },
        settings=s,
        timeout_sec=int(os.environ.get("RECYM_CABECERA_TIMEOUT") or "90"),
    )
    cymdist_ok = bool(job.get("ok"))
    if cymdist_ok:
        sess["status"] = "cabecera_ok"
        save_session(s, sess)

    return jsonify({
        "ok": cymdist_ok,
        "P_kW": p,
        "Q_kvar": q,
        "S_kVA": sess.get("S_kVA"),
        "P_avg_kW": sess.get("P_avg_kW"),
        "factor_carga_pct": sess.get("factor_carga_pct"),
        "medidor": sess.get("medidor") or "",
        "medicion_file": sess.get("medicion_file") or "",
        "Vll_kV": sess.get("Vll_kV"),
        "Va_kV": sess.get("Va_kV"),
        "Vb_kV": sess.get("Vb_kV"),
        "Vc_kV": sess.get("Vc_kV"),
        "fecha_medicion": sess.get("fecha_medicion") or "",
        "mode": sess.get("mode"),
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "study_path": s.get("study_path"),
        "study_file": os.path.basename(s.get("study_path") or "") or s.get("study_file"),
        "database_mdb": s.get("database_mdb"),
        "cymdist": job.get("cymdist") or job,
        "cymdist_ok": cymdist_ok,
        "session_saved": True,
        "excel": excel_path,
        "reset_downstream": reset_info,
        "elapsed_sec": job.get("elapsed_sec"),
        "error": None if cymdist_ok else (job.get("error") or "Fallo SetDemand CYMDIST"),
        "msg": (
            ("Cabecera OK en %s · SetDemand + Vph fuente · §§2-4 restablecidos" % (s.get("feeder_id") or ""))
            if cymdist_ok and reset_info is not None
            else (
                "Cabecera OK en CYMDIST (Demanda Total kW/kvar + tensiones fuente)"
                if cymdist_ok
                else (
                    "Sesion/Excel guardados, pero CYMDIST fallo: %s. Cierre Cyme.exe y reintente Guardar."
                    % (job.get("error") or "error")
                )
            )
        ),
    })

@app.route("/api/clientes/archivos")
def api_clientes_archivos():
    s = _settings()
    return jsonify({
        "ok": True,
        "suministro": list_suministro_files(s),
        "clientesimportantes": list_clientes_importantes_files(s),
    })

@app.route("/api/clientes/radiales")
def api_clientes_radiales():
    """Lista RADIAL únicos del archivo suministrocliente (con conteo)."""
    s = _settings()
    sum_file = (request.args.get("suministro_file") or "").strip() or None
    try:
        items, used = list_radiales_from_suministro(s, suministro_file=sum_file)
        # Compat SPA: id + alias radial/RADIAL
        radiales = [
            {
                "id": it.get("id"),
                "radial": it.get("id"),
                "RADIAL": it.get("id"),
                "n": it.get("n"),
            }
            for it in (items or [])
        ]
        return jsonify({
            "ok": True,
            "suministro_file": used,
            "radiales": radiales,
            "n": len(radiales),
            "default": s.get("feeder_id"),
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

def _parse_feeders_body(body, settings):
    """Extrae feeders / feeder del body JSON.

    - 1 alimentador: cruce solo de ese RADIAL
    - N alimentadores: solo si el cliente los envia explicitamente en feeders[]
    """
    feeders = body.get("feeders")
    if isinstance(feeders, str):
        feeders = [x.strip() for x in re.split(r"[,;]+", feeders) if x.strip()]
    elif not isinstance(feeders, (list, tuple)):
        feeders = None
    if feeders:
        feeders = [str(x).strip().upper() for x in feeders if str(x).strip()]
        # dedupe preservando orden
        seen = set()
        uniq = []
        for f in feeders:
            if f not in seen:
                seen.add(f)
                uniq.append(f)
        feeders = uniq
    all_feeders = False  # nunca «todos» implícito
    feeder = (body.get("feeder") or "").strip()
    if feeders:
        feeder = feeders[0] if len(feeders) == 1 else ",".join(feeders)
    elif feeder:
        parts = [x.strip().upper() for x in re.split(r"[,;]+", feeder) if x.strip()]
        feeders = parts
        feeder = parts[0] if len(parts) == 1 else ",".join(parts)
    else:
        feeder = (settings.get("feeder_id") or "").strip()
        feeders = [feeder.upper()] if feeder else None
        if feeders:
            feeder = feeders[0]
    return feeder, feeders, all_feeders


def _settings_for_clientes(body, fallback=None):
    """Settings del alimentador seleccionado en el body (no el default de sesión).

    SED↔ / LoadID deben resolverse contra el inventario CYMDIST de ese radial.
    """
    base = fallback or _settings()
    feeder, feeders, all_feeders = _parse_feeders_body(body, base)
    primary = None
    if feeders and len(feeders) == 1:
        primary = feeders[0]
    elif feeder and "," not in str(feeder):
        primary = str(feeder).strip().upper()
    elif feeders:
        primary = feeders[0]
    if primary:
        return load_settings(feeder_id=primary, synthesize=True), feeder, feeders, all_feeders
    return base, feeder, feeders, all_feeders


@app.route("/api/clientes/tabla", methods=["POST"])
def api_clientes_tabla():
    body = request.get_json(force=True) or {}
    s, feeder, feeders, all_feeders = _settings_for_clientes(body)
    ci = (body.get("clientes_file") or "").strip()
    if not ci:
        return jsonify({
            "ok": False,
            "error": "Seleccione un archivo de clientesimportantes en el desplegable.",
            "disponibles": list_clientes_importantes_files(s),
        })
    try:
        if not all_feeders and not feeders and not feeder:
            return jsonify({"ok": False, "error": "Seleccione al menos un alimentador (RADIAL)."})
        print("[clientes/tabla] Cruzando NIS · CI=%s · feeders=%s" % (ci, feeders or feeder))
        rows, meta = build_feeder_clientes_table(
            s,
            feeder,
            clientes_file=ci,
            suministro_file=body.get("suministro_file") or None,
            all_feeders=all_feeders,
            feeders=feeders,
        )
        print("[clientes/tabla] Filas cruzadas:", len(rows or []))
        # Match SED↔: usa loads.json en disco; si falta, inventaria desde CYMDIST (1 vez).
        attach_note = ""
        try:
            from core.cymdist_com import pause_cymdist_for_cympy
            pause_cymdist_for_cympy(s)
            loads = _loads_for_feeders(
                feeders or [s.get("feeder_id")],
                open_cymdist=True,
            )
            rows = attach_cymdist_loads(rows, loads, primary_only=True)
            meta["n_loads_inventory"] = len(loads or [])
            if not loads:
                attach_note = (
                    "Sin SpotLoad en el estudio para este radial; "
                    "verifique network_id / estudio §1."
                )
        except Exception as ex_att:
            print("AVISO attach SED (tabla igual se muestra):", ex_att)
            attach_note = "Cruce Excel OK; Match SED pendiente (%s)" % ex_att
            meta["n_loads_inventory"] = 0
        csv_path = output_path(s, "clientes", "clientes_alimentador.csv")
        json_path = output_path(s, "clientes", "clientes_alimentador.json")
        # Solo reutilizar Activo si la tabla previa era del MISMO alimentador
        prev_rows = load_saved_clientes_rows(json_path)
        prev_meta_feeder = ""
        try:
            if os.path.isfile(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    prev_meta_feeder = str((json.load(f).get("meta") or {}).get("feeder_id") or "").strip().upper()
        except Exception:
            prev_meta_feeder = ""
        cur_feeder = str(meta.get("feeder_id") or feeder or "").strip().upper()
        if prev_meta_feeder and cur_feeder and prev_meta_feeder != cur_feeder:
            prev_rows = None  # descartar tabla de otro radial
        rows = merge_activo(
            rows,
            activo_map=body.get("activo"),
            previous_rows=prev_rows,
        )
        rows = ensure_activo(rows, default=True)
        # 3.1: Restar cab. siempre arranca sin marcar (el usuario elige a mano)
        rows = merge_restar_cabecera(
            rows,
            restar_map=body.get("restar_cabecera"),
            previous_rows=None,
        )
        rows = ensure_restar_cabecera(rows, default=False)
        for r in rows:
            if body.get("restar_cabecera") is None:
                r["RestarCabecera"] = False
        rows = ensure_restar_cabecera(rows, default=False)
        meta["n_match_sed"] = sum(1 for r in rows if r.get("Match_SED"))
        meta["n_sin_sed"] = sum(1 for r in rows if not r.get("Match_SED"))
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        meta["n_restar_cabecera"] = sum(
            1 for r in rows if (not r.get("Activo")) and r.get("RestarCabecera")
        )
        meta["loads_feeder_id"] = s.get("feeder_id")
        meta["n_rows"] = len(rows or [])
        if attach_note:
            meta["attach_note"] = attach_note
        save_table_csv(csv_path, rows)
        save_table_json(json_path, rows, meta)

        # Anti-saturación: al re-armar 3.1, liberar en CYMDIST los CI previos
        # que ya no están en la tabla nueva (Unlocked + KWH/kW=0) y guardar.
        cym_refresh = {"skipped": True}
        try:
            from pipeline.apply_clientes_to_cymdist import (
                previous_applied_load_ids,
                keep_load_ids_from_rows,
                release_clientes_loads,
            )
            from pipeline.run_demand_allocation import load_session, save_session
            prev_ids = previous_applied_load_ids(s)
            keep_ids = keep_load_ids_from_rows(rows, solo_activos=False)
            stale = prev_ids - keep_ids
            if stale:
                from core.cymdist_com import pause_cymdist_for_cympy
                from core.common import require_cympy, load_json
                from core.cympy_adapter import CymPyAdapter
                pause_cymdist_for_cympy(s)
                s_w = dict(s)
                s_w["skip_db_project_save"] = True
                api = load_json("config/cympy_api_map.json")
                c = require_cympy(s_w)
                a = CymPyAdapter(c, api, s_w)
                a.open_study(force_backup=False)
                released = release_clientes_loads(a, stale, reconnect=True)
                if s.get("save_after_write", True):
                    try:
                        a.save_study()
                    except Exception as ex_sv:
                        print("AVISO save post 3.1 liberar:", ex_sv)
                try:
                    a.close_study(save=False)
                except Exception:
                    pass
                cym_refresh = {
                    "skipped": False,
                    "n_liberados": released.get("n_liberados"),
                    "n_stale": len(stale),
                    "saved": True,
                }
                print("[3.1] CYMDIST liberados:", cym_refresh)
            else:
                cym_refresh = {"skipped": True, "reason": "sin_stale", "n_prev": len(prev_ids)}
            try:
                sess = load_session(s)
                sess["alloc_locks_ready"] = False
                sess.pop("alloc_locks_fixed_key", None)
                sess["tabla_armada_at"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
                save_session(s, sess)
            except Exception:
                pass
        except Exception as ex_ref:
            print("AVISO refresh CYMDIST 3.1:", ex_ref)
            cym_refresh = {"skipped": True, "error": str(ex_ref)}

        tablero = None
        # Tablero es opcional y lento; no bloquear la tabla cruzada
        try:
            if body.get("build_tablero"):
                from analysis.build_dashboard import main as build_tablero
                build_tablero()
                tablero = output_path(s, "diagnostics", "tablero.html")
        except Exception as ex_tab:
            print("AVISO tablero:", ex_tab)
        msg31 = "Tabla cruzada: %d filas" % len(rows or [])
        if not cym_refresh.get("skipped") and cym_refresh.get("n_liberados"):
            msg31 += " · CYMDIST liberó %d SED previos (anti-saturación)" % int(
                cym_refresh.get("n_liberados") or 0
            )
        return jsonify({
            "ok": True,
            "rows": rows,
            "meta": meta,
            "csv": csv_path,
            "tablero": tablero,
            "n_rows": len(rows or []),
            "cymdist_refresh": cym_refresh,
            "msg": msg31,
        })
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/clientes/activo", methods=["POST"])
def api_clientes_activo():
    """Persiste checkboxes Incluir/Activo.

    - Si no hay tabla Excel, siembra desde inventario SpotLoad (todas Incluir).
    - Capacidad SED (260044) NO bloquea Incluir.
    - apply_cymdist=true: conecta + dibuja símbolo de las incluidas (best-effort).
    - merge_inventory=false (§3): no mezcla SpotLoad residual en la tabla cruzada.
    """
    body = request.get_json(force=True) or {}
    s, _feeder, _feeders, _all = _settings_for_clientes(body)
    from core.clientes_suministro import (
        merge_activo, ensure_activo, merge_restar_cabecera, ensure_restar_cabecera,
        save_table_json, save_table_csv, ensure_clientes_table,
        clientes_importantes_rows,
    )
    json_path = output_path(s, "clientes", "clientes_alimentador.json")
    merge_inv = body.get("merge_inventory")
    if merge_inv is None:
        merge_inv = True
    try:
        rows, meta, json_path = ensure_clientes_table(
            s, merge_inventory=bool(merge_inv)
        )
        # §3: mantener solo filas con EA (clientes importantes)
        if not merge_inv:
            ci = clientes_importantes_rows(rows)
            if ci:
                rows = ci
        rows = merge_activo(rows, activo_map=body.get("activo"))
        rows = ensure_activo(rows, default=True)
        rows = merge_restar_cabecera(rows, restar_map=body.get("restar_cabecera"))
        rows = ensure_restar_cabecera(rows, default=False)
        meta = dict(meta or {})
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        meta["n_restar_cabecera"] = sum(
            1 for r in rows if (not r.get("Activo")) and r.get("RestarCabecera")
        )
        meta["capacity_not_blocking"] = True
        meta["merge_inventory"] = bool(merge_inv)
        save_table_json(json_path, rows, meta)
        save_table_csv(output_path(s, "clientes", "clientes_alimentador.csv"), rows)

        apply_info = None
        if body.get("apply_cymdist") or body.get("draw") or body.get("sync_model"):
            # Solo sync SpotLoads de clientes importantes (rápido)
            apply_info = _sync_incluir_to_cymdist(s, clientes_importantes_rows(rows) or rows)

        # Refrescar tablero JSON
        try:
            from analysis.build_dashboard import main as build_tablero
            build_tablero()
        except Exception as ex_b:
            print("AVISO rebuild tablero tras activo:", ex_b)

        return jsonify({
            "ok": True,
            "rows": rows,
            "n_activos": meta["n_activos"],
            "n_excluidos": meta["n_excluidos"],
            "n_restar_cabecera": meta.get("n_restar_cabecera", 0),
            "n": len(rows),
            "meta": meta,
            "apply_cymdist": apply_info,
            "msg": (
                "Incluir guardado · %s activas · %s excluidas · %s restan cabecera"
                % (meta["n_activos"], meta["n_excluidos"], meta.get("n_restar_cabecera", 0))
                + (" · modelo actualizado" if apply_info else "")
            ),
        })
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(ex)})


def _sync_incluir_to_cymdist(settings, rows):
    """Conecta/dibuja SpotLoads Incluir=SI; desconecta las excluidas.

    No aborta por capacidad conectada (260044): intenta subir ConnectedKVA
    o PF en best-effort y sigue.
    """
    from core.common import require_cympy, load_json, truthy
    from core.cympy_adapter import CymPyAdapter
    from pipeline.model_quality_gate import _pause_gui

    _pause_gui(settings)
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(settings)
    a = CymPyAdapter(c, api, settings)
    a.open_study(force_backup=False)
    report = {"ok": 0, "excluded": 0, "drawn": 0, "capacity_fix": 0, "errors": []}
    try:
        for r in rows:
            lid = str(r.get("LoadID_CYMDIST") or "").strip()
            if not lid:
                continue
            activo = truthy(r.get("Activo", True))
            try:
                if not activo:
                    a.set_load_connected(lid, False)
                    report["excluded"] += 1
                    continue
                a.set_load_connected(lid, True)
                if a._ensure_spot_symbol(lid):
                    report["drawn"] += 1
                # Capacidad / FP: best-effort, nunca bloquea Incluir
                try:
                    a.raise_load_connected_kva(lid)
                    report["capacity_fix"] += 1
                except Exception:
                    pass
                try:
                    a.raise_spotload_power_factor(lid, float(settings.get("min_device_pf") or 0.85))
                except Exception:
                    pass
                report["ok"] += 1
            except Exception as ex:
                report["errors"].append("%s: %s" % (lid, ex))
        if settings.get("save_after_fix", True):
            try:
                a.save_study()
                report["saved"] = True
            except Exception as ex_s:
                report["saved"] = False
                report["save_error"] = str(ex_s)
    finally:
        try:
            a.close_study(save=False)
        except Exception:
            pass
    report["n_errors"] = len(report["errors"])
    return report

@app.route("/api/clientes/export_xlsx", methods=["POST"])
def api_clientes_export_xlsx():
    """Descarga la tabla de clientes (§2) como Excel (.xlsx), con Incluir actual."""
    body = request.get_json(force=True) or {}
    s, _feeder, _feeders, _all = _settings_for_clientes(body)
    rows = body.get("rows")
    if not rows:
        json_path = output_path(s, "clientes", "clientes_alimentador.json")
        rows = load_saved_clientes_rows(json_path)
    if not rows:
        return jsonify({"ok": False, "error": "No hay tabla para exportar. Arme la tabla primero."})
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

        headers = [
            "Incluir", "RestarCabecera", "RADIAL", "Suministro", "Cliente", "SED", "EA", "Pot",
            "LoadID", "CI", "SED_match", "Generador", "Concesion", "Cliente_CI", "Codigo_CL",
        ]
        wb = Workbook()
        ws = wb.active
        ws.title = "Clientes"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="0F766E")
        thin = Border(
            left=Side(style="thin", color="CCCCCC"),
            right=Side(style="thin", color="CCCCCC"),
            top=Side(style="thin", color="CCCCCC"),
            bottom=Side(style="thin", color="CCCCCC"),
        )
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            cell.border = thin
        for i, r in enumerate(rows, 2):
            activo = r.get("Activo")
            incluir = "SI" if (activo is not False and activo not in ("false", "0", 0)) else "NO"
            restar = r.get("RestarCabecera")
            restar_txt = "SI" if (restar is not False and restar not in ("false", "0", 0)) else "NO"
            vals = [
                incluir,
                restar_txt,
                r.get("RADIAL") or "",
                r.get("Suministro") or "",
                r.get("Cliente") or "",
                r.get("SED") or "",
                r.get("EA"),
                r.get("Pot"),
                r.get("LoadID_CYMDIST") or r.get("LoadID") or "",
                "SI" if r.get("Match_CI") else "NO",
                "SI" if r.get("Match_SED") else "NO",
                r.get("Generador") or "",
                r.get("Concesion") or "",
                r.get("Cliente_CI") or "",
                r.get("Codigo_CL") or "",
            ]
            for col, v in enumerate(vals, 1):
                cell = ws.cell(row=i, column=col, value=v)
                cell.border = thin
                if incluir == "NO":
                    cell.fill = PatternFill("solid", fgColor="F3F4F6")
        from openpyxl.utils import get_column_letter
        widths = [10, 14, 10, 14, 28, 12, 12, 12, 28, 6, 10, 12, 12, 20, 12]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        feeder = s.get("feeder_id") or "feeder"
        feeds = body.get("feeders") or []
        if feeds:
            feeder = "_".join(str(x) for x in feeds[:3])
        ci = (body.get("clientes_file") or "").strip()
        stamp = re.sub(r"[^\w\-]+", "_", (ci or "clientes").replace(".xlsb", "").replace(".xlsx", ""))[:40]
        fname = "clientes_%s_%s.xlsx" % (feeder, stamp)

        # También guardar copia en output del alimentador
        try:
            out_path = output_path(s, "clientes", fname)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(buf.getvalue())
            buf.seek(0)
        except Exception:
            pass

        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=fname,
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/clientes/aplicar", methods=["POST"])
def api_clientes_aplicar():
    """3.2 · Solo carga EA/Pot en CYMDIST desde la tabla ya armada (3.1).

    No vuelve a cruzar NIS salvo que no exista tabla guardada o body.rebuild=true.
    """
    body = request.get_json(force=True) or {}
    s, feeder, feeders, all_feeders = _settings_for_clientes(body)
    ci = (body.get("clientes_file") or "").strip()
    rebuild = bool(body.get("rebuild") or body.get("force_rebuild") or body.get("rearmar"))
    try:
        if not all_feeders and not feeders and not feeder:
            return jsonify({"ok": False, "error": "Seleccione al menos un alimentador (RADIAL)."})

        json_path = output_path(s, "clientes", "clientes_alimentador.json")
        rows = None
        meta = {}
        if not rebuild:
            rows = load_saved_clientes_rows(json_path)
            if rows:
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        meta = json.load(f).get("meta") or {}
                except Exception:
                    meta = {}
                # Si la tabla guardada es de otro radial, no usarla
                prev_fid = str(meta.get("feeder_id") or "").strip().upper()
                cur_fid = str(s.get("feeder_id") or feeder or "").strip().upper()
                if prev_fid and cur_fid and prev_fid != cur_fid:
                    rows = None
                    meta = {}

        if not rows:
            if not ci:
                return jsonify({
                    "ok": False,
                    "error": (
                        "No hay tabla cruzada guardada. Ejecute primero 3.1 · Armar tabla "
                        "(o seleccione clientesimportantes para reconstruir)."
                    ),
                    "disponibles": list_clientes_importantes_files(s),
                })
            rows, meta = build_feeder_clientes_table(
                s,
                feeder,
                clientes_file=ci,
                suministro_file=body.get("suministro_file") or None,
                all_feeders=all_feeders,
                feeders=feeders,
            )
            # Preferir inventario en disco (96); solo abrir CYMDIST si falta JSON
            loads = _loads_for_feeders(
                feeders or [s.get("feeder_id")],
                open_cymdist=False,
            )
            if not loads:
                loads = _loads_for_feeders(
                    feeders or [s.get("feeder_id")],
                    open_cymdist=True,
                )
            rows = attach_cymdist_loads(rows, loads, primary_only=True)
            meta["n_loads_inventory"] = len(loads or [])
            meta["loads_feeder_id"] = s.get("feeder_id")
        else:
            meta = dict(meta or {})
            meta["from_saved_table"] = True

        # Solo clientes importantes (EA); quitar inventario SpotLoad mezclado
        from core.clientes_suministro import clientes_importantes_rows
        ci_only = clientes_importantes_rows(rows)
        if ci_only:
            rows = ci_only

        rows = merge_activo(
            rows,
            activo_map=body.get("activo"),
            previous_rows=load_saved_clientes_rows(json_path) if rebuild else rows,
        )
        rows = ensure_activo(rows, default=True)
        rows = merge_restar_cabecera(
            rows,
            restar_map=body.get("restar_cabecera"),
            previous_rows=load_saved_clientes_rows(json_path) if rebuild else rows,
        )
        rows = ensure_restar_cabecera(rows, default=False)
        meta["n_match_sed"] = sum(1 for r in rows if r.get("Match_SED"))
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        meta["n_restar_cabecera"] = sum(
            1 for r in rows if (not r.get("Activo")) and r.get("RestarCabecera")
        )
        meta["feeder_id"] = s.get("feeder_id")
        meta["n_rows"] = len(rows)
        meta["n_con_ea_pot"] = sum(
            1 for r in rows if r.get("EA") not in (None, "") and r.get("Pot") not in (None, "")
        )
        save_table_json(json_path, rows, meta)
        save_table_csv(output_path(s, "clientes", "clientes_alimentador.csv"), rows)

        if s.get("dry_run"):
            return jsonify({
                "ok": True, "dry_run": True, "rows": rows,
                "ok_count": 0, "excluido_count": meta["n_excluidos"], "total": len(rows),
            })

        api = load_json("config/cympy_api_map.json")
        from core.cymdist_com import (
            pause_cymdist_for_cympy, open_cymdist_gui, is_keep_open, set_keep_open,
        )
        from core.common import write_csv
        was_open = is_keep_open(s)
        pause_cymdist_for_cympy(s)

        # Escritura: no SaveProject BD (estudios multi-red cuelgan la UI)
        s_write = dict(s)
        s_write["skip_db_project_save"] = True
        c = require_cympy(s_write)
        a = CymPyAdapter(c, api, s_write)
        a.open_study(force_backup=False)
        fp = float(body.get("fp") or 0.95)
        # Anti-saturación: liberar CI previos fuera de la tabla, luego escribir EA/Pot
        from pipeline.apply_clientes_to_cymdist import (
            previous_applied_load_ids,
            refresh_clientes_in_cymdist,
        )
        prev_ids = previous_applied_load_ids(s)
        report, released, keep_ids = refresh_clientes_in_cymdist(
            a, rows, fp=fp, previous_ids=prev_ids
        )
        if s.get("save_after_write", True):
            try:
                a.save_study()
            except Exception as ex_save:
                print("AVISO save post EA/Pot:", ex_save)
        # Ajuste cabecera en SESION (sin SetDemand aqui: evita crash Cyme tras
        # muchas escrituras). SetDemand con P ajustado lo hace 3.3.
        cab_adj = {"skipped": True, "reason": "pending"}
        try:
            from pipeline.run_demand_allocation import (
                load_session, save_session, adjust_cabecera_for_excluidas,
            )
            cab_adj = adjust_cabecera_for_excluidas(
                s, rows, cympy=None, write_cymdist=False
            )
            print("[3.2] cabecera vs excluidas (sesion):", cab_adj.get("msg") or cab_adj)
        except Exception as ex_cab:
            print("AVISO ajuste cabecera excluidas 3.2:", ex_cab)
            cab_adj = {"ok": False, "skipped": True, "error": str(ex_cab)}

        # Invalidar sello de locks 3.3: al recargar EA/Pot hay que
        # reafirmar Locked/Unlocked en la proxima distribucion.
        try:
            from pipeline.run_demand_allocation import load_session, save_session
            sess32 = load_session(s)
            sess32["alloc_locks_ready"] = False
            sess32.pop("alloc_locks_fixed_key", None)
            sess32["ea_pot_loaded_at"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
            sess32["ea_pot_n_keep"] = len(keep_ids or [])
            sess32["ea_pot_n_liberados"] = int((released or {}).get("n_liberados") or 0)
            save_session(s, sess32)
        except Exception as ex_sess:
            print("AVISO session post 3.2:", ex_sess)
        try:
            a.close_study(save=False)
        except Exception:
            pass
        # Liberar COM antes de reabrir GUI (Access Violation si se solapan)
        try:
            import time as _t
            _t.sleep(1.2)
        except Exception:
            pass
        try:
            import gc
            del a
            del c
            gc.collect()
        except Exception:
            pass

        ok_count = sum(1 for r in report if r.get("Estado") == "OK")
        warn_kwh = sum(1 for r in report if r.get("Estado") == "WARN_KWH")
        excluido_count = sum(1 for r in report if r.get("Estado") == "EXCLUIDO")
        sin_sed = sum(1 for r in report if r.get("Estado") == "SIN_SED")
        kwh_verified = sum(1 for r in report if r.get("KWH_ok") is True)
        n_liberados = int((released or {}).get("n_liberados") or 0)
        report_path = output_path(s, "clientes", "apply_cymdist_report.csv")
        try:
            write_csv(
                report_path, report,
                ["Suministro", "Cliente", "SED", "LoadID", "EA", "Pot",
                 "KWH_antes", "KWH_despues", "KWH_ok", "Estado", "Activo",
                 "Detalle", "ConnectionStatus"],
            )
        except Exception as ex_rep:
            print("AVISO report EA/Pot:", ex_rep)
            report_path = None

        # Reabrir GUI con calma (sin kill agresivo: pause ya cerró Cyme)
        open_gui = True if body.get("open_gui") is None else bool(body.get("open_gui"))
        com = {"ok": True, "cymdist_open": False, "deferred": True}
        if open_gui:
            set_keep_open(s, True, reason="cargar_ea_pot")
            try:
                import threading
                import time as _time

                def _open_gui():
                    try:
                        _time.sleep(1.5)
                        # kill_existing=False: Cyme ya no debe estar; evita doble kill+OpenStudy
                        open_cymdist_gui(s, kill_existing=False, reason="cargar_ea_pot")
                    except Exception as ex_gui:
                        print("AVISO open_cymdist_gui diferido:", ex_gui)
                threading.Thread(target=_open_gui, name="open_cyme_ea_pot", daemon=True).start()
                com = {
                    "ok": True,
                    "cymdist_open": True,
                    "deferred": True,
                    "was_open": was_open,
                }
            except Exception as ex_th:
                com = {"ok": False, "error": str(ex_th)}
        else:
            set_keep_open(s, was_open, reason="cargar_ea_pot_keep")

        msg32 = (
            "3.2 OK · EA→Consumo(KWH) %d · excluidas %d · sin SED %d · KWH verificado %d"
            % (ok_count, excluido_count, sin_sed, kwh_verified)
        )
        if n_liberados:
            msg32 += " · liberados previos %d (anti-saturación)" % n_liberados
        if warn_kwh:
            msg32 += " · WARN KWH %d" % warn_kwh
        if cab_adj and not cab_adj.get("skipped"):
            msg32 += " · " + str(cab_adj.get("msg") or "")
        elif cab_adj and cab_adj.get("reason") == "sin_cabecera_medicion":
            msg32 += " · AVISO: sin cabecera §1, no se restó Pot de excluidas"

        return jsonify({
            "ok": True,
            "ok_count": ok_count,
            "warn_kwh_count": warn_kwh,
            "excluido_count": excluido_count,
            "sin_sed_count": sin_sed,
            "kwh_verified": kwh_verified,
            "n_liberados": n_liberados,
            "released": released,
            "total": len(rows),
            "rows": rows,
            "report": report,
            "report_path": report_path,
            "from_saved_table": bool(meta.get("from_saved_table")),
            "cymdist_open": bool(com.get("cymdist_open")),
            "cabecera_ajustada": cab_adj,
            "P_kW": (cab_adj or {}).get("P_kW"),
            "Q_kvar": (cab_adj or {}).get("Q_kvar"),
            "P_kW_medicion": (cab_adj or {}).get("P_kW_medicion"),
            "P_kW_excluidas_restadas": (cab_adj or {}).get("P_kW_excluidas_restadas"),
            "msg": msg32,
            "cymdist": com,
        })
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/distribucion", methods=["POST"])
def api_distribucion():
    """3.3 · Solo LoadAllocation.Run (API CYMDIST). Cabecera §1 + fijos de 3.2."""
    s = _settings()
    body = request.get_json(silent=True) or {}

    def _run():
        if s.get("dry_run"):
            return {"ok": True, "dry_run": True}
        from pipeline.run_demand_allocation import seed_session_from_excel, run_load_allocation_module
        sess = seed_session_from_excel(s)
        if sess.get("P_kW") in (None, ""):
            return {"ok": False, "error": "Defina y guarde la demanda de cabecera (seccion 1)."}
        result = run_load_allocation_module(
            s,
            sess,
            activo_map=body.get("activo"),
            restar_map=body.get("restar_cabecera"),
        )
        summary = {k: result[k] for k in result if k not in ("scaled", "applied")}
        summary["n_scaled"] = len(result.get("scaled") or [])
        summary["n_applied"] = len(result.get("applied") or [])
        val = result.get("validation") or {}
        if isinstance(val, dict) and val:
            summary["validation"] = {
                "ok": val.get("ok"),
                "msg": val.get("msg") or val.get("error"),
                "n_ok": val.get("n_ok"),
                "n_warn": val.get("n_warn"),
                "n_fail": val.get("n_fail"),
                "n_zero_fixed": val.get("n_zero_fixed"),
                "n_zero_residual": val.get("n_zero_residual"),
                "sum_kw": val.get("sum_kw"),
                "balance_ok": val.get("balance_ok"),
                "balance_msg": val.get("balance_msg"),
                "fails": [r for r in (val.get("rows") or []) if r.get("Estado") == "FAIL"][:30],
            }
        ok = result.get("status") in (
            "ok", "ok_fallback_kwh", "ok_with_warnings", "ok_validation_fail", "dry_run"
        )
        return {
            "ok": ok,
            "result": summary,
            "validation_ok": result.get("validation_ok"),
            "error": None if ok else (result.get("fallback_error") or result.get("allocation_error")),
            "msg": (
                "LoadAllocation.Run · " + str((val or {}).get("msg") or "validacion pendiente")
                if ok else None
            ),
        }

    return _cympy_run("distribucion", _run)


@app.route("/api/flujo", methods=["POST"])
def api_flujo():
    """LoadFlow independiente: situacional (desconecta §3) | proyectado (conecta §3).
    update_informe=true (default) rellena §5 tras el flujo."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    scenario = (body.get("scenario") or "").strip().lower() or None
    update_informe = body.get("update_informe", True)

    def _run():
        result = run_load_flow(s, scenario=scenario)
        ok = result.get("status") in ("ok", "dry_run")
        informe = None
        if ok and update_informe:
            try:
                informe = fill_informe(s, overwrite_copy=True)
            except Exception as ex_inf:
                informe = {"ok": False, "error": str(ex_inf)}
        return {
            "ok": ok,
            "result": result,
            "error": None if ok else (result.get("error") or "LoadFlow fallo"),
            "ayuda": result.get("ayuda"),
            "engine": result.get("engine"),
            "informe": informe,
            "paths": {
                "saved_to": result.get("saved_to"),
                "saved_scenario_to": result.get("saved_scenario_to"),
            },
        }

    return _cympy_run("flujo_%s" % (scenario or "general"), _run)

@app.route("/api/informe/rutas")
def api_informe_rutas():
    s = _settings()
    try:
        paths = informe_paths(s)
        out_base = s.get("output_dir") or os.path.join("data", "output", "feeders", str(s.get("feeder_id") or "feeder"))
        if not os.path.isabs(out_base):
            from core.common import p as _p
            img = _p(*(out_base.replace("\\", "/").split("/") + ["informe_images"]))
        else:
            img = os.path.join(out_base, "informe_images")
        paths["images_dir"] = img
        return jsonify({"ok": True, "paths": paths})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/informe/status")
def api_informe_status():
    """Checklist de entrega (LF sit/proy + OCR + 4 PNG) sin rellenar doc."""
    s = _settings()
    try:
        return jsonify(delivery_status(s))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/informe/capturas", methods=["POST"])
def api_informe_capturas():
    """
    Captura viva CYMDIST (API): LoadFlow situacional/proyectado + coloreo
    VoltageLevel/LoadingLevel + ExportActiveView/GUI → 4 PNG del informe.
    Body: {force: bool, open_gui: bool, scenarios: null|'situacional'|'proyectado'}
    """
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        from pipeline.capture_informe_color_views import capture_informe_color_views
        force = bool(body.get("force", True))
        open_gui = body.get("open_gui")
        if open_gui is None:
            open_gui = True
        scenarios = body.get("scenarios")
        res = capture_informe_color_views(
            settings=s,
            scenarios=scenarios,
            open_gui=bool(open_gui),
            force=force,
        )
        return jsonify(res)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/armar", methods=["POST"])
def api_informe_armar():
    """Copia plantillas a doc/ y rellena valores desde LoadFlow (fill=true por defecto).
    Con fill=true aplica gate de entrega (ambos LF + OCR + 4 PNG).
    Integra capturas CYMDIST API (estado actual / con proyecto) por defecto."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    do_fill = body.get("fill", True)
    # Permitir forzar recaptura desde UI
    if body.get("force_captures"):
        s = dict(s)
        s["force_cymdist_captures"] = True
        s["informe_auto_cymdist_capture"] = True
    try:
        if do_fill:
            manifest = fill_informe(s, overwrite_copy=True, require_delivery=True)
        else:
            manifest = assemble_informe(s, overwrite=True)
        return jsonify(manifest)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/preview")
def api_informe_preview():
    """Vista preliminar del informe creado (meta + métricas + gráficas) antes de cerrar."""
    s = _settings()
    try:
        return jsonify(build_informe_preview(s))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/mapa_ubicacion", methods=["POST"])
def api_informe_mapa_ubicacion():
    """Regenera topologia.png = mapa satelite de la carga nueva (nodo de conexion)."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        from pipeline.generate_location_map import generate_location_map
        res = generate_location_map(s, force=True)
        return jsonify(res)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/cerrar", methods=["POST"])
def api_informe_cerrar():
    """Confirma/cierra entrega solo tras validar la vista preliminar."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    if not body.get("validated"):
        return jsonify({
            "ok": False,
            "error": "Marque que validó la vista preliminar antes de cerrar la entrega.",
        })
    try:
        return jsonify(confirm_informe_entrega(
            s,
            note=body.get("note") or "",
            force=bool(body.get("force")),
        ))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/imagen/<name>")
def api_informe_imagen(name):
    """Sirve PNG de gráficas del informe (vista preliminar)."""
    s = _settings()
    try:
        safe = os.path.basename(name or "")
        if not safe.lower().endswith(".png") or ".." in safe:
            return jsonify({"ok": False, "error": "Imagen no permitida"}), 400
        from pipeline.fill_informe import _images_dir
        path = os.path.join(_images_dir(s), safe)
        if not os.path.isfile(path):
            return jsonify({"ok": False, "error": "No existe: %s" % safe}), 404
        return send_file(path, mimetype="image/png")
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/api/informe/archivo/<kind>")
def api_informe_archivo(kind):
    """Descarga informe.docx, justificacion.xlsx o informe.pdf rellenados."""
    s = _settings()
    try:
        paths = informe_paths(s)
        key = (kind or "").strip().lower()
        if key in ("informe", "docx", "word"):
            path = paths.get("informe_doc")
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            download = "informe.docx"
        elif key in ("justificacion", "xlsx", "excel"):
            path = paths.get("justificacion_doc")
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            download = "justificacion.xlsx"
        elif key in ("pdf", "informe_pdf"):
            path = os.path.join(paths.get("doc_dir") or "", "informe.pdf")
            mime = "application/pdf"
            download = "informe.pdf"
        else:
            return jsonify({"ok": False, "error": "kind=informe|justificacion|pdf"}), 400
        if not path or not os.path.isfile(path):
            return jsonify({"ok": False, "error": "Archivo no generado. Rellene informes primero."}), 404
        return send_file(path, mimetype=mime, as_attachment=True, download_name=download)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/api/informe/pagina/<name>")
def api_informe_pagina(name):
    """Sirve JPEG de pagina renderizada (doc/informe_preview/)."""
    s = _settings()
    try:
        safe = os.path.basename(name or "")
        if not safe or ".." in safe:
            return jsonify({"ok": False, "error": "nombre invalido"}), 400
        paths = informe_paths(s)
        path = os.path.join(paths.get("doc_dir") or "", "informe_preview", safe)
        if not os.path.isfile(path):
            return jsonify({"ok": False, "error": "No existe: %s" % safe}), 404
        mime = "image/jpeg" if safe.lower().endswith((".jpg", ".jpeg")) else "image/png"
        return send_file(path, mimetype=mime)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/api/informe/meta", methods=["GET", "POST"])
def api_informe_meta():
    s = _settings()
    try:
        if request.method == "GET":
            meta = load_informe_meta(s) or {}
            return jsonify({
                "ok": True,
                "meta": meta,
                "complete": meta_is_complete(meta),
                "path": output_path(s, "demand", "informe_meta.json"),
            })
        body = request.get_json(silent=True) or {}
        existing = load_informe_meta(s) or {}
        existing.update(body)
        existing["source"] = existing.get("source") or "manual_ui"
        if existing.get("potencia_kw") is not None and not existing.get("potencia_txt"):
            try:
                existing["potencia_txt"] = "%dKW" % int(round(float(existing["potencia_kw"])))
            except Exception:
                pass
        path = save_informe_meta(s, existing)
        return jsonify({
            "ok": True,
            "meta": existing,
            "complete": meta_is_complete(existing),
            "path": path,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/informe/meta_pdf", methods=["POST"])
def api_informe_meta_pdf():
    """Upload PDF → OCR/texto → informe_meta.json."""
    s = _settings()
    try:
        # SPA y clientes pueden enviar "pdf" o "file"
        f = request.files.get("pdf") or request.files.get("file")
        if f is None or not f.filename:
            return jsonify({
                "ok": False,
                "error": "Adjunte un archivo PDF (campo pdf).",
            })
        dest_dir = os.path.dirname(output_path(s, "demand", "informe_meta.json"))
        mkdir(dest_dir)
        safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(f.filename)) or "solicitud.pdf"
        if not safe.lower().endswith(".pdf"):
            safe = safe + ".pdf"
        dest = os.path.join(dest_dir, "solicitud_meta_" + safe)
        f.save(dest)
        res = extract_informe_meta_from_pdf(dest, s, save=True)
        return jsonify(res)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/nodos/inventario", methods=["POST"])
def api_nodos_inventario():
    s = _settings()
    body = request.get_json(force=True) or {}
    try:
        refresh = bool(body.get("refresh"))
        topo, path = get_topology(s, refresh=refresh)
        _NODE_CACHE["feeder"] = s.get("feeder_id")
        _NODE_CACHE["topo"] = topo
        return jsonify({
            "ok": True,
            "n_nodes": len(topo.get("nodes") or []),
            "n_sections": len(topo.get("sections") or []),
            "path": path,
            "refreshed": refresh,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/nodos/buscar")
def api_nodos_buscar():
    s = _settings()
    q = request.args.get("q") or ""
    limit = int(request.args.get("limit") or 80)
    try:
        # Sin botón inventario: si no hay cache, search_nodes lo genera
        nodes = search_nodes(s, query=q, limit=limit, refresh=False)
        return jsonify({"ok": True, "nodes": nodes, "q": q})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/nodos/resolver", methods=["POST"])
def api_nodos_resolver():
    s = _settings()
    body = request.get_json(force=True) or {}
    try:
        topo, _ = get_topology(s, refresh=False)
        if not (topo.get("nodes") or []):
            topo, _ = get_topology(s, refresh=True)
        resolved = resolve_connection(
            topo,
            body.get("node_id"),
            _existing_load_ids(s),
            load_name=body.get("load_name") or body.get("nombre") or body.get("Nombre"),
        )
        return jsonify({"ok": True, **resolved})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/cargas/conectadas", methods=["GET"])
def api_cargas_conectadas():
    """Cargas §4 guardadas (4.2 o 4.3). §5 las usa sin repetir conexión."""
    s = _settings()
    try:
        rows = list_connected_spot_loads(s)
        return jsonify({
            "ok": True,
            "n": len(rows),
            "rows": rows,
            "msg": (
                "%s carga(s) §4 en estudio — listas para §5"
                % len(rows)
            ) if rows else "Sin cargas §4 aún (use 4.2 o 4.3).",
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/cargas/nueva", methods=["POST"])
def api_cargas_nueva():
    """SpotLoad concentrada: guarda en estudio + figura ubicación. §5 independiente."""
    s = _settings()
    body = request.get_json(force=True) or {}
    node_id = (body.get("node_id") or body.get("NodeID") or "").strip()
    if not node_id:
        return jsonify({"ok": False, "error": "Seleccione un nodo."})
    load_name = (
        body.get("load_name") or body.get("nombre") or body.get("Nombre") or ""
    ).strip()
    if not load_name:
        return jsonify({
            "ok": False,
            "error": "Indique el nombre de la carga concentrada (aparecerá dibujado en CYMDIST).",
        })
    try:
        import time as _time
        compute_pq(body.get("mode"), body.get("P_kW"), body.get("Q_kvar"), body.get("cosfi"))
        result = connect_spot_load(
            s,
            node_id,
            body.get("mode") or "KW_COSFI",
            body.get("P_kW"),
            q_kvar=body.get("Q_kvar"),
            cosfi=body.get("cosfi"),
            refresh_topo=False,
            lock=True,
            load_name=load_name,
            recreate=True,
        )
        report = append_report(s, result)
        result["report"] = report
        result["saved_for_simulations"] = True
        try:
            map_res = attach_location_map(s, result)
            if map_res.get("ok"):
                result["location_map_url"] = (
                    "/api/informe/imagen/topologia.png?t=%d" % int(_time.time())
                )
        except Exception as ex:
            result["location_map"] = {"ok": False, "error": str(ex)}
        _invalidate_caches()
        if result.get("LoadID"):
            try:
                inv = output_path(s, "inventory", "loads.json")
                loads = []
                if os.path.isfile(inv):
                    with open(inv, "r", encoding="utf-8") as f:
                        loads = json.load(f).get("loads") or []
                loads = [r for r in loads if str(r.get("LoadID")) != str(result.get("LoadID"))]
                loads.append({
                    "LoadID": result.get("LoadID"),
                    "Tipo": "SpotLoad",
                    "SectionID": result.get("SectionID"),
                    "NodeID": result.get("NodeID"),
                    "kW": str(result.get("P_kW")),
                    "kvar": str(result.get("Q_kvar")),
                    "LoadValueType": "LoadValueKW_KVAR",
                    "ZoneID": "",
                    "Label": "%s (SpotLoad)" % result.get("LoadID"),
                })
                os.makedirs(os.path.dirname(inv), exist_ok=True)
                with open(inv, "w", encoding="utf-8") as f:
                    json.dump(
                        {"feeder_id": s["feeder_id"], "network_id": s.get("network_id"), "loads": loads},
                        f, indent=2, ensure_ascii=False,
                    )
            except Exception:
                pass
        return jsonify({"ok": True, "result": result})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cargas/plantilla", methods=["GET"])
def api_cargas_plantilla():
    """Descarga plantilla CSV o Excel para SpotLoad en bloque."""
    s = _settings()
    fmt = (request.args.get("fmt") or request.args.get("format") or "xlsx").lower().strip()
    feeder = (s.get("feeder_id") or "feeder").strip() or "feeder"
    try:
        if fmt in ("csv", "txt"):
            data = build_batch_template_csv()
            fname = "spotload_lote_%s.csv" % feeder
            return send_file(
                io.BytesIO(data),
                mimetype="text/csv; charset=utf-8",
                as_attachment=True,
                download_name=fname,
            )
        data = build_batch_template_xlsx()
        fname = "spotload_lote_%s.xlsx" % feeder
        return send_file(
            io.BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=fname,
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cargas/pendientes", methods=["GET"])
def api_cargas_pendientes():
    """Lista SpotLoad §4 fallidas / pendientes de actualizar."""
    s = _settings()
    try:
        rows = list_pending_spot_loads(s)
        return jsonify({"ok": True, "n": len(rows), "rows": rows})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cargas/lote/preview", methods=["POST"])
def api_cargas_lote_preview():
    """Sube CSV/Excel y devuelve filas validadas (sin escribir CYMDIST)."""
    s = _settings()
    try:
        rows = []
        f = request.files.get("file") or request.files.get("csv") or request.files.get("excel")
        if f and f.filename:
            raw = f.read()
            rows = parse_batch_file(raw, filename=f.filename or "")
        else:
            body = request.get_json(force=True, silent=True) or {}
            if body.get("rows"):
                rows = [normalize_batch_row(r, i) for i, r in enumerate(body.get("rows") or [])]
            else:
                return jsonify({"ok": False, "error": "Adjunte un CSV/Excel o envíe rows[]."})
        n_ok = sum(1 for r in rows if r.get("ok"))
        return jsonify({
            "ok": True,
            "feeder_id": s.get("feeder_id"),
            "n": len(rows),
            "n_ok": n_ok,
            "n_error": len(rows) - n_ok,
            "rows": rows,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cargas/lote/conectar", methods=["POST"])
def api_cargas_lote_conectar():
    """Conecta en bloque; guarda estudio + figura ubicación. Independiente de 4.2 unitaria."""
    s = _settings()
    try:
        import time as _time
        rows = []
        f = request.files.get("file") or request.files.get("csv") or request.files.get("excel")
        if f and f.filename:
            raw = f.read()
            rows = parse_batch_file(raw, filename=f.filename or "")
        else:
            body = request.get_json(force=True, silent=True) or {}
            if body.get("rows"):
                rows = [normalize_batch_row(r, i) for i, r in enumerate(body.get("rows") or [])]
            else:
                return jsonify({"ok": False, "error": "Adjunte un CSV/Excel o envíe rows[]."})
        result = connect_spot_loads_bulk(s, rows, open_gui=True)
        result["saved_for_simulations"] = bool(result.get("n_ok"))
        if (result.get("location_map") or {}).get("ok"):
            result["location_map_url"] = (
                "/api/informe/imagen/topologia.png?t=%d" % int(_time.time())
            )
        _invalidate_caches()
        return jsonify({"ok": bool(result.get("ok")), **result})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


# —— §6 Optimización / §7 Suite (vinculación pipeline → UI) ——

_OPT_MAP = {
    "reclosers": ("optimal_recloser", "Ejecutar_Opt_Recloser"),
    "regulators": ("optimal_regulator", "Ejecutar_Opt_Regulador"),
    "capacitors": ("optimal_capacitor", "Ejecutar_Opt_Capacitor"),
}


@app.route("/api/optimizacion/<kind>", methods=["POST"])
def api_optimizacion(kind):
    s = _settings()
    body = request.get_json(silent=True) or {}
    key = (kind or "").strip().lower()
    if key not in _OPT_MAP:
        return jsonify({"ok": False, "error": "Tipo desconocido. Use reclosers|regulators|capacitors."})
    cmd, flag = _OPT_MAP[key]
    try:
        # Import relativo al paquete optimization (sys.path incluye src)
        import sys as _sys
        opt_dir = os.path.join(ROOT, "src", "optimization")
        if opt_dir not in _sys.path:
            _sys.path.insert(0, opt_dir)
        from common_opt import run_opt
        result = run_opt(cmd, flag, settings=s, force=bool(body.get("force")))
        return jsonify(result)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex), "command": cmd})


@app.route("/api/suite/entorno")
def api_suite_entorno():
    s = _settings()
    try:
        from core.common import resolve_python
        from core.feeder_context import list_study_files
        cyme = s.get("cyme_root") or ""
        mdb = s.get("database_mdb") or ""
        study = s.get("study_path") or ""
        info = {
            "ok": True,
            "utility": s.get("utility_name"),
            "feeder_id": s.get("feeder_id"),
            "feeders": list_feeders(),
            "studies_root": s.get("studies_root"),
            "projects_dir": s.get("projects_dir"),
            "database_mdb": mdb,
            "mdb_exists": os.path.isfile(mdb) if mdb else False,
            "study_path": study,
            "study_exists": os.path.isfile(study) if study else False,
            "cyme_root": cyme,
            "cyme_exists": os.path.isdir(cyme) if cyme else False,
            "python_exe": resolve_python(s),
            "dry_run": s.get("dry_run"),
            "n_studies": len(list_study_files(s) or []),
        }
        cympy_ok = False
        cympy_ver = None
        try:
            c = require_cympy(s)
            cympy_ok = True
            cympy_ver = getattr(c, "version", str(c))
        except Exception as ex:
            info["cympy_error"] = str(ex)
        info["cympy_ok"] = cympy_ok
        info["cympy_version"] = cympy_ver
        info["ok"] = bool(info["cyme_exists"] and info["mdb_exists"] and cympy_ok)
        info["msg"] = "Entorno OK" if info["ok"] else "Entorno incompleto (revise CYME/MDB/CymPy)"
        return jsonify(info)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/conexion", methods=["POST"])
def api_suite_conexion():
    s = _settings()
    try:
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        db_ok = False
        study_ok = False
        if s.get("database_mdb") and os.path.isfile(s["database_mdb"]):
            a.connect_database()
            db_ok = True
        if s.get("study_path") and os.path.isfile(s["study_path"]):
            a.open_study(connect_db=False)
            study_ok = True
            try:
                a.close_study(save=False)
            except Exception:
                pass
        ok = db_ok or study_ok
        return jsonify({
            "ok": ok,
            "cympy_version": getattr(c, "version", "?"),
            "database_connected": db_ok,
            "study_opened": study_ok,
            "study_path": s.get("study_path"),
            "msg": "Conexión Electro Dunas OK" if study_ok else (
                "API OK (BD) pero falta study_path/.zxst" if db_ok else "Sin BD ni estudio"
            ),
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/validar_entradas", methods=["POST"])
def api_suite_validar_entradas():
    s = _settings()
    try:
        import io
        from pipeline import validate_inputs as vi
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            # validate_inputs.main usa load_settings vía env/argv
            os.environ["RECYM_FEEDER"] = str(s.get("feeder_id") or "")
            vi.main()
        finally:
            sys.stdout = old
        log = buf.getvalue()
        return jsonify({"ok": True, "msg": "Validación ejecutada", "log": log[-4000:], "feeder_id": s.get("feeder_id")})
    except SystemExit as se:
        return jsonify({"ok": int(getattr(se, "code", 1) or 0) == 0, "error": str(se), "feeder_id": s.get("feeder_id")})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/inventario_cargas", methods=["POST"])
def api_suite_inventario_cargas():
    """Inventario SpotLoad de TODO el sistema (~96 alimentadores) vía ELD/BD.

    body.system=false + feeder → solo ese alimentador (legado).
    Por defecto: sistema completo.
    """
    body = request.get_json(silent=True) or {}
    s = _settings()
    only_feeder = (body.get("feeder") or "").strip().upper()
    do_system = body.get("system", True)
    if only_feeder and body.get("system") is False:
        do_system = False

    def _run():
        from pipeline.inventory_loads import inventory_system_loads, save_feeder_loads, collect_loads
        from core.cymdist_com import pause_cymdist_for_cympy

        _LOAD_CACHE["feeder"] = None
        _LOAD_CACHE["loads"] = []
        pause_cymdist_for_cympy(s)

        if not do_system:
            fs = load_settings(feeder_id=only_feeder or s.get("feeder_id"), synthesize=True)
            inv = output_path(fs, "inventory", "loads.json")
            _safe_remove(inv)
            loads = _loads(fs, open_cymdist=True)
            return {
                "ok": True,
                "system": False,
                "n_loads": len(loads or []),
                "n_feeders": 1,
                "path": inv,
                "feeder_id": fs.get("feeder_id"),
                "msg": "%d cargas · %s" % (len(loads or []), fs.get("feeder_id")),
            }

        res = inventory_system_loads(
            s,
            study_path=body.get("study_path") or s.get("eld_study_path"),
            limit=int(body.get("limit") or 0),
            network_ids=body.get("network_ids"),
        )
        # invalidar caché para que Armar tabla lea los JSON nuevos
        _LOAD_CACHE["feeder"] = None
        _LOAD_CACHE["loads"] = []
        res["system"] = True
        res["msg"] = (
            "Inventario sistema: %s alimentadores · %s SpotLoad · %.0fs"
            % (
                res.get("n_feeders_ok"),
                res.get("n_loads_total"),
                float(res.get("elapsed_sec") or 0),
            )
        )
        return res

    # Operación larga: timeout alto en el lock
    return _cympy_run("inventario_cargas_sistema", _run, timeout_sec=2.0)

@app.route("/api/suite/sync_equipos", methods=["POST"])
def api_suite_sync_equipos():
    s = _settings()
    try:
        import io
        from pipeline import sync_equipment_from_excel as sync_mod
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(s)
        os.environ["RECYM_FEEDER"] = str(s.get("feeder_id") or "")
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            sync_mod.main()
        finally:
            sys.stdout = old
        return jsonify({
            "ok": True,
            "msg": "Sync equipos Excel→CYMDIST OK",
            "feeder_id": s.get("feeder_id"),
            "log": buf.getvalue()[-4000:],
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/fix_default", methods=["POST"])
def api_suite_fix_default():
    s = _settings()
    try:
        from pipeline.fix_default_aaac_xlpe import main as fix_main
        from core.cymdist_com import pause_cymdist_for_cympy
        import core.cympy_adapter as ca
        pause_cymdist_for_cympy(s)
        # fix_default hace ConnectDatabaseByName limpio: hay que cerrar estudio
        # reutilizado por otras rutas §7 (export/sync/pipeline) en el mismo proceso.
        try:
            api = load_json("config/cympy_api_map.json")
            c = require_cympy(s)
            a = CymPyAdapter(c, api, s)
            a.close_study(save=False)
            try:
                import cympy.db as db
                db.DisconnectDatabase()
            except Exception:
                pass
            ca._PROCESS_STUDY_PATH = None
            ca._PROCESS_DB_NAME = None
        except Exception as ex:
            print("AVISO pre-close fix_default:", ex)
        rc = fix_main([])
        return jsonify({
            "ok": rc == 0,
            "rc": rc,
            "msg": "DEFAULT AAAC/XLPE cerrados" if rc == 0 else ("fix_default rc=%s" % rc),
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/export_ascii", methods=["POST"])
def api_suite_export_ascii():
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        from pipeline.export_cymdist_ascii import export_ascii
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(s)
        out_dir = (body.get("out_dir") or "").strip() or os.path.join(
            s.get("studies_root") or ROOT, "exportarTXT"
        )
        prefix = (body.get("prefix") or "").strip() or ts_prefix()
        files = export_ascii(
            s,
            out_dir=out_dir,
            prefix=prefix,
            connection_name=body.get("connection") or None,
            study_path=body.get("study_path") or s.get("eld_study_path") or None,
        )
        return jsonify({
            "ok": True,
            "msg": "Export ASCII OK",
            "out_dir": out_dir,
            "prefix": prefix,
            "files": files,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


def ts_prefix():
    from datetime import datetime
    return datetime.now().strftime("%y%m%d")


@app.route("/api/suite/nuevo_alimentador", methods=["POST"])
def api_suite_nuevo_alimentador():
    body = request.get_json(silent=True) or {}
    fid = (body.get("feeder_id") or body.get("feeder") or "").strip().upper().replace(" ", "_")
    if not fid:
        return jsonify({"ok": False, "error": "Indique feeder_id."})
    try:
        from core.feeder_context import create_feeder_from_template
        import shutil
        path = create_feeder_from_template(
            fid,
            name=(body.get("name") or fid),
            network_id=(body.get("network_id") or ""),
            study_path=(body.get("study_path") or ""),
            voltage_kv=float(
                body.get("voltage_kv") or body.get("voltage_ll_kv") or 22.9
            ),
        )
        dest = os.path.join(ROOT, "data", "input", "feeders", fid)
        os.makedirs(dest, exist_ok=True)
        from_feeder = (body.get("from_feeder") or "").strip() or str(
            (load_json("config/settings.json") or {}).get("active_feeder") or ""
        ).strip()
        copied = []
        src = os.path.join(ROOT, "data", "input", "feeders", from_feeder) if from_feeder else ""
        if src and os.path.isdir(src):
            for fname in ("Control_Simulacion.xlsx", "Catalogo_Maestro.xlsx"):
                sfile = os.path.join(src, fname)
                dfile = os.path.join(dest, fname)
                if os.path.isfile(sfile) and not os.path.isfile(dfile):
                    shutil.copy2(sfile, dfile)
                    copied.append(dfile)
        return jsonify({
            "ok": True,
            "feeder_id": fid,
            "config": path,
            "input_dir": dest,
            "copied_excel": copied,
            "feeders": list_feeders(),
            "msg": "Alimentador %s creado" % fid,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/suite/pipeline", methods=["POST"])
def api_suite_pipeline():
    """Ejecuta run_all para el alimentador activo (batch)."""
    s = _settings()
    feeder = s.get("feeder_id")
    if not feeder:
        return jsonify({"ok": False, "error": "Sin alimentador activo."})
    try:
        import io
        from pipeline import run_all as ra
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = ra.run_one(feeder)
        finally:
            sys.stdout = old
        return jsonify({
            "ok": rc == 0,
            "rc": rc,
            "feeder_id": feeder,
            "msg": "PIPELINE OK" if rc == 0 else ("PIPELINE rc=%s" % rc),
            "log": buf.getvalue()[-6000:],
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/tablero")
def tablero_page():
    """Legado HTML. En SPA use GET /api/tablero (JSON) en el panel §2."""
    s = _settings()
    if SPA_MODE:
        try:
            from analysis.build_dashboard import main as build_tablero
            build_tablero()
        except Exception as ex:
            return jsonify({"ok": False, "error": str(ex)}), 500
        path = output_path(s, "diagnostics", "tablero.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["ok"] = True
            data["deprecated_html"] = True
            data["msg"] = "Use la SPA §2 · Calidad + Tablero (GET /api/tablero)."
            return jsonify(data)
        return jsonify({"ok": False, "error": "tablero.json no encontrado"}), 404
    try:
        from analysis.build_dashboard import main as build_tablero
        build_tablero()
    except Exception as ex:
        return "Error generando tablero: %s" % ex, 500
    path = output_path(s, "diagnostics", "tablero.html")
    if not os.path.isfile(path):
        return "Tablero no encontrado", 404
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def main():
    try:
        # Windows cp1252: evitar UnicodeEncodeError en print (flechas, etc.)
        import io
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        elif getattr(sys.stdout, "encoding", None) and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    port = int(os.environ.get("RECYM_UI_PORT") or "5055")
    try:
        s = load_settings()
        print("Alimentadores:", ", ".join(list_feeders()))
        print("Activo:", s.get("feeder_id"))
        print("DRY_RUN:", s.get("dry_run"))
        print("UI version:", UI_VERSION)
        print("Abriendo http://127.0.0.1:%s" % port)
    except Exception as ex:
        print("AVISO settings:", ex)
    # Waitress: más hilos para que ping/listas sigan vivos aunque 1–2 workers estén en COM.
    # channel_timeout NO aborta requests activas; el lock COM evita saturar todos los hilos.
    try:
        from waitress import serve
        n_threads = int(os.environ.get("RECYM_UI_THREADS") or "24")
        print("Servidor: waitress · threads=%s (light APIs no esperan COM)" % n_threads)
        serve(
            app,
            host="127.0.0.1",
            port=port,
            threads=n_threads,
            channel_timeout=120,
            connection_limit=200,
        )
    except Exception as ex:
        print("AVISO waitress no disponible (%s) — Flask threaded" % ex)
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()

