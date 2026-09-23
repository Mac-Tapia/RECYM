# RECYM: A Multi-Feeder CYMDIST Workflow for Demand Allocation, Spot-Load Studies, and Situational–Projected Load-Flow Comparison

> **Manuscript draft for IEEE PES Transactions** (target: *IEEE Transactions on Power Delivery*).  
> **Format numerals:** Abstract 150–250 words · Index Terms alphabetical · Sections I–VII · Citations `[n]` · First submission **≤ 10 pages** (PES).  
> **Authors / affiliations / ORCID:** TODO before submission.  
> **Language:** English (IEEE journal).  
> **Honesty note:** Load-flow voltage/loading scalars in Section VI use only validated campaign artifacts; where the current CSV export is `DRY_RUN`, figures from the report pipeline should be frozen before camera-ready.

---

**Authors**  
First A. Author, *Member, IEEE*, Second B. Author, and Third C. Author  
*(TODO: Electro Dunas / ELDICA affiliations and emails)*

---

## Abstract

Distribution utilities must repeatedly correct network models, allocate measured headroom demand, connect prospective concentrated loads, and compare base versus future load-flow cases inside commercial tools such as CYMDIST. Manual campaigns are error-prone, hard to audit, and difficult to reproduce across dozens of feeders. This paper presents RECYM, a multi-feeder software suite that couples CYMDIST/CymPy and COM engines with a seven-step single-page application and a batch pipeline. The workflow enforces a model-quality gate, maps large-customer energy and contracted power onto secondary distribution transformers, allocates residual demand by energy (kWh) against a measured headroom total, inserts locked three-phase spot loads on existing nodes, and runs dual load-flow scenarios that disconnect or reconnect the prospective load. On Electro Dunas feeder PA217 (22.9 kV; 1324 nodes; 253 loads), RECYM preserved headroom balance at 9537.88 kW, updated ten secondary transformers with energy-to-kWh and power-to-kW locked injections, and connected a 1420 kW spot load for situational–projected comparison, with zero diagnostic problems on the quality board after corrections. The architecture, coupling rules, and reproducible artifacts are documented so peer utilities can replicate the campaign on additional feeders.

*(Word count: ~198 — within IEEE 150–250.)*

## Index Terms

CYMDIST, demand allocation, distribution networks, load flow, power system modeling, software tools, spot load.

---

## Nomenclature

| Symbol | Description |
|--------|-------------|
| \(P,Q\) | Three-phase active/reactive power at feeder headroom (kW, kvar) |
| \(S\) | Apparent power at headroom (kVA) |
| \(V_{\mathrm{ll}}\) | Line-to-line nominal voltage (kV) |
| SED | Secondary distribution transformer / customer delivery point in the model |
| EA | Billed active energy mapped to CYMDIST *Consumo* (kWh) |
| Pot | Contracted/peak power mapped to locked kW |
| SPA | Single-page application (operator UI) |

---

## I. Introduction

Planning and connection studies on medium-voltage (MV) distribution feeders require a trustworthy digital twin: correct connectivity and equipment data, demand that matches metered headroom, explicit treatment of large customers, and a transparent comparison between the present operating point and a projected case that includes a new concentrated load [1], [2]. Commercial packages such as CYMDIST provide load allocation and load-flow engines, but production campaigns still rely on long sequences of manual clicks, spreadsheets, and ad-hoc scripts. Across a utility with many feeders, those steps become inconsistent, poorly logged, and difficult to defend in regulatory or customer-facing reports.

Prior open platforms (e.g., OpenDSS-based research stacks) emphasize flexible simulation APIs [3], while vendor documentation covers allocation and load-flow algorithms in isolation [4], [5]. What is still scarce in the literature is an *end-to-end operational workflow*—model diagnostics, large-customer injection, kWh-based residual allocation, locked spot-load insertion, dual scenario load flow, and delivery-report generation—bound to a multi-feeder configuration and an auditable UI.

This paper presents **RECYM** (suite for Electro Dunas CYMDIST studies), which addresses that gap. The contributions are:

1. A layered architecture (SPA, FastAPI/Flask bridge, domain pipelines, CymPy/COM adapters) that operates one feeder or batch modes under a shared settings model.
2. A seven-step campaign (§§1–7) with explicit coupling rules so allocation, spot load, and situational/projected load flows cannot be mixed incorrectly.
3. An industrial case study on feeder PA217 demonstrating headroom-consistent allocation, SED energy/power updates, a 1420 kW spot load, and reproducible report artifacts.

The remainder of this paper is organized as follows. Section II reviews related work. Section III describes the system architecture. Section IV details the proposed workflow and algorithms. Section V presents the case-study setup. Section VI discusses results and limitations. Section VII concludes.

---

## II. Related Work

Distribution system modeling and analysis fundamentals are well established [1], [2]. Load allocation methods that scale customer or transformer energy to match a measured feeder total are standard in utility practice and are available inside CYMDIST [4]. Balanced and unbalanced load-flow formulations for radial and weakly meshed networks underpin commercial and open tools [5], [6].

Open-source ecosystems such as OpenDSS enable scripted studies and research collaboration [3]. Python-centric frameworks (e.g., pandapower) similarly automate power-flow experiments [7]. Vendor COM/API layers expose study open/save, device edits, and engine runs, but leave campaign design to the utility.

RECYM does not replace CYMDIST’s numerical engines. Instead, it *orchestrates* them: quality gates before writes, deterministic mapping of billing fields (EA→kWh, Pot→kW), residual allocation by consumption, locked spot loads with equal phase split, and scenario switching that disconnects or reconnects the prospective load before load flow. That operational coupling, plus multi-feeder packaging and report automation, is the focus of this work.

---

## III. System Architecture

### A. Layered Design

RECYM is organized in five layers (Fig. 1):

1. **Presentation:** React/Vite SPA with seven operator panels, served with the API on a local host port.
2. **API:** FastAPI contract for jobs (asynchronous POST/GET/SSE), native dashboard endpoints, and a WSGI bridge to legacy Flask handlers.
3. **Domain:** Pipelines for diagnostics, customer application, demand allocation, spot-load insertion, load flow, report fill, and optional equipment optimization.
4. **Core adapters:** `cympy_adapter` (study/database I/O, customers, spot loads), `cymdist_com` (COM load flow / allocation), and `feeder_context` (path resolution).
5. **External data:** CYMDIST study files (`.zxst`), Access databases (`.mdb`), and Excel workbooks for control, catalog, and headroom measurements.

```
[Fig. 1 — Architecture stack: SPA → API/jobs → pipeline/analysis/optimization → CymPy/COM → .zxst/.mdb/Excel]
```

### B. Multi-Feeder Configuration

Global paths (CYME root, studies root, database, Python 3.7 win32 host) live in `settings.json`. Each feeder adds a JSON record with `network_id`, study path, control/catalog workbooks, and output directory `data/output/feeders/<ID>/`. Selection priority is CLI/`RECYM_FEEDER`, UI header `X-Feeder`, then `active_feeder`. Batch mode (`--all-feeders`) reuses the same pipeline sequence.

### C. Write Safety

Model writes require a resolved study path, `dry_run=false`, and the configured write gate. Artifacts (customers, allocation validation, load-flow products, dashboard JSON, report images) are stored per feeder for audit.

---

## IV. Proposed Workflow

### A. Seven-Step Campaign

Fig. 2 summarizes the operator campaign:

| Step | Panel | Function |
|------|-------|----------|
| §1 | Context | Bind database + study; save headroom \(P,Q\) for allocation |
| §2 | Quality | NetworkDiagnostic (feeder / 96-feeder system / ELD); corrections; gate ≈ 0 issues |
| §3 | Customers | NIS cross-match → SED; Incluir on/off; EA→Consumo (kWh), Pot→kW Locked; LoadAllocation by kWh |
| §4 | Spot load | Concentrated load on an *existing* node; \(P_a=P_b=P_c=P/3\), likewise \(Q\); Locked |
| §5 | Load flows | **Situational:** disconnect §4 then LF. **Projected:** connect §4 then LF |
| §6 | Reports | OCR/meta from request PDF; fill Word/PDF delivery package |
| §7 | Suite | Optional equipment optimization and batch tools |

```
[Fig. 2 — Campaign flowchart §§1–7 with situational/projected branch after SpotLoad]
```

### B. Coupling Rules

1. Diagnostics (§2) use the network already in the database; they do not depend on §§4–5.
2. After §3 or §4, CYMDIST typically remains session-open; subsequent steps reuse that study.
3. After connecting a spot load (§4), **do not** re-run residual allocation (§3.3)—only load flow (§5).
4. Saving a new headroom (§1) resets session artifacts for §§3–5 to avoid mixing campaigns.
5. Situational versus projected differs *only* by ConnectionStatus of the §4 spot load (and thus its contribution to the LF case)—not by re-allocation.

### C. Customer and Allocation Logic

For each included large customer with a resolved SED load ID:

- Set CYMDIST consumption field from EA (kWh).
- Set active power from Pot (kW) and lock the load.
- Mark Incluir=off customers Disconnected with zero injection.

Headroom allocation uses CYMDIST LoadAllocation with consumption-based residuals so that the sum of allocated kW matches the measured headroom total within tolerance. On PA217, the COM path (`LoadAllocation` by KWH) succeeded when the native CymPy allocation path was unavailable.

### D. Spot-Load Insertion

Given three-phase demand \(P\) (kW) and \(Q\) (kvar) at an existing node:

\[
P_\phi = \frac{P}{3},\qquad Q_\phi = \frac{Q}{3},\quad \phi\in\{A,B,C\}.
\]

The device is written Locked. Topology export records coordinates for the delivery report map.

### E. Batch Sequence

Unattended mode runs a configurable `run_sequence` (validate → diagnose → correct → inventory → customers → allocate → report, with optional load flow). Control workbook flags can skip LF or optimization stages.

---

## V. Case Study Setup

### A. Network and Utility Context

- **Utility:** Electro Dunas (Peru).  
- **Feeder:** PA217, network `NET_2030_179_PA217`, \(V_{\mathrm{ll}}=22.9\) kV (SET Paracas).  
- **Inventory:** 1324 nodes, 1324 sections, 253 loads.  
- **Prospect load:** San Fernando S.A. incubation plant request, **1420 kW** at node `NODE_1080_320357_MI-17145_2` (Paracas district, Ica).  
- **Software:** CYMDIST 9.2, CymPy, COM engines, RECYM SPA v6, FastAPI on the engineering workstation.

### B. Headroom Measurement

Session headroom used for allocation:

- \(P=9537.88\) kW, \(Q=2587.65\) kvar, \(S=9882.67\) kVA  
- Loading factor 65.05 %, meter `L-PA235`, \(V_{\mathrm{ll}}=22.9\) kV  
- Timestamp in source workbook: 3 March 2026, 10:00

### C. Metrics

| Metric | Role |
|--------|------|
| Diagnostic problem count | Quality gate before demand writes |
| SED apply KWH_ok / ConnectionStatus | Customer injection correctness |
| \(\lvert\sum P_{\mathrm{loads}}-P_{\mathrm{head}}\rvert/P_{\mathrm{head}}\) | Allocation balance |
| Spot-load phase powers | Equal split verification |
| LF convergence; \(V_{\min}\), loading, losses | Situational vs projected (freeze from LF export) |

---

## VI. Results and Discussion

### A. Model Quality Gate

After diagnostic/correction cycles, the PA217 quality board reported **0 problems** (`n_problems=0`) in the dashboard summary used for campaign closure. The gate enables subsequent customer and allocation writes with a clean model checklist.

### B. Large-Customer Injection at SED

Twelve supply rows were processed in the apply report. **Ten** SED loads were written Connected with EA→Consumo (kWh) and Pot→kW Locked (examples include Minerales Paracas, LJMetales, Emsalsa, Uvica, among others). **One** customer was excluded (`Incluir=false`) and forced Disconnected with zero kW/kWh. **One** row lacked a SED mapping (`SIN_SED`) and was flagged rather than silently written. Session counters recorded `ea_pot_n_keep=10` and one liberated entry.

### C. Demand Allocation Balance

Fast validation against the COM LoadAllocation (KWH) engine reported:

- \(\sum P = 9537.87\) kW versus headroom \(P=9537.88\) kW  
- Relative mismatch \(d=0.0\%\) (balance OK)

Thus the residual model matches the measured headroom used as the Connected+Total allocation target.

### D. Spot Load and Dual Scenarios

The prospective load of **1420 kW** was placed at `NODE_1080_320357_MI-17145_2` (map artifact `topologia.png`, UTM zone 18). Equal phase split yields \(P_\phi=473.33\) kW/phase (an earlier validation campaign also exercised 1400 kW → 466.67 kW/phase). Per coupling rules, situational LF disconnects this device; projected LF reconnects it—without re-running kWh allocation.

Report images for situational/projected voltage and loading are produced by the §5–§6 pipeline for the delivery package. **Numeric \(V_{\min}\)/loss tables must be frozen from a non-`DRY_RUN` LF export before final submission** (current `diagnostico_actual.csv` still labels a dry-run row and must not be cited as measured LF results).

### E. End-to-End Validation

An integral validation checklist (syntax, imports, config, study open, 10 SED updates, spot-load phase split, allocation/LF artifacts, UI reachability) returned **PASS** on 21 September 2026 for PA217. Closure jobs for panels §§1–7 completed with OK statuses in the campaign report log.

### F. Coverage of the Full Product Scope

Beyond the PA217 numbers, the same codebase supports: system-wide diagnostics (96-feeder ELD study), inventory exports across many feeders, Word/PDF informe fill from request meta, and optional §7 equipment optimization. Those modules share the architecture in Section III; PA217 is the detailed quantitative case.

### G. Limitations

1. Dependence on Windows COM/CymPy and a pinned 32-bit Python host.  
2. Single interactive CYMDIST session assumptions during SPA campaigns.  
3. Native CymPy LoadAllocation may fail while COM succeeds—operators must trust the validation board.  
4. LF scalar KPIs in this draft await a frozen non-dry-run export for camera-ready tables.  
5. Results are utility-specific; other companies need feeder JSON + workbook mapping.

---

## VII. Conclusion

RECYM provides a complete, multi-feeder orchestration layer over CYMDIST for industrial demand and connection studies. By combining a quality gate, SED energy/power injection, kWh residual allocation, locked spot loads, and situational–projected load flows inside an auditable SPA/API/pipeline stack, the suite turns a fragile manual campaign into a repeatable procedure. On feeder PA217, headroom balance, ten SED updates, and a 1420 kW spot-load case were demonstrated with a clean diagnostic board and PASS integral validation.

Future work includes freezing dual-scenario LF KPIs for all active feeders, promoting §7 optimization results into the same evidence pack, and publishing anonymized multi-feeder statistics for the 96-feeder system study.

---

## Acknowledgment

TODO: Electro Dunas / ELDICA funding, CYME licenses, and colleagues who supported field data.

---

## References

[1] W. H. Kersting, *Distribution System Modeling and Analysis*, 4th ed. Boca Raton, FL, USA: CRC Press, 2017.

[2] T. Gönen, *Electric Power Distribution Engineering*, 3rd ed. Boca Raton, FL, USA: CRC Press, 2014.

[3] R. C. Dugan and T. E. McDermott, “An open source platform for collaborating on smart grid research,” in *Proc. IEEE Power Energy Soc. Gen. Meeting*, Detroit, MI, USA, 2011, pp. 1–7.

[4] CYME International T&D, *CYMDIST User Guide* (Load Allocation), Eaton, version 9.2.

[5] CYME International T&D, *CYMDIST User Guide* (Balanced Load Flow), Eaton, version 9.2.

[6] D. Shirmohammadi, H. W. Hong, A. Semlyen, and G. X. Luo, “A compensation-based power flow method for weakly meshed distribution and transmission networks,” *IEEE Trans. Power Syst.*, vol. 3, no. 2, pp. 753–762, May 1988.

[7] L. Thurner *et al.*, “pandapower—An open-source Python tool for convenient modeling, analysis, and optimization of electric power systems,” *IEEE Trans. Power Syst.*, vol. 33, no. 6, pp. 6510–6521, Nov. 2018.

[8] IEEE Std 1547-2018, *IEEE Standard for Interconnection and Interoperability of Distributed Energy Resources with Associated Electric Power Systems Interfaces*.

[9] J. Arrillaga and C. P. Arnold, *Computer Analysis of Power Systems*. Chichester, U.K.: Wiley, 1990.

[10] H. L. Willis, *Power Distribution Planning Reference Book*, 2nd ed. Boca Raton, FL, USA: CRC Press, 2004.

*(Expand to 25–35 peer-reviewed items before submission; keep IEEE numeric order of first appearance.)*

---

## Appendix A — Artifact Map (not counted toward narrative if journal allows online supplement)

```
data/output/feeders/PA217/
  clientes/     apply report + JSON
  demand/       session, allocation_validation, informe_meta
  diagnostics/  tablero, dashboard summaries
  informe_images/  topologia, situacional_*, proyectado_*
  inventory/    loads.json, nodes.json
```

## Appendix B — PES Page Budget (authors’ control)

| Block | Target pages (approx.) |
|-------|-------------------------|
| Title + Abstract + Index Terms | 0.5 |
| I–II | 1.5 |
| III–IV | 3.0 |
| V–VI | 3.5 |
| VII + Ack + Refs (+ short bios) | 1.5 |
| **Total first submission** | **≤ 10** |

Trim related-work prose and move API endpoint lists to a supplement if the compiled PDF exceeds 10 pages.

---

## Pre-submission checklist (IEEE)

- [x] Abstract one paragraph, 150–250 words (~198)
- [x] Index Terms alphabetical
- [x] Sections numbered I–VII (IEEE style)
- [x] Full project scope mapped (architecture + §§1–7 + batch + case)
- [x] Numbers from repo artifacts only (LF scalars marked pending)
- [ ] Authors / affiliations / funding
- [ ] Freeze LF situacional vs proyectado table from non-dry-run export
- [ ] Compile with IEEEtran; verify ≤ 10 pages
- [ ] Expand references; cover letter
- [ ] Coauthor approval
