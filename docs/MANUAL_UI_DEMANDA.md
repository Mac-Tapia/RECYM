# Manual UI de demanda RECYM (PA217 / multi-alimentador)

Interfaz: `scripts\20_demand_ui.bat` → **http://127.0.0.1:5055**  
Motor: CymPy + API COM CYMDIST 9.2 · estudio `.zxst` + BD `.mdb` Electro Dunas.

Orden obligatorio:

**§1 Cabecera → §2 EA/Pot + distribución → §3 SpotLoad nueva → §4 Flujos → §5 Informes**

Tras **Cargar EA/Pot** o **Conectar carga**, CYMDIST queda abierto; §§2–5 operan sobre la misma sesión física.

---

## §1 — Máxima demanda de cabecera

- Ingrese P/Q, P+cosφ o I+V+cosφ y **Guarde**.
- Esa demanda es la entrada de **LoadAllocation** (demanda Connected+Total).
- Guardar cabecera **restablece** §§2–4 (tabla, distribución, carga nueva) para evitar mezclar campañas.

---

## §2 — Clientes importantes → SED + distribución

### Cargar EA/Pot

1. Elija `suministrocliente` y `clientesimportantes`.
2. Marque alimentador(es) RADIAL.
3. **Armar tabla** (cruce NIS).
4. Columna **Incluir**:
   - Marcada → se escribe en CYMDIST.
   - Desmarcada → la SpotLoad SED se **desconecta físicamente** (`ConnectionStatus=Disconnected`) y P/Q/kWh=0. No entra en distribución ni en flujos.
5. **Cargar EA/Pot en CYMDIST**:
   - **EA → casillero Consumo (kWh)** (`CustomerLoadValues[].KWH`), con verificación de relectura.
   - **Pot → potencia real (kW)** + kvar desde FP; **Locked** (cliente fijo).
   - SED típica: un solo valor Total (Phase=ABC).
   - Abre CYMDIST (COM) en el mismo estudio.

### Distribución de carga (Consumo kWh)

- Método CYME: **Consumo (kWh)** = `KWHMethod` (IL917115ES).
- Clientes importantes Incluidos = **fijos Locked** (restan de cabecera).
- Resto de SpotLoad = **Unlocked**; su **Consumo (kWh)** define el peso del residual.
- Resultado: actualiza **kW/kvar** del residual.
- Tras la corrida se valida que el Consumo de clientes siga igual al EA.
- SpotLoad nuevas del §3 (si ya existían) quedan Locked y **no** entran al prorrateo.

No vuelva a distribuir después de conectar una SpotLoad nueva (§3).

---

## §3 — Nueva carga concentrada (SpotLoad)

1. Busque nodo → se deriva SectionID.
2. Nombre obligatorio (= DeviceNumber en el plano).
3. Ingrese **P trifásica (kW)** + cosφ o Q.
4. **Conectar carga en CYMDIST**:
   - Dibuja símbolo SpotLoad en el tramo (From/To), no lateral tipo SED.
   - La potencia trifásica se reparte a **monofásica por fase**:
     - A / B / C = **P/3** y **Q/3**
     - Casilleros CYMDIST: *Potencia real (kW)* y *Potencia reactiva (kvar)* por fase.
   - Queda **Locked** (fuera de distribución).
   - Tras COM se reescriben P/Q (el COM puede dejar 0 si no se reaplica).

Ejemplo: 1400 kW · cosφ 0.95 → Q≈460.16 kvar → **466.67 kW / 153.39 kvar** en A, B y C.

---

## §4 — Flujos (LoadFlow) — botones independientes

| Botón | Acción física en modelo | Salida |
|-------|-------------------------|--------|
| **Flujo estado situacional** | **Desconecta** todas las SpotLoad §3 (`Disconnected`) y corre LoadFlow | `loadflow_situacional.json` |
| **Flujo con cargas nuevas** | **Conecta** SpotLoad §3 con su P/Q y corre LoadFlow | `loadflow_proyectado.json` |
| Flujo general | Sin conmutar escenario (o proyectado si hay §3) | `loadflow_result.json` |

- Cada botón deja el modelo en ese estado (no se restaura solo).
- Tras cada flujo OK se **actualiza automáticamente el §5** (informe).
- No redistribuir tras §3.

Manual CYME: BalLoadFlowInd / IL917123ES.

---

## §5 — Informes de entrega (riguroso)

Orden recomendado:

1. **PDF OCR (§5.1)** — cargar solicitud/factibilidad PDF → Extraer datos generales → revisar/guardar meta (`demand/informe_meta.json`). Mínimo: **cliente + potencia_kw**.
2. **§4 Flujo situacional** (sin carga nueva §3) → genera `loadflow_situacional.json` + gráficas `situacional_*.png`.
3. **§4 Flujo proyectado** (con carga nueva §3) → genera `loadflow_proyectado.json` + gráficas `proyectado_*.png`.
4. **Rellenar informes → doc** — solo completa si hay ambos LF + meta OCR + 4 PNG LF.

### Gates de entrega

| Requisito | Origen |
|-----------|--------|
| `loadflow_situacional.json` | §4 situacional |
| `loadflow_proyectado.json` | §4 proyectado |
| `informe_meta.json` (cliente + kW) | PDF OCR / guardar meta §5 |
| 4 PNG LF | Auto desde JSON (matplotlib) o override CYMDIST |

Si falta algo, `fill_informe` retorna `ok: false` + `missing[]` y **no** sobrescribe `doc/` con plantilla.

### Gráficas

- Auto: `situacional_tension.png`, `situacional_cargabilidad.png`, `proyectado_tension.png`, `proyectado_cargabilidad.png`.
- Override: capturas CYMDIST con el mismo nombre y mtime más reciente que el JSON LF.
- Opcionales: `topologia.png`, `trafo_cargabilidad.png`.

### APIs

- `POST /api/informe/meta_pdf` — upload PDF
- `GET|POST /api/informe/meta` — leer/guardar campos
- `POST /api/informe/armar` — fill con gate

Tras §4 el auto-fill también aplica el gate (puede quedar incompleto hasta tener ambos escenarios + OCR).

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
  clientes/precision_report.csv
  demand/allocation_result.json
  demand/residual_scaled.csv
  demand/loadflow_situacional.json
  demand/loadflow_proyectado.json
  demand/informe_meta.json
  informe_images/situacional_*.png
  informe_images/proyectado_*.png
  loads/new_spot_loads_report.csv
```

---

## Validación rápida

```bat
scripts\01_check_environment.bat
scripts\03_test_cymdist_connection.bat --feeder PA217

:: Precisión EA→Consumo / Pot→kW (clientes Incluir=on)
.tools\python37-win32\python.exe -c "import sys; sys.path.insert(0,'src'); from analysis.verify_clientes_precision import main; main()"
```

En UI: tras Cargar EA/Pot debe aparecer «Consumo(KWH) verificado»; tras flujos, «§5 informe actualizado».
