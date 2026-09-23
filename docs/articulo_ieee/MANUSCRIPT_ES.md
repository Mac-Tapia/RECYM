# RECYM: Flujo automatizado multi-alimentador para asignación de demanda y estudios de flujo de carga en redes de distribución CYMDIST

**Borrador de manuscrito — estructura IEEE (Transactions / Conference)**  
**Estilo de citas:** IEEE numerado `[n]` en orden de aparición  
**Estado:** Draft v0.3 ES — marco teórico, desarrollo y discusión reforzados con tesis y artículos  
**Autor:** Mac Tapia Ccosyo  
**Afiliación:** Electro Dunas S.A.A. (empresa concesionaria)  
**Autor de correspondencia:** mtapia@electrodunas.com

> Versión en español para revisión interna.  
> Para *IEEE Transactions on Power Delivery* u otros journals PES, usar `MANUSCRIPT.md` (EN) como envío.  
> Auditoría estructural: `IEEE_VALIDACION.md`. Figuras: `figures/`.

---

> **Separación de productos:** este archivo es el *artículo científico* (desarrollo y aplicación de RECYM). El *informe de entrega* (modelo + resultados de una ejecución para expediente) vive en doc/informe.* y es otro documento. Ver docs/SEPARACION_INFORME_ARTICULO.md.


## Resumen

Las empresas de distribución requieren procedimientos repetibles para limpiar modelos de red, asignar la demanda medida en cabecera, inyectar clientes importantes y cargas concentradas prospectivas, y comparar casos situacional versus proyectado. Este artículo presenta RECYM, una suite multi-alimentador que acopla CYMDIST/CymPy con una aplicación de página única de siete pasos y un pipeline por lotes. El flujo integra diagnóstico de red, mapeo de energía y potencia de grandes clientes a SED, asignación de carga por kWh vía API COM de CYMDIST, SpotLoads trifásicas bloqueadas, escenarios duales de flujo de carga y generación automatizada de artefactos de campaña (distintos del informe de expediente en doc/). RECYM ya está conectado a la base Access de Electro Dunas con **97 configuraciones de alimentador** y múltiples estudios CYMDIST (`.zxst`) por alimentador; el alimentador **PA217** (22,9 kV) se reporta aquí como **muestra experimental representativa**. En PA217 la campaña cerró con cero problemas de diagnóstico, clientes importantes verificados dentro de tolerancia, asignación balanceada (9537,9 kW frente a 9537,88 kW), SpotLoad prospectiva de 1420 kW y flujos situacional/proyectado exitosos con deltas cuantificados de P/Q/S en cabecera.

**Palabras clave**—Asignación de carga, CYMDIST, estudios de demanda, flujo de carga, modelado de sistemas de potencia, redes de distribución, herramientas de software.

---

## I. Introducción

La planificación de redes de distribución depende de modelos trifásicos detallados para evaluar perfiles de tensión, cargabilidad térmica y el impacto de nuevos clientes [1], [2]. Los motores comerciales de asignación de carga y flujo desbalanceado, entre ellos CYMDIST, son estándar en utilities [3], [4]. No obstante, las campañas productivas aún combinan correcciones manuales de equipos, transferencia de energía/demanda de facturación a nodos SED, bloqueo de cargas, conexión de SpotLoads y regeneración de reportes situacional versus proyectado.

La calidad del resultado está condicionada por la consistencia del modelo y por la regla de asignación elegida [1], [5], [6]. La literatura muestra que la asignación por energía (kWh) suele superar a la asignación por kVA conectado cuando se dispone de mediciones de consumo [7], [8], y que los flujos radiales/débilmente mallados se resuelven de forma eficiente con métodos de compensación y barrido [9], [10]. Herramientas abiertas (OpenDSS, pandapower) permiten automatizar experimentos [11], [12]; varias tesis han convertido o validado modelos CYMDIST hacia esas plataformas [13]–[15]. En Latinoamérica, trabajos de grado y maestría documentan integración y estudios en CYMDIST sobre alimentadores reales [16], [17], y tesis doctorales abordan reconfiguración y pérdida con OpenDSS [18]. Persiste, sin embargo, una brecha operativa: orquestar *sobre* CYMDIST nativo (sin migrar el sistema de registro) un flujo auditable multi-alimentador que una compuerta de calidad, clientes importantes, asignación por kWh, SpotLoad Locked y comparación situacional/proyectada.

Este artículo presenta **RECYM** (*Redes / Electro Dunas CYMDIST Management*), que:

1. Ofrece una arquitectura por capas (UI SPA, API REST/jobs, pipeline Python, núcleo CymPy/COM) ya desplegada sobre **97 alimentadores** y múltiples estudios en la BD CYMDIST de Electro Dunas;
2. Formaliza y automatiza una campaña de siete pasos anclada en teoría de asignación y flujo;
3. Reporta el cierre extremo a extremo en **PA217 como muestra experimental representativa**, con métricas de precisión, balance, LF situacional/proyectado y contraste frente a autores similares.

La Sección II desarrolla el marco teórico y trabajos relacionados. La III describe la arquitectura. La IV presenta modelos matemáticos, algoritmos y el plan de validación estadística. La V presenta el caso de estudio. La VI discute resultados frente a literatura afín. La VII concluye.

---

## II. Marco teórico y trabajos relacionados

### A. Modelado trifásico y flujo de carga en distribución

Kersting [1] y Gönen [2] establecen la representación de líneas, transformadores y cargas desbalanceadas. Willis [3] sitúa estos modelos en la planificación de capacidad. Para redes radiales o débilmente malladas, Shirmohammadi *et al.* [9] formularon un flujo por compensación que evita la inversión densa de Jacobianos de transmisión; Cheng y Shirmohammadi [10] lo extendieron a trifásico con generadores dispersos, reguladores y capacitores, base conceptual de muchos motores comerciales y de OpenDSS [11]. Momoh [19] enfatiza la automatización de distribución como capa de software sobre dichos algoritmos.

### B. Teoría de asignación de demanda (load allocation)

La asignación reparte la demanda de cabecera \(P_{\mathrm{cab}}\) entre cargas aguas abajo. En la forma proporcional por energía, para el subconjunto de cargas *no bloqueadas* \(\mathcal{U}\),

\begin{equation}
P_i = P_{\mathrm{cab}}^{\mathrm{res}} \frac{E_i}{\sum_{j\in\mathcal{U}} E_j},\qquad i\in\mathcal{U},
\end{equation}

donde \(E_i\) es el consumo de energía (kWh) y \(P_{\mathrm{cab}}^{\mathrm{res}}\) es el residual tras restar las cargas Locked [4], [7]. La alternativa por kVA conectado usa potencias nominales de transformador como pesos. Arritt *et al.* [7] compararon estimadores con AMI y mostraron el impacto material de la regla elegida. Peppanen *et al.* [8] concluyeron, sobre un conjunto utility a gran escala, que la asignación por kWh de transformador supera de forma consistente a la por kVA. Kersting y Phillips [20] formalizaron la asignación asistida por lecturas AMR. Ghosh *et al.* [5] y Baran y Kelley [6] relacionan el modelado de carga con estimación de estado, subrayando que errores de asignación se propagan al flujo.

CYMDIST implementa plantillas Connected+Total con consumo kWh, factor de carga y factor de pérdidas [4]. Chumbi y Verdugo [16] documentaron en CENTROSUR la asignación por kVA conectados con tolerancia 0,001 % previa al flujo por caída de tensión; Ramos y Espinoza [17] usaron distribución horaria en CYMDIST sobre un alimentador peruano (Caudivilla-51) como base de escenarios con GD fotovoltaica.

### C. Automatización, CYMDIST y plataformas abiertas

Dugan y McDermott [11] popularizaron OpenDSS como motor scriptable; Thurner *et al.* [12] hicieron lo propio con pandapower. Ramachandran [13] (M.Sc., West Virginia) convirtió alimentadores AEP desde CYMDIST a OpenDSS con mapeo componente a componente y validó flujos. Estudios posteriores de maestría/doctorado repiten el patrón de exportación CYME/CYMDIST → OpenDSS para flexibilidad de escenarios [14], [15]. En contraste, RECYM **no migra** el modelo: orquesta COM/CymPy sobre el `.zxst`/`.mdb` oficial, enfoque más cercano a la operación diaria de una concesionaria que ya estandarizó CYMDIST.

Peppanen *et al.* [21] y Wang *et al.* [22] muestran cómo AMI mejora calibración y conciencia situacional; RECYM usa hoy energía/potencia de clientes importantes y cabecera de medidor, dejando AMI masivo como extensión natural.

### D. Capacidad, nueva carga y escenarios duales

Los estudios de *hosting capacity* comparan un caso base con uno incremental bajo límites de tensión y térmicos [23], [24]. Alturki [25] (Ph.D.) formaliza optimización de capacidad de alojamiento; Rylander *et al.* [23] y Ding y Mather [24] ofrecen métodos streamlining y sensibilidad. IEEE Std 1547 [26] enmarca interconexiones. La dicotomía situacional/proyectado de RECYM es la analogía operativa para una SpotLoad de cliente MT: mismo modelo de demanda residual, conmutando solo la conexión de la carga nueva — coherente con la lógica de casos base/incremental de esa literatura, aplicada a factibilidad comercial.

### E. Brecha y posicionamiento

| Enfoque | Autores representativos | Limitación respecto a RECYM |
|---------|-------------------------|------------------------------|
| Conversión CYMDIST→OpenDSS | Ramachandran [13]; tesis afines [14], [15] | Abandona el sistema de registro nativo |
| Asignación/AMI | Arritt [7]; Peppanen [8], [21] | No cierran campaña UI+informes+SpotLoad |
| Integración CYMDIST utility | Chumbi & Verdugo [16]; Ramos & Espinoza [17] | Procesos poco orquestados/multi-feeder |
| Reconfiguración / OpenDSS | Puma Ttito [18] | Optimización topológica, no campaña de demanda |

RECYM ocupa el nicho de **orquestación industrial multi-alimentador sobre CYMDIST**, con compuerta de calidad y evidencia auditable.

---

## III. Arquitectura del sistema

RECYM se organiza en cinco capas \(L_1,\ldots,L_5\) (Fig. 1):

\begin{equation}
L_1\xrightarrow{\mathrm{HTTP/JSON/SSE}} L_2\xrightarrow{\mathrm{dominio}} L_3\xrightarrow{\mathrm{CymPy/COM}} L_4\xrightarrow{\mathrm{I/O}} L_5,
\end{equation}

donde \(L_1\) es la SPA React (§§1–7), \(L_2\) la API FastAPI/jobs/SSE con puente Flask, \(L_3\) el dominio Python (`pipeline`, `analysis`, `optimization`), \(L_4\) el núcleo CymPy/COM CYMDIST y \(L_5\) los activos externos (`.zxst`, `.mdb` compartida, Excel). Los jobs asíncronos evitan *timeouts* de UI durante sesiones COM [19]. La configuración es el par \((\mathcal{S},\mathcal{F})\): settings globales \(\mathcal{S}\) y catálogo \(\mathcal{F}=\{f_1,\ldots,f_{97}\}\) más ELD. Escritura con estudio usable y `dry_run=false`; asignación y flujo prefieren COM [4].

---

## IV. Modelos matemáticos y algoritmos

### A. Modelo de cabecera, cargas Locked y asignación por kWh

Sea \(P_{\mathrm{cab}}\) la potencia activa de cabecera y \(\mathcal{L}\) el conjunto de cargas. Se particiona \(\mathcal{L}=\mathcal{F}\cup\mathcal{U}\) en clientes Locked \(\mathcal{F}\) y residuales \(\mathcal{U}\). Con energía \(E_i\) (kWh) y potencia fija \(P_j^{\mathrm{fix}}\),

\begin{equation}
P_{\mathrm{cab}}^{\mathrm{res}} = P_{\mathrm{cab}} - \sum_{j\in\mathcal{F}} P_j^{\mathrm{fix}},\qquad
P_i = P_{\mathrm{cab}}^{\mathrm{res}}\frac{E_i}{\sum_{u\in\mathcal{U}} E_u},\quad i\in\mathcal{U}.
\end{equation}

El **error de balance de asignación** de validación es

\begin{equation}
\varepsilon_P = \frac{\left|\sum_{i\in\mathcal{L}} P_i - P_{\mathrm{cab}}\right|}{P_{\mathrm{cab}}}\times 100\%.
\end{equation}

La precisión de escritura frente a metas \((E_i^\star,P_i^\star)\) usa \(\lvert\Delta E_i\rvert\) y \(\lvert\Delta P_i\rvert\), aceptadas si \(\lvert\Delta E_i\rvert\le 0{,}5\,\mathrm{kWh}\) y \(\lvert\Delta P_i\rvert\le 0{,}01\,\mathrm{kW}\). Sobre el conjunto aceptado \(\mathcal{A}\),

\begin{equation}
\mathrm{MAE}_P=\frac{1}{\lvert\mathcal{A}\rvert}\sum_{i\in\mathcal{A}}\lvert\Delta P_i\rvert,\quad
\mathrm{RMSE}_P=\sqrt{\frac{1}{\lvert\mathcal{A}\rvert}\sum_{i\in\mathcal{A}}(\Delta P_i)^2}.
\end{equation}

Este párrafo establece el **primer modelo matemático cerrado** de RECYM (asignación por kWh) [7], [8], [4].

### B. Modelo de SpotLoad por fase y escenarios duales de flujo

Una SpotLoad concentrada \((P_{3\phi},Q_{3\phi})\) en nodo existente se reparte por fase y queda Locked:

\begin{equation}
P_\phi=\frac{P_{3\phi}}{3},\quad Q_\phi=\frac{Q_{3\phi}}{3},\quad \phi\in\{A,B,C\}.
\end{equation}

Sea \(c\in\{0,1\}\) el flag de conexión del conjunto prospectivo \(\mathcal{S}\). El caso **situacional** resuelve el flujo desbalanceado \(F\) con \(c=0\); el **proyectado** con \(c=1\):

\begin{equation}
y^{\mathrm{sit}}=F(x;\,c=0),\qquad y^{\mathrm{prj}}=F(x;\,c=1),
\end{equation}

con \(y\) apilando \(P,Q,S\) de cabecera, tensiones y cargabilidades [9], [10], [4]. El impacto incremental es \(\Delta y=y^{\mathrm{prj}}-y^{\mathrm{sit}}\) y \(\delta_P=100\cdot\Delta P/P^{\mathrm{sit}}\). El desbalance de fases de la SpotLoad se monitorea con \(\max_{\phi,\psi}\lvert P_\phi-P_\psi\rvert\). Este párrafo establece el **segundo modelo matemático** (SpotLoad + LF dual), alineado a lógica base/incremental [23]–[25].

### C. Pseudocódigo

**Algoritmo 1** — Asignación residual por kWh  
**Entrada:** \(P_{\mathrm{cab}}\), \(\mathcal{F}\), \(\mathcal{U}\) con \(E_i\)  
1: \(P_{\mathrm{cab}}^{\mathrm{res}} \leftarrow P_{\mathrm{cab}}-\sum_{j\in\mathcal{F}} P_j^{\mathrm{fix}}\)  
2: \(E_{\mathrm{tot}} \leftarrow \sum_{u\in\mathcal{U}} E_u\)  
3: **para** cada \(i\in\mathcal{U}\) **hacer** \(P_i \leftarrow P_{\mathrm{cab}}^{\mathrm{res}}\cdot E_i/E_{\mathrm{tot}}\)  
4: Escribir vía COM LoadAllocation; calcular \(\varepsilon_P\) (3)  
5: **devolver** cargas, \(\varepsilon_P\)

**Algoritmo 2** — Flujo dual situacional/proyectado  
**Entrada:** estudio \(x\), conjunto SpotLoad \(\mathcal{S}\)  
1: Desconectar \(\ell\in\mathcal{S}\); \(y^{\mathrm{sit}}\leftarrow\mathrm{COM\_LoadFlow}(x)\)  
2: Conectar \(\ell\in\mathcal{S}\) con (5); \(y^{\mathrm{prj}}\leftarrow\mathrm{COM\_LoadFlow}(x)\)  
3: \(\Delta y\leftarrow y^{\mathrm{prj}}-y^{\mathrm{sit}}\); exportar mapas/escalares  
4: **devolver** \(y^{\mathrm{sit}},y^{\mathrm{prj}},\Delta y\)

**Algoritmo 3** — Orquestación campaña §§1–7  
1: Enlazar BD+estudio; cargar \((P_{\mathrm{cab}},Q_{\mathrm{cab}})\)  
2: Diagnosticar hasta cero Error/Warning/Hint  
3: Aplicar clientes importantes; Algoritmo 1; verificar (4)  
4: Insertar SpotLoad Locked (5); Algoritmo 2  
5: Persistir artefactos de campaña; checklist de cierre  

### D. Compuerta de calidad y plan de validación estadística

Sea \(N_{\mathrm{msg}}\) el número de mensajes NetworkDiagnostic. La compuerta exige \(N_{\mathrm{msg}}=0\) antes de escribir demanda [5], [6]. Chequeos estadísticos en la muestra: (i) \(\varepsilon_P\) frente a umbral de ingeniería; (ii) tasa de acierto \(\hat{p}=\lvert\mathcal{A}\rvert/n\) con IC 95% Clopper–Pearson; (iii) MAE/RMSE de \(\Delta P,\Delta E\); (iv) desbalance de fases; (v) deltas pareados \(\Delta P,\Delta Q,\Delta S\) y \(\delta_P\); (vi) cierre binario de campaña (21/21). Con errores de escritura ~0, un \(t\)-test pareado sobre \(\Delta P_i\) es degenerado; se reportan magnitudes exactas frente a tolerancias declaradas.

## V. Caso de estudio / experimentación

### A. Corpus multi-alimentador versus muestra

RECYM opera sobre el corpus productivo CYMDIST de Electro Dunas: una base Access compartida (.mdb) y **múltiples estudios** (.zxst) en projects_dir, con **97 configuraciones** ya registradas en config/feeders/ (≈96 habilitadas) más el estudio ELD. Cada alimentador tiene `network_id`, ruta de estudio, libros de control/catálogo y árbol data/output/feeders/<ID>/. El modo batch (--all-feeders) y el header SPA X-Feeder seleccionan cualquier alimentador configurado sin cambiar código.

**PA217 no es el único alimentador disponible**; es la **muestra experimental** usada para validar el *software y el flujo* RECYM (campaña §§1–7: cabecera, clientes importantes, SpotLoad prospectiva MT de 1420 kW, mapas duales, cierre automatizado). Los resultados ilustran la **validez del método**, no sustituyen el informe de entrega del expediente (doc/informe.*). El mismo pipeline aplica al resto del catálogo de 97.

### B. Red y software de la muestra

- **Utility:** Electro Dunas (Perú), SET Paracas.
- **Muestra:** PA217, NET_2030_179_PA217, \(V_{LL}=22{,}9\,\mathrm{kV}\).
- **Inventario:** 1324 nodos, 1324 secciones, 253 cargas.
- **Estudio / BD:** PA217.zxst, Access 20260919.mdb (compartida con el catálogo).
- **Software:** CYMDIST 9.2, CymPy, Python 3.7 win32, RECYM SPA v6.
- **SpotLoad prospectiva MT (muestra):** **1420 kW** en nodo existente (caso de uso industrial). La narrativa de cliente/expediente pertenece al informe de entrega, no a este artículo.

### C. Medición de cabecera (muestra)

Medidor L-PA235 (2026-03-03): \(P=9537{,}88\) kW, \(Q=2587{,}65\) kvar, \(S=9882{,}67\) kVA, \(P\) promedio 6204,65 kW, factor de carga 65,05 %.

### D. Protocolo experimental

Ejecutado sobre el estudio vivo PA217 (dry_run=false):

1. Aplicar BD + estudio; cargar cabecera (§1).
2. NetworkDiagnostic hasta 0 Error/Warning/Hint (§2).
3. Armar tabla de clientes; aplicar EA→KWH / Pot→kW Locked; LoadAllocation COM por kWh (§3).
4. Conectar SpotLoad Locked en nodo existente (§4).
5. LoadFlow COM situacional (SpotLoad off) y proyectado (SpotLoad on); exportar mapas (§5).
6. Generar artefactos de campaña y cierre automatizado §§1–7 (la emisión del informe Word de expediente es un producto aparte en doc/).

Métricas [7], [8], [13], [16]. Artefactos: data/output/feeders/PA217/.

---

## VI. Resultados y discusión

### A. Calidad del modelo (muestra PA217)

Post-campaña: **0** mensajes / **0** problemas (compuerta §2), condición necesaria según [5], [6], [21].

### B. Precisión de clientes y chequeos estadísticos

Doce filas candidatas; **11** SED OK (\(n_{\mathrm{fail}}=0\), \(n_{\mathrm{skip}}=1\)); tasa \(\hat{p}=11/11=1{,}00\) (IC 95% Clopper–Pearson \([0{,}72;\,1{,}00]\) para \(n=11\)). \(\mathrm{MAE}_P=\mathrm{RMSE}_P=0\) kW y \(\mathrm{MAE}_E=\mathrm{RMSE}_E=0\) kWh bajo tolerancias \(0{,}01\,\mathrm{kW}/0{,}5\,\mathrm{kWh}\) (Tabla I; Fig. 8). \(\sum P^{\mathrm{fix}}=7896{,}28\,\mathrm{kW}\).

### C. Balance de asignación

LoadAllocation COM: \(\sum P=9537{,}87278\,\mathrm{kW}\) vs \(P_{\mathrm{cab}}=9537{,}88\,\mathrm{kW}\), \(\varepsilon_P\approx 7{,}6\times 10^{-5}\%\) (eq. 3). Suite T1–T4 OK. Consistente con [7], [8].

### D. SpotLoad prospectiva

**1420 kW** Locked (Fig. 3). Reparto (eq. 5): verificación \(466{,}67/466{,}67/466{,}67\,\mathrm{kW}\) para 1400 kW (\(\max\lvert P_\phi-P_\psi\rvert=0\)). Huérfano 0 kW desconectado.

### E. Flujos duales y deltas pareados

Salidas COM LoadFlow de la campaña RECYM en PA217 (Figs. 4–7)—evidencia de la herramienta, no el documento `doc/informe.*`:

**TABLA III** — Cabecera situacional vs proyectado (muestra PA217)

| Magnitud | Situacional | Proyectado | \(\Delta\) | Rel. |
|----------|------------:|-----------:|----------:|------:|
| \(V_{\mathrm{cab}}\) A/B/C (%) | 99,84 / 99,84 / 99,84 | 99,84 / 99,84 / 99,84 | 0,00 pp | — |
| Caída (pp) | 0,16 | 0,16 | 0,00 | — |
| \(P\) (kW) | 10156,0 | 11900,0 | +1744,0 | \(\delta_P=+17{,}17\%\) |
| \(Q\) (kvar) | 3301,0 | 4287,0 | +986,0 | +29,87% |
| \(S\) (kVA) | 10679,0 | 12648,7 | +1969,7 | +18,44% |
| Factor de potencia (%) | 95,10 | 94,08 | −1,02 | — |

Tensión de cabecera dentro de ±5 % MT. Cierre **21/21** (Fig. 9). Compuerta \(N_{\mathrm{msg}}=0\).

### F. Discusión contrastada con autores similares

**TABLA II**  
CONTRASTE CON TRABAJOS AFINES

| Trabajo | Dominio | Similitud | Diferencia / aporte RECYM |
|---------|---------|-----------|---------------------------|
| Arritt *et al.* [7]; Peppanen *et al.* [8] | Asignación kWh vs kVA | Pesos por energía | Locked+residual+UI multi-feeder |
| Ramachandran [13] | CYMDIST→OpenDSS | Validación en alimentador real | Conserva CYMDIST nativo (COM) |
| Chumbi & Verdugo [16] | Integración CYMDIST utility | Multi-alimentador, asignación+LF | **97 alimentadores** + §§1–7 + SpotLoad dual + jobs |
| Ramos & Espinoza [17] | CYMDIST en Perú | Uso local de CYMDIST | Factibilidad MT SpotLoad + auditoría |
| Rylander [23]; Alturki [25] | Hosting / incremental | Lógica base vs incremental | Aplicado a SpotLoad comercial MT |
| Puma Ttito [18] | Optimización topológica | Motores de distribución | Demanda/factibilidad primero; §7 después |

### G. Limitaciones

(i) Acoplamiento Windows/COM; (ii) integridad del .zxst; (iii) fallback COM; (iv) §7 no es el foco métrico de la muestra PA217. **Las tablas numéricas detalladas se reportan para un alimentador muestra (PA217)** aunque el catálogo ya tiene **97 alimentadores y múltiples estudios**; la agregación de KPIs a toda la flota, AMI [21], [22] y puntuación regulatoria [27], [28] quedan como trabajo futuro.

---

## VII. Conclusión

RECYM automatiza sobre CYMDIST una campaña multi-alimentador anclada en teoría de asignación por kWh [7], [8] y flujo trifásico [9], [10], ya configurada para **97 alimentadores Electro Dunas** y múltiples estudios .zxst sobre una BD Access compartida. Tomando **PA217 como muestra experimental representativa**, se lograron cero problemas de diagnóstico, precisión de clientes, balance de cabecera, SpotLoad de 1420 kW, deltas LF situacional/proyectado (Tabla III) y cierre 21/21. Trabajo futuro: KPIs de flota sobre el catálogo completo, puntuación regulatoria [27], AMI y endurecimiento de optimización §7 / reconfiguración [18], [19].

---

## Apéndice A — 
un_sequence (extracto)

alidate_inputs → 
etwork_diagnostic → sync_equipment → uild_corrections → ulk_fix → ix_base_voltages → 
etwork_diagnostic_after → inventory_loads → uild_clientes → pply_clientes → erify_precision → demand_allocation → 
eport.

## Apéndice B — Fuentes de figuras (artefactos reales)

| Fig. | Fuente |
|------|--------|
| 1–2 | Diagramas de arquitectura / flujo |
| 3 | Mapa de campaña topologia.png (SpotLoad 1420 kW) → figures/ |
| 4–5 | Mapas LF situacional_*.png / proyectado_*.png → figures/ |
| 6–7 | Gráficos desde escalares LF de campaña (no desde doc/informe.docx) |
| 8 | clientes/precision_report.json |
| 9 | demand/cierre_1_7_report.json (21/21) |

---

## Referencias

[1] W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed. Boca Raton, FL, USA: CRC Press, 2017.

[2] T. Gönen, *Electric Power Distribution Engineering*, 3rd ed. Boca Raton, FL, USA: CRC Press, 2014.

[3] H. L. Willis, *Power Distribution Planning Reference Book*, 2nd ed. New York, NY, USA: Marcel Dekker, 2004.

[4] Eaton CYME, *CYMDIST Reference Manual / How-to Tutorials* (Load Allocation, Load Flow), version 9.2. Saint-Bruno, QC, Canada: Eaton, 2022.

[5] A. K. Ghosh, D. L. Lubkeman, and R. H. Jones, “Load modeling for distribution circuit state estimation,” *IEEE Trans. Power Del.*, vol. 12, no. 2, pp. 999–1005, Apr. 1997.

[6] M. E. Baran and A. W. Kelley, “State estimation for real-time monitoring of distribution systems,” *IEEE Trans. Power Syst.*, vol. 9, no. 3, pp. 1601–1609, Aug. 1994.

[7] R. F. Arritt, R. C. Dugan, R. W. Uluski, and T. F. Weaver, “Investigation load estimation methods with the use of AMI metering for distribution system analysis,” in *Proc. IEEE Rural Electric Power Conf.*, Milwaukee, WI, USA, 2012, pp. B3-1–B3-9.

[8] J. Peppanen *et al.*, “Enhanced load modeling with expanded system monitoring,” in *Proc. IEEE Power Syst. Conf. (PSC)*, Clemson, SC, USA, 2018, doi: 10.1109/PSC.2018.8664033.

[9] D. Shirmohammadi, H. W. Hong, A. Semlyen, and G. X. Luo, “A compensation-based power flow method for weakly meshed distribution and transmission networks,” *IEEE Trans. Power Syst.*, vol. 3, no. 2, pp. 753–762, May 1988.

[10] C. S. Cheng and D. Shirmohammadi, “A three-phase power flow method for real-time distribution system analysis,” *IEEE Trans. Power Syst.*, vol. 10, no. 2, pp. 671–679, May 1995.

[11] R. C. Dugan and T. E. McDermott, “An open source platform for collaborating on smart grid research,” in *Proc. IEEE Power Energy Soc. Gen. Meeting*, Detroit, MI, USA, 2011, pp. 1–7.

[12] L. Thurner *et al.*, “pandapower—An open-source Python tool for convenient modeling, analysis, and optimization of electric power systems,” *IEEE Trans. Power Syst.*, vol. 33, no. 6, pp. 6510–6521, Nov. 2018.

[13] V. Ramachandran, “Modeling of utility distribution feeder in OpenDSS with steady state impact analysis of distributed generation,” M.S. thesis, Dept. Elect. Eng., West Virginia Univ., Morgantown, WV, USA, 2011.

[14] A. Dubey, “Impact of electric vehicle loads on utility distribution network voltages,” M.S. thesis, Univ. Texas at Austin, Austin, TX, USA, 2014.

[15] S. Thakar, “Detailed modeling and simulation of distribution systems using sub-transmission–distribution co-simulation,” Ph.D. dissertation, Arizona State Univ., Tempe, AZ, USA, 2023.

[16] R. H. Chumbi Quito and T. I. Verdugo Romero, “Integración con Cymdist de las redes de media tensión y subtransmisión del sistema de la Centrosur,” Tesis, Univ. de Cuenca, Cuenca, Ecuador, 2013.

[17] N. A. Ramos Lázaro and W. E. Espinoza Rodríguez, “Modelamiento de generación distribuida fotovoltaica para mejorar el servicio eléctrico del alimentador Caudivilla-51 de Enel distribución Perú,” Tesis de maestría, Univ. Nacional del Callao, Callao, Perú, 2023.

[18] D. W. Puma Ttito, “Reconfiguración de redes de distribución de energía eléctrica, considerando las restricciones de operación y minimizando la pérdida de potencia,” Tesis doctoral, Univ. Nacional de Ingeniería, Lima, Perú, 2024.

[19] J. A. Momoh, *Electric Power Distribution, Automation, Protection, and Control*. Boca Raton, FL, USA: CRC Press, 2008.

[20] W. H. Kersting and W. H. Phillips, “Load allocation based upon automatic meter readings,” in *Proc. IEEE/PES Transm. Distrib. Conf. Expo.*, 2008, pp. 1–7.

[21] J. Peppanen, M. J. Reno, M. Thakkar, S. Grijalva, and R. G. Harley, “Leveraging AMI data for distribution system model calibration and situational awareness,” *IEEE Trans. Smart Grid*, vol. 6, no. 4, pp. 2000–2009, Jul. 2015.

[22] Y. Wang, Q. Chen, T. Hong, and C. Kang, “Review of smart meter data analytics: Applications, methodologies, and challenges,” *IEEE Trans. Smart Grid*, vol. 10, no. 3, pp. 3125–3148, May 2019.

[23] M. Rylander, J. Smith, and W. Sunderman, “Streamlined method for determining distribution system hosting capacity,” in *Proc. IEEE Rural Electric Power Conf.*, Asheville, NC, USA, 2015, pp. 3–9.

[24] F. Ding and B. Mather, “On distributed PV hosting capacity estimation, sensitivity study, and improvement,” *IEEE Trans. Sustain. Energy*, vol. 8, no. 3, pp. 1010–1020, Jul. 2017.

[25] M. T. Alturki, “Hosting capacity optimization in modern distribution grids,” Ph.D. dissertation, Univ. Denver, Denver, CO, USA, 2018.

[26] *IEEE Standard for Interconnection and Interoperability of Distributed Energy Resources with Associated Electric Power Systems Interfaces*, IEEE Std 1547-2018, Apr. 2018.

[27] OSINERGMIN, *Normativa técnica de calidad de servicio eléctrico / distribución* (Perú). Lima, Peru. [Online]. Available: https://www.osinergmin.gob.pe

[28] *IEEE Guide for Electric Power Distribution Reliability Indices*, IEEE Std 1366-2022, 2022.
