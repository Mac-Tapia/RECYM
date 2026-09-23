# Validación integral RECYM — PA217

**Fecha:** 2026-09-21 · **Resultado:** PASS

## Manuales actualizados

| Documento | Cambio |
|-----------|--------|
| [`docs/ARQUITECTURA.md`](ARQUITECTURA.md) | Capas SPA v6, API, CymPy/COM, artefactos |
| [`docs/FLUJO_TRABAJO.md`](FLUJO_TRABAJO.md) | Campaña §§1–7 + batch + criterios de cierre |
| [`docs/MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md) | Manual operativo UI §§1–7 |
| [`README.md`](../README.md) | Estructura repo + enlaces docs |
| [`docs/cymdist/README.md`](cymdist/README.md) | Situacional/proyectado = desconecta/conecta SpotLoad |
| [`docs/ARTICULO_IEEE_OUTLINE.md`](ARTICULO_IEEE_OUTLINE.md) | Outline manuscrito IEEE |

## Checklist de validación

| Chequeo | Estado |
|---------|--------|
| Sintaxis módulos clave (adapter, apply, allocation, loadflow, add_spot, fill, UI) | OK |
| Imports pipeline | OK |
| Config Load (KWH, ConnectionStatus, Lock, P/Q) | OK |
| `dry_run=false`, estudio `.zxst` y `.mdb` existen | OK |
| Apertura estudio NET_2030_179_PA217 | OK |
| Clientes Activo: EA→Consumo / Pot→kW | OK (10 SED) |
| SpotLoad §3 `SAN_FERNANDO1`: 1400 kW → 466.67×3 fases | OK |
| Orphan `SAN_FERNANDO` (0 kW) desconectado | OK |
| Artefactos loadflow situacional/proyectado + allocation | OK |
| UI http://127.0.0.1:5055 | OK |

Informe JSON: `data/output/feeders/PA217/validation_integral_report.json`

## Flujo validado (resumen)

Numeración SPA actual (§§1–7):

1. **§3 Incluir off** → `Disconnected` + 0  
2. **§3 EA** → Consumo (kWh); distribución actualiza kW residual  
3. **§4 SpotLoad** → P₃φ → A/B/C = P/3, Q/3 (Locked)  
4. **§5 situacional** → desconecta §4 + LoadFlow (+ insumos §6)  
5. **§5 proyectado** → conecta §4 + LoadFlow (+ insumos §6)  

Nota histórica: en validaciones previas SpotLoad figuraba como §3 y flujos como §4; el producto SPA v6 usa la tabla de arriba.
