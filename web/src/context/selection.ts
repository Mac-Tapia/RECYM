export type FeederOption = {
  feeder_id: string;
  network_id: string;
  label?: string;
};

export type StudyOption = {
  path: string;
  feeder_id?: string;
  ext?: string;
};

export function studiesForFeeder(
  studies: Array<StudyOption | string>,
  feederId: string
): Array<StudyOption | string> {
  const wanted = (feederId || "").trim().toUpperCase();
  if (!wanted) return [];

  return (studies || []).filter((study) => {
    const path = typeof study === "string" ? study : study.path;
    const stem = path.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "";
    const owner = (typeof study === "string" ? stem : study.feeder_id || stem)
      .trim()
      .toUpperCase();
    if (owner === "ELD") return true;
    const family = owner.match(/^([A-Z]{1,3}\d{2,4})/)?.[1] || owner;
    return family === wanted;
  });
}

/** Estudio dedicado exacto del alimentador; nunca reutiliza otro por defecto. */
export function chooseStudyForFeeder(
  studies: StudyOption[],
  feederId: string
): string {
  const wanted = (feederId || "").trim().toUpperCase();
  if (!wanted) return "";
  const rank: Record<string, number> = {
    ".zxst": 0,
    ".sxst": 1,
    ".zsxst": 2,
    ".xst": 3,
  };
  const matches = (studies || []).filter(
    (item) => String(item.feeder_id || "").trim().toUpperCase() === wanted
  );
  matches.sort((a, b) => {
    const extA = String(a.ext || a.path.match(/\.[^.\\/]+$/)?.[0] || "").toLowerCase();
    const extB = String(b.ext || b.path.match(/\.[^.\\/]+$/)?.[0] || "").toLowerCase();
    return (rank[extA] ?? 9) - (rank[extB] ?? 9);
  });
  return String(matches[0]?.path || "");
}

export type FeederReadiness = {
  operational?: boolean;
  inputs_ready?: boolean;
};

export type FeederReadinessPresentation = {
  contextLabel: "listo" | "disponible" | "incompleto" | "pendiente 1.1";
  inputsLabel: "listas" | "bloqueadas" | "por validar";
  tone: "ok" | "bad" | "neutral";
};

/** No convierte metadatos ausentes en fallos confirmados. */
export function deriveFeederReadiness(
  feeder: FeederReadiness | undefined,
  cymdistReady: boolean
): FeederReadinessPresentation {
  const contextLabel = cymdistReady
    ? "listo"
    : feeder?.operational === true
      ? "disponible"
      : feeder?.operational === false
        ? "incompleto"
        : "pendiente 1.1";
  const inputsLabel =
    feeder?.inputs_ready === true
      ? "listas"
      : feeder?.inputs_ready === false
        ? "bloqueadas"
        : "por validar";
  const tone =
    feeder?.inputs_ready === false || (!cymdistReady && feeder?.operational === false)
      ? "bad"
      : cymdistReady || feeder?.operational === true
        ? "ok"
        : "neutral";
  return { contextLabel, inputsLabel, tone };
}

export type SelectionState = {
  databaseMdb: string;
  canonicalDatabaseMdb: string;
  studyPath: string;
  feederId: string;
  networkId: string;
  databaseRequestId: number;
  feeders: FeederOption[];
};

type PickerResult = {
  ok?: boolean;
  cancelled?: boolean;
  kind?: "database" | "study" | string;
  path?: string;
  canonical_path?: string;
};

type DiscoveryResult = {
  database_mdb?: string;
  canonical_database_mdb?: string;
  feeders?: FeederOption[];
};

function fallbackCanonical(path: string): string {
  return (path || "").trim().replace(/\//g, "\\").toLowerCase();
}

/**
 * 1.1 solo puede cambiar la ruta elegida cuando el backend confirma que creó
 * y guardó un estudio nuevo. Si reutiliza uno existente, conserva identidad
 * estricta para impedir que otro estudio sustituya silenciosamente al elegido.
 */
export function resolveAppliedStudy(
  requestedStudy: string,
  returnedStudy: string,
  studyCreated: boolean
): string {
  const requested = (requestedStudy || "").trim();
  const returned = (returnedStudy || "").trim();
  if (!returned) throw new Error("STUDY_IDENTITY_MISMATCH: 1.1 no devolvió estudio");
  if (!requested || studyCreated || fallbackCanonical(requested) === fallbackCanonical(returned)) {
    return returned;
  }
  throw new Error("STUDY_IDENTITY_MISMATCH: 1.1 devolvió otro estudio existente");
}

export function beginDatabaseSelection(
  state: SelectionState,
  path: string,
  canonicalPath?: string
): SelectionState {
  return {
    ...state,
    databaseMdb: (path || "").trim(),
    canonicalDatabaseMdb: (canonicalPath || fallbackCanonical(path)).trim(),
    studyPath: "",
    feederId: "",
    networkId: "",
    feeders: [],
    databaseRequestId: state.databaseRequestId + 1,
  };
}

export function selectStudy(state: SelectionState, path: string): SelectionState {
  return { ...state, studyPath: (path || "").trim() };
}

export function selectFeeder(
  state: SelectionState,
  feederId: string,
  networkId: string
): SelectionState {
  return {
    ...state,
    studyPath: "",
    feederId: (feederId || "").trim(),
    networkId: (networkId || "").trim(),
  };
}

export function applyPickerResult(
  state: SelectionState,
  result: PickerResult
): SelectionState {
  if (!result || result.cancelled || !result.path) return state;
  if (result.kind === "database") {
    return beginDatabaseSelection(state, result.path, result.canonical_path);
  }
  if (result.kind === "study") return selectStudy(state, result.path);
  return state;
}

export function acceptDiscoveryResult(
  state: SelectionState,
  requestId: number,
  result: DiscoveryResult
): SelectionState {
  const canonical =
    result.canonical_database_mdb || result.database_mdb || "";
  if (
    requestId !== state.databaseRequestId ||
    fallbackCanonical(canonical) !== fallbackCanonical(state.canonicalDatabaseMdb)
  ) {
    return state;
  }
  return { ...state, feeders: [...(result.feeders || [])] };
}
