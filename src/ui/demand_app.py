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
    get_topology, append_report,
)
from pipeline.assemble_informe import assemble_informe, informe_paths
from pipeline.fill_informe import fill_informe, delivery_status
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
    merge_activo, load_saved_clientes_rows, ensure_activo,
    list_radiales_from_suministro,
)
from core.spot_load_new import compute_pq

UI_VERSION = "4.2"
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
table th.col-incluir{background:#ccfbf1;color:#115e59;min-width:72px;text-align:center}
table td.col-incluir{text-align:center;background:#f0fdfa}
table td.col-incluir input{width:18px;height:18px;cursor:pointer;accent-color:#0f766e}
tr.off-row{opacity:.55;background:#fafaf9}
</style>
</head>
<body>
<header>
  <h1>RECYM · Demanda y cargas CYMDIST <span class="badge" id="hdrBadge">v{{ ui_version }}</span></h1>
  <p>{{ utility }} · Alimentador <b>{{ feeder }}</b> · Red {{ network }}
     · UI v{{ ui_version }}
     · <a href="#panelEntrega">Entrega</a>
     · <a href="#panelCalidad">Calidad modelo</a>
     · <a href="/tablero" target="_blank">Tablero</a>
     {% if dry_run %}<span class="err"> · DRY_RUN activo</span>{% endif %}</p>
</header>
<main>
  <section class="panel">
    <h2>1. Máxima demanda de cabecera (medición)</h2>
    <p class="muted">Datos del <b>medidor / máxima demanda</b> en cabecera del alimentador.
      Al <b>Guardar medición</b> se escriben <b>solo estos P/Q</b> en CYMDIST
      (Propiedades de la red → Demanda → Conectado + Total, casilleros kW / kvar)
      y en la sesión RECYM. Eso <b>restablece §§2–4</b> (tabla clientes, distribución, carga nueva e informes de análisis):
      debe volver a cargar EA/Pot, distribuir, conectar carga y analizar.
      Obligatorios para la <b>distribución de carga</b> (§2, tras cargar EA/Pot).</p>
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
      El gate del alimentador activo queda <b>LISTO</b> con 0 Error/Warning/Hint + converge.
      Use <b>Diagnosticar sistema</b> para los ~96 alimentadores clasificados por tipo de error.</p>
    <ol class="steps">
      <li>Diagnosticar (feeder activo) o Diagnosticar sistema (todas las redes de la BD).</li>
      <li>Proponer → mapear cada código a acción (catálogo cymsg / manual).</li>
      <li>Aplicar → escribir correcciones en CYMDIST (feeder activo).</li>
      <li>Verificar convergencia → LoadFlow + IsValidResults (sin escenario §3).</li>
      <li>O usar el botón principal: cicla 1–4 hasta limpio (feeder activo).</li>
    </ol>
    <div class="actions">
      <button type="button" id="btnMqUntil" onclick="mqUntilClean()">▶ Ejecutar: corregir hasta limpio + converge</button>
      <button type="button" id="btnMqDiag" class="ghost" onclick="mqDiagnose()">Diagnosticar</button>
      <button type="button" id="btnMqDiagSys" class="secondary" onclick="mqDiagnoseSystem()">Diagnosticar sistema (96)</button>
      <button type="button" id="btnMqDiagEld" class="secondary" onclick="mqDiagnoseEld()">Diagnosticar ELD</button>
      <button type="button" id="btnMqProp" class="ghost" onclick="mqPropose()">Proponer</button>
      <button type="button" id="btnMqApply" class="secondary" onclick="mqApply()">Aplicar</button>
      <button type="button" id="btnMqConv" class="ghost" onclick="mqConverge()">Verificar convergencia</button>
      <button type="button" id="btnMqRefresh" class="ghost" onclick="mqRefreshStatus()">Actualizar estado</button>
      <span class="muted" id="mqMsg">Pulse «Diagnosticar sistema» para el parque completo, o Diagnosticar para el feeder activo.</span>
    </div>
    <div class="pathbox" id="mqStatus">
      Estado gate: <b id="mqReady">—</b>
      · Converge: <b id="mqConv">—</b>
      · Problemas: <b id="mqProblems">—</b>
      · Feeder: <b>{{ feeder }}</b> · Red: <b>{{ network }}</b>
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
    La columna <b>Incluir</b> viene marcada: desmarque cargas que <b>salen del alimentador</b>
    o no deben actualizarse (p.ej. pasan a otro radial). Al cargar EA/Pot esas SED quedan
    <b>desconectadas en el modelo físico</b> de CYMDIST (no entran en distribución ni en flujos).</p>
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
          <button type="button" class="ghost" onclick="selectOnlyCurrentFeeder()">Solo {{ feeder }}</button>
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
    <p class="muted">Busque un <b>nodo</b>; el sistema deriva el <b>SectionID</b>.
      Indique el <b>nombre</b> de la carga (aparecerá dibujado en el plano CYMDIST).
      Solo se ingresa <b>P (kW) trifásica</b> y <b>cos φ</b> o <b>Q (kvar)</b>. Sin EA/kWh. Una carga por vez.
      En CYMDIST se reparte a <b>monofásica por fase</b>: A/B/C = P/3 y Q/3
      (casilleros Potencia real / Potencia reactiva de la carga concentrada).
      Queda <b>Locked</b> (no entra en distribución). Se dibuja el <b>símbolo SpotLoad
      (carga concentrada)</b> en el tramo del nodo — <b>no</b> como lateral tipo SED.
      Conéctela <b>después</b> de distribuir en §2; luego flujos (§4). No redistribuir.</p>
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
      <button type="button" class="ghost" onclick="refreshNodes(true)">Actualizar inventario nodos</button>
      <button type="button" id="btnConnectLoad" onclick="connectLoad()" disabled>Conectar carga en CYMDIST</button>
      <span class="muted" id="loadMsg">Busque un nodo para habilitar la conexión.</span>
    </div>
    <div id="loadResolve" class="muted" style="margin-top:8px"></div>
    <div id="loadHistory" style="max-height:220px;overflow:auto;margin-top:10px"></div>
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
    </div>
    <pre id="informeOut" class="muted" style="white-space:pre-wrap;margin-top:12px;font-size:12px;max-height:180px;overflow:auto"></pre>
  </section>
</main>
<script>
let cliTableReady = false;
let _pathsCache = null;
const DEFAULT_FEEDER = {{ feeder|tojson }};
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
  const body = headBody();
  body.reset_downstream = !!resetDownstream;
  const r=await fetch('/api/cabecera',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(j.ok){
    let msg='OK · P='+j.P_kW.toFixed(2)+' kW · Q='+j.Q_kvar.toFixed(2)+' kvar';
    if(j.cymdist){
      msg += ' · CYMDIST Demanda Total actualizado';
      if(j.cymdist.saved) msg += ' y estudio guardado';
    }
    if(j.reset_downstream){
      msg += ' · §§2–4 restablecidos (vuelva a cargar EA/Pot → distribuir → carga → flujos)';
      resetDownstreamUI();
    }
    document.getElementById('headMsg').textContent=msg;
    document.getElementById('headMsg').className='ok';
    if(j.P_kW!=null && document.getElementById('mode').value==='A_COSFI'){
      document.getElementById('p_kw').value = j.P_kW.toFixed(2);
      document.getElementById('q_kvar').value = j.Q_kvar.toFixed(2);
    }
  }else{
    document.getElementById('headMsg').textContent=j.error||'Error';
    document.getElementById('headMsg').className='err';
  }
  previewHead();
  return j;
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

function updateFeederSelLabel(){
  const sel = getSelectedFeeders();
  const el = document.getElementById('feederSel');
  const total = (radialCatalog||[]).length;
  if (!total) {
    el.textContent = 'Sin alimentadores en el archivo suministro.';
    return;
  }
  if (!sel.length) {
    el.innerHTML = '<span class="err">Seleccione un alimentador.</span>';
    return;
  }
  if (sel.length === 1) {
    const item = (radialCatalog||[]).find(x=>String(x.id||'').toUpperCase()===sel[0]);
    const n = item ? item.n : '?';
    el.innerHTML = 'Seleccionado: <b>'+sel[0]+'</b> · '+n+' clientes · cruce NIS <b>solo</b> este RADIAL';
    return;
  }
  el.innerHTML = '<b>'+sel.length+'</b> seleccionados a propósito: <b>'+sel.join(', ')+'</b> · active «Permitir varios» para sumar más';
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
  const want = String(DEFAULT_FEEDER||'').toUpperCase();
  selectFeeder(want, false);
}

function rebuildFeederInputs(){
  const multi = isMultiAllowed();
  const selected = new Set(getSelectedFeeders().map(x=>String(x).toUpperCase()));
  document.querySelectorAll('#feederList label.feeder-item').forEach(lab=>{
    const id = (lab.dataset.id||'').toUpperCase();
    const checked = selected.has(id) ? 'checked' : '';
    if (multi) {
      lab.innerHTML = `<input type="checkbox" class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>`
        +`<span>${id}</span><span class="cnt">${(radialCatalog.find(x=>String(x.id).toUpperCase()===id)||{}).n||'?'} clientes</span>`;
    } else {
      lab.innerHTML = `<input type="radio" name="feederRadial" class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>`
        +`<span>${id}</span><span class="cnt">${(radialCatalog.find(x=>String(x.id).toUpperCase()===id)||{}).n||'?'} clientes</span>`;
    }
  });
}

function renderFeederList(items, preferSelected){
  radialCatalog = items || [];
  const box = document.getElementById('feederList');
  let prefer = '';
  if (preferSelected && preferSelected.length === 1) {
    prefer = String(preferSelected[0]).toUpperCase();
  } else if (preferSelected && preferSelected.length > 1 && isMultiAllowed()) {
    prefer = ''; // se marca el set abajo
  } else if (DEFAULT_FEEDER) {
    prefer = String(DEFAULT_FEEDER).toUpperCase();
  }
  // Si venían varios de una sesión vieja y no hay multi, quedarse con el último
  if (preferSelected && preferSelected.length > 1 && !isMultiAllowed()) {
    prefer = String(preferSelected[preferSelected.length-1]).toUpperCase();
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
  box.innerHTML = radialCatalog.map(it=>{
    const id = String(it.id||'').toUpperCase();
    const checked = prev.has(id) ? 'checked' : '';
    const typ = multi ? 'checkbox' : 'radio';
    const name = multi ? '' : 'name="feederRadial"';
    return `<label class="feeder-item" data-id="${id}">
      <input type="${typ}" ${name} class="feeder-cb" value="${id}" ${checked} onchange="onFeederCheckChange(this, event)"/>
      <span>${id}</span><span class="cnt">${it.n} clientes</span>
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

function syncActivoFromDom(){
  const map = collectActivoMap();
  cliRowsCache.forEach(r=>{
    const k = cliRowKey(r);
    if (k in map) r.Activo = map[k];
  });
  const nOff = cliRowsCache.filter(r=>r.Activo===false).length;
  const tip = document.getElementById('cliActivoTip');
  if (tip) {
    tip.textContent = nOff
      ? (nOff+' carga(s) desmarcada(s): se desconectarán en CYMDIST (modelo físico) y no entrarán en distribución/flujo.')
      : 'Todas incluidas. Desmarque las que salen del alimentador o no desea actualizar.';
  }
}

async function persistActivo(){
  syncActivoFromDom();
  try{
    await fetch('/api/clientes/activo',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({activo: collectActivoMap()}),
    });
  }catch(_e){ /* la selección sigue en memoria / se reenvía al aplicar */ }
}

function toggleAllActivo(on){
  document.querySelectorAll('#cliTable input.cli-activo').forEach(cb=>{ cb.checked = !!on; });
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
  cliRowsCache = rows.map(r=>({...r, Activo: r.Activo!==false && r.Activo!=='false' && r.Activo!==0 && r.Activo!=='0'}));
  const nOff = cliRowsCache.filter(r=>!r.Activo).length;
  let html='<div class="actions" style="margin:0 0 8px 0">'
    +'<button type="button" class="ghost" onclick="toggleAllActivo(true)">Marcar todas</button>'
    +'<button type="button" class="ghost" onclick="toggleAllActivo(false)">Desmarcar todas</button>'
    +'<button type="button" class="secondary" onclick="downloadCliExcel()" id="btnCliExcel">Descargar Excel</button>'
    +'<span class="muted" id="cliActivoTip">'
    +(nOff
      ? (nOff+' carga(s) desmarcada(s): se desconectarán en CYMDIST (modelo físico) y no entrarán en distribución/flujo.')
      : 'Todas incluidas por defecto. Desmarque manualmente las que salen del alimentador (ej. Caliza cementos inca).')
    +'</span></div>';
  html+='<table><thead><tr>'
    +'<th class="col-incluir" title="Incluir: conectada. Desmarcar = desconectar en modelo físico CYMDIST">'
    +'<input type="checkbox" id="cliActivoAll" '
    +(nOff===0?'checked':'')
    +' onchange="toggleAllActivo(this.checked)" title="Marcar/desmarcar todas"/> Incluir</th>'
    +'<th>RADIAL</th><th>Suministro</th><th>Cliente</th><th>SED</th><th>EA</th><th>Pot</th><th>LoadID</th><th>CI</th><th>SED↔</th>'
    +'</tr></thead><tbody>';
  cliRowsCache.forEach(r=>{
    const ea = r.EA==null?'':Number(r.EA).toFixed(1);
    const pot = r.Pot==null?'':Number(r.Pot).toFixed(2);
    const key = cliRowKey(r);
    const checked = r.Activo ? 'checked' : '';
    const dim = r.Activo ? '' : ' class="off-row"';
    html+=`<tr${dim}>
      <td class="col-incluir"><input type="checkbox" class="cli-activo" data-key="${key}" ${checked} onchange="syncActivoFromDom();persistActivo()"/></td>
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

async function mqFetch(path, body){
  const opts = {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : {'Content-Type':'application/json'},
  };
  if (body !== undefined) opts.body = JSON.stringify(body || {});
  const r = await fetch(path, opts);
  let j = null;
  try { j = await r.json(); } catch(e) {
    throw new Error('Respuesta no JSON ('+r.status+') en '+path);
  }
  if (!r.ok && j && j.error) throw new Error(j.error);
  if (!r.ok) throw new Error('HTTP '+r.status+' en '+path);
  return j;
}

const MQ_BTNS = ['btnMqUntil','btnMqDiag','btnMqDiagSys','btnMqDiagEld','btnMqProp','btnMqApply','btnMqConv','btnMqRefresh'];

function mqBusy(on, label){
  MQ_BTNS.forEach(id=>{
    const b = document.getElementById(id);
    if (b) b.disabled = !!on;
  });
  const msg = document.getElementById('mqMsg');
  if (on && label) msg.textContent = label;
}

function mqRenderStatus(j){
  const gate = (j && (j.gate || j)) || {};
  const sum = j.summary || j.diagnostic_summary || {};
  let lastSum = sum;
  if ((!sum || sum.n_problems == null) && j.iterations && j.iterations.length) {
    const last = j.iterations[j.iterations.length-1] || {};
    lastSum = last.diagnostic_after || last.diagnostic || sum;
  }
  const ready = !!(j.ready || gate.ready);
  document.getElementById('mqReady').textContent = ready ? 'LISTO' : 'PENDIENTE';
  document.getElementById('mqReady').style.color = ready ? '#047857' : '#b91c1c';
  document.getElementById('mqConv').textContent = j.converge || gate.converge || '—';
  const np = (lastSum && lastSum.n_problems != null) ? lastSum.n_problems
    : (gate.n_problems != null ? gate.n_problems : '—');
  document.getElementById('mqProblems').textContent = np;
  const sys = j.system_diagnostic || (j.summary && j.summary.scope==='system' ? j.summary : null);
  const sysEl = document.getElementById('mqSysProblems');
  if (sysEl) {
    if (sys && sys.n_problems != null) {
      sysEl.textContent = (sys.n_networks_ok||'?')+' redes · '+sys.n_problems+' problemas';
    } else {
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
  mqBusy(true, 'Ejecutando NetworkDiagnostic (API CYMDIST)…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar', {});
    document.getElementById('mqOut').textContent = JSON.stringify(j.summary || j, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderStatus(j);
    mqRenderRows((j.summary && j.summary.top_errors) || j.rows || []);
    msg.innerHTML = '<span class="ok">Diagnóstico OK · problemas='+((j.summary||{}).n_problems)+' · E='+((j.summary||{}).n_errors)+' W='+((j.summary||{}).n_warnings)+' H='+((j.summary||{}).n_hints)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqDiagnoseSystem(){
  const msg = document.getElementById('mqMsg');
  if(!confirm('Diagnosticar TODO el sistema (~96 alimentadores).\n\nNo requiere cabecera ni §§3–4.\nPuede tardar varios minutos. ¿Continuar?')) return;
  mqBusy(true, 'NetworkDiagnostic sistema (todas las redes de la BD)…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar_sistema', {});
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
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
    mqRenderStatus({system_diagnostic: sum, summary: sum});
    mqRenderRows(sum.by_code_detail || sum.top_errors || []);
    msg.innerHTML = '<span class="ok">Sistema OK · redes='+(sum.n_networks_ok||0)
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)
      +' · <a href="#" onclick="return false;">ver CSV por código</a></span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqDiagnoseEld(){
  const msg = document.getElementById('mqMsg');
  if(!confirm('Herramienta diagnóstica API → estudio ELD.zxst (96 redes).\n\nMisma herramienta de CYMDIST (Topología + Equipos).\n¿Continuar?')) return;
  mqBusy(true, 'Herramienta diagnóstica → ELD.zxst…');
  try{
    const j = await mqFetch('/api/calidad/diagnosticar_eld', {});
    const sum = j.summary || {};
    document.getElementById('mqOut').textContent = JSON.stringify({
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
    mqRenderStatus({system_diagnostic: sum, summary: sum});
    mqRenderRows(sum.by_code_detail || sum.top_errors || []);
    msg.innerHTML = '<span class="ok">ELD OK · redes='+(sum.n_networks_ok||0)
      +' · problemas='+(sum.n_problems||0)
      +' · E='+(sum.n_errors||0)+' W='+(sum.n_warnings||0)+' H='+(sum.n_hints||0)+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqPropose(){
  const msg = document.getElementById('mqMsg');
  mqBusy(true, 'Proponiendo correcciones (catálogo cymsg)…');
  try{
    const j = await mqFetch('/api/calidad/proponer', {});
    document.getElementById('mqOut').textContent = JSON.stringify({
      n_total:j.n_total, n_activas:j.n_activas, n_revisar:j.n_revisar, csv:j.csv
    }, null, 2);
    if(j.ok === false){ msg.innerHTML = '<span class="err">'+(j.error||'Error')+'</span>'; return; }
    mqRenderRows(j.rows||[]);
    msg.innerHTML = '<span class="ok">Propuestas: '+j.n_activas+' activas / '+j.n_total+' total (revisar='+j.n_revisar+')</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqApply(){
  const msg = document.getElementById('mqMsg');
  mqBusy(true, 'Aplicando correcciones en el estudio CYMDIST…');
  try{
    const j = await mqFetch('/api/calidad/aplicar', {});
    document.getElementById('mqOut').textContent = JSON.stringify({
      n_ok:j.n_ok, n_error:j.n_error, base_voltages:j.base_voltages, preview_csv:j.preview_csv
    }, null, 2);
    mqRenderRows(j.preview||[]);
    if(j.ok === false || (j.n_error||0) > 0){
      msg.innerHTML = '<span class="err">Aplicadas OK='+j.n_ok+' ERR='+j.n_error+(j.error?(' · '+j.error):'')+'</span>';
    } else {
      msg.innerHTML = '<span class="ok">Aplicadas OK='+j.n_ok+' ERR='+j.n_error+'</span>';
    }
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqConverge(){
  const msg = document.getElementById('mqMsg');
  mqBusy(true, 'LoadFlow + IsValidResults…');
  try{
    const j = await mqFetch('/api/calidad/convergencia', {});
    document.getElementById('mqOut').textContent = JSON.stringify(j, null, 2);
    mqRenderStatus(j);
    if(j.converge==='SI') msg.innerHTML = '<span class="ok">Converge = SI</span>';
    else msg.innerHTML = '<span class="err">Converge = '+(j.converge||'NO')+(j.error?(' · '+j.error):'')+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqUntilClean(){
  const msg = document.getElementById('mqMsg');
  mqBusy(true, 'Ejecutando ciclo completo (puede tardar varios minutos con CYMDIST)…');
  try{
    const j = await mqFetch('/api/calidad/hasta_limpio', {max_iters: 4});
    document.getElementById('mqOut').textContent = (j.log||[]).join('\n') + '\n\n' + (j.msg||j.error||'');
    mqRenderStatus(j);
    // Mostrar top problemas del último diagnóstico
    const last = (j.iterations||[]).slice(-1)[0] || {};
    const tops = ((last.diagnostic_after||last.diagnostic||{}).top_errors) || [];
    mqRenderRows(tops);
    if(j.ok) msg.innerHTML = '<span class="ok">'+(j.msg||'Listo')+'</span>';
    else msg.innerHTML = '<span class="err">'+(j.msg||j.error||'No limpio')+'</span>';
  }catch(e){
    msg.innerHTML = '<span class="err">'+e.message+'</span>';
    document.getElementById('mqOut').textContent = String(e);
  }finally{ mqBusy(false); }
}

async function mqRefreshStatus(){
  try{
    const j = await mqFetch('/api/calidad/estado');
    mqRenderStatus(j);
    const msg = document.getElementById('mqMsg');
    if (j.ready) msg.innerHTML = '<span class="ok">Gate LISTO · puede continuar a §2</span>';
    else msg.textContent = 'Gate pendiente · ejecute diagnóstico / correcciones.';
  }catch(e){
    document.getElementById('mqMsg').innerHTML = '<span class="err">'+e.message+'</span>';
  }
}

document.addEventListener('DOMContentLoaded', function(){ mqRefreshStatus(); });

async function buildClientes(){
  const ci = requireCiFile();
  if (!ci) return;
  const ff = feederRequestFields();
  if (!ff.feeders.length) {
    document.getElementById('cliMsg').innerHTML='<span class="err">Seleccione un alimentador (RADIAL).</span>';
    return;
  }
  document.getElementById('cliMsg').textContent='Cruzando NIS solo en '+ci+' · alimentador(es): '+ff.feeders.join(', ')+'…';
  const body={
    suministro_file: document.getElementById('sumFile').value,
    clientes_file: ci,
    feeder: ff.feeders.length===1 ? ff.feeders[0] : ff.feeders.join(','),
    feeders: ff.feeders,
    all_feeders: false,
  };
  const r=await fetch('/api/clientes/tabla',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(!j.ok){document.getElementById('cliMsg').innerHTML='<span class="err">'+j.error+'</span>';return;}
  cliTableReady = true;
  document.getElementById('btnApplyCli').disabled = false;
  const label = ff.feeders.length===1 ? ('solo <b>'+ff.feeders[0]+'</b>') : ('<b>'+ff.feeders.join(', ')+'</b>');
  document.getElementById('cliMsg').innerHTML='<span class="ok">Cruce OK · archivo '+ci+' · '+label+'</span>';
  const m=j.meta||{};
  document.getElementById('cliMeta').innerHTML=
    `Archivo CI: <b>${m.clientes_file}</b> (NIS en archivo: ${m.n_nis_en_archivo_ci||'?'}) · RADIAL <b>${m.feeder_id||ff.feeder}</b> · Filtrados ${m.n_filtrados} · EA/Pot ${m.n_con_ea_pot} · SED ${m.n_match_sed} · sin SED ${m.n_sin_sed}`
    + (m.n_excluidos?` · <b>excluidas ${m.n_excluidos}</b>`:'')
    + (j.tablero?` · <a href="/tablero" target="_blank">Ver en tablero</a>`:'');
  renderCliTable(j.rows||[]);
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
  };
  const r=await fetch('/api/clientes/aplicar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(!j.ok){document.getElementById('cliMsg').innerHTML='<span class="err">'+j.error+'</span>';return;}
  const excl = (j.excluido_count!=null)?j.excluido_count:nOff;
  document.getElementById('cliMsg').innerHTML=`<span class="ok">CYMDIST OK · ${j.ok_count}/${j.total} · archivo ${ci} · <b>${ff.feeders.join(', ')}</b>`
    +(j.kwh_verified!=null?` · Consumo(KWH) verificado ${j.kwh_verified}`:'')
    +(j.warn_kwh_count?` · <span class="err">WARN KWH ${j.warn_kwh_count}</span>`:'')
    +(excl?` · ${excl} excluida(s) desconectadas`:'')
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
  msg.textContent='Distribuyendo (LoadAllocation)... cabecera − clientes importantes → residual';
  if(out) out.textContent='';
  try{
    // Guardar cabecera actual antes de distribuir (sin restablecer §§2–4)
    await saveHead({resetDownstream: false});
    const r=await fetch('/api/distribucion',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const j=await r.json();
    if(!j.ok){msg.innerHTML='<span class="err">'+(j.error||'Error')+'</span>';if(out) out.textContent=JSON.stringify(j,null,2);return;}
    const d=j.result||{};
    const fallback = String(d.method||'').indexOf('fallback')>=0;
    msg.innerHTML = fallback
      ? `<span class="ok">Distribución OK (fallback kWh) · residual ${Number(d.P_residual_kW||0).toFixed(1)} kW</span>`
      : `<span class="ok">Distribución OK · ${d.method||'?'} · residual ${Number(d.P_residual_kW||0).toFixed(1)} kW</span>`;
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
    ? 'Flujo situacional: desconectando cargas §3 y ejecutando LoadFlow…'
    : (scenario==='proyectado'
      ? 'Flujo proyectado: conectando cargas §3 y ejecutando LoadFlow…'
      : 'Ejecutando flujo de carga normal (LoadFlow)...');
  msg.textContent=label;
  out.textContent='';
  try{
    const body = scenario ? {scenario: scenario, update_informe: true} : {update_informe: true};
    const r=await fetch('/api/flujo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
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
    const r=await fetch('/api/informe/rutas');
    const j=await r.json();
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
  msg.textContent='Validando LF + OCR + gráficas y rellenando informes…';
  out.textContent='';
  try{
    const r=await fetch('/api/informe/armar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fill:true})});
    const j=await r.json();
    if(!j.ok){
      msg.innerHTML='<span class="err">'+(j.error||'Informe incompleto')+'</span>';
      out.textContent=JSON.stringify({
        delivery_ready: j.delivery_ready,
        missing: j.missing,
        charts: j.charts_generated,
        escenarios: j.scenarios_used,
        meta: j.meta,
        error: j.error,
      },null,2);
      await refreshDeliveryStatus();
      return;
    }
    applyPathsUI(Object.assign({}, j.paths||{}, {images_dir:j.images_dir}));
    msg.innerHTML='<span class="ok">Entrega lista · informes en doc · gráficas LF reemplazadas</span>';
    out.textContent=JSON.stringify({
      delivery_ready: j.delivery_ready,
      destino: j.paths && j.paths.doc_dir,
      meta: j.meta,
      meta_source: j.meta_source,
      escenarios: j.scenarios_used,
      excel: j.excel_notes,
      word_reemplazos: (j.word&&j.word.replacements)||[],
      imagenes: (j.word&&j.word.images_replaced)||[],
      charts_generated: j.charts_generated,
      aviso_imagenes: j.aviso_imagenes,
      manifesto: j.fill_manifest,
    },null,2);
    await refreshDeliveryStatus();
  }catch(e){
    msg.innerHTML='<span class="err">'+e+'</span>';
  }finally{
    btn.disabled=false;
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
  const r = await fetch('/api/nodos/buscar?q='+encodeURIComponent(q)+'&limit=80');
  const j = await r.json();
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
    (j.nodes||[]).length ? ('Coincidencias: '+(j.nodes||[]).length) : 'Sin nodos. Pulse «Actualizar inventario nodos».';
  _resolved = null;
  document.getElementById('autoSection').value = '';
  document.getElementById('autoLoadId').value = '';
  document.getElementById('loadResolve').textContent = '';
  document.getElementById('btnConnectLoad').disabled = true;
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
  const r = await fetch('/api/nodos/resolver', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({node_id: nid, load_name: loadName})
  });
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'No se pudo resolver')+'</span>';
    document.getElementById('btnConnectLoad').disabled = true;
    return;
  }
  _resolved = j;
  document.getElementById('autoSection').value = j.SectionID || '';
  document.getElementById('autoLoadId').value = j.LoadID || sanitizeLoadNameClient(loadName) || '';
  document.getElementById('loadResolve').textContent =
    'Nodo '+j.NodeID+' · From '+ (j.FromNode||'?') +' → To '+(j.ToNode||'?')
    +' · candidatos '+(j.n_sections||0)
    +(j.LoadID?(' · dibujará como '+j.LoadID):'');
  const needName = !sanitizeLoadNameClient(loadName);
  if (needName) {
    document.getElementById('loadMsg').innerHTML = '<span class="err">Indique el nombre de la carga concentrada.</span>';
    document.getElementById('btnConnectLoad').disabled = true;
  } else {
    document.getElementById('loadMsg').innerHTML = '<span class="ok">Listo: complete P y cosφ/Q · nombre en plano: <b>'+(j.LoadID||'')+'</b></span>';
    document.getElementById('btnConnectLoad').disabled = false;
  }
}

async function refreshNodes(force){
  document.getElementById('loadMsg').textContent = 'Inventariando nodos desde CYMDIST…';
  const r = await fetch('/api/nodos/inventario', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({refresh: !!force})
  });
  const j = await r.json();
  if (!j.ok) {
    document.getElementById('loadMsg').innerHTML = '<span class="err">'+(j.error||'Error inventario')+'</span>';
    return;
  }
  document.getElementById('loadMsg').innerHTML =
    '<span class="ok">Inventario OK · '+j.n_nodes+' nodos · '+j.n_sections+' tramos</span>';
  await searchNodes();
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
  document.getElementById('btnConnectLoad').disabled = true;
  document.getElementById('loadMsg').textContent = 'Conectando SpotLoad trifásica «'+sanitizeLoadNameClient(loadName)+'»…';
  const body = {
    node_id: nid,
    load_name: loadName,
    mode: document.getElementById('loadMode').value,
    P_kW: document.getElementById('loadP').value,
    Q_kvar: document.getElementById('loadQ').value,
    cosfi: document.getElementById('loadCosfi').value,
  };
  try{
    const r = await fetch('/api/cargas/nueva', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const j = await r.json();
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
      `<span class="ok">${d.Estado||'OK'} · SpotLoad <b>${d.LoadID}</b> en nodo ${d.NodeID||''} @ ${d.SectionID||''}`
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

// Si hay inventario en disco, listar; si no, pedir actualizar
searchNodes();
</script>
</body>
</html>
"""

_LOAD_CACHE = {"feeder": None, "loads": []}
_NODE_CACHE = {"feeder": None, "topo": None}

def _settings():
    feeder = request.args.get("feeder") or request.headers.get("X-Feeder")
    return load_settings(feeder_id=feeder) if feeder else load_settings()

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
    """Al guardar cabecera (§1): limpia artefactos de §§2–4 para forzar el flujo de nuevo.

    No borra dispositivos en CYMDIST; solo resultados/tablas de sesión RECYM.
    """
    removed = []
    targets = [
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
    _invalidate_caches()
    return {"cleared": removed, "n": len(removed)}

def _loads(s):
    if _LOAD_CACHE["feeder"] == s.get("feeder_id") and _LOAD_CACHE["loads"]:
        return _LOAD_CACHE["loads"]
    inv = output_path(s, "inventory", "loads.json")
    if os.path.isfile(inv):
        with open(inv, "r", encoding="utf-8") as f:
            data = json.load(f)
        _LOAD_CACHE["feeder"] = s.get("feeder_id")
        _LOAD_CACHE["loads"] = data.get("loads") or []
        return _LOAD_CACHE["loads"]
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    rows = collect_loads(c, s.get("network_id"))
    _LOAD_CACHE["feeder"] = s.get("feeder_id")
    _LOAD_CACHE["loads"] = rows
    os.makedirs(os.path.dirname(inv), exist_ok=True)
    with open(inv, "w", encoding="utf-8") as f:
        json.dump({"feeder_id": s["feeder_id"], "loads": rows}, f, indent=2, ensure_ascii=False)
    return rows

def _existing_load_ids(s):
    return [str(r.get("LoadID")) for r in (_loads(s) or []) if r.get("LoadID")]

@app.route("/")
def index():
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

@app.route("/api/calidad/estado")
def api_calidad_estado():
    from pipeline.model_quality_gate import get_gate_status
    try:
        return jsonify(get_gate_status(_settings()))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/diagnosticar", methods=["POST"])
def api_calidad_diagnosticar():
    from pipeline.model_quality_gate import run_network_diagnostic
    s = _settings()
    try:
        return jsonify(run_network_diagnostic(s, suffix=""))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/diagnosticar_sistema", methods=["POST"])
def api_calidad_diagnosticar_sistema():
    """Diagnóstico de todas las redes de la BD. Independiente de §§1–4 / SpotLoad."""
    from pipeline.model_quality_gate import run_system_network_diagnostic
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(run_system_network_diagnostic(
            s,
            limit=int(body.get("limit") or 0),
            network_ids=body.get("networks") or None,
        ))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/diagnosticar_eld", methods=["POST"])
def api_calidad_diagnosticar_eld():
    """Herramienta diagnóstica API sobre ELD.zxst (Topología + Equipos)."""
    from pipeline.model_quality_gate import run_eld_network_diagnostic
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(run_eld_network_diagnostic(
            s,
            limit=int(body.get("limit") or 0),
            network_ids=body.get("networks") or None,
        ))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/proponer", methods=["POST"])
def api_calidad_proponer():
    from pipeline.model_quality_gate import propose_corrections
    s = _settings()
    try:
        return jsonify(propose_corrections(s))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/aplicar", methods=["POST"])
def api_calidad_aplicar():
    from pipeline.model_quality_gate import apply_corrections
    s = _settings()
    try:
        return jsonify(apply_corrections(s, fix_voltages=True))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/convergencia", methods=["POST"])
def api_calidad_convergencia():
    from pipeline.model_quality_gate import check_convergence
    s = _settings()
    try:
        return jsonify(check_convergence(s, run_lf=True))
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/calidad/hasta_limpio", methods=["POST"])
def api_calidad_hasta_limpio():
    from pipeline.model_quality_gate import run_until_converges
    s = _settings()
    body = request.get_json(silent=True) or {}
    try:
        result = run_until_converges(
            s,
            max_iters=int(body.get("max_iters") or 4),
            skip_initial_lf=bool(body.get("skip_initial_lf")),
        )
        result["ok_http"] = True
        return jsonify(result)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


@app.route("/api/cabecera", methods=["POST"])
def api_cabecera():
    s = _settings()
    body = request.get_json(force=True) or {}
    # Por defecto restablece §§2–4 (botón Guardar medición).
    # Distribución pasa reset_downstream=false para no borrar la tabla recién cargada.
    reset_flag = body.get("reset_downstream")
    if reset_flag is None:
        reset_flag = True
    else:
        reset_flag = bool(reset_flag)
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
    sess = load_session(s)
    sess["mode"] = body.get("mode")
    sess["P_kW"] = p
    sess["Q_kvar"] = q
    sess["cosfi"] = body.get("cosfi")
    if body.get("I_A") not in (None, ""):
        sess["I_A"] = float(body.get("I_A"))
    if body.get("Vll_kV") not in (None, ""):
        sess["Vll_kV"] = float(body.get("Vll_kV"))
    sess["fecha_medicion"] = (body.get("fecha_medicion") or "").strip()
    sess["status"] = "cabecera_ok"
    if reset_flag:
        # No conservar cargas fijas / estado de pasos posteriores
        sess["fixed_loads"] = []
        sess.pop("allocation", None)
        sess.pop("last_allocation", None)
        sess.pop("downstream", None)
    save_session(s, sess)

    reset_info = None
    if reset_flag:
        reset_info = reset_downstream_after_cabecera(s)

    # Unica fuente: medicion UI → casilleros CYMDIST + Control Excel
    cymdist_info = None
    excel_path = None
    try:
        excel_path = sync_control_excel_cabecera(
            s, p, q, cosfi=sess.get("cosfi"), fecha=sess.get("fecha_medicion")
        )
    except Exception as ex:
        return jsonify({
            "ok": False,
            "error": "Sesion guardada pero fallo sync Excel: %s" % ex,
            "P_kW": p, "Q_kvar": q,
            "reset_downstream": reset_info,
        })
    try:
        cymdist_info = apply_cabecera_medicion(s, p, q, save=True)
    except Exception as ex:
        return jsonify({
            "ok": False,
            "error": "Sesion/Excel OK pero fallo escritura CYMDIST Demanda: %s" % ex,
            "P_kW": p, "Q_kvar": q, "excel": excel_path,
            "reset_downstream": reset_info,
        })

    return jsonify({
        "ok": True,
        "P_kW": p,
        "Q_kvar": q,
        "mode": sess["mode"],
        "cymdist": cymdist_info,
        "excel": excel_path,
        "reset_downstream": reset_info,
        "msg": (
            "Cabecera actualizada; §§2–4 restablecidos"
            if reset_info is not None
            else "Cabecera actualizada en CYMDIST (Demanda Total kW/kvar) y Control Excel"
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
        return jsonify({
            "ok": True,
            "suministro_file": used,
            "radiales": items,
            "n": len(items),
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

@app.route("/api/clientes/tabla", methods=["POST"])
def api_clientes_tabla():
    s = _settings()
    body = request.get_json(force=True) or {}
    ci = (body.get("clientes_file") or "").strip()
    if not ci:
        return jsonify({
            "ok": False,
            "error": "Seleccione un archivo de clientesimportantes en el desplegable.",
            "disponibles": list_clientes_importantes_files(s),
        })
    try:
        feeder, feeders, all_feeders = _parse_feeders_body(body, s)
        if not all_feeders and not feeders and not feeder:
            return jsonify({"ok": False, "error": "Seleccione al menos un alimentador (RADIAL)."})
        rows, meta = build_feeder_clientes_table(
            s,
            feeder,
            clientes_file=ci,
            suministro_file=body.get("suministro_file") or None,
            all_feeders=all_feeders,
            feeders=feeders,
        )
        loads = _loads(s)
        rows = attach_cymdist_loads(rows, loads, primary_only=True)
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
        meta["n_match_sed"] = sum(1 for r in rows if r.get("Match_SED"))
        meta["n_sin_sed"] = sum(1 for r in rows if not r.get("Match_SED"))
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        save_table_csv(csv_path, rows)
        save_table_json(json_path, rows, meta)
        try:
            from analysis.build_dashboard import main as build_tablero
            build_tablero()
            tablero = output_path(s, "diagnostics", "tablero.html")
        except Exception:
            tablero = None
        return jsonify({
            "ok": True,
            "rows": rows,
            "meta": meta,
            "csv": csv_path,
            "tablero": tablero,
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/clientes/activo", methods=["POST"])
def api_clientes_activo():
    """Persiste checkboxes Incluir/Activo sin reescribir CYMDIST."""
    s = _settings()
    body = request.get_json(force=True) or {}
    json_path = output_path(s, "clientes", "clientes_alimentador.json")
    rows = load_saved_clientes_rows(json_path)
    if not rows:
        return jsonify({"ok": False, "error": "No hay tabla armada. Pulse «Armar tabla» primero."})
    try:
        meta = {}
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                meta = (json.load(f).get("meta") or {})
        rows = merge_activo(rows, activo_map=body.get("activo"))
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        save_table_json(json_path, rows, meta)
        save_table_csv(output_path(s, "clientes", "clientes_alimentador.csv"), rows)
        return jsonify({
            "ok": True,
            "rows": rows,
            "n_activos": meta["n_activos"],
            "n_excluidos": meta["n_excluidos"],
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/clientes/export_xlsx", methods=["POST"])
def api_clientes_export_xlsx():
    """Descarga la tabla de clientes (§2) como Excel (.xlsx), con Incluir actual."""
    s = _settings()
    body = request.get_json(force=True) or {}
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
            "Incluir", "RADIAL", "Suministro", "Cliente", "SED", "EA", "Pot",
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
            vals = [
                incluir,
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
        widths = [10, 10, 14, 28, 12, 12, 12, 28, 6, 10, 12, 12, 20, 12]
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
    s = _settings()
    body = request.get_json(force=True) or {}
    ci = (body.get("clientes_file") or "").strip()
    if not ci:
        return jsonify({
            "ok": False,
            "error": "Seleccione un archivo de clientesimportantes en el desplegable.",
            "disponibles": list_clientes_importantes_files(s),
        })
    try:
        feeder, feeders, all_feeders = _parse_feeders_body(body, s)
        if not all_feeders and not feeders and not feeder:
            return jsonify({"ok": False, "error": "Seleccione al menos un alimentador (RADIAL)."})
        rows, meta = build_feeder_clientes_table(
            s,
            feeder,
            clientes_file=ci,
            suministro_file=body.get("suministro_file") or None,
            all_feeders=all_feeders,
            feeders=feeders,
        )
        loads = _loads(s)
        rows = attach_cymdist_loads(rows, loads, primary_only=True)
        json_path = output_path(s, "clientes", "clientes_alimentador.json")
        rows = merge_activo(
            rows,
            activo_map=body.get("activo"),
            previous_rows=load_saved_clientes_rows(json_path),
        )
        rows = ensure_activo(rows, default=True)
        meta["n_match_sed"] = sum(1 for r in rows if r.get("Match_SED"))
        meta["n_activos"] = sum(1 for r in rows if r.get("Activo"))
        meta["n_excluidos"] = sum(1 for r in rows if not r.get("Activo"))
        save_table_json(json_path, rows, meta)
        save_table_csv(output_path(s, "clientes", "clientes_alimentador.csv"), rows)

        if s.get("dry_run"):
            return jsonify({
                "ok": True, "dry_run": True, "rows": rows,
                "ok_count": 0, "excluido_count": meta["n_excluidos"], "total": len(rows),
            })

        api = load_json("config/cympy_api_map.json")
        from core.cymdist_com import (
            pause_cymdist_for_cympy, open_cymdist_gui, is_keep_open,
        )
        was_open = is_keep_open(s)
        pause_cymdist_for_cympy(s)

        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        a.open_study()
        fp = float(body.get("fp") or 0.95)
        report = apply_rows(a, rows, fp=fp, lock=True)
        if s.get("save_after_write", True):
            a.save_study()
        try:
            a.close_study(save=False)
        except Exception:
            pass

        # Abrir CYMDIST visible: desde aqui §§2–5 trabajan por API fisica
        com = open_cymdist_gui(s, kill_existing=True, reason="cargar_ea_pot")
        ok_count = sum(1 for r in report if r.get("Estado") == "OK")
        warn_kwh = sum(1 for r in report if r.get("Estado") == "WARN_KWH")
        excluido_count = sum(1 for r in report if r.get("Estado") == "EXCLUIDO")
        kwh_verified = sum(1 for r in report if r.get("KWH_ok") is True)
        try:
            from analysis.build_dashboard import main as build_tablero
            build_tablero()
            tablero = output_path(s, "diagnostics", "tablero.html")
        except Exception:
            tablero = None
        return jsonify({
            "ok": True,
            "rows": rows,
            "report": report,
            "ok_count": ok_count,
            "warn_kwh_count": warn_kwh,
            "kwh_verified": kwh_verified,
            "excluido_count": excluido_count,
            "total": len(report),
            "meta": meta,
            "tablero": tablero,
            "cymdist_open": bool(com.get("cymdist_open")),
            "com": com,
            "was_open": was_open,
            "msg": (
                "EA→Consumo(KWH) + Pot→kW verificados · CYMDIST abierto — continue con distribución "
                "(actualiza kW residual), carga nueva, flujos e informes."
                if com.get("ok")
                else ("EA/Pot OK pero CYMDIST no abrio: %s" % com.get("error"))
            ),
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/distribucion", methods=["POST"])
def api_distribucion():
    """LoadAllocation Consumo (kWh). Si CYMDIST 130013, usa fallback por energia."""
    s = _settings()
    try:
        if s.get("dry_run"):
            return jsonify({"ok": True, "dry_run": True})
        sess = seed_session_from_excel(s)
        if sess.get("P_kW") in (None, ""):
            return jsonify({"ok": False, "error": "Defina y guarde la demanda de cabecera (seccion 1)."})
        result = run_allocation(s, sess)
        summary = {k: result[k] for k in result if k not in ("scaled", "applied")}
        summary["n_scaled"] = len(result.get("scaled") or [])
        summary["n_applied"] = len(result.get("applied") or [])
        ok = result.get("status") in ("ok", "ok_fallback_kwh", "dry_run")
        return jsonify({"ok": ok, "result": summary, "error": None if ok else (result.get("fallback_error") or result.get("allocation_error"))})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/flujo", methods=["POST"])
def api_flujo():
    """LoadFlow independiente: situacional (desconecta §3) | proyectado (conecta §3).
    update_informe=true (default) rellena §5 tras el flujo."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    scenario = (body.get("scenario") or "").strip().lower() or None
    update_informe = body.get("update_informe", True)
    try:
        result = run_load_flow(s, scenario=scenario)
        ok = result.get("status") in ("ok", "dry_run")
        informe = None
        if ok and update_informe:
            try:
                informe = fill_informe(s, overwrite_copy=True)
            except Exception as ex_inf:
                informe = {"ok": False, "error": str(ex_inf)}
        return jsonify({
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
        })
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

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

@app.route("/api/informe/armar", methods=["POST"])
def api_informe_armar():
    """Copia plantillas a doc/ y rellena valores desde LoadFlow (fill=true por defecto).
    Con fill=true aplica gate de entrega (ambos LF + OCR + 4 PNG)."""
    s = _settings()
    body = request.get_json(silent=True) or {}
    do_fill = body.get("fill", True)
    try:
        if do_fill:
            manifest = fill_informe(s, overwrite_copy=True, require_delivery=True)
        else:
            manifest = assemble_informe(s, overwrite=True)
        return jsonify(manifest)
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})


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
        f = request.files.get("pdf")
        if f is None or not f.filename:
            return jsonify({"ok": False, "error": "Adjunte un archivo PDF (campo pdf)."})
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
        resolved = resolve_connection(
            topo,
            body.get("node_id"),
            _existing_load_ids(s),
            load_name=body.get("load_name") or body.get("nombre") or body.get("Nombre"),
        )
        return jsonify({"ok": True, **resolved})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/cargas/nueva", methods=["POST"])
def api_cargas_nueva():
    """SpotLoad concentrada trifasica: nodo + nombre + P + (cosfi|Q). Sin EA."""
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
        # Validacion previa (mensajes claros en UI)
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
        _invalidate_caches()
        # Actualizar inventario local de cargas con la nueva entrada
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

@app.route("/tablero")
def tablero_page():
    s = _settings()
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
    # Waitress = servidor WSGI estable (produccion local). Fallback Flask.
    try:
        from waitress import serve
        print("Servidor: waitress (produccion local)")
        serve(app, host="127.0.0.1", port=port, threads=4)
    except Exception as ex:
        print("AVISO waitress no disponible (%s) — Flask threaded" % ex)
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
