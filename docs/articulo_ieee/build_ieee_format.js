/**
 * Build IEEE-standardized 2-column Word manuscript (EN) for review.
 * Content from MANUSCRIPT.md math/results; layout approximates IEEEtran journal.
 * Run: node docs/articulo_ieee/build_ieee_format.js
 */
const fs = require("fs");
const path = require("path");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  AlignmentType,
  Header,
  Footer,
  PageNumber,
  ImageRun,
  Table,
  TableRow,
  TableCell,
  WidthType,
  BorderStyle,
  convertInchesToTwip,
} = require("docx");

const ROOT = __dirname;
const FIG = path.join(ROOT, "figures");
const OUT = path.join(ROOT, "RECYM_IEEE_standard.docx");
const OUT_ES = path.join(ROOT, "RECYM_IEEE_standard_ES.docx");

const thin = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const borders = { top: thin, bottom: thin, left: thin, right: thin };
const none = {
  top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};

function p(text, o = {}) {
  return new Paragraph({
    alignment: o.align || AlignmentType.JUSTIFIED,
    spacing: {
      after: o.after ?? 120,
      before: o.before ?? 0,
      line: o.line || 240,
    },
    indent: o.indent || undefined,
    children: [
      new TextRun({
        text,
        bold: !!o.bold,
        italics: !!o.italic,
        size: o.size || 20, // 10pt
        font: "Times New Roman",
      }),
    ],
  });
}

function runs(parts, o = {}) {
  return new Paragraph({
    alignment: o.align || AlignmentType.JUSTIFIED,
    spacing: { after: o.after ?? 120, before: o.before ?? 0, line: 240 },
    children: parts.map(
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

function h1(text) {
  // IEEE section: I. INTRODUCTION style
  return p(text, { bold: true, size: 20, align: AlignmentType.LEFT, before: 200, after: 120 });
}

function h2(text) {
  return p(text, { bold: true, italic: true, size: 20, align: AlignmentType.LEFT, before: 160, after: 100 });
}

function caption(text) {
  return p(text, { italic: true, size: 18, align: AlignmentType.CENTER, before: 60, after: 140 });
}

function img(file, w, h, alt) {
  const data = fs.readFileSync(path.join(FIG, file));
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120, after: 40 },
    children: [
      new ImageRun({
        type: "png",
        data,
        transformation: { width: w, height: h },
        altText: { title: alt, description: alt, name: file },
      }),
    ],
  });
}

function cell(text, w, o = {}) {
  return new TableCell({
    borders,
    width: { size: w, type: WidthType.DXA },
    children: [
      new Paragraph({
        children: [
          new TextRun({
            text,
            bold: !!o.bold,
            size: 16,
            font: "Times New Roman",
          }),
        ],
      }),
    ],
  });
}

function build(es) {
  const title = es
    ? "RECYM: Flujo Automatizado Multi-Alimentador para Asignacion de Demanda y Estudios de Flujo de Carga en Redes CYMDIST"
    : "RECYM: An Automated Multi-Feeder Workflow for Demand Allocation and Load-Flow Studies in CYMDIST Distribution Networks";

  const abstract = es
    ? "Las empresas de distribucion requieren procedimientos repetibles para limpiar modelos de red, asignar la demanda de cabecera, inyectar clientes importantes y SpotLoads prospectivas, y comparar casos situacional versus proyectado. Este articulo presenta RECYM, una suite multi-alimentador que acopla CYMDIST/CymPy con una SPA de siete pasos y un pipeline por lotes. El flujo integra diagnostico de red, mapeo energia/potencia a SED, asignacion por kWh via API COM, SpotLoads Locked, escenarios duales de flujo y artefactos de campana. RECYM opera sobre la BD Access de Electro Dunas con 97 configuraciones de alimentador y multiples estudios .zxst; PA217 (22,9 kV) es la muestra experimental. En PA217: 0 problemas de diagnostico, precision de clientes verificada, balance de asignacion (eps_P ~ 7.6e-5 %), SpotLoad de 1420 kW y flujos duales con delta_P = +17.17 %."
    : "Distribution utilities need repeatable procedures to clean network models, allocate measured headroom demand, inject important-customer and prospective spot loads, and compare situational versus projected operating cases. This paper presents RECYM, a multi-feeder software suite that couples CYMDIST/CymPy with a seven-step SPA and a batch pipeline. The workflow integrates network diagnostics, large-customer energy/power mapping to SED nodes, kWh-based load allocation via the CYMDIST COM API, locked three-phase spot loads, dual load-flow scenarios, and campaign artifacts. RECYM is wired to the Electro Dunas Access database with 97 feeder configurations and multiple .zxst studies; PA217 (22.9 kV) is the representative experimental sample. On PA217 the campaign achieved zero diagnostic problems, verified customer precision, allocation balance error eps_P ~ 7.6e-5%, a 1420 kW spot load, and dual load flows with delta_P = +17.17%.";

  const body = [];

  // Title block (single-column feel via full-width paragraphs before columns section - we use one section with 2 cols for all; title spans via continuous? docx-js: use first section 1-col then 2-col)
  const titleChildren = [
    p(title, { bold: true, size: 24, align: AlignmentType.CENTER, after: 200, line: 276 }),
    p(es ? "Mac Tapia Ccosyo" : "Mac Tapia Ccosyo", {
      align: AlignmentType.CENTER,
      size: 20,
      after: 40,
    }),
    p(es ? "Electro Dunas S.A.A., Peru" : "Electro Dunas S.A.A., Peru", {
      italic: true,
      align: AlignmentType.CENTER,
      size: 18,
      after: 40,
    }),
    p("e-mail: mtapia@electrodunas.com", {
      align: AlignmentType.CENTER,
      size: 18,
      after: 240,
    }),
    runs(
      [
        { text: es ? "Resumen—" : "Abstract—", bold: true, italic: true },
        { text: abstract, italic: true },
      ],
      { after: 160 }
    ),
    runs(
      [
        { text: es ? "Palabras clave—" : "Index Terms—", bold: true, italic: true },
        {
          text: es
            ? "asignacion de carga, CYMDIST, estudios de demanda, flujo de carga, modelado de sistemas de potencia, redes de distribucion, herramientas de software."
            : "CYMDIST, demand studies, distribution networks, load allocation, load flow analysis, power system modeling, software tools.",
          italic: true,
        },
      ],
      { after: 200 }
    ),
  ];

  const colChildren = [
    h1(es ? "I. INTRODUCCION" : "I. INTRODUCTION"),
    p(
      es
        ? "La planificacion de distribucion depende de modelos trifasicos detallados [1], [2]. CYMDIST ofrece asignacion y flujo desbalanceado [3], [4], pero las campanas suelen ser manuales. OpenDSS y pandapower automatizan investigacion [11], [12]; varias tesis migran CYMDIST a esas plataformas [13]-[15]. RECYM orquesta COM/CymPy sobre el .zxst/.mdb nativo, con arquitectura multi-alimentador (97 configs), campaña §§1-7, y validacion en la muestra PA217."
        : "Distribution planning relies on detailed three-phase feeder models [1], [2]. CYMDIST provides allocation and unbalanced load flow [3], [4], yet campaigns often remain manual. OpenDSS and pandapower automate research [11], [12]; theses often migrate CYMDIST models [13]-[15]. RECYM instead orchestrates COM/CymPy on native .zxst/.mdb assets, with a multi-feeder architecture (97 configs), a §§1-7 campaign, and validation on sample feeder PA217."
    ),
    p(
      es
        ? "Contribuciones: (i) arquitectura en capas L1-L5; (ii) modelos matematicos de asignacion kWh y LF dual con pseudocodigo; (iii) validacion estadistica experimental en PA217 como muestra del catalogo Electro Dunas."
        : "Contributions: (i) layered architecture L1-L5; (ii) mathematical models for kWh allocation and dual LF with pseudocode; (iii) experimental statistical validation on PA217 as a sample from the Electro Dunas catalog."
    ),

    h1(es ? "II. MARCO TEORICO Y TRABAJOS RELATED" : "II. THEORETICAL FRAMEWORK AND RELATED WORK"),
    h2(es ? "A. Flujo trifasico y asignacion" : "A. Three-Phase Flow and Allocation"),
    p(
      es
        ? "Kersting [1] y Cheng-Shirmohammadi [9], [10] fundamentan el flujo radial/debilmente mallado. La asignacion por energia suele superar a kVA cuando hay mediciones [7], [8]. CYMDIST implementa plantillas Connected+Total [4]."
        : "Kersting [1] and Cheng-Shirmohammadi [9], [10] underpin radial/weakly meshed flow. Energy-based allocation often outperforms connected-kVA when measurements exist [7], [8]. CYMDIST implements Connected+Total templates [4]."
    ),
    h2(es ? "B. Posicionamiento" : "B. Positioning"),
    p(
      es
        ? "A diferencia de conversiones CYMDIST→OpenDSS [13]-[15], RECYM no abandona el sistema de registro. Frente a integraciones utility [16], [17], anade orquestacion SPA/jobs, SpotLoad Locked y escenarios situacional/proyectado [23]-[25]."
        : "Unlike CYMDIST→OpenDSS conversions [13]-[15], RECYM keeps the system of record. Versus utility integrations [16], [17], it adds SPA/job orchestration, Locked SpotLoad, and situational/projected scenarios [23]-[25]."
    ),

    h1(es ? "III. ARQUITECTURA DEL SISTEMA" : "III. SYSTEM ARCHITECTURE"),
    p(
      es
        ? "RECYM se organiza en cinco capas L1..L5 (Fig. 1): SPA React; API FastAPI/SSE + puente Flask; dominio pipeline/analysis/optimization; nucleo CymPy/COM; datos .zxst/.mdb/Excel. Configuracion (S, F) con |F|=97 alimentadores + estudio ELD."
        : "RECYM is a five-layer stack L1..L5 (Fig. 1): React SPA; FastAPI/SSE API + Flask bridge; domain pipeline/analysis/optimization; CymPy/COM core; .zxst/.mdb/Excel data. Configuration (S, F) with |F|=97 feeders plus ELD study."
    ),
    img("fig1_architecture.png", 320, 210, "Fig. 1"),
    caption(es ? "Fig. 1. Arquitectura por capas de RECYM." : "Fig. 1. RECYM layered architecture."),
    img("fig2_workflow.png", 320, 140, "Fig. 2"),
    caption(es ? "Fig. 2. Campana operativa §§1-7." : "Fig. 2. Operational campaign §§1-7."),

    h1(es ? "IV. MODELOS MATEMATICOS Y ALGORITMOS" : "IV. MATHEMATICAL MODELS AND ALGORITHMS"),
    h2(es ? "A. Modelo de asignacion por kWh" : "A. kWh Allocation Model"),
    p(
      es
        ? "Sea Pcab la potencia de cabecera y L = F ∪ U la particion Locked/unlocked. El residual y la asignacion son Pcab_res = Pcab − Σ_j∈F Pj_fix y Pi = Pcab_res · Ei / Σ_u∈U Eu para i∈U. El error de balance es eps_P = |Σ_i Pi − Pcab| / Pcab · 100%. La precision usa MAE_P y RMSE_P de |ΔPi| con tolerancia 0.01 kW (0.5 kWh en energia). Este parrafo establece el primer modelo matematico cerrado [7], [8], [4]."
        : "Let Pcab be headroom active power and L = F ∪ U the Locked/unlocked partition. Residual and allocation are Pcab_res = Pcab − Σ_j∈F Pj_fix and Pi = Pcab_res · Ei / Σ_u∈U Eu for i∈U. Balance error is eps_P = |Σ_i Pi − Pcab| / Pcab · 100%. Precision uses MAE_P and RMSE_P of |ΔPi| with tolerance 0.01 kW (0.5 kWh for energy). This paragraph states the first closed-form mathematical model [7], [8], [4]."
    ),
    h2(es ? "B. Modelo SpotLoad y LF dual" : "B. Spot-Load and Dual LF Model"),
    p(
      es
        ? "Para SpotLoad (P3φ, Q3φ): Pφ = P3φ/3, Qφ = Q3φ/3, φ∈{A,B,C}, estado Locked. Con flag c∈{0,1}, y_sit = F(x; c=0) y y_prj = F(x; c=1); Δy = y_prj − y_sit; δP = 100·ΔP/Psit. Este parrafo establece el segundo modelo matematico [9], [10], [23]-[25]."
        : "For SpotLoad (P3φ, Q3φ): Pφ = P3φ/3, Qφ = Q3φ/3, φ∈{A,B,C}, Locked. With flag c∈{0,1}, y_sit = F(x; c=0) and y_prj = F(x; c=1); Δy = y_prj − y_sit; δP = 100·ΔP/Psit. This paragraph states the second mathematical model [9], [10], [23]-[25]."
    ),
    h2(es ? "C. Pseudocodigo" : "C. Pseudocode"),
    p(
      es
        ? "Algoritmo 1 (asignacion): calcular Pcab_res; repartir Pi por Ei; escribir COM; devolver eps_P. Algoritmo 2 (LF dual): desconectar SpotLoad → LF situacional; conectar → LF proyectado; Δy. Algoritmo 3 (campana): cabecera → diagnostico Nmsg=0 → Alg.1 → SpotLoad → Alg.2 → artefactos/cierre."
        : "Algorithm 1 (allocation): compute Pcab_res; distribute Pi by Ei; COM write; return eps_P. Algorithm 2 (dual LF): disconnect SpotLoad → situational LF; connect → projected LF; Δy. Algorithm 3 (campaign): headroom → diagnose Nmsg=0 → Alg.1 → SpotLoad → Alg.2 → artifacts/closure."
    ),

    h1(es ? "V. EXPERIMENTACION" : "V. EXPERIMENTATION"),
    p(
      es
        ? "Corpus: 97 configs + ELD, BD Access compartida, multiples .zxst. Muestra: PA217 (22.9 kV), 1324 nodos, 253 cargas. Cabecera L-PA235: P=9537.88 kW, Q=2587.65 kvar. Protocolo dry_run=false §§1-7. El informe de expediente (doc/informe.*) es un producto distinto; aqui se validan software y metodo."
        : "Corpus: 97 configs + ELD, shared Access DB, multiple .zxst. Sample: PA217 (22.9 kV), 1324 nodes, 253 loads. Headroom L-PA235: P=9537.88 kW, Q=2587.65 kvar. Protocol dry_run=false §§1-7. The utility delivery report (doc/informe.*) is a different product; here we validate software and method."
    ),

    h1(es ? "VI. RESULTADOS Y VALIDACION" : "VI. RESULTS AND VALIDATION"),
    p(
      es
        ? "Diagnostico: Nmsg=0. Precision: 11/11 OK, p-hat=1.00 (IC95% Clopper-Pearson [0.72, 1.00]), MAE=RMSE=0. Asignacion: eps_P ≈ 7.6×10^−5 %. SpotLoad 1420 kW; desbalance de fases 0. LF dual: ΔP=+1744 kW (δP=+17.17%), ΔQ=+986 kvar, ΔS=+1969.7 kVA; Vcab=99.84% en ambos. Cierre 21/21."
        : "Diagnostics: Nmsg=0. Precision: 11/11 OK, p-hat=1.00 (Clopper-Pearson 95% CI [0.72, 1.00]), MAE=RMSE=0. Allocation: eps_P ≈ 7.6×10^−5%. SpotLoad 1420 kW; phase imbalance 0. Dual LF: ΔP=+1744 kW (δP=+17.17%), ΔQ=+986 kvar, ΔS=+1969.7 kVA; Vhead=99.84% both cases. Closure 21/21."
    ),
    p(es ? "TABLA I. PRECISION CLIENTES (MUESTRA)" : "TABLE I. CUSTOMER PRECISION (SAMPLE)", {
      bold: true,
      align: AlignmentType.CENTER,
      size: 16,
      before: 100,
      after: 60,
    }),
    new Table({
      width: { size: 4680, type: WidthType.DXA },
      columnWidths: [1600, 900, 1100, 1080],
      rows: [
        new TableRow({
          children: [
            cell(es ? "Cliente" : "Customer", 1600, { bold: true }),
            cell("SED", 900, { bold: true }),
            cell("Pot kW", 1100, { bold: true }),
            cell("Status", 1080, { bold: true }),
          ],
        }),
        ...[
          ["Caliza cementos", "SE30940", "3800.57", "OK"],
          ["Minerales Paracas", "SE30480", "1273.76", "OK"],
          ["LJMetales", "SE30642", "956.49", "OK"],
          ["Emsalsa", "SE30353", "458.00", "OK"],
        ].map(
          (r) =>
            new TableRow({
              children: r.map((t, i) => cell(t, [1600, 900, 1100, 1080][i])),
            })
        ),
      ],
    }),
    img("fig6_lf_demand_compare.png", 300, 175, "Fig. 6"),
    caption(es ? "Fig. 3. Demanda situacional vs proyectado (PA217)." : "Fig. 3. Situational vs projected demand (PA217)."),
    img("fig3_topologia.png", 280, 200, "Topo"),
    caption(es ? "Fig. 4. Ubicacion SpotLoad 1420 kW (campana)." : "Fig. 4. SpotLoad 1420 kW location (campaign)."),
    img("fig4a_situacional_tension.png", 240, 170, "Vsit"),
    caption(es ? "Fig. 5. Tension situacional." : "Fig. 5. Situational voltage map."),
    img("fig4b_proyectado_tension.png", 240, 170, "Vprj"),
    caption(es ? "Fig. 6. Tension proyectado." : "Fig. 6. Projected voltage map."),

    h1(es ? "VII. CONCLUSION" : "VII. CONCLUSION"),
    p(
      es
        ? "RECYM formaliza arquitectura, modelos de asignacion/LF dual, pseudocodigo y validacion sobre un catalogo de 97 alimentadores, con PA217 como muestra. Trabajo futuro: KPIs de flota, plantilla IEEEtran oficial y AMI."
        : "RECYM formalizes architecture, allocation/dual-LF models, pseudocode, and validation on a 97-feeder catalog, with PA217 as sample. Future work: fleet KPIs, official IEEEtran camera-ready, and AMI."
    ),

    h1(es ? "REFERENCIAS" : "REFERENCES"),
    ...[
      "[1] W. H. Kersting, Distribution System Modeling and Analysis, 4th ed. CRC Press, 2017.",
      "[2] T. Gonen, Electric Power Distribution Engineering, 3rd ed. CRC Press, 2014.",
      "[3] H. L. Willis, Power Distribution Planning Reference Book, 2nd ed. Marcel Dekker, 2004.",
      "[4] Eaton CYME, CYMDIST Reference Manual, v9.2, 2022.",
      "[5] A. K. Ghosh et al., IEEE Trans. Power Del., vol. 12, no. 2, pp. 999-1005, 1997.",
      "[6] M. E. Baran and A. W. Kelley, IEEE Trans. Power Syst., vol. 9, no. 3, pp. 1601-1609, 1994.",
      "[7] R. F. Arritt et al., in Proc. IEEE REPC, 2012.",
      "[8] J. Peppanen et al., in Proc. IEEE PSC, 2018.",
      "[9] D. Shirmohammadi et al., IEEE Trans. Power Syst., vol. 3, no. 2, pp. 753-762, 1988.",
      "[10] C. S. Cheng and D. Shirmohammadi, IEEE Trans. Power Syst., vol. 10, no. 2, pp. 671-679, 1995.",
      "[11] R. C. Dugan and T. E. McDermott, in Proc. IEEE PES GM, 2011.",
      "[12] L. Thurner et al., IEEE Trans. Power Syst., vol. 33, no. 6, pp. 6510-6521, 2018.",
      "[13] V. Ramachandran, M.S. thesis, West Virginia Univ., 2011.",
      "[16] R. H. Chumbi and T. I. Verdugo, Tesis, Univ. de Cuenca, 2013.",
      "[17] N. A. Ramos and W. E. Espinoza, Tesis de maestria, UNAC, 2023.",
      "[18] D. W. Puma Ttito, Tesis doctoral, UNI, 2024.",
      "[23] M. Rylander et al., in Proc. IEEE REPC, 2015.",
      "[26] IEEE Std 1547-2018.",
    ].map((r) => p(r, { size: 16, after: 60, align: AlignmentType.LEFT })),
  ];

  return new Document({
    styles: {
      default: {
        document: {
          styles: [{ id: "Normal", run: { font: "Times New Roman", size: 20 } }],
        },
      },
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: 12240, height: 15840 }, // Letter
            margin: {
              top: convertInchesToTwip(0.75),
              bottom: convertInchesToTwip(1.0),
              left: convertInchesToTwip(0.625),
              right: convertInchesToTwip(0.625),
            },
          },
        },
        headers: {
          default: new Header({
            children: [
              p(es ? "RECYM — formato IEEE (revision)" : "RECYM — IEEE-format draft (review)", {
                italic: true,
                size: 14,
                align: AlignmentType.RIGHT,
                after: 0,
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
                  new TextRun({ text: "", size: 16, font: "Times New Roman" }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, font: "Times New Roman" }),
                ],
              }),
            ],
          }),
        },
        children: titleChildren,
      },
      {
        properties: {
          page: {
            size: { width: 12240, height: 15840 },
            margin: {
              top: convertInchesToTwip(0.75),
              bottom: convertInchesToTwip(1.0),
              left: convertInchesToTwip(0.625),
              right: convertInchesToTwip(0.625),
            },
          },
          column: {
            count: 2,
            space: convertInchesToTwip(0.25),
            equalWidth: true,
          },
        },
        headers: {
          default: new Header({
            children: [
              p("Mac Tapia Ccosyo: RECYM multi-feeder CYMDIST workflow", {
                italic: true,
                size: 14,
                align: AlignmentType.CENTER,
                after: 0,
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
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, font: "Times New Roman" }),
                ],
              }),
            ],
          }),
        },
        children: colChildren,
      },
    ],
  });
}

async function main() {
  const en = build(false);
  const es = build(true);
  fs.writeFileSync(OUT, await Packer.toBuffer(en));
  fs.writeFileSync(OUT_ES, await Packer.toBuffer(es));
  console.log("Wrote", OUT);
  console.log("Wrote", OUT_ES);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
