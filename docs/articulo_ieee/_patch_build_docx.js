const fs = require("fs");
const p = "docs/articulo_ieee/build_docx.js";
let s = fs.readFileSync(p, "utf8");
const needle = 'h2(es ? "IV. FLUJO DE TRABAJO PROPUESTO" : "IV. PROPOSED WORKFLOW"),';
if (!s.includes(needle)) {
  console.log("needle missing or already patched");
  process.exit(0);
}
const insert = `h2(es ? "IV. MODELOS MATEMATICOS Y ALGORITMOS" : "IV. MATHEMATICAL MODELS AND ALGORITHMS"),
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
`;
s = s.replace(needle, insert + "\n    " + needle);
fs.writeFileSync(p, s);
console.log("build_docx patched OK");
