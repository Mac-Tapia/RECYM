import { useFeeder } from "../state/feeder";

/** Muestra el enlace §1 (alimentador · estudio · BD) usado en CYMDIST. */
export function ContextBind({ hint }: { hint?: string }) {
  const { feeder, studyPath, databaseMdb } = useFeeder();
  const studyFile = (studyPath || "").split(/[/\\]/).pop() || "";
  const dbFile = (databaseMdb || "").split(/[/\\]/).pop() || "";
  const ok = Boolean(feeder && studyPath && databaseMdb);

  return (
    <p className="muted" style={{ marginTop: 0 }}>
      {hint ? `${hint} · ` : null}
      Contexto CYMDIST:{" "}
      <b>{feeder || "—"}</b>
      {" · estudio "}
      <b title={studyPath || ""}>{studyFile || "—"}</b>
      {" · BD "}
      <b title={databaseMdb || ""}>{dbFile || "—"}</b>
      {!ok ? (
        <span style={{ color: "#b45309" }}>
          {" "}
          — configure §1 y pulse <b>1.1 Aplicar</b>
        </span>
      ) : null}
    </p>
  );
}

export function useHasSectionContext() {
  const { feeder, studyPath, databaseMdb } = useFeeder();
  return Boolean(feeder && studyPath && databaseMdb);
}
