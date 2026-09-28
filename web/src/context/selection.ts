export type FeederOption = {
  feeder_id: string;
  network_id: string;
  label?: string;
};

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
  return (path || "").trim().replace(/\//g, "\\").toLocaleLowerCase();
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
    (result.canonical_database_mdb || fallbackCanonical(result.database_mdb || "")).trim();
  if (requestId !== state.databaseRequestId || canonical !== state.canonicalDatabaseMdb) {
    return state;
  }
  return { ...state, feeders: [...(result.feeders || [])] };
}
