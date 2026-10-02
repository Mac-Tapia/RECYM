import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState, type ComponentType } from "react";
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

const STEP_PAGES: Record<string, ComponentType> = {
  "/1": Step1Contexto,
  "/2": Step2CalidadTablero,
  "/3": Step3Clientes,
  "/4": Step4SpotLoad,
  "/5": Step5Flujos,
  "/6": Step6Informes,
  "/7": Step7Suite,
};

export function App() {
  const { feeder, studyPath, databaseMdb, setContext } = useFeeder();
  const location = useLocation();
  const [visited, setVisited] = useState<Set<string>>(() => new Set([location.pathname]));
  useEffect(() => {
    if (!STEP_PAGES[location.pathname]) return;
    setVisited((prev) =>
      prev.has(location.pathname) ? prev : new Set(prev).add(location.pathname)
    );
  }, [location.pathname]);
  const studyFile = (studyPath || "").split(/[/\\]/).pop() || "";
  const dbFile = (databaseMdb || "").split(/[/\\]/).pop() || "";

  useEffect(() => {
    // Bootstrap UNA sola vez al montar. No re-ejecutar cuando setContext
    // cambia (si no, pisa la selección nueva del formulario con settings viejos:
    // p.ej. sidebar AL209/BASE JUL25 mientras §1 ya tiene CA101V2/260924).
    let cancelled = false;
    (async () => {
      try {
        const j = await api<{
          ok?: boolean;
          current_feeder?: string;
          current_network?: string;
          current_study?: string;
          current_database?: string;
        }>("/api/contexto/archivos", { timeoutMs: 30000 });
        if (cancelled) return;
        if (j?.ok && (j.current_feeder || j.current_study || j.current_database)) {
          setContext({
            feeder: j.current_feeder || "",
            network: j.current_network || "",
            studyPath: j.current_study || "",
            databaseMdb: j.current_database || "",
          });
        }
      } catch {
        /* sin contexto aún */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo montaje
  }, []);

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
          {studyFile ? (
            <>
              <br />
              Estudio: <b>{studyFile}</b>
            </>
          ) : null}
          {dbFile ? (
            <>
              <br />
              BD: <b>{dbFile}</b>
            </>
          ) : null}
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
          <Route path="*" element={null} />
        </Routes>
        {/* Cada módulo se monta al visitarlo y queda vivo (oculto) al cambiar de
            paso: conserva selecciones y resultados hasta Actualizar/Restablecer,
            que recargan la página. */}
        {STEPS.filter((s) => visited.has(s.path)).map((s) => {
          const Page = STEP_PAGES[s.path];
          return (
            <div key={s.path} hidden={location.pathname !== s.path}>
              <Page />
            </div>
          );
        })}
      </main>
    </div>
  );
}
