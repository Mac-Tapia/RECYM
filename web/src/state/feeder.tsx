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
  studyMode: "single" | "transfer";
  transferPeer: string;
  scenarioId: string;
  transferNode: string;
  transferSectionalizer: string;
  transferTieSwitch: string;
  setFeeder: (f: string, network?: string) => void;
  setContext: (opts: {
    feeder?: string;
    network?: string;
    studyPath?: string;
    databaseMdb?: string;
    contextFingerprint?: string;
    inputsReady?: boolean | null;
    inputErrors?: string[];
    studyMode?: "single" | "transfer";
    transferPeer?: string;
    scenarioId?: string;
    transferNode?: string;
    transferSectionalizer?: string;
    transferTieSwitch?: string;
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
  const [studyMode, setStudyMode] = useState<"single" | "transfer">("single");
  const [transferPeer, setTransferPeer] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [transferNode, setTransferNode] = useState("");
  const [transferSectionalizer, setTransferSectionalizer] = useState("");
  const [transferTieSwitch, setTransferTieSwitch] = useState("");
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
      studyMode,
      transferPeer,
      scenarioId,
      transferNode,
      transferSectionalizer,
      transferTieSwitch,
      setFeeder: (f, n) => {
        const nextFeeder = f || "";
        const nextNetwork = n === undefined ? network : n || "";
        const identityChanged = nextFeeder !== feeder || nextNetwork !== network;
        if (nextFeeder !== feeder) {
          setInputsReady(null);
          setInputErrors([]);
        }
        if (identityChanged) {
          setContextFingerprint("");
          setContextVersion((value) => value + 1);
        }
        setF(nextFeeder);
        if (n !== undefined) setN(n || "");
        setActiveFeeder(nextFeeder);
        setActiveContext({
          feeder: nextFeeder,
          network: n,
          ...(identityChanged ? { contextFingerprint: "" } : {}),
        });
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
        if (opts.studyMode !== undefined) setStudyMode(opts.studyMode);
        if (opts.transferPeer !== undefined) setTransferPeer(opts.transferPeer || "");
        if (opts.scenarioId !== undefined) setScenarioId(opts.scenarioId || "");
        if (opts.transferNode !== undefined) setTransferNode(opts.transferNode || "");
        if (opts.transferSectionalizer !== undefined) setTransferSectionalizer(opts.transferSectionalizer || "");
        if (opts.transferTieSwitch !== undefined) setTransferTieSwitch(opts.transferTieSwitch || "");
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
      studyMode,
      transferPeer,
      scenarioId,
      transferNode,
      transferSectionalizer,
      transferTieSwitch,
    ]
  );
  return <FeederCtx.Provider value={value}>{children}</FeederCtx.Provider>;
}

export function useFeeder() {
  const c = useContext(FeederCtx);
  if (!c) throw new Error("useFeeder fuera de provider");
  return c;
}
