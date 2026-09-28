import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { setActiveContext, setActiveFeeder } from "../api/client";

type Ctx = {
  feeder: string;
  network: string;
  studyPath: string;
  databaseMdb: string;
  contextFingerprint: string;
  contextVersion: number;
  inputsReady: boolean | null;
  inputErrors: string[];
  setFeeder: (f: string, network?: string) => void;
  setContext: (opts: {
    feeder?: string;
    network?: string;
    studyPath?: string;
    databaseMdb?: string;
    contextFingerprint?: string;
    inputsReady?: boolean | null;
    inputErrors?: string[];
  }) => void;
};

const FeederCtx = createContext<Ctx | null>(null);

export function FeederProvider({ children }: { children: ReactNode }) {
  const [feeder, setF] = useState("");
  const [network, setN] = useState("");
  const [studyPath, setStudyPath] = useState("");
  const [databaseMdb, setDatabaseMdb] = useState("");
  const [contextFingerprint, setContextFingerprint] = useState("");
  const [contextVersion, setContextVersion] = useState(0);
  const [inputsReady, setInputsReady] = useState<boolean | null>(null);
  const [inputErrors, setInputErrors] = useState<string[]>([]);
  const value = useMemo<Ctx>(
    () => ({
      feeder,
      network,
      studyPath,
      databaseMdb,
      contextFingerprint,
      contextVersion,
      inputsReady,
      inputErrors,
      setFeeder: (f, n) => {
        if ((f || "") !== feeder) {
          setInputsReady(null);
          setInputErrors([]);
        }
        if ((f || "") !== feeder || (n !== undefined && (n || "") !== network)) {
          setContextFingerprint("");
          setContextVersion((value) => value + 1);
        }
        setF(f || "");
        if (n !== undefined) setN(n || "");
        setActiveFeeder(f || "");
        setActiveContext({ feeder: f || "", network: n, contextFingerprint: "" });
      },
      setContext: (opts) => {
        const identityChanged =
          (opts.feeder !== undefined && (opts.feeder || "") !== feeder) ||
          (opts.network !== undefined && (opts.network || "") !== network) ||
          (opts.studyPath !== undefined && (opts.studyPath || "") !== studyPath) ||
          (opts.databaseMdb !== undefined && (opts.databaseMdb || "") !== databaseMdb);
        if (opts.feeder !== undefined) setF(opts.feeder || "");
        if (opts.network !== undefined) setN(opts.network || "");
        if (opts.studyPath !== undefined) setStudyPath(opts.studyPath || "");
        if (opts.databaseMdb !== undefined) setDatabaseMdb(opts.databaseMdb || "");
        if (opts.contextFingerprint !== undefined) {
          setContextFingerprint(opts.contextFingerprint || "");
        } else if (identityChanged) {
          setContextFingerprint("");
        }
        if (identityChanged) setContextVersion((value) => value + 1);
        if (opts.inputsReady !== undefined) setInputsReady(opts.inputsReady);
        if (opts.inputErrors !== undefined) setInputErrors(opts.inputErrors);
        setActiveContext({
          feeder: opts.feeder !== undefined ? opts.feeder || "" : undefined,
          network: opts.network,
          studyPath: opts.studyPath,
          databaseMdb: opts.databaseMdb,
          contextFingerprint:
            opts.contextFingerprint !== undefined
              ? opts.contextFingerprint || ""
              : identityChanged
                ? ""
                : undefined,
        });
      },
    }),
    [
      feeder,
      network,
      studyPath,
      databaseMdb,
      contextFingerprint,
      contextVersion,
      inputsReady,
      inputErrors,
    ]
  );
  return <FeederCtx.Provider value={value}>{children}</FeederCtx.Provider>;
}

export function useFeeder() {
  const c = useContext(FeederCtx);
  if (!c) throw new Error("useFeeder fuera de provider");
  return c;
}
