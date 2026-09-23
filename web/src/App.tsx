import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useFeeder } from "./state/feeder";
import { api } from "./api/client";
import { Step1Contexto } from "./pages/Step1Contexto";
import { Step2CalidadTablero } from "./pages/Step2CalidadTablero";
import { Step3Clientes } from "./pages/Step3Clientes";
import { Step4SpotLoad } from "./pages/Step4SpotLoad";
import { Step5Flujos } from "./pages/Step5Flujos";
import { Step6Informes } from "./pages/Step6Informes";
import { Step7Suite } from "./pages/Step7Suite";

const STEPS = [
  { n: 1, path: "/1", title: "Contexto + cabecera", sub: "BD, estudio, medición" },
  { n: 2, path: "/2", title: "Calidad + Tablero", sub: "Diagnóstico y errores" },
  { n: 3, path: "/3", title: "Clientes + distribución", sub: "EA/Pot → SED" },
  { n: 4, path: "/4", title: "SpotLoad nueva", sub: "Carga concentrada" },
  { n: 5, path: "/5", title: "Flujos", sub: "Situacional / proyectado" },
  { n: 6, path: "/6", title: "Informes", sub: "OCR + entrega doc" },
  { n: 7, path: "/7", title: "Opt + Suite", sub: "Herramientas pipeline" },
];

export function App() {
  const { feeder } = useFeeder();

  async function refreshUi() {
    // Actualizar DEBE vaciar el tablero (campos → 0). Ping+reload solo
    // resucitaba el mismo tablero.json con errores viejos.
    try {
      await api("/api/ui/actualizar", {
        method: "POST",
        body: "{}",
        timeoutMs: 15000,
      });
    } catch {
      try {
        await api("/api/tablero?clear=1", { timeoutMs: 15000 });
      } catch {
        /* recargar igual */
      }
    }
    const u = window.location.pathname + window.location.search;
    const sep = u.indexOf("?") >= 0 ? "&" : "?";
    window.location.replace(u.replace(/[?&]_r=\d+/g, "") + sep + "_r=" + Date.now());
  }

  async function resetUi() {
    try {
      await api("/api/ui/reset", {
        method: "POST",
        body: "{}",
        timeoutMs: 15000,
      });
    } catch {
      try {
        await api("/api/tablero?clear=1", { timeoutMs: 15000 });
      } catch {
        /* recargar igual */
      }
    }
    const u = window.location.pathname;
    window.location.replace(u + "?_r=" + Date.now());
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>RECYM</h1>
        <div className="meta">
          Demanda Electro Dunas · SPA v6
          <br />
          Alimentador: <b>{feeder || "—"}</b>
        </div>
        <nav>
          {STEPS.map((s) => (
            <NavLink
              key={s.n}
              to={s.path}
              className={({ isActive }) => "nav-step" + (isActive ? " active" : "")}
            >
              <span className="num">{s.n}</span>
              <span className="label">
                {s.n} · {s.title}
                <span className="sub">{s.sub}</span>
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="actions" style={{ marginTop: 18 }}>
          <button type="button" className="secondary" onClick={refreshUi}>
            ↻ Actualizar
          </button>
          <button type="button" className="ghost" onClick={resetUi}>
            ⟲ Restablecer
          </button>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/1" replace />} />
          <Route path="/1" element={<Step1Contexto />} />
          <Route path="/2" element={<Step2CalidadTablero />} />
          <Route path="/3" element={<Step3Clientes />} />
          <Route path="/4" element={<Step4SpotLoad />} />
          <Route path="/5" element={<Step5Flujos />} />
          <Route path="/6" element={<Step6Informes />} />
          <Route path="/7" element={<Step7Suite />} />
        </Routes>
      </main>
    </div>
  );
}
