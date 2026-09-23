# Outline — Artículo científico IEEE (RECYM)

Documento de trabajo para el manuscrito. Cumple la estructura típica de **IEEE Transactions / Journals** y el estilo de citas **IEEE** (numeradas `[1]`, lista de referencias al final).

> Estado: **manuscrito draft v0.2** (EN + ES, con figuras).  
> Entregables en [`docs/articulo_ieee/`](articulo_ieee/):
> - [`MANUSCRIPT.md`](articulo_ieee/MANUSCRIPT.md) / [`MANUSCRIPT_ES.md`](articulo_ieee/MANUSCRIPT_ES.md)
> - [`RECYM_IEEE_draft.docx`](articulo_ieee/RECYM_IEEE_draft.docx) / [`RECYM_IEEE_draft_ES.docx`](articulo_ieee/RECYM_IEEE_draft_ES.docx)
> - [`references.bib`](articulo_ieee/references.bib) · [`figures/`](articulo_ieee/figures/)
> - [`RECYM_IEEEtran_skeleton.tex`](articulo_ieee/RECYM_IEEEtran_skeleton.tex)

---

## 1. Formato IEEE (checklist)

| Elemento | Norma |
|----------|--------|
| Plantilla | IEEE conference o journal (IEEEtran LaTeX / Word) |
| Título | Conciso, ≤ ~15 palabras, sin acrónimos no definidos |
| Autores | Nombre, afiliación, ORCID si aplica |
| Abstract | 150–250 palabras; problema → método → resultado → conclusión |
| Keywords | 4–6 términos Index Terms |
| Cuerpo | I. Introduction … VII. Conclusion (ajustar según journal) |
| Figuras / tablas | Caption debajo (fig) / encima (tabla); citadas en texto |
| Citas | Estilo IEEE: `[1]`, `[2]–[4]`; orden de aparición |
| Referencias | Lista numerada al final; formato IEEE |
| Unidades | SI; kW, kVAr, kWh, p.u. |

Herramientas sugeridas: **IEEEtran.cls** (LaTeX) o plantilla Word IEEE; BibTeX con `IEEEtran.bst`.

---

## 2. Estructura del manuscrito (propuesta)

### Title (borrador)

*RECYM: An Automated Multi-Feeder Workflow for Demand Allocation and Load-Flow Studies in CYMDIST Distribution Networks*

(Alternativa ES→EN a fijar con autores.)

### Abstract (esqueleto)

Distribution utilities require repeatable workflows to correct network models, allocate measured headroom demand, connect prospective spot loads, and compare situational versus projected load-flow cases. This paper presents **RECYM**, a software suite that couples CYMDIST/CymPy with a seven-step SPA and batch pipeline for Electro Dunas feeders. The method integrates network diagnostics, large-customer energy/power injection at SED nodes, kWh-based load allocation, locked three-phase spot loads, and dual load-flow scenarios. Results on feeder **PA217** (and optionally the 96-feeder system study) demonstrate …

### Index Terms

`Distribution networks`, `Load allocation`, `Load flow`, `CYMDIST`, `Power system modeling`, `Software tools`

---

### I. Introduction

1. Contexto: planificación de redes de distribución, calidad de modelo, clientes importantes, nuevas cargas.
2. Brecha: procesos manuales en CYMDIST; falta de trazabilidad situacional vs proyectado.
3. Contribuciones (bullet):
   - Arquitectura multi-alimentador (config + pipeline + SPA §§1–7).
   - Flujo acoplado diagnóstico → SED/EA-Pot → LoadAllocation → SpotLoad → LF dual.
   - Validación operativa en alimentador(es) reales Electro Dunas.
4. Organización del paper.

### II. Related Work

- Herramientas DMS / load allocation (CYME, OpenDSS, pandapower, etc.).
- Automatización COM/API de estudios de distribución.
- Reportes regulatorios / calidad de servicio (si aplica marco peruano NT / OSINERGMIN — citar normas).

*Citas IEEE numeradas desde la primera mención.*

### III. System Architecture

- Capas: UI SPA, API (FastAPI/Flask), pipeline, CymPy/COM, datos `.zxst`/`.mdb`.
- Fig. 1: diagrama de arquitectura (ver `docs/ARQUITECTURA.md`).
- Multi-feeder: `settings.json` + `config/feeders/<ID>.json`.

### IV. Proposed Workflow

1. Context & headroom measurement (§1).
2. Model quality gate — NetworkDiagnostic (§2).
3. Important customers → SED (EA→kWh, Pot→kW) + load allocation (§3).
4. New concentrated SpotLoad, phase split P/3 Q/3, Locked (§4).
5. Situational vs projected load flow (§5).
6. Delivery reports (§6); optional optimization (§7).
- Fig. 2: flowchart de campaña (`FLUJO_TRABAJO.md`).
- Algoritmos / reglas (pseudocódigo corto de allocation y conmutación de escenario).

### V. Case Study / Experimental Setup

- Utility: Electro Dunas; feeder PA217 (`NET_2030_179_PA217`); Vll = 22.9 kV.
- Software: CYMDIST 9.2 R1, CymPy, Python 3.7 win32, RECYM SPA v6.
- Inputs: Excel cabecera, suministrocliente, clientesimportantes, Control_Simulacion.
- Metrics: diagnostic error counts; EA/Pot precision tolerances; LF convergence; voltage/loading maps.

### VI. Results and Discussion

- Antes/después del gate de calidad (§2).
- Verificación clientes SED (N SED, kWh/kW).
- SpotLoad ejemplo (p.ej. 1400 kW → 466.67 kW/fase).
- Comparación situacional vs proyectado (tensiones, cargabilidad).
- Tabla I / Fig. 3–N.
- Limitaciones: dependencia COM, sesión única, dry_run, etc.

### VII. Conclusion

- Resumen de aportes y resultados.
- Trabajo futuro: más alimentadores, optimización §7 en producción, métricas regulatorias.

### Appendix (opcional)

- Mapa de endpoints API; secuencia `run_sequence`.

### References

Lista IEEE (ejemplos placeholder — **reemplazar con fuentes reales**):

```
[1] CYME International, “CYMDIST User Guide,” Eaton, version 9.2.
[2] W. H. Kersting, Distribution System Modeling and Analysis, 4th ed. CRC Press, 2017.
[3] IEEE Std 1547-2018, IEEE Standard for Interconnection and Interoperability of Distributed Energy Resources...
[4] R. C. Dugan and T. E. McDermott, “An open source platform for collaborating on smart grid research,”
     in Proc. IEEE Power Energy Soc. Gen. Meeting, 2011.
[5] L. F. Ochoa et al., “Distribution network capacity assessment: Incorporating smart operation,”
     IEEE Trans. Power Syst., ...
```

*(Completar con papers de load allocation, DMS, y normas locales al redactar el paper.)*

---

## 3. Estilo de citas IEEE (recordatorio)

**En el texto:**

- Una fuente: `as reported in [1].`
- Varias: `several methods [2], [5], [7]` o `[2]–[4]`.
- Autor + cita: `Kersting [2] presents…`

**En References (ejemplos):**

```
[1] A. Author, “Title of paper,” IEEE Trans. Power Syst., vol. 34, no. 2, pp. 100–110, Mar. 2019.
[2] B. Author and C. Author, Title of Book, 2nd ed. City, Country: Publisher, 2020.
[3] D. Author et al., “Conference paper title,” in Proc. IEEE PES Gen. Meeting, Chicago, IL, USA, 2017, pp. 1–5.
[4] Name of Manual/Standard, Organization, Year.
```

No usar APA/Harvard en el manuscrito final.

---

## 4. Figuras a preparar desde el repo

| Fig. | Fuente sugerida |
|------|-----------------|
| Arquitectura | Diagrama §1 de `ARQUITECTURA.md` |
| Flujo §§1–7 | Mermaid de `FLUJO_TRABAJO.md` |
| Topología / ubicación SpotLoad | `data/output/feeders/PA217/informe_images/topologia.png` |
| Tensión / cargabilidad | `situacional_*.png`, `proyectado_*.png` |
| Tablero errores | Export desde `diagnostics/tablero.json` |

---

## 5. Próximos pasos (artículo)

1. Completar **autores / afiliación / ORCID** y elegir venue (Transactions vs Conference).
2. Pegar el draft en la **plantilla oficial IEEE** (Word o IEEEtran) — el `.docx` actual es borrador de contenido, no tipografía final de revista.
3. Insertar **Fig. 1–5** (arquitectura, flujo, topología, tensión/cargabilidad) con captions IEEE.
4. Ampliar Results con tablas de LF situacional vs proyectado (mín./máx. V, % loading).
5. Revisar bibliografía [1]–[20] (páginas/DOI oficiales) y añadir 5–10 refs locales/regulatorias si el venue lo pide.
6. Corrección de inglés técnico + plagiarism/format check IEEE.
