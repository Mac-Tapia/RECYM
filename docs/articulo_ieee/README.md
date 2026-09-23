# Artículo científico IEEE — RECYM (desarrollo y aplicación)

**No confundir con el informe de entrega.**  
Informe operativo → carpeta `doc/` · Separación → [`../SEPARACION_INFORME_ARTICULO.md`](../SEPARACION_INFORME_ARTICULO.md)

## Qué es

Manuscrito sobre el **desarrollo del proyecto RECYM** (arquitectura, flujo §§1–7, integración CYMDIST/CymPy) y su **aplicación/validación** sobre el corpus multi-alimentador Electro Dunas (97 configs; muestra experimental PA217).

Usa métricas y figuras de ejecución como **evidencia experimental del software**, no como sustituto del informe de expediente.

## Entregables (solo artículo)

| Archivo | Uso |
|---------|-----|
| [`MANUSCRIPT.md`](MANUSCRIPT.md) | Texto completo **EN** |
| [`MANUSCRIPT_ES.md`](MANUSCRIPT_ES.md) | Texto completo **ES** |
| [`RECYM_IEEE_standard_ES.pdf`](RECYM_IEEE_standard_ES.pdf) / [`RECYM_IEEE_standard.pdf`](RECYM_IEEE_standard.pdf) | **PDF formato IEEE 2 columnas** (revisión) |
| [`RECYM_IEEE_draft_ES.pdf`](RECYM_IEEE_draft_ES.pdf) | Borrador 1 columna (contenido amplio) |
| [`build_ieee_format.js`](build_ieee_format.js) | Genera Word/PDF tipografía tipo IEEE |
| [`references.bib`](references.bib) | BibTeX |
| [`IEEE_VALIDACION.md`](IEEE_VALIDACION.md) | Checklist pre-envío |
| [`figures/`](figures/) | Figuras del paper (pueden originarse en corridas, pero viven aquí para el artículo) |

## Autor

- **Mac Tapia Ccosyo** · Electro Dunas S.A.A. · mtapia@electrodunas.com

## Qué no va en el artículo

- Narrativa de expediente (carta, RUC, recomendaciones de energización al cliente)
- Plantillas `doc/informe.docx` / justificación Excel
- Presentar el paper como “el informe de factibilidad”

## Regenerar Word / PDF

```bat
node docs\articulo_ieee\build_docx.js
```

Luego exportar PDF desde Word o el flujo ya usado en el repo.
