# RECYM: An Automated Multi-Feeder Workflow for Demand Allocation and Load-Flow Studies in CYMDIST Distribution Networks

**Draft manuscript — IEEE PES Transactions structure**  
**Target venue:** *IEEE Transactions on Power Delivery* (alt.: *IEEE Trans. Smart Grid* / *IEEE Access*)  
**Citation style:** IEEE numbered `[n]` (order of appearance)  
**Status:** Draft v0.3 — strengthened theory, method, and discussion with theses + peer-reviewed papers  
**Author:** Mac Tapia Ccosyo  
**Affiliation:** Electro Dunas S.A.A.  
**Corresponding author:** mtapia@electrodunas.com

### IEEE / PES numerals

| Requirement | Limit | This draft |
|-------------|-------|------------|
| Abstract | 150–250 words, one paragraph | ~165 words |
| Index Terms | Alphabetical | Yes |
| Sections | I–VII | Yes |
| First PES submission | ≤ 10 pages | **Risk after theory expansion** — trim or use supplement / IEEE Access |
| Citations | `[n]` | Yes (28 sources) |

Structural audit: `IEEE_VALIDACION.md`. Spanish twin: `MANUSCRIPT_ES.md`.

---

> **Product separation:** this file is the *scientific article* (RECYM development and application). The *delivery report* (model + run results for a utility expediente) lives in doc/informe.* and is a different document. See docs/SEPARACION_INFORME_ARTICULO.md.


## Abstract

Distribution utilities need repeatable procedures to clean network models, allocate measured headroom demand, inject important-customer and prospective spot loads, and compare situational versus projected operating cases in production planning. This paper presents RECYM, a multi-feeder software suite that couples CYMDIST/CymPy with a seven-step single-page application and a batch pipeline. The workflow integrates network diagnostics, large-customer energy/power mapping to secondary distribution transformers, kilowatt-hour-based load allocation via the CYMDIST COM API, locked three-phase spot loads, dual load-flow scenarios, and automated delivery reports. RECYM is already wired to the Electro Dunas Access database with **97 feeder configurations** and multiple per-feeder CYMDIST study files (`.zxst`); feeder **PA217** (22.9 kV) is reported here as a representative experimental sample. On PA217 the campaign closed with zero diagnostic problems, important customers verified within configured tolerances, headroom-balanced allocation (9537.9 kW versus 9537.88 kW), a 1420 kW prospective spot load, and successful situational and projected load flows with quantified headroom P/Q/S deltas.

## Index Terms

CYMDIST, demand studies, distribution networks, load allocation, load flow analysis, power system modeling, software tools.

---

## I. Introduction

Distribution planning relies on detailed three-phase feeder models to assess voltage profiles, thermal loading, and new-customer impacts [1], [2]. Commercial allocation and unbalanced load-flow engines such as CYMDIST are industry standards [3], [4]. Productive campaigns nonetheless still mix manual equipment fixes, billing-to-SED transfers, load locking, spot-load connection, and regeneration of situational versus projected reports.

Result quality depends on model consistency and on the chosen allocation rule [1], [5], [6]. Evidence shows that energy-based (kWh) allocation often outperforms connected-kVA allocation when consumption measurements exist [7], [8], while radial/weakly meshed flows are efficiently solved by compensation and sweep methods [9], [10]. Open tools (OpenDSS, pandapower) automate experiments [11], [12]; multiple theses convert or validate CYMDIST models on those platforms [13]–[15]. In Latin America, degree and master’s works document CYMDIST integration on real feeders [16], [17], and doctoral work addresses reconfiguration and losses with OpenDSS [18]. A remaining operational gap is to orchestrate *on native CYMDIST*—without migrating the system of record—an auditable multi-feeder workflow that unifies a quality gate, important customers, kWh allocation, locked spot loads, and situational/projected comparison.

This paper presents **RECYM**, which: (i) provides a layered SPA/API/pipeline/CymPy–COM architecture already deployed against **97 feeders** and multiple studies in the Electro Dunas CYMDIST database; (ii) formalizes a seven-step campaign grounded in allocation and load-flow theory; and (iii) reports a full end-to-end experimental closure on **PA217 as a representative sample**, with quantitative metrics and contrast against related authors.

Section II develops the theoretical framework and related work. Section III describes the architecture. Section IV presents mathematical models, algorithms, and the statistical validation plan. Section V presents the case study. Section VI discusses results against similar literature. Section VII concludes.

---

## II. Theoretical Framework and Related Work

### A. Three-Phase Modeling and Distribution Load Flow

Kersting [1] and Gönen [2] establish unbalanced line, transformer, and load models; Willis [3] situates them in capacity planning. For radial/weakly meshed networks, Shirmohammadi *et al.* [9] formulated compensation-based power flow; Cheng and Shirmohammadi [10] extended it to three-phase systems with dispersed generation, regulators, and capacitors—foundational for commercial engines and OpenDSS [11]. Momoh [19] emphasizes distribution automation as a software layer over such algorithms.

### B. Load-Allocation Theory

Headroom demand \(P_{\mathrm{cab}}\) is distributed to downstream loads. For unlocked loads \(\mathcal{U}\),

\begin{equation}
P_i = P_{\mathrm{cab}}^{\mathrm{res}} \frac{E_i}{\sum_{j\in\mathcal{U}} E_j},\qquad i\in\mathcal{U},
\end{equation}

where \(E_i\) is energy (kWh) and \(P_{\mathrm{cab}}^{\mathrm{res}}\) is the residual after Locked loads [4], [7]. Connected-kVA weighting is the main alternative. Arritt *et al.* [7] compared AMI-informed estimators; Peppanen *et al.* [8] showed transformer kWh allocation consistently beats kVA allocation on a large utility data set. Kersting and Phillips [20] formalized AMR-assisted allocation. Ghosh *et al.* [5] and Baran and Kelley [6] link load modeling to state estimation, underscoring error propagation into power flow.

CYMDIST implements Connected+Total templates with kWh consumption, load factor, and loss factor [4]. Chumbi and Verdugo [16] documented kVA-connected allocation (0.001% tolerance) before voltage-drop load flow at CENTROSUR; Ramos and Espinoza [17] used CYMDIST hourly allocation on a Peruvian feeder (Caudivilla-51) as the base for PV-DG scenarios.

### C. Automation, CYMDIST, and Open Platforms

Dugan and McDermott [11] and Thurner *et al.* [12] enabled scriptable OpenDSS/pandapower studies. Ramachandran [13] (M.S.) converted AEP feeders from CYMDIST to OpenDSS with component-wise mapping and validated flows; later theses continue CYME/CYMDIST→OpenDSS export for scenario flexibility [14], [15]. RECYM instead **orchestrates** COM/CymPy on the official `.zxst`/`.mdb`, closer to day-to-day utility practice.

Peppanen *et al.* [21] and Wang *et al.* [22] show AMI-driven calibration; RECYM currently uses important-customer energy/power plus headroom metering, with mass AMI as a natural extension.

### D. Hosting Capacity, New Load, and Dual Scenarios

Hosting-capacity studies compare base versus incremental cases under voltage/thermal limits [23], [24]. Alturki [25] (Ph.D.) formalizes hosting-capacity optimization; IEEE Std 1547 [26] frames interconnections. RECYM’s situational/projected pair is the operational analogue for an MV commercial spot load: calibrated residual demand, switching only the new load’s connection.

### E. Gap and Positioning

| Approach | Representative authors | Gap vs. RECYM |
|----------|------------------------|---------------|
| CYMDIST→OpenDSS conversion | Ramachandran [13]; [14], [15] | Leaves native system of record |
| Allocation / AMI | Arritt [7]; Peppanen [8], [21] | No full UI+report+spot-load campaign |
| Utility CYMDIST integration | Chumbi & Verdugo [16]; Ramos & Espinoza [17] | Limited multi-feeder orchestration |
| Topology optimization | Puma Ttito [18] | Not demand/feasibility campaigns |

---

## III. System Architecture

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

## V. Case Study and Experimentation

### A. Multi-Feeder Corpus Versus Sample Feeder

RECYM operates on the Electro Dunas production CYMDIST corpus: one shared Access database (`.mdb`) and **multiple study files** (`.zxst`) under `projects_dir`, with **97 feeder configurations** already registered in `config/feeders/` (≈96 enabled) plus study ELD for system-wide diagnostics. Each feeder has its own `network_id`, study path, control/catalog workbooks, and `data/output/feeders/<ID>/` artifact tree. Batch mode (`--all-feeders`) and SPA header `X-Feeder` select any configured feeder without code changes.

**PA217 is not the only available feeder**; it is the **representative experimental sample** used to validate the RECYM *software and workflow* (complete §§1–7 campaign: headroom, important customers, a prospective MV spot load of 1420 kW, dual load-flow maps, automated closure). Results illustrate **method validity**, not a substitute for the utility delivery report (doc/informe.*). The same pipeline applies to the remaining feeders in the 97-entry catalog.

### B. Sample Network and Software

- **Utility:** Electro Dunas (Peru), SET Paracas.
- **Sample feeder:** PA217 (`NET_2030_179_PA217`), \(V_{LL}=22.9\) kV.
- **Inventory:** 1324 nodes, 1324 sections, 253 loads.
- **Study / DB:** `PA217.zxst`, Access `20260919.mdb` (shared with the rest of the catalog).
- **Software:** CYMDIST 9.2, CymPy, Python 3.7 win32, RECYM SPA v6.
- **Prospective MV spot load (sample):** **1420 kW** on an existing node (industrial feasibility use-case). Client/expediente narrative belongs to the separate delivery report, not this article.

### C. Headroom Measurement (Sample)

Meter `L-PA235` (Excel *SISTEMA Pisco.xls*, 2026-03-03): \(P=9537.88\) kW, \(Q=2587.65\) kvar, \(S=9882.67\) kVA, average \(P=6204.65\) kW, load factor 65.05%.

### D. Experimental Protocol

Executed on the live PA217 study (`dry_run=false`):

1. Apply BD + study; load headroom (§1).
2. NetworkDiagnostic until 0 Error/Warning/Hint (§2).
3. Build important-customer table; apply EA→KWH / Pot→kW Locked; COM LoadAllocation by kWh (§3).
4. Connect prospective SpotLoad Locked on existing node (§4).
5. COM LoadFlow situational (SpotLoad off) and projected (SpotLoad on); export maps (§5).
6. Assemble delivery package; run automated §§1–7 closure (§§6–7).

Metrics follow [7], [8], [13], [16]: diagnostic counts; EA/Pot precision; headroom balance; phase split; LF headroom P/Q/S and voltage; campaign closure (`cierre_1_7_report.json`). Artifact roots: `data/output/feeders/PA217/`.

---

## VI. Results and Discussion

### A. Model Quality (Sample PA217)

Post-campaign diagnostics: **0** messages / **0** problems (gate §2 satisfied), as required before trusting allocation and flow [5], [6], [21].

### B. Important-Customer Precision and Statistical Checks

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

### F. Contrast With Similar Authors

**TABLE II**

| Work | Domain | Similarity | RECYM difference |
|------|--------|------------|------------------|
| Arritt [7]; Peppanen [8] | kWh vs kVA allocation | Energy weights | Locked+residual+multi-feeder UI |
| Ramachandran [13] | CYMDIST→OpenDSS | Real feeder validation | Keeps native CYMDIST (COM) |
| Chumbi & Verdugo [16] | Utility CYMDIST | Multi-feeder + alloc/LF | **97 feeders** + §§1–7 + dual spot load + jobs |
| Ramos & Espinoza [17] | CYMDIST in Peru | Local CYMDIST practice | MV spot-load feasibility + audit trail |
| Rylander [23]; Alturki [25] | Hosting / incremental | Base vs incremental logic | Applied to commercial MV spot load |
| Puma Ttito [18] | Topology optimization | Distribution engines | Demand/feasibility first; §7 later |

### G. Limitations

Windows/COM coupling; study-file integrity; COM fallback when native allocation fails; §7 optimization not the metric focus of the PA217 sample. **Detailed numerical tables are reported for one sample feeder (PA217)** even though the catalog already contains **97 feeders and multiple studies**—fleet-wide KPI aggregation across all enabled feeders, AMI mass calibration [21], [22], and regulatory scoring [27], [28] remain future work.

---

## VII. Conclusion

RECYM automates a multi-feeder CYMDIST campaign grounded in kWh allocation theory [7], [8] and three-phase distribution power flow [9], [10], already configured for **97 Electro Dunas feeders** and multiple `.zxst` studies on a shared Access database. Using **PA217 as a representative experimental sample**, the method achieved a clean diagnostic gate, customer precision, headroom-balanced allocation, a 1420 kW SpotLoad, quantified situational/projected LF deltas (Table III), and 21/21 campaign closure. Future work: fleet KPIs over the full catalog, regulatory scoring [27], AMI, and §7/reconfiguration hardening [18], [19].

---

## Appendix A — `run_sequence` (excerpt)

`validate_inputs` → `network_diagnostic` → … → `demand_allocation` → `report`.

## Appendix B — Figure sources (real campaign artifacts)

| Fig. | Source |
|------|--------|
| 1–2 | Generated architecture/workflow diagrams |
| 3 | Campaign map `topologia.png` (SpotLoad 1420 kW) → `figures/` |
| 4–5 | Campaign LF maps → `figures/` |
| 6–7 | Charts from campaign LF scalars (not from `doc/informe.docx`) |
| 8–9 | `precision_report.json` / `cierre_1_7_report.json` |

---

## References

[1] W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed. Boca Raton, FL, USA: CRC Press, 2017.

[2] T. Gönen, *Electric Power Distribution Engineering*, 3rd ed. Boca Raton, FL, USA: CRC Press, 2014.

[3] H. L. Willis, *Power Distribution Planning Reference Book*, 2nd ed. New York, NY, USA: Marcel Dekker, 2004.

[4] Eaton CYME, *CYMDIST Reference Manual / How-to Tutorials* (Load Allocation, Load Flow), version 9.2. Saint-Bruno, QC, Canada: Eaton, 2022.

[5] A. K. Ghosh, D. L. Lubkeman, and R. H. Jones, “Load modeling for distribution circuit state estimation,” *IEEE Trans. Power Del.*, vol. 12, no. 2, pp. 999–1005, Apr. 1997.

[6] M. E. Baran and A. W. Kelley, “State estimation for real-time monitoring of distribution systems,” *IEEE Trans. Power Syst.*, vol. 9, no. 3, pp. 1601–1609, Aug. 1994.

[7] R. F. Arritt, R. C. Dugan, R. W. Uluski, and T. F. Weaver, “Investigation load estimation methods with the use of AMI metering for distribution system analysis,” in *Proc. IEEE Rural Electric Power Conf.*, Milwaukee, WI, USA, 2012, pp. B3-1–B3-9.

[8] J. Peppanen *et al.*, “Enhanced load modeling with expanded system monitoring,” in *Proc. IEEE Power Syst. Conf. (PSC)*, 2018, doi: 10.1109/PSC.2018.8664033.

[9] D. Shirmohammadi, H. W. Hong, A. Semlyen, and G. X. Luo, “A compensation-based power flow method for weakly meshed distribution and transmission networks,” *IEEE Trans. Power Syst.*, vol. 3, no. 2, pp. 753–762, May 1988.

[10] C. S. Cheng and D. Shirmohammadi, “A three-phase power flow method for real-time distribution system analysis,” *IEEE Trans. Power Syst.*, vol. 10, no. 2, pp. 671–679, May 1995.

[11] R. C. Dugan and T. E. McDermott, “An open source platform for collaborating on smart grid research,” in *Proc. IEEE Power Energy Soc. Gen. Meeting*, Detroit, MI, USA, 2011, pp. 1–7.

[12] L. Thurner *et al.*, “pandapower—An open-source Python tool for convenient modeling, analysis, and optimization of electric power systems,” *IEEE Trans. Power Syst.*, vol. 33, no. 6, pp. 6510–6521, Nov. 2018.

[13] V. Ramachandran, “Modeling of utility distribution feeder in OpenDSS with steady state impact analysis of distributed generation,” M.S. thesis, West Virginia Univ., Morgantown, WV, USA, 2011.

[14] A. Dubey, “Impact of electric vehicle loads on utility distribution network voltages,” M.S. thesis, Univ. Texas at Austin, Austin, TX, USA, 2014.

[15] S. Thakar, “Detailed modeling and simulation of distribution systems using sub-transmission–distribution co-simulation,” Ph.D. dissertation, Arizona State Univ., Tempe, AZ, USA, 2023.

[16] R. H. Chumbi Quito and T. I. Verdugo Romero, “Integración con Cymdist de las redes de media tensión y subtransmisión del sistema de la Centrosur,” Thesis, Univ. de Cuenca, Cuenca, Ecuador, 2013.

[17] N. A. Ramos Lázaro and W. E. Espinoza Rodríguez, “Modelamiento de generación distribuida fotovoltaica para mejorar el servicio eléctrico del alimentador Caudivilla-51 de Enel distribución Perú,” M.S. thesis, Univ. Nacional del Callao, Callao, Peru, 2023.

[18] D. W. Puma Ttito, “Reconfiguración de redes de distribución de energía eléctrica, considerando las restricciones de operación y minimizando la pérdida de potencia,” Ph.D. dissertation, Univ. Nacional de Ingeniería, Lima, Peru, 2024.

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
