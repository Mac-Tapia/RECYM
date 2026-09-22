# Manual UI de demanda RECYM (PA217 / multi-alimentador)

Interfaz SPA: `scripts\20_demand_ui.bat` → **http://127.0.0.1:5055** (React + FastAPI §§1–7)  
Legacy Flask: `scripts\20_demand_ui_legacy.bat`  
Contrato API: [`API_CONTRATO_UI.md`](API_CONTRATO_UI.md)  
Motor: CymPy + API COM CYMDIST 9.2 · estudio `.zxst` + BD `.mdb` Electro Dunas.

Orden obligatorio (SPA numerada):

**§1 Cabecera → §2 Calidad+Tablero → §3 EA/Pot + distribución → §4 SpotLoad → §5 Flujos → §6 Informes → §7 Opt/Suite**

- **§2 Calidad / NetworkDiagnostic** (feeder o **sistema 96**) **no depende** de §§4–5 ni de cabecera: usa redes y equipos ya en la BD.
- Tras **Cargar EA/Pot** o **Conectar carga**, CYMDIST queda abierto; §§3–6 operan sobre la misma sesión física.
- El **tablero** vive en §2 (`GET /api/tablero`); ya no se usa `tablero.html` como producto.

### Diagnóstico de sistema (96 alimentadores)

- UI: botones **2.7 Diagnosticar sistema (96)** / **2.8 Diagnosticar ELD** en §2.
- CLI sistema: `scripts\24_system_network_diagnostic.bat`
- CLI estudio ELD (Herramienta diagnóstica API): `scripts\25_eld_diagnostic.bat`  
  Estudio: `D:\BaseDatosElectroDunas\260919BaseDatos\proyectos\ELD.zxst`  
  Salida: `data/output/system/diagnostics/ELD/`
- Salida sistema: `data/output/system/diagnostics/cymdist_diagnostic_errors_system.csv` + `diagnostic_by_code_system.csv`

---

## §1 — Contexto + máxima demanda de cabecera

- Elija BD + estudio y pulse **1.1 Aplicar BD + estudio**.
- Ingrese P/Q, P+cosφ o I+V+cosφ y **1.2 Guarde**.
- Esa demanda es la entrada de **LoadAllocation** (demanda Connected+Total).
- Guardar cabecera **restablece** artefactos de sesión de §§3–5 para evitar mezclar campañas.

---

## §2 — Calidad del modelo + Tablero dinámico

- Botones 2.1–2.8 (diagnosticar, proponer, aplicar, convergencia, sistema, ELD).
- Tablero: cards de errores, códigos antes/después, top errores, tabla clientes Incluir.
- Gate listo (0 Error/Warning/Hint + converge) antes de §3.

---

## §3 — Clientes importantes → SED + distribución

1. Elija `suministrocliente` y `clientesimportantes`.
2. Marque alimentador(es) RADIAL.
3. **3.1 Armar tabla** (cruce NIS).
4. Columna **Incluir** (en §2 Tablero): marcada → escribe CYMDIST; desmarcada → desconecta SED.
5. **3.2 Cargar EA/Pot** — EA→Consumo(kWh), Pot→kW Locked.
6. **3.3 Distribución** Consumo (kWh). No redistribuir tras §4.

---

## §4 — Nueva carga concentrada (SpotLoad)

1. **4.1** Actualizar inventario nodos → busque nodo.
2. Nombre obligatorio (= DeviceNumber).
3. P trifásica + cosφ/Q → **4.2 Conectar** (A/B/C = P/3, Q/3; Locked).

---

## §5 — Flujos (LoadFlow)

| Botón | Acción |
|-------|--------|
| **5.1 Situacional** | Desconecta SpotLoad §4 → LoadFlow |
| **5.2 Proyectado** | Conecta SpotLoad §4 → LoadFlow |
| **5.3 General** | Sin conmutar escenario |

Tras cada flujo OK se intenta actualizar §6.

---

## §6 — Informes de entrega

1. **6.1 PDF OCR** → meta (cliente + potencia_kw mínimo).
2. Ambos flujos §5 + 4 PNG.
3. **6.2 Rellenar informes → doc**.

### APIs informe

- `POST /api/informe/meta_pdf` — upload PDF
- `GET|POST /api/informe/meta` — leer/guardar campos
- `POST /api/informe/armar` — fill con gate

---

## §7 — Optimización + Suite

- 7.1 Optimización (reclosers / regulators / capacitors).
- 7.2 Entorno, conexión, validar entradas, inventario 96.
- 7.3 Sync equipos / fix DEFAULT / export ASCII.
- 7.4 Nuevo alimentador RECYM.
- 7.5 Pipeline batch.

---

## Jobs asíncronos

Operaciones largas de §2/§3/§5: `POST /api/jobs` + SSE `/api/jobs/{id}/events`.

---

## Campos CYMDIST clave (API)

| Concepto UI | Campo CymPy |
|-------------|-------------|
| Consumo (kWh) | `CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[i].KWH` |
| Potencia real / reactiva | `...LoadValue.KW` / `.KVAR` |
| Conectado / Desconectado | `CustomerLoads[0].ConnectionStatus` = `Connected` \| `Disconnected` |
| Bloqueo distribución | `...LockDuringLoadAllocation` = `Locked` \| `Unlocked` |
| SED (Total) | `CustomerLoadValues.Count=1`, Phase=`ABC` |
| Carga nueva por fase | `Count=3`, Phase A/B/C → P/3, Q/3 |

---

## Salidas típicas (PA217)

```
data/output/feeders/PA217/
  clientes/clientes_alimentador.json
  demand/allocation_result.json
  demand/loadflow_situacional.json
  demand/loadflow_proyectado.json
  demand/informe_meta.json
  diagnostics/tablero.json
  informe_images/situacional_*.png
  informe_images/proyectado_*.png
```

---

## Validación rápida

```bat
scripts\01_check_environment.bat
scripts\03_test_cymdist_connection.bat --feeder PA217
scripts\20_demand_ui.bat
```
