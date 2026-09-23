# Manuales y tutoriales CYMDIST / CYME

Fuente: instalacion CYME 9.2 (`C:\Program Files (x86)\CYME\CYME\tutorial\How-to`).

## Diferencia clave: Distribución de carga vs Flujo de carga

| | **Distribución de carga** (`LoadAllocation`) | **Flujo de carga** (`LoadFlow`) |
|--|----------------------------------------------|----------------------------------|
| Manual | `LoadAllocation.pdf` / IL917115ES | `BalLoadFlowInd.pdf` / IL917123ES |
| Qué hace | **Ajusta** las SpotLoad para que la suma iguale la demanda medida | **Calcula** tensiones/corrientes en régimen permanente |
| Demanda (entrada) | Cabecera/medidor en **kW-kvar** (o A-FP) | — (usa lo ya escrito en cada carga) |
| Peso / método RECYM | **Consumo (kWh)** = `KWHMethod`: la **energía** de cada carga define la porción | No aplica |
| Resultado en modelo | Escribe **kW y kvar** en cada SpotLoad (SED) | Lee esos **kW-kvar**; no los redistribuye |
| Cargas sin kWh | Porción **0** (sin inventar peso) | kW/kvar = 0 en esas cargas |
| Orden | 1º EA/Pot en SED → 2º distribuir → 3º flujo | Después de tener kW-kvar correctos |
| Error frecuente | 130013 si parámetros de flujo no válidos | Convergencia / límites si el modelo es inconsistente |

### Plantilla correcta · Propiedades de la red → Demanda (antes de 3.3)

RECYM escribe esta plantilla en `set_network_demand` / 3.3:

| Campo | Valor |
|-------|-------|
| Ingresar demanda de la red | ON |
| Modelo de carga | DEFAULT |
| Conectado | ON |
| **Total** | **ON** (P/Q totales, no por fase) |
| Tipo | kW-kvar |
| P / Q | Cabecera §1 (p.ej. 9537,88 / 2587,65) |
| Pérdidas | 0 W por fase |
| Datos aguas abajo | **Consumo kW-h** (método KWH) |
| Factor de carga (FdC) | 65,0 % (`Topo.LoadFactor`) |
| Constante k | 0,3 (`Topo.LossLoadFactorK`) |

FdC/k son de **pérdidas anuales** (Topo); no cambian el peso kWh del prorrateo. Si tras 3.3 el flujo en fuente no cierra a la cabecera, revisar Locked/residual y, si aplica, ajustar FdC en `config/settings.json` (`network_load_factor_pct`).

En RECYM (UI de demanda — detalle en [`docs/MANUAL_UI_DEMANDA.md`](../MANUAL_UI_DEMANDA.md)):

- **Cargar EA/Pot** → EA = Consumo (kWh); Pot = kW Locked (clientes fijos). Incluir off = `Disconnected`.
- **Distribuir carga** → `run_demand_allocation.py` (cabecera − fijos → residual por KWH). SpotLoad §3 Locked, fuera del prorrateo.
- **Flujo situacional** → desconecta físicamente cargas §3 + LoadFlow → `loadflow_situacional.json` + intento §5 (gate puede quedar incompleto).
- **Flujo proyectado** → conecta cargas §3 con P/Q + LoadFlow → `loadflow_proyectado.json` + intento §5.
- **§5 entrega** exige ambos LF + `informe_meta.json` (PDF OCR) + 4 PNG LF (auto matplotlib o override CYMDIST).
- SpotLoad nueva (§3): P trifásica → A/B/C = P/3, Q/3 en casilleros de potencia.
## Uso en RECYM

1. **EquipmentModeling** — Los equipos se crean primero en la biblioteca (Equipos / cympy.eq.Add) y luego se asignan a dispositivos de red. RECYM solo asigna IDs que existen en la BD.
2. **LoadAllocation** — Distribucion por kVA conectados / kWh / kVA real / REA; demanda de alimentador o medidor; requiere parametros de flujo de carga validos.
3. **LoadFlow** — Analisis de regimen permanente (tutorial BalLoadFlowInd).
4. **StartDatabase / StartStudy** — Conexion MDB + apertura de estudio .zxst.
5. Parametros electricos faltantes (R, GMR, ampacidad, etc.) se toman de Excel en data/input/common/equipment y se sincronizan con sync_equipment_from_excel.py.

## Exportar ASCII (error 530014)

Mensaje: *No puede exportar a ASCII. Favor de cargar sus redes y actualizarlas en primer lugar.*

**Causa:** con solo la conexion `20260919` marcada no basta. `ExportASCII` exige un **estudio abierto**, **todas** las redes de la BD cargadas, y **Actualizar red** (`db.Update`) antes de exportar. El Utilitario de BD falla igual si ese paso no se hizo.

### En la GUI CYMDIST

1. Conectar `20260919`.
2. **Archivo → Nuevo estudio** (o abrir un `.zxst`).
3. **Seleccionar redes** → marcar **Todas las redes** → Aceptar (deben quedar cargadas en el unifilar).
4. **Archivo → Base de datos → Actualizar red**.
5. Exportar → **Archivo(s) CYME ASCII**, con extensiones `.txt` completas  
   (`…Equipos.txt`, `…Red.txt`, `…Cargas.txt` — no dejar `Equipos.` ni `Cargas.t`).

### Desde RECYM (recomendado)

```bat
scripts\23_export_cymdist_ascii.bat
```

Genera en `D:\BaseDatosElectroDunas\260919BaseDatos\exportarTXT\`:

- `260921Red.txt`
- `260921Equipos.txt`
- `260921Cargas.txt`

## Archivos locales

Ver PDFs copiados en esta carpeta y extractos .txt generados para busqueda (`LoadAllocation.txt`, `BalLoadFlowInd.txt`).
