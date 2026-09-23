# -*- coding: utf-8 -*-
from __future__ import print_function
import io
import re

MATH_EN = r'''## III. System Architecture

RECYM is organized as a five-layer stack \(L_1,\ldots,L_5\) (Fig. 1):

\begin{equation}
L_1\xrightarrow{\mathrm{HTTP/JSON/SSE}} L_2\xrightarrow{\mathrm{domain\ calls}} L_3\xrightarrow{\mathrm{CymPy/COM}} L_4\xrightarrow{\mathrm{I/O}} L_5,
\end{equation}

where \(L_1\) is the React SPA (§§1–7), \(L_2\) the FastAPI job/SSE API with Flask bridge, \(L_3\) the Python domain (`pipeline`, `analysis`, `optimization`), \(L_4\) the CymPy/COM CYMDIST core, and \(L_5\) external assets (`.zxst`, shared `.mdb`, Excel). Asynchronous jobs avoid UI timeouts during COM sessions [19]. Configuration is a pair \((\mathcal{S},\mathcal{F})\): global settings \(\mathcal{S}\) and feeder catalog \(\mathcal{F}=\{f_1,\ldots,f_{97}\}\) with ELD for system diagnostics. Writes require a usable study and `dry_run=false`; allocation and load flow prefer COM [4].

---

## IV. Mathematical Models and Algorithms

### A. Headroom, Locked Loads, and kWh Allocation Model

Let \(P_{\mathrm{cab}}\) be measured headroom active power and \(\mathcal{L}\) the set of modeled loads. Partition \(\mathcal{L}=\mathcal{F}\cup\mathcal{U}\) into Locked (fixed) customers \(\mathcal{F}\) and unlocked residual loads \(\mathcal{U}\). With energy \(E_i\) (kWh) and locked power \(P_j^{\mathrm{fix}}\),

\begin{equation}
P_{\mathrm{cab}}^{\mathrm{res}} = P_{\mathrm{cab}} - \sum_{j\in\mathcal{F}} P_j^{\mathrm{fix}},\qquad
P_i = P_{\mathrm{cab}}^{\mathrm{res}}\frac{E_i}{\sum_{u\in\mathcal{U}} E_u},\quad i\in\mathcal{U}.
\end{equation}

Reactive power follows the configured power-factor rule (or measured \(Q_{\mathrm{cab}}\) split analogously). The **allocation balance error** used for validation is

\begin{equation}
\varepsilon_P = \frac{\left|\sum_{i\in\mathcal{L}} P_i - P_{\mathrm{cab}}\right|}{P_{\mathrm{cab}}}\times 100\%.
\end{equation}

Customer write precision against billing targets \((E_i^\star,P_i^\star)\) uses absolute errors \(\lvert\Delta E_i\rvert=\lvert E_i^{\mathrm{CYM}}-E_i^\star\rvert\) and \(\lvert\Delta P_i\rvert=\lvert P_i^{\mathrm{CYM}}-P_i^\star\rvert\), accepted iff \(\lvert\Delta E_i\rvert\le 0.5\,\mathrm{kWh}\) and \(\lvert\Delta P_i\rvert\le 0.01\,\mathrm{kW}\). Aggregate MAE/RMSE over the accepted set \(\mathcal{A}\) are

\begin{equation}
\mathrm{MAE}_P=\frac{1}{\lvert\mathcal{A}\rvert}\sum_{i\in\mathcal{A}}\lvert\Delta P_i\rvert,\quad
\mathrm{RMSE}_P=\sqrt{\frac{1}{\lvert\mathcal{A}\rvert}\sum_{i\in\mathcal{A}}(\Delta P_i)^2}
\end{equation}

(and likewise for energy). This paragraph states the **first closed-form allocation model** of RECYM, grounded in kWh weighting [7], [8], [4].

### B. Spot-Load Phase Model and Dual Load-Flow Scenarios

A three-phase concentrated spot load of total active/reactive power \((P_{3\phi},Q_{3\phi})\) is attached to an existing node with equal phase split and Locked status:

\begin{equation}
P_\phi=\frac{P_{3\phi}}{3},\quad Q_\phi=\frac{Q_{3\phi}}{3},\quad \phi\in\{A,B,C\}.
\end{equation}

Let \(c\in\{0,1\}\) be the connection flag of the prospective spot-load set \(\mathcal{S}\) (\(c=0\) disconnected, \(c=1\) connected). The **situational** case solves the unbalanced load-flow map \(F\) on network state \(x\) with \(c=0\); the **projected** case uses \(c=1\):

\begin{equation}
y^{\mathrm{sit}}=F(x;\,c=0),\qquad y^{\mathrm{prj}}=F(x;\,c=1),
\end{equation}

where \(y\) stacks headroom \(P,Q,S\), phase voltages, and loadings [9], [10], [4]. Incremental impact is \(\Delta y=y^{\mathrm{prj}}-y^{\mathrm{sit}}\). Relative headroom demand change is \(\delta_P=100\cdot\Delta P/P^{\mathrm{sit}}\). Phase imbalance of the spot load is monitored by \(\max_{\phi,\psi}\lvert P_\phi-P_\psi\rvert\). This paragraph states the **second mathematical model** (spot load + dual LF), aligned with base/incremental hosting-capacity logic [23]–[25].

### C. Pseudocode

**Algorithm 1** — kWh residual allocation  
**Input:** \(P_{\mathrm{cab}}\), locked set \(\mathcal{F}\), unlocked \(\mathcal{U}\) with energies \(E_i\)  
1: \(P_{\mathrm{cab}}^{\mathrm{res}} \leftarrow P_{\mathrm{cab}}-\sum_{j\in\mathcal{F}} P_j^{\mathrm{fix}}\)  
2: \(E_{\mathrm{tot}} \leftarrow \sum_{u\in\mathcal{U}} E_u\)  
3: **for** each \(i\in\mathcal{U}\) **do** \(P_i \leftarrow P_{\mathrm{cab}}^{\mathrm{res}}\cdot E_i/E_{\mathrm{tot}}\)  
4: Write \(P_i\) via COM LoadAllocation; compute \(\varepsilon_P\) (3)  
5: **return** allocated loads, \(\varepsilon_P\)

**Algorithm 2** — Dual scenario load flow  
**Input:** study \(x\), spot-load set \(\mathcal{S}\)  
1: Disconnect each \(\ell\in\mathcal{S}\); \(y^{\mathrm{sit}}\leftarrow\mathrm{COM\_LoadFlow}(x)\)  
2: Connect each \(\ell\in\mathcal{S}\) with (5); \(y^{\mathrm{prj}}\leftarrow\mathrm{COM\_LoadFlow}(x)\)  
3: \(\Delta y\leftarrow y^{\mathrm{prj}}-y^{\mathrm{sit}}\); export maps/scalars  
4: **return** \(y^{\mathrm{sit}},y^{\mathrm{prj}},\Delta y\)

**Algorithm 3** — Campaign §§1–7 (orchestration)  
1: Bind BD+study; load \((P_{\mathrm{cab}},Q_{\mathrm{cab}})\)  
2: Diagnose until zero Error/Warning/Hint  
3: Apply important customers; run Algorithm 1; verify (4)  
4: Insert Locked spot load (5); run Algorithm 2  
5: Persist campaign artifacts; record closure checklist  

### D. Quality Gate and Statistical Validation Plan

Let \(N_{\mathrm{msg}}\) be NetworkDiagnostic messages. The quality gate requires \(N_{\mathrm{msg}}=0\) before demand writes [5], [6]. Statistical checks on the sample feeder: (i) allocation \(\varepsilon_P\) vs. engineering threshold (target \(\varepsilon_P\ll 1\%\)); (ii) customer pass rate \(\hat{p}=\lvert\mathcal{A}\rvert/n\) with Clopper–Pearson 95% CI; (iii) MAE/RMSE of \(\Delta P,\Delta E\); (iv) phase-split imbalance; (v) paired situational/projected deltas \(\Delta P,\Delta Q,\Delta S\) and \(\delta_P\); (vi) campaign closure binary success (21/21 steps). With near-zero write errors, classical paired \(t\)-tests on \(\Delta P_i\) are degenerate; we therefore report exact error magnitudes against declared tolerances rather than inflated \(p\)-values.

'''

MATH_ES = r'''## III. Arquitectura del sistema

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

'''

STATS_EN = r'''### B. Important-Customer Precision and Statistical Checks

Twelve candidate rows; **11** SED mappings OK (\(n_{\mathrm{fail}}=0\), \(n_{\mathrm{skip}}=1\)); pass rate \(\hat{p}=11/11=1.00\) on writable SED (Clopper–Pearson 95% CI \([0.72,\,1.00]\) for \(n=11\)). Observed \(\mathrm{MAE}_P=\mathrm{RMSE}_P=0\) kW and \(\mathrm{MAE}_E=\mathrm{RMSE}_E=0\) kWh within tolerances \(0.01\,\mathrm{kW}/0.5\,\mathrm{kWh}\) (Table I; Fig. 8). Sum of verified Pot \(\sum P^{\mathrm{fix}}=7896.28\,\mathrm{kW}\).

### C. Load-Allocation Balance

COM kWh LoadAllocation yielded \(\sum P=9537.87278\,\mathrm{kW}\) vs \(P_{\mathrm{cab}}=9537.88\,\mathrm{kW}\), hence \(\varepsilon_P\approx 7.6\times 10^{-5}\%\) (eq. 3)—far below a 1% engineering gate. Suite T1–T4 passed (COM engine, re-entry, balance, artifact). Consistent with energy-weighting evidence [7], [8].

### D. Prospective SpotLoad

Locked **1420 kW** at existing node (Fig. 3). Phase split (eq. 5): verification campaign showed \(466.67/466.67/466.67\,\mathrm{kW}\) for a 1400 kW three-phase device (\(\max\lvert P_\phi-P_\psi\rvert=0\)). Orphan 0 kW device disconnected.

### E. Dual Load-Flow Results and Paired Deltas

From RECYM campaign COM LoadFlow on sample PA217 (Figs. 4–7)—tool validation evidence, not the delivery-report document:

**TABLE III** — Situational vs projected headroom (sample PA217)

| Metric | Situational | Projected | \(\Delta\) | Rel. |
|--------|------------:|----------:|----------:|------:|
| \(V_{\mathrm{head}}\) A/B/C (%) | 99.84 / 99.84 / 99.84 | 99.84 / 99.84 / 99.84 | 0.00 pp | — |
| Voltage drop (pp) | 0.16 | 0.16 | 0.00 | — |
| \(P\) (kW) | 10156.0 | 11900.0 | +1744.0 | \(\delta_P=+17.17\%\) |
| \(Q\) (kvar) | 3301.0 | 4287.0 | +986.0 | +29.87% |
| \(S\) (kVA) | 10679.0 | 12648.7 | +1969.7 | +18.44% |
| Power factor (%) | 95.10 | 94.08 | −1.02 | — |

Headroom voltage remains within ±5% MT practice. Automated closure: **21/21** steps OK (Fig. 9). Quality gate \(N_{\mathrm{msg}}=0\).

'''

STATS_ES = r'''### B. Precisión de clientes y chequeos estadísticos

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

'''


def replace_between(text, start_marker, end_marker, new_block):
    i = text.find(start_marker)
    j = text.find(end_marker)
    if i < 0 or j < 0 or j <= i:
        raise SystemExit("markers fail %r -> %r (%s,%s)" % (start_marker, end_marker, i, j))
    return text[:i] + new_block.strip() + "\n\n" + text[j:]


def main():
    pen = r"docs\articulo_ieee\MANUSCRIPT.md"
    ten = io.open(pen, encoding="utf-8").read()
    ten = replace_between(
        ten,
        "## III. System Architecture",
        "## V. Case Study and Experimentation",
        MATH_EN,
    )
    i = ten.find("### B. Important-Customer Precision")
    j = ten.find("### F. Contrast With Similar Authors")
    if i < 0 or j < 0:
        raise SystemExit("EN results markers fail %s %s" % (i, j))
    ten = ten[:i] + STATS_EN.strip() + "\n\n" + ten[j:]
    ten = ten.replace(
        "Section III describes the architecture. Section IV details the method.",
        "Section III describes the architecture. Section IV presents mathematical models, algorithms, and the statistical validation plan.",
    )
    io.open(pen, "w", encoding="utf-8", newline="\n").write(ten)
    print("EN updated")

    pes = r"docs\articulo_ieee\MANUSCRIPT_ES.md"
    tes = io.open(pes, encoding="utf-8").read()
    tes = re.sub(
        r"Cada alimentador tiene\s*\n?\s*etwork_id",
        "Cada alimentador tiene `network_id`",
        tes,
    )
    tes = replace_between(
        tes, "## III. Arquitectura del sistema", "## V. Caso de estudio", MATH_ES
    )
    i = tes.find("### B. Precisión de clientes")
    if i < 0:
        i = tes.find("### B. Precisión de clientes importantes")
    j = tes.find("### F. Discusión contrastada")
    if i < 0 or j < 0:
        raise SystemExit("ES results markers %s %s" % (i, j))
    tes = tes[:i] + STATS_ES.strip() + "\n\n" + tes[j:]
    tes = tes.replace(
        "La Sección III describe la arquitectura. La IV detalla el desarrollo metodológico.",
        "La Sección III describe la arquitectura. La IV presenta modelos matemáticos, algoritmos y el plan de validación estadística.",
    )
    io.open(pes, "w", encoding="utf-8", newline="\n").write(tes)
    print("ES updated")
    print("done")


if __name__ == "__main__":
    main()
