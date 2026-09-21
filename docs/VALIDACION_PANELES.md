# Validación paneles / módulos RECYM

**Fecha:** 2026-09-21 · **UI:** v5.5 · **Resultado:** PASS (54/54)

Informe JSON: `data/output/system/validation_panels_report.json`

Ejecutar de nuevo:

```bat
.tools\python37-win32\python.exe -u src\analysis\validate_panels.py --feeder IN112 --global
```

## Alcance verificado

| Modo | Qué prueba | Estado |
|------|------------|--------|
| **Un alimentador** (`IN112`) | Contexto, cabecera preview, armar tabla NIS, gate, informes, suite | PASS |
| **Global BD** | `force=1` lista **96 redes** CYMDIST + catálogo en disco | PASS |
| **Módulos** | 19 imports pipeline/analysis/opt | PASS |

## Panel por panel

| Panel | Objetivo | Evidencia |
|-------|----------|-----------|
| Arranque | UI viva, no cuelga | ping ~ms, v5.5 |
| §1 Contexto/cabecera | BD/estudios + P/Q sin COM | listas OK · preview_only OK |
| Calidad | Soft sin CYMDIST · force = 96 | memory/disk + cympy |
| §2 Clientes | Archivos, 65 radiales, armar tabla 1 feeder | OK |
| §5 Informes | status / rutas / meta | OK |
| §6 Optimización | Endpoint responde JSON | OK |
| §7 Suite | Entorno CYME/MDB/CymPy | OK |
| Config | DEMO01 / IN112 / PA217 | OK |

## Notas operativas

- **Uno a uno:** en UI marque un alimentador (Calidad o §2) y ejecute la acción.
- **Global:** Calidad → *Diagnosticar sistema (96)* / *Actualizar lista* (catálogo completo).
- Artefactos §4 LoadFlow / entrega completa siguen siendo opcionales hasta correr flujos.
- Escrituras CYMDIST (guardar cabecera, EA/Pot, distribución, flujo) van bajo **lock COM** para no matar la UI.
