# Validación integral RECYM — PA217

**Fecha:** 2026-09-21 · **Resultado:** PASS

## Manuales actualizados

| Documento | Cambio |
|-----------|--------|
| [`docs/MANUAL_UI_DEMANDA.md`](MANUAL_UI_DEMANDA.md) | Nuevo manual operativo §§1–5 |
| [`README.md`](../README.md) | Enlace al manual + reglas EA/SpotLoad/flujos |
| [`docs/cymdist/README.md`](cymdist/README.md) | Situacional/proyectado = desconecta/conecta |
| [`docs/ARQUITECTURA.md`](ARQUITECTURA.md) | Capas alineadas al flujo actual |

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

1. **§2 Incluir off** → `Disconnected` + 0  
2. **§2 EA** → Consumo (kWh); distribución actualiza kW residual  
3. **§3** → P₃φ → A/B/C = P/3, Q/3  
4. **§4 situacional** → desconecta §3 + LF + §5  
5. **§4 proyectado** → conecta §3 + LF + §5  
