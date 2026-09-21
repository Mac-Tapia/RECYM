# -*- coding: utf-8 -*-
"""Genera HTML + JSON consolidado del tablero (diagnóstico + clientes SED)."""
from __future__ import print_function
import csv
import json
import os
from core.feeder_context import load_settings, output_path

def _load(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_clientes(s):
    """Carga tabla final clientes (JSON preferido, CSV fallback)."""
    jpath = output_path(s, "clientes", "clientes_alimentador.json")
    cpath = output_path(s, "clientes", "clientes_alimentador.csv")
    apply_path = output_path(s, "clientes", "apply_cymdist_report.csv")
    data = {"rows": [], "meta": {}, "apply": []}
    if os.path.isfile(jpath):
        raw = _load(jpath) or {}
        data["rows"] = raw.get("rows") or []
        data["meta"] = raw.get("meta") or {}
        data["json_path"] = jpath
    elif os.path.isfile(cpath):
        with open(cpath, "r", encoding="utf-8-sig") as f:
            data["rows"] = list(csv.DictReader(f))
        data["csv_path"] = cpath
    if os.path.isfile(apply_path):
        with open(apply_path, "r", encoding="utf-8-sig") as f:
            data["apply"] = list(csv.DictReader(f))
        data["apply_path"] = apply_path
    if os.path.isfile(cpath):
        data["csv_path"] = cpath
    return data

def _esc(v):
    return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _fmt_num(v, nd=1):
    if v is None or v == "":
        return ""
    try:
        return ("%%.%df" % nd) % float(v)
    except Exception:
        return _esc(v)

def main():
    s = load_settings()
    before = _load(output_path(s, "diagnostics", "dashboard_summary.json"))
    after = _load(output_path(s, "diagnostics", "dashboard_summary_after.json"))
    preview = output_path(s, "preview_changes.csv")
    clientes = _load_clientes(s)

    board = {
        "utility": s.get("utility_name"),
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "dry_run": s.get("dry_run"),
        "study_path": s.get("study_path"),
        "before": before,
        "after": after,
        "preview_csv": preview if os.path.isfile(preview) else None,
        "clientes": {
            "meta": clientes.get("meta") or {},
            "n": len(clientes.get("rows") or []),
            "csv": clientes.get("csv_path"),
            "json": clientes.get("json_path"),
            "apply_csv": clientes.get("apply_path"),
            "rows": clientes.get("rows") or [],
        },
    }
    out_json = output_path(s, "diagnostics", "tablero.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2, ensure_ascii=False)

    b_total = (before or {}).get("total_messages", 0)
    a_total = (after or {}).get("total_messages")
    b_codes = (before or {}).get("by_code") or {}
    a_codes = (after or {}).get("by_code") or {}

    rows_html = []
    for code in sorted(set(list(b_codes.keys()) + list(a_codes.keys()))):
        rows_html.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (code, b_codes.get(code, 0), a_codes.get(code, "—"))
        )

    top = ((after or before) or {}).get("top_errors") or []
    top_html = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (
            e.get("Codigo", ""),
            e.get("Tipo", ""),
            e.get("ID_CYMDIST", ""),
            _esc(e.get("Mensaje") or ""),
        )
        for e in top[:30]
    )

    # --- Tabla clientes final ---
    from core.common import truthy as _truthy
    cli_rows = clientes.get("rows") or []
    cli_meta = clientes.get("meta") or {}
    n_cli = len(cli_rows)
    n_ea = sum(1 for r in cli_rows if r.get("Match_CI") in (True, "True", "true", "1") or r.get("EA") not in (None, ""))
    n_sed = sum(1 for r in cli_rows if r.get("Match_SED") in (True, "True", "true", "1") or r.get("LoadID_CYMDIST"))
    n_ok_apply = sum(1 for r in (clientes.get("apply") or []) if str(r.get("Estado") or "").upper() == "OK")
    n_excluidos = sum(1 for r in cli_rows if not _truthy(r.get("Activo", True)))
    n_activos = n_cli - n_excluidos

    cli_body = []
    for r in cli_rows:
        match_ci = "✓" if r.get("Match_CI") in (True, "True", "true", "1") or r.get("EA") not in (None, "") else "✗"
        match_sed = "✓" if r.get("Match_SED") in (True, "True", "true", "1") or r.get("LoadID_CYMDIST") else "✗"
        activo = _truthy(r.get("Activo", True))
        key = "%s|%s" % (
            str(r.get("Suministro") or "").strip(),
            str(r.get("SED") or "").strip(),
        )
        checked = " checked" if activo else ""
        dim = ' class="off"' if not activo else ""
        cli_body.append(
            "<tr%s>"
            "<td><input type='checkbox' class='cli-activo' data-key='%s'%s/></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td>"
            "</tr>"
            % (
                dim,
                _esc(key),
                checked,
                _esc(r.get("RADIAL")),
                _esc(r.get("Suministro")),
                _esc(r.get("Cliente")),
                _esc(r.get("SED")),
                _fmt_num(r.get("EA"), 1),
                _fmt_num(r.get("Pot"), 2),
                _esc(r.get("LoadID_CYMDIST")),
                match_ci,
                match_sed,
            )
        )
    cli_table = (
        "<table class='cli' id='cliTable'>"
        "<thead><tr>"
        "<th><input type='checkbox' id='cliActivoAll' title='Marcar/desmarcar todas'%s/> Incluir</th>"
        "<th>RADIAL</th><th>Suministro</th><th>Cliente</th><th>SED</th>"
        "<th>EA (kWh)</th><th>Pot (kW)</th><th>LoadID CYMDIST</th><th>CI</th><th>SED↔</th>"
        "</tr></thead><tbody>%s</tbody></table>"
        % (
            " checked" if n_excluidos == 0 and n_cli else "",
            "".join(cli_body) if cli_body else "<tr><td colspan='10'>Sin tabla de clientes. Arme la tabla en la interfaz (§2).</td></tr>",
        )
    )

    ci_file = _esc(cli_meta.get("clientes_file") or "—")
    sum_file = _esc(cli_meta.get("suministro_file") or "—")

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<title>RECYM Tablero — {feeder}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f6f7f9;color:#1a1a1a}}
h1{{margin:0 0 8px}}
h2{{margin-top:28px;border-bottom:2px solid #0f766e;padding-bottom:6px}}
.meta{{color:#555;margin-bottom:20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}}
.card{{background:#fff;border:1px solid #ddd;padding:14px 18px;min-width:140px;border-radius:8px}}
.card b{{display:block;font-size:28px;margin-top:4px}}
table{{border-collapse:collapse;width:100%;background:#fff;margin-bottom:24px}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;font-size:13px}}
th{{background:#eee}}
table.cli th{{background:#ccfbf1;color:#115e59}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr.off{{opacity:.55;background:#fafaf9}}
.ok{{color:#0a7a32}} .bad{{color:#b00020}}
.note{{font-size:13px;color:#57534e;margin:8px 0 12px}}
.wrap{{overflow:auto;max-height:520px;border:1px solid #ddd;background:#fff}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}}
button{{cursor:pointer;border:0;border-radius:8px;padding:8px 12px;background:#0f766e;color:#fff;font:inherit}}
button.ghost{{background:#fff;color:#0f766e;border:1px solid #0f766e}}
#cliMsg{{font-size:13px;color:#57534e}}
a.back{{color:#0f766e}}
</style>
</head>
<body>
<p><a class="back" href="/">← Volver a la interfaz</a></p>
<h1>RECYM — Tablero</h1>
<div class="meta">{utility} · Alimentador <b>{feeder}</b> · Red {net}<br/>
Estudio: {study}<br/>dry_run={dry}</div>

<div class="cards">
  <div class="card">Errores antes<b class="bad">{b_total}</b></div>
  <div class="card">Errores después<b>{a_total}</b></div>
  <div class="card">220052 antes<b>{c52b}</b></div>
  <div class="card">220047 antes<b>{c47b}</b></div>
  <div class="card">220052 después<b>{c52a}</b></div>
  <div class="card">220047 después<b>{c47a}</b></div>
</div>

<h2>Clientes del alimentador (tabla final)</h2>
<div class="note">Suministro: <b>{sum_file}</b> · Clientes importantes: <b>{ci_file}</b> ·
Filas <b>{n_cli}</b> · con EA/Pot <b>{n_ea}</b> · SED en CYMDIST <b>{n_sed}</b> · aplicados OK <b>{n_ok}</b></div>
<div class="note">Columna <b>Incluir</b>: desmarque cargas que salen del alimentador o no desea actualizar.
Al guardar, quedan fuera de distribución y de los flujos. Luego use «Cargar EA/Pot» en la interfaz (§2).</div>
<div class="cards">
  <div class="card">Clientes tabla<b>{n_cli}</b></div>
  <div class="card">Incluidas<b class="ok" id="cardActivos">{n_activos}</b></div>
  <div class="card">Excluidas<b class="bad" id="cardExcluidos">{n_excluidos}</b></div>
  <div class="card">Match SED<b class="ok">{n_sed}</b></div>
  <div class="card">Cargados CYMDIST<b>{n_ok}</b></div>
</div>
<div class="actions">
  <button type="button" class="ghost" onclick="toggleAll(true)">Marcar todas</button>
  <button type="button" class="ghost" onclick="toggleAll(false)">Desmarcar todas</button>
  <button type="button" onclick="guardarActivo()">Guardar selección Incluir</button>
  <span id="cliMsg">Los cambios se aplican al modelo al cargar EA/Pot en la interfaz.</span>
</div>
<div class="wrap">{cli_table}</div>
<p class="note">CSV: {cli_csv}</p>

<h2>Códigos de error (antes / después)</h2>
<table><tr><th>Código</th><th>Antes</th><th>Después</th></tr>{code_rows}</table>
<h2>Muestra de errores</h2>
<table><tr><th>Código</th><th>Tipo</th><th>ID</th><th>Mensaje</th></tr>{top_rows}</table>
<p>JSON: {out_json}</p>
<script>
function collectActivo(){{
  var map={{}};
  document.querySelectorAll('input.cli-activo').forEach(function(cb){{
    map[cb.dataset.key]=cb.checked;
    cb.closest('tr').classList.toggle('off', !cb.checked);
  }});
  var nOff=Object.keys(map).filter(function(k){{return !map[k];}}).length;
  var nOn=Object.keys(map).length-nOff;
  var a=document.getElementById('cardActivos');
  var e=document.getElementById('cardExcluidos');
  if(a) a.textContent=nOn;
  if(e) e.textContent=nOff;
  var all=document.getElementById('cliActivoAll');
  if(all) all.checked=(nOff===0 && Object.keys(map).length>0);
  return map;
}}
function toggleAll(on){{
  document.querySelectorAll('input.cli-activo').forEach(function(cb){{cb.checked=!!on;}});
  collectActivo();
}}
document.getElementById('cliActivoAll') && document.getElementById('cliActivoAll').addEventListener('change', function(){{
  toggleAll(this.checked);
}});
document.querySelectorAll('input.cli-activo').forEach(function(cb){{
  cb.addEventListener('change', collectActivo);
}});
function guardarActivo(){{
  var msg=document.getElementById('cliMsg');
  msg.textContent='Guardando…';
  fetch('/api/clientes/activo',{{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{activo: collectActivo()}})
  }}).then(function(r){{return r.json();}}).then(function(j){{
    if(!j.ok){{msg.innerHTML='<span class="bad">'+(j.error||'Error')+'</span>';return;}}
    msg.innerHTML='<span class="ok">Guardado · incluidas '+(j.n_activos||0)+' · excluidas '+(j.n_excluidos||0)+
      '. Vuelva a la interfaz y pulse «Cargar EA/Pot en CYMDIST».</span>';
  }}).catch(function(e){{
    msg.innerHTML='<span class="bad">'+e+'</span> · Abra el tablero desde http://127.0.0.1:5055/tablero';
  }});
}}
collectActivo();
</script>
</body></html>""".format(
        utility=_esc(board["utility"]),
        feeder=_esc(board["feeder_id"]),
        net=_esc(board["network_id"]),
        study=_esc(board["study_path"]),
        dry=board["dry_run"],
        b_total=b_total,
        a_total=a_total if a_total is not None else "—",
        c52b=b_codes.get("220052", 0),
        c47b=b_codes.get("220047", 0),
        c52a=a_codes.get("220052", "—"),
        c47a=a_codes.get("220047", "—"),
        code_rows="".join(rows_html) or "<tr><td colspan=3>Sin datos</td></tr>",
        top_rows=top_html or "<tr><td colspan=4>Sin datos</td></tr>",
        out_json=_esc(out_json),
        sum_file=sum_file,
        ci_file=ci_file,
        n_cli=n_cli,
        n_ea=n_ea,
        n_sed=n_sed,
        n_ok=n_ok_apply,
        n_activos=n_activos,
        n_excluidos=n_excluidos,
        cli_table=cli_table,
        cli_csv=_esc(clientes.get("csv_path") or "—"),
    )
    out_html = output_path(s, "diagnostics", "tablero.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print("Tablero JSON:", out_json)
    print("Tablero HTML:", out_html)
    print("Clientes en tablero:", n_cli)

if __name__ == "__main__":
    main()
