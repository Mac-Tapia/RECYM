# Validación integral RECYM — contexto universal

> La sección histórica PA217 que sigue conserva evidencia de 2026-09-21 y no demuestra por sí sola el estado actual ni otros alimentadores.

## Corte automatizado 2026-09-27

| Puerta | Resultado |
|---|---:|
| Python | 57 passed, 5 warnings |
| Vitest SPA | 8 passed |
| TypeScript `--noEmit` | PASS |
| Vite producción | PASS (99 módulos) |
| Contexto 4 campos + huella | PASS unitario |
| Rechazo de informe ajeno | PASS unitario |
| Selector/descubrimiento/1.1 CYMDIST real | PENDIENTE de canario live |
| Escrituras §§1–7 y guardado físico | PENDIENTE de coordinador y ejecución controlada |

Estas pruebas no se presentan como ejecución real de CYMDIST. El canario
`scripts/validate_universal_context.py` registra salud, readiness, descubrimiento,
1.1 opcional, duraciones, identidad y SHA-256 de la evidencia; en modo
`--skip-apply` no inicia escrituras ni informes.

## Fundamento técnico verificable

- Hasan, tesis de maestría (Boise State, 2023), propone verificar procedencia durante la ejecución mediante hashes: https://doi.org/10.18122/td.2050.boisestate
- Procko, tesis doctoral (Embry-Riddle, 2025), sustenta la captura automática de trazas entre actividad y artefactos: https://commons.erau.edu/edt/898/
- Rajbhandari, tesis doctoral (Cardiff, 2007), trata la procedencia como receta para documentar y reejecutar workflows de servicios: https://orca.cardiff.ac.uk/id/eprint/54620/
- Moreau et al., artículo indexado sobre procedencia de workflows científicos y reproducibilidad: https://arxiv.org/abs/1311.4610
- Eaton documenta que CYMDIST ofrece flujo de carga, asignación de carga y resultados de tensión, corriente, pérdidas y condiciones anormales; por eso la validación nativa se mantiene separada de las pruebas simuladas: https://www.eaton.com/us/en-us/software/utility-solutions/software-modules/cymdist.html

La aplicación concreta de estas fuentes es: identidad explícita en cada etapa,
hash de contexto y artefactos, manifiestos append-only/no destructivos, rechazo
fail-closed y separación estricta entre evidencia automatizada y evidencia nativa.

---

# Validación histórica RECYM — PA217

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
