# Separación: Informe de entrega ≠ Artículo científico

Estos son **productos distintos**. No deben mezclarse ni presentarse como el mismo documento.

| | **Informe de entrega** | **Artículo científico IEEE** |
|--|------------------------|------------------------------|
| **Qué es** | Documento técnico-comercial de una **ejecución** (modelo CYMDIST + resultados LF de un caso) | Documento de **desarrollo y aplicación** de la suite RECYM (método, arquitectura, validación) |
| **Para quién** | Concesionaria / expediente / cliente solicitante | Comunidad académica / revista / conferencia |
| **Carpeta** | `doc/` | `docs/articulo_ieee/` |
| **Archivos** | `informe.docx`, `informe.pdf`, `justificacion.xlsx`, preview | `MANUSCRIPT.md`, `MANUSCRIPT_ES.md`, `RECYM_IEEE_draft*.pdf`, refs |
| **Contenido típico** | Antecedentes del solicitante, objeto, tensión/cargabilidad del punto, conclusiones de factibilidad, recomendaciones de campo | Introducción, estado del arte, arquitectura RECYM, flujo §§1–7, experimentación multi-alimentador, resultados de **validación del software**, discusión, referencias IEEE |
| **Origen de datos** | Salida del pipeline §6 sobre un estudio `.zxst` | Métricas/artefactos de campaña usados como **evidencia de que RECYM funciona**; no sustituye al informe |
| **Cliente / expediente** | Sí (nombre, RUC, carta, ubicación) | Solo contexto mínimo de caso (p. ej. alimentador + kW); **no** es el informe del expediente |

## Regla operativa

1. Generar o editar el **informe** solo en `doc/` (plantillas + fill desde `data/output/feeders/<ID>/`).
2. Redactar o revisar el **artículo** solo en `docs/articulo_ieee/`.
3. El artículo puede **citar** artefactos de ejecución (`loadflow`, `precision_report`, mapas) como validación experimental de RECYM.
4. El artículo **no** debe copiar la narrativa del informe (antecedentes del solicitante, objeto del expediente, recomendaciones de energización como si el paper fuera la respuesta a la carta).
5. El informe **no** debe incluir secciones IEEE (Abstract, Index Terms, Related Work, References académicas).

## Flujo en el proyecto

```
Ejecución RECYM (PA217 u otro)
        │
        ├──► artefacto técnico  ──►  doc/informe.*     (entrega / expediente)
        │
        └──► métricas + mapas   ──►  docs/articulo_ieee/*  (paper: desarrollo + aplicación)
```

Ambos salen del mismo motor; **son archivos y finalidades individuales**.
