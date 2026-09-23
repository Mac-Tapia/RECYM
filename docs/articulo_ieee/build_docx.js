/**
 * Build IEEE draft Word manuscripts (EN + ES) with embedded figures.
 * Run: node docs/articulo_ieee/build_docx.js
 */
const fs = require("fs");
const path = require("path");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  AlignmentType,
  Table,
  TableRow,
  TableCell,
  WidthType,
  BorderStyle,
  Header,
  Footer,
  PageNumber,
  ImageRun,
  PageBreak,
} = require("docx");

const ROOT = __dirname;
const FIG = path.join(ROOT, "figures");

const thin = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const borders = { top: thin, bottom: thin, left: thin, right: thin };

function p(text, opts = {}) {
  const {
    bold = false,
    italic = false,
    size = 20,
    align = AlignmentType.JUSTIFIED,
    spaceAfter = 120,
    spaceBefore = 0,
  } = opts;
  return new Paragraph({
    alignment: align,
    spacing: { after: spaceAfter, before: spaceBefore, line: 276 },
    children: [
      new TextRun({ text, bold, italics: italic, size, font: "Times New Roman" }),
    ],
  });
}

function mixed(runs, opts = {}) {
  const { align = AlignmentType.JUSTIFIED, spaceAfter = 120, spaceBefore = 0 } = opts;
  return new Paragraph({
    alignment: align,
    spacing: { after: spaceAfter, before: spaceBefore, line: 276 },
    children: runs.map(
      (r) =>
        new TextRun({
          text: r.text,
          bold: !!r.bold,
          italics: !!r.italic,
          size: r.size || 20,
          font: "Times New Roman",
        })
    ),
  });
}

function h2(text) {
  return p(text, {
    bold: true,
    size: 22,
    align: AlignmentType.LEFT,
    spaceBefore: 280,
    spaceAfter: 140,
  });
}

function caption(text) {
  return p(text, {
    italic: true,
    size: 18,
    align: AlignmentType.CENTER,
    spaceBefore: 80,
    spaceAfter: 200,
  });
}

function cell(text, width, opts = {}) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    children: [
      new Paragraph({
        children: [
          new TextRun({
            text,
            bold: !!opts.bold,
            size: 17,
            font: "Times New Roman",
          }),
        ],
      }),
    ],
  });
}

function img(file, widthPx, heightPx, alt) {
  const data = fs.readFileSync(path.join(FIG, file));
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 160, after: 40 },
    children: [
      new ImageRun({
        type: "png",
        data,
        transformation: { width: widthPx, height: heightPx },
        altText: { title: alt, description: alt, name: file },
      }),
    ],
  });
}

function tableI(es) {
  const H = es
    ? ["Cliente", "SED", "EA (kWh)", "Pot (kW)", "ΔkWh", "ΔkW", "Estado"]
    : ["Customer", "SED", "EA (kWh)", "Pot (kW)", "ΔkWh", "ΔkW", "Status"];
  const rows = [
    ["Caliza cementos inca", "SE30940", "1,747,551.27", "3800.57", "0.0", "0.0", "OK"],
    ["Minerales Paracas", "SE30480", "678,852.12", "1273.76", "0.0", "0.0", "OK"],
    ["LJMetales", "SE30642", "527,079.81", "956.49", "0.0", "0.0", "OK"],
    ["Emsalsa", "SE30353", "157,621.44", "458.00", "0.0", "0.0", "OK"],
    ["Uvica", "SE30424", "167,101.44", "366.30", "0.0", "0.0", "OK"],
  ];
  const w = [2100, 1100, 1800, 1400, 1000, 1000, 960];
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: w,
    rows: [
      new TableRow({ children: H.map((t, i) => cell(t, w[i], { bold: true })) }),
      ...rows.map(
        (r) => new TableRow({ children: r.map((t, i) => cell(t, w[i])) })
      ),
    ],
  });
}

const REFS = [
  "[1] W. H. Kersting, Distribution System Modeling and Analysis, 4th ed. Boca Raton, FL, USA: CRC Press, 2017.",
  "[2] T. Gönen, Electric Power Distribution Engineering, 3rd ed. Boca Raton, FL, USA: CRC Press, 2014.",
  "[3] Eaton CYME, CYMDIST Reference Manual / How-to Tutorials (Load Allocation, Load Flow), version 9.2. Saint-Bruno, QC, Canada: Eaton, 2022.",
  "[4] R. C. Dugan, M. F. McGranaghan, S. Santoso, and H. W. Beaty, Electrical Power Systems Quality, 3rd ed. New York, NY, USA: McGraw-Hill, 2012.",
  "[5] R. C. Dugan and T. E. McDermott, “An open source platform for collaborating on smart grid research,” in Proc. IEEE Power Energy Soc. Gen. Meeting, Detroit, MI, USA, 2011, pp. 1–7.",
  "[6] L. Thurner et al., “pandapower—An open-source Python tool for convenient modeling, analysis, and optimization of electric power systems,” IEEE Trans. Power Syst., vol. 33, no. 6, pp. 6510–6521, Nov. 2018.",
  "[7] J. Peppanen, M. J. Reno, M. Thakkar, S. Grijalva, and R. G. Harley, “Leveraging AMI data for distribution system model calibration and situational awareness,” IEEE Trans. Smart Grid, vol. 6, no. 4, pp. 2000–2009, Jul. 2015.",
  "[8] Y. Wang, Q. Chen, T. Hong, and C. Kang, “Review of smart meter data analytics: Applications, methodologies, and challenges,” IEEE Trans. Smart Grid, vol. 10, no. 3, pp. 3125–3148, May 2019.",
  "[9] A. K. Ghosh, D. L. Lubkeman, and R. H. Jones, “Load modeling for distribution circuit state estimation,” IEEE Trans. Power Del., vol. 12, no. 2, pp. 999–1005, Apr. 1997.",
  "[10] M. E. Baran and A. W. Kelley, “State estimation for real-time monitoring of distribution systems,” IEEE Trans. Power Syst., vol. 9, no. 3, pp. 1601–1609, Aug. 1994.",
  "[11] T. Brown, J. Hörsch, and D. Schlachtberger, “PyPSA: Python for power system analysis,” J. Open Res. Softw., vol. 6, no. 1, Art. no. 4, 2018.",
  "[12] M. Rylander, J. Smith, and W. Sunderman, “Streamlined method for determining distribution system hosting capacity,” in Proc. IEEE Rural Electric Power Conf., Asheville, NC, USA, 2015, pp. 3–9.",
  "[13] F. Ding and B. Mather, “On distributed PV hosting capacity estimation, sensitivity study, and improvement,” IEEE Trans. Sustain. Energy, vol. 8, no. 3, pp. 1010–1020, Jul. 2017.",
  "[14] IEEE Standard for Interconnection and Interoperability of Distributed Energy Resources with Associated Electric Power Systems Interfaces, IEEE Std 1547-2018, Apr. 2018.",
  "[15] H. L. Willis, Power Distribution Planning Reference Book, 2nd ed. New York, NY, USA: Marcel Dekker, 2004.",
  "[16] J. A. Momoh, Electric Power Distribution, Automation, Protection, and Control. Boca Raton, FL, USA: CRC Press, 2008.",
  "[17] A. Abur and A. G. Expósito, Power System State Estimation: Theory and Implementation. New York, NY, USA: Marcel Dekker, 2004.",
  "[18] OSINERGMIN, Normativa técnica de calidad de servicio eléctrico / distribución (Perú). Lima, Peru. [Online]. Available: https://www.osinergmin.gob.pe",
  "[19] IEEE Guide for Electric Power Distribution Reliability Indices, IEEE Std 1366-2022, 2022.",
  "[20] S. Conti, S. Raiti, G. Tina, and U. Vagliasindi, “Study of the impact of PV generation on voltage profile in LV distribution networks,” in Proc. IEEE Power Tech, St. Petersburg, Russia, 2005, pp. 1–6.",
];

function buildDoc(es) {
  const title = es
    ? "RECYM: Flujo automatizado multi-alimentador para asignación de demanda y estudios de flujo de carga en redes de distribución CYMDIST"
    : "RECYM: An Automated Multi-Feeder Workflow for Demand Allocation and Load-Flow Studies in CYMDIST Distribution Networks";

  const children = [
    p(title, { bold: true, size: 26, align: AlignmentType.CENTER, spaceAfter: 160 }),
    p("Mac Tapia Ccosyo", {
      align: AlignmentType.CENTER,
      size: 20,
      spaceAfter: 40,
    }),
    p(
      es
        ? "Electro Dunas S.A.A. (empresa concesionaria)  ·  mtapia@electrodunas.com"
        : "Electro Dunas S.A.A. (distribution concessionaire)  ·  mtapia@electrodunas.com",
      {
        align: AlignmentType.CENTER,
        size: 18,
        italic: true,
        spaceAfter: 240,
      }
    ),

    p(es ? "Resumen" : "Abstract", { bold: true, align: AlignmentType.LEFT, spaceAfter: 80 }),
    p(
      es
        ? "Las empresas de distribución requieren procedimientos repetibles para limpiar modelos de red, asignar la demanda medida en cabecera, inyectar clientes importantes y cargas concentradas prospectivas, y comparar casos situacional versus proyectado. Este artículo presenta RECYM, una suite multi-alimentador que acopla CYMDIST/CymPy con una SPA de siete pasos y un pipeline por lotes. El flujo integra diagnóstico de red, mapeo energía/potencia a SED, asignación por kWh vía API COM, SpotLoads Locked, escenarios duales de flujo e informes automatizados. En el alimentador PA217 (22,9 kV, Electro Dunas), la campaña cerró con cero problemas de diagnóstico, clientes verificados dentro de tolerancia, asignación balanceada (9537,9 kW vs. 9537,88 kW), SpotLoad de 1420 kW y flujos situacional/proyectado exitosos. La arquitectura escala a ~96 alimentadores con BD Access compartida."
        : "Distribution utilities need repeatable procedures to clean network models, allocate measured substation demand, inject important-customer and prospective spot loads, and compare situational versus projected operating cases. This paper presents RECYM, a multi-feeder software suite that couples CYMDIST/CymPy with a seven-step SPA and a batch pipeline. The workflow integrates network diagnostics, large-customer energy/power mapping to SED nodes, kWh-based load allocation via the CYMDIST COM API, locked three-phase spot loads, dual load-flow scenarios, and automated delivery reports. On feeder PA217 (22.9 kV, Electro Dunas), the campaign closed with zero diagnostic problems, customers verified within tolerances, headroom-balanced allocation (9537.9 kW vs. 9537.88 kW), a 1420 kW prospective spot load, and successful dual load flows. The architecture scales to ~96 feeders sharing one Access database."
    ),
    mixed(
      [
        { text: es ? "Palabras clave—" : "Index Terms—", bold: true, italic: true },
        {
          text: es
            ? "CYMDIST, estudios de demanda, redes de distribución, asignación de carga, flujo de carga, modelado de sistemas de potencia, herramientas de software."
            : "CYMDIST, demand studies, distribution networks, load allocation, load flow analysis, power system modeling, software tools.",
          italic: true,
        },
      ],
      { spaceAfter: 220 }
    ),

    h2(es ? "I. INTRODUCCIÓN" : "I. INTRODUCTION"),
    p(
      es
        ? "La planificación de distribución depende de modelos detallados de alimentadores para evaluar tensión, cargabilidad e impacto de nuevos clientes [1], [2]. CYMDIST ofrece asignación de carga y flujo desbalanceado [3], pero las campañas suelen ser manuales en GUI. Herramientas abiertas como OpenDSS [5] y pandapower [6] automatizan investigación; muchas utilities latinoamericanas, sin embargo, estandarizan .zxst/.mdb. RECYM cierra esa brecha [7], [8] con arquitectura por capas, campaña §§1–7 y validación en PA217 (22,9 kV)."
        : "Modern distribution planning relies on detailed feeder models [1], [2]. CYMDIST provides load allocation and unbalanced load flow [3], yet campaigns often remain manual. OpenDSS [5] and pandapower [6] support research automation, while many Latin American utilities standardize on .zxst/.mdb assets. RECYM bridges that gap [7], [8] with a layered architecture, a §§1–7 campaign, and validation on PA217 (22.9 kV)."
    ),

    h2(es ? "II. TRABAJOS RELACIONADOS" : "II. RELATED WORK"),
    p(
      es
        ? "Kersting [1] formaliza el modelado trifásico. La asignación usa energía/demanda/kVA como pesos [3], [9]. La automatización COM de herramientas comerciales es crítica cuando el sistema de registro es propietario [7], [8]. Estudios de capacidad e interconexión motivan narrativas situacional vs. proyectado [12]–[14]."
        : "Kersting [1] formalizes three-phase modeling. Allocation uses energy/demand/kVA weights [3], [9]. COM automation of commercial tools is critical when the system of record is proprietary [7], [8]. Capacity and interconnection studies motivate situational vs. projected narratives [12]–[14]."
    ),

    h2(es ? "III. ARQUITECTURA DEL SISTEMA" : "III. SYSTEM ARCHITECTURE"),
    p(
      es
        ? "Cinco capas: presentación (SPA React), API (FastAPI jobs/SSE + puente Flask), dominio (pipeline/analysis/optimization), núcleo CymPy/COM y datos externos (.zxst/.mdb/Excel). Config multi-alimentador vía settings.json + feeders/<ID>.json (~96 alimentadores + estudio ELD)."
        : "Five layers: presentation (React SPA), API (FastAPI jobs/SSE + Flask bridge), domain (pipeline/analysis/optimization), CymPy/COM core, and external data (.zxst/.mdb/Excel). Multi-feeder config via settings.json + feeders/<ID>.json (~96 feeders + ELD study)."
    ),
    img("fig1_architecture.png", 520, 340, "Fig. 1 Architecture"),
    caption(
      es
        ? "Fig. 1. Arquitectura por capas de RECYM (UI → API → dominio → núcleo CYMDIST → datos)."
        : "Fig. 1. RECYM layered architecture (UI → API → domain → CYMDIST core → data)."
    ),

    h2(es ? "IV. MODELOS MATEMATICOS Y ALGORITMOS" : "IV. MATHEMATICAL MODELS AND ALGORITHMS"),
    p(
      es
        ? "Modelo 1 (asignacion kWh): Pcab_res = Pcab - suma Pfix; Pi = Pcab_res * Ei / suma Eu; error eps_P = |suma Pi - Pcab|/Pcab * 100%. Precision MAE/RMSE de DeltaP, DeltaE (tol. 0.01 kW / 0.5 kWh)."
        : "Model 1 (kWh allocation): Pcab_res = Pcab - sum Pfix; Pi = Pcab_res * Ei / sum Eu; balance error eps_P = |sum Pi - Pcab|/Pcab * 100%. Precision MAE/RMSE of DeltaP, DeltaE (tol. 0.01 kW / 0.5 kWh)."
    ),
    p(
      es
        ? "Modelo 2 (SpotLoad + LF dual): Pphase = P3ph/3, Qphase = Q3ph/3; y_sit = F(x; c=0), y_prj = F(x; c=1); Delta y = y_prj - y_sit; delta_P = 100*DeltaP/Psit. Pseudocodigo Algoritmos 1-3. Validacion muestra PA217: eps_P ~ 7.6e-5%, MAE=0, delta_P=+17.17%, cierre 21/21."
        : "Model 2 (SpotLoad + dual LF): Pphase = P3ph/3, Qphase = Q3ph/3; y_sit = F(x; c=0), y_prj = F(x; c=1); Delta y = y_prj - y_sit; delta_P = 100*DeltaP/Psit. Pseudocode Algorithms 1-3. Sample PA217 validation: eps_P ~ 7.6e-5%, MAE=0, delta_P=+17.17%, closure 21/21."
    ),
    h2(es ? "IV-bis. FLUJO OPERATIVO" : "IV-bis. OPERATIONAL WORKFLOW"),

    h2(es ? "IV. FLUJO DE TRABAJO PROPUESTO" : "IV. PROPOSED WORKFLOW"),
    p(
      es
        ? "§1 contexto/cabecera; §2 compuerta de calidad; §3 clientes EA→KWH / Pot→kW Locked + asignación; §4 SpotLoad P/3 Q/3 Locked (sin redistribuir después); §5 LF situacional (desconecta §4) / proyectado (conecta §4); §§6–7 informes y suite."
        : "§1 context/headroom; §2 quality gate; §3 customers EA→KWH / Pot→kW Locked + allocation; §4 SpotLoad P/3 Q/3 Locked (no re-allocation afterward); §5 situational (disconnect §4) / projected (connect §4) LF; §§6–7 reports and suite."
    ),
    img("fig2_workflow.png", 540, 235, "Fig. 2 Workflow"),
    caption(
      es
        ? "Fig. 2. Campaña operativa RECYM §§1–7."
        : "Fig. 2. RECYM operational campaign §§1–7."
    ),

    h2(es ? "V. CASO DE ESTUDIO" : "V. CASE STUDY"),
    p(
      es
        ? "RECYM ya opera sobre la BD Access de Electro Dunas con 97 configuraciones de alimentador y múltiples estudios .zxst; PA217 (22,9 kV) se reporta como muestra experimental representativa. En PA217: 0 problemas de diagnóstico, clientes verificados, asignación balanceada (9537,9 vs 9537,88 kW), SpotLoad 1420 kW y LF situacional/proyectado con deltas P/Q/S cuantificados."
        : "RECYM is already wired to the Electro Dunas Access database with 97 feeder configurations and multiple .zxst studies; PA217 (22.9 kV) is reported as a representative experimental sample. On PA217: zero diagnostic problems, verified customers, headroom-balanced allocation (9537.9 vs 9537.88 kW), 1420 kW SpotLoad, and dual LF with quantified P/Q/S deltas.",
      { spaceAfter: 120 }
    ),
    p(
      es
        ? "Corpus: 97 feeders + ELD; BD compartida; estudios .zxst múltiples. PA217 es muestra para validar RECYM (no es el informe de entrega de doc/)."
        : "Corpus: 97 feeders + ELD; shared DB; multiple .zxst. PA217 is a sample to validate RECYM (not the delivery report in doc/).",
      { spaceAfter: 160 }
    ),

    h2(es ? "VI. RESULTADOS Y DISCUSIÓN" : "VI. RESULTS AND DISCUSSION"),
    p(
      es
        ? "Diagnóstico: 0 mensajes / 0 problemas. Precisión clientes: 11 OK, 0 fallos (Tabla I). Asignación COM: ΣP=9537,9 kW vs cabecera 9537,88 kW (Δ≈0%), 257 cargas. SpotLoad Locked 1420 kW en NODE_1080_320357_MI-17145_2 (Fig. 3). Flujos situacional y proyectado OK (Figs. 4–5). Cierre automatizado 21/21 pasos."
        : "Diagnostics: 0 messages / 0 problems. Customer precision: 11 OK, 0 fails (Table I). COM allocation: ΣP=9537.9 kW vs headroom 9537.88 kW (Δ≈0%), 257 loads. Locked SpotLoad 1420 kW at NODE_1080_320357_MI-17145_2 (Fig. 3). Situational and projected LF OK (Figs. 4–5). Automated closure 21/21 steps."
    ),
    p(
      es
        ? "TABLA I. PRECISIÓN DE CLIENTES IMPORTANTES EN PA217 (MUESTRA)"
        : "TABLE I. IMPORTANT-CUSTOMER PRECISION ON PA217 (SAMPLE)",
      { bold: true, align: AlignmentType.CENTER, size: 18, spaceBefore: 120, spaceAfter: 80 }
    ),
    tableI(es),

    img("fig3_topologia.png", 480, 340, "Fig. 3 Topology"),
    caption(
      es
        ? "Fig. 3. Ubicación de la SpotLoad prospectiva (1420 kW) en PA217."
        : "Fig. 3. Location of the prospective SpotLoad (1420 kW) on PA217."
    ),

    img("fig4a_situacional_tension.png", 420, 300, "Fig. 4a"),
    caption(
      es
        ? "Fig. 4a. Mapa de tensión — escenario situacional (SpotLoad §4 desconectada)."
        : "Fig. 4a. Voltage map — situational scenario (SpotLoad §4 disconnected)."
    ),
    img("fig4b_proyectado_tension.png", 420, 300, "Fig. 4b"),
    caption(
      es
        ? "Fig. 4b. Mapa de tensión — escenario proyectado (SpotLoad §4 conectada)."
        : "Fig. 4b. Voltage map — projected scenario (SpotLoad §4 connected)."
    ),

    img("fig5a_situacional_cargabilidad.png", 420, 300, "Fig. 5a"),
    caption(
      es
        ? "Fig. 5a. Cargabilidad — escenario situacional."
        : "Fig. 5a. Loading — situational scenario."
    ),
    img("fig5b_proyectado_cargabilidad.png", 420, 300, "Fig. 5b"),
    caption(
      es
        ? "Fig. 5b. Cargabilidad — escenario proyectado (muestra PA217)."
        : "Fig. 5b. Loading — projected scenario (sample PA217)."
    ),

    img("fig6_lf_demand_compare.png", 480, 280, "Fig. 6"),
    caption(
      es
        ? "Fig. 6. Demanda de cabecera situacional vs proyectado (datos reales LF COM PA217)."
        : "Fig. 6. Headroom demand situational vs projected (real COM LF data, PA217)."
    ),
    img("fig7_lf_voltage_pf_table.png", 480, 220, "Fig. 7"),
    caption(
      es
        ? "Fig. 7. Tabla III visual: tensión, FP y P/Q/S (muestra PA217)."
        : "Fig. 7. Visual Table III: voltage, PF and P/Q/S (sample PA217)."
    ),
    img("fig8_clientes_pot.png", 480, 260, "Fig. 8"),
    caption(
      es
        ? "Fig. 8. Pot (kW) de clientes importantes verificados en la muestra PA217."
        : "Fig. 8. Verified important-customer Pot (kW) on sample PA217."
    ),
    img("fig9_cierre_steps.png", 500, 280, "Fig. 9"),
    caption(
      es
        ? "Fig. 9. Cierre automatizado §§1–7 en PA217 (21/21 OK)."
        : "Fig. 9. Automated §§1–7 closure on PA217 (21/21 OK)."
    ),

    p(
      es
        ? "Limitaciones: Windows/COM; integridad .zxst; fallback COM. Las tablas detalladas son de la muestra PA217; el catálogo ya tiene 97 alimentadores y múltiples estudios — KPIs de flota quedan como trabajo futuro."
        : "Limitations: Windows/COM; study integrity; COM fallback. Detailed tables are for sample PA217; the catalog already has 97 feeders and multiple studies—fleet KPIs remain future work.",
      { spaceBefore: 80 }
    ),

    h2(es ? "VII. CONCLUSIÓN" : "VII. CONCLUSION"),
    p(
      es
        ? "RECYM automatiza campañas CYMDIST multi-alimentador sobre 97 alimentadores Electro Dunas y múltiples .zxst. Con PA217 como muestra representativa: 0 problemas de diagnóstico, precisión verificada, asignación balanceada, LF dual para 1420 kW y cierre 21/21. Trabajo futuro: KPIs de flota sobre el catálogo completo y endurecimiento §7."
        : "RECYM automates multi-feeder CYMDIST campaigns across 97 Electro Dunas feeders and multiple .zxst studies. With PA217 as representative sample: zero diagnostic issues, verified precision, balanced allocation, dual LF for 1420 kW, and 21/21 closure. Future work: fleet KPIs over the full catalog and §7 hardening."
    ),

    h2(es ? "REFERENCIAS" : "REFERENCES"),
    ...REFS.map((r) => p(r, { align: AlignmentType.LEFT, size: 17, spaceAfter: 70 })),

    p(
      es
        ? "Nota: pegar en plantilla oficial IEEE antes del envío. Texto: MANUSCRIPT_ES.md. BibTeX: references.bib. Autor: Mac Tapia Ccosyo (Electro Dunas S.A.A.)."
        : "Note: paste into the official IEEE template before submission. Text: MANUSCRIPT.md. BibTeX: references.bib. Author: Mac Tapia Ccosyo (Electro Dunas S.A.A.).",
      { italic: true, size: 15, spaceBefore: 200, align: AlignmentType.LEFT }
    ),
  ];

  return new Document({
    sections: [
      {
        properties: {
          page: {
            size: { width: 12240, height: 15840 },
            margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [
                  new TextRun({
                    text: es
                      ? "RECYM — borrador IEEE ES v0.2 (con figuras)"
                      : "RECYM — IEEE draft EN v0.2 (with figures)",
                    italics: true,
                    size: 14,
                    font: "Times New Roman",
                    color: "666666",
                  }),
                ],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: "Page ", size: 14, font: "Times New Roman" }),
                  new TextRun({
                    children: [PageNumber.CURRENT],
                    size: 14,
                    font: "Times New Roman",
                  }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
}

async function main() {
  const en = buildDoc(false);
  const es = buildDoc(true);
  const enBuf = await Packer.toBuffer(en);
  const esBuf = await Packer.toBuffer(es);
  const enPath = path.join(ROOT, "RECYM_IEEE_draft.docx");
  const esPath = path.join(ROOT, "RECYM_IEEE_draft_ES.docx");
  fs.writeFileSync(enPath, enBuf);
  fs.writeFileSync(esPath, esBuf);
  console.log("Wrote", enPath);
  console.log("Wrote", esPath);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
