# Validación IEEE — formato estandarizado (v0.5)

**Fecha:** 2026-09-22  

## PDFs para revisión (formato armado tipo IEEE)

| Archivo | Formato | Páginas |
|---------|--------|---------|
| **[`RECYM_IEEE_standard_ES.pdf`](RECYM_IEEE_standard_ES.pdf)** | **2 columnas**, Times, Abstract—, Index Terms—, §§ romanos | 3 |
| **[`RECYM_IEEE_standard.pdf`](RECYM_IEEE_standard.pdf)** | Igual en inglés (envío) | 3 |
| `RECYM_IEEE_draft*.pdf` | Borrador 1 columna (contenido amplio, **no** tipografía IEEE) | ~8 |

Regenerar: `node docs/articulo_ieee/build_ieee_format.js` → exportar PDF con Word.

## Qué se estandarizó

- Letter, márgenes ~0.75″ / 0.625″  
- **Portada 1 columna:** título, autor, afiliación, email, Abstract—, Index Terms—  
- **Cuerpo 2 columnas:** I–VII + References  
- Times New Roman 10 pt, justificado  
- Figuras + Tabla I embebidas  
- Sin notas de repo (“draft”, separación informe) en el PDF de revisión  

## Contenido científico

- 2 párrafos con modelos matemáticos (asignación kWh + SpotLoad/LF dual)  
- Pseudocódigo Alg. 1–3  
- Arquitectura L1–L5 + 97 alimentadores  
- Validación: εP, MAE, IC Clopper–Pearson, δP, cierre 21/21  

## Veredicto

| Uso | ¿Listo? |
|-----|---------|
| Revisión visual “¿parece IEEE?” | **SÍ** — `RECYM_IEEE_standard_ES.pdf` |
| Envío ScholarOne T-PWRD | **AÚN NO** — falta plantilla oficial IEEE / IEEEtran + proofreading |
| Confundir con `doc/informe.pdf` | **NO** — productos distintos |

**Nota:** Este PDF **imita** IEEE (2 col.). La tipografía **oficial** de revista se obtiene pegando el texto EN en la plantilla IEEE Author Center / `IEEEtran.cls`.
